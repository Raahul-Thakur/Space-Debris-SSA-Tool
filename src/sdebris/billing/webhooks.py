"""Verification and interpretation of billing provider webhooks.

Dodo Payments signs deliveries with the `Standard Webhooks
<https://www.standardwebhooks.com>`_ scheme: three headers carrying an event
id, a timestamp and one or more versioned HMAC-SHA256 signatures over
``{id}.{timestamp}.{body}``.

Header names, event names and payload fields were checked against Dodo's
webhook guide and OpenAPI reference in November 2026. Two facts from that
reference shape everything below:

* A one-time purchase names its product inside ``data.product_cart``, not in a
  top-level ``product_id``; only subscription payloads carry ``product_id``.
* Refund and dispute payloads name the ``payment_id`` they reverse and nothing
  else, so reversing a subscription needs the payment-to-subscription link
  recorded when the payment succeeded.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

ID_HEADER = "webhook-id"
TIMESTAMP_HEADER = "webhook-timestamp"
SIGNATURE_HEADER = "webhook-signature"

#: How far a delivery's timestamp may drift before it is treated as a replay.
TOLERANCE = timedelta(minutes=5)
#: Secrets are issued with this prefix; the payload is base64 after it.
SECRET_PREFIX = "whsec_"


class WebhookError(Exception):
    """A delivery could not be trusted."""


@dataclass(frozen=True, slots=True)
class BillingEvent:
    """A verified delivery, reduced to what entitlement handling needs."""

    event_id: str
    event_type: str
    email: str | None
    payment_id: str | None
    subscription_id: str | None
    product_id: str | None
    #: The provider's customer id, needed to open their billing portal.
    customer_id: str | None
    #: The auth subject the checkout was started for, carried in metadata.
    subject: str | None
    #: End of the paid period for a recurring purchase, if the provider sent one.
    period_end: datetime | None
    payload: dict[str, Any]
    #: When the event happened, from the payload's ``timestamp``. Not the
    #: ``webhook-timestamp`` header: that is the time of each delivery
    #: attempt, so a retry carries a newer one than the event it repeats.
    occurred_at: datetime | None = None
    #: A refund that returned only part of the payment.
    is_partial: bool = False

    @property
    def is_subscription(self) -> bool:
        return self.event_type.startswith("subscription.")

    @property
    def external_ref(self) -> str | None:
        """The key a grant from this event is stored under.

        A subscription's grant outlives any one payment, so it is keyed on the
        subscription; a one-time purchase has only its payment.
        """
        return self.subscription_id or self.payment_id


#: How long a subscription grant outlives the provider's renewal date. Renewal
#: webhooks can lag by hours, and a subscriber should not lose access in the
#: gap; a genuine failure arrives as its own revoking event.
RENEWAL_GRACE = timedelta(days=3)
#: Used when a recurring event arrives without a renewal date.
DEFAULT_PERIOD = timedelta(days=31)


def _decode_secret(secret: str) -> bytes:
    raw = secret.removeprefix(SECRET_PREFIX)
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        # Some dashboards show the secret already decoded.
        return raw.encode("utf-8")


def verify_signature(
    *,
    secret: str,
    headers: dict[str, str],
    body: bytes,
    now: datetime | None = None,
) -> str:
    """Return the event id once the delivery's signature checks out."""
    lowered = {key.lower(): value for key, value in headers.items()}
    event_id = lowered.get(ID_HEADER)
    timestamp = lowered.get(TIMESTAMP_HEADER)
    signature_header = lowered.get(SIGNATURE_HEADER)
    if not (event_id and timestamp and signature_header):
        raise WebhookError("delivery is missing its signature headers")

    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise WebhookError("delivery timestamp is not a unix time") from exc
    moment = now or datetime.now(timezone.utc)
    if abs(moment - sent_at) > TOLERANCE:
        raise WebhookError("delivery timestamp is outside the replay window")

    signed = b"%s.%s.%s" % (event_id.encode(), timestamp.encode(), body)
    expected = base64.b64encode(
        hmac.new(_decode_secret(secret), signed, hashlib.sha256).digest()
    ).decode()

    # The header carries a space-separated list so secrets can be rotated.
    for candidate in signature_header.split():
        _, _, value = candidate.partition(",")
        if value and hmac.compare_digest(value, expected):
            return event_id
    raise WebhookError("no signature in the delivery matched")


#: Events that start or extend a subscription grant. A one-time purchase is
#: granted from ``payment.succeeded`` instead, because a subscription's first
#: payment also fires that event and must not create a second grant.
SUBSCRIPTION_GRANTING_EVENTS = frozenset({"subscription.active", "subscription.renewed"})
#: Subscription events that end access now. Each arrives after the paid
#: period has already run out or never began, so there is nothing to honour.
SUBSCRIPTION_ENDING_EVENTS = {
    "subscription.expired": "expired",
    "subscription.failed": "failed",
    "subscription.on_hold": "on_hold",
}
#: Payment reversals, mapped to the status recorded on the grant they undo.
REVERSAL_EVENTS = {
    "refund.succeeded": "refunded",
    "dispute.opened": "disputed",
    "dispute.lost": "disputed",
}
#: A dispute settled in the seller's favour restores what it suspended.
DISPUTE_WON = "dispute.won"
#: Every dispute outcome that should restore access: won by the seller,
#: withdrawn by the customer, or lapsed without a decision. Only ``won`` was
#: handled before, so a withdrawn dispute left Pro suspended for good.
DISPUTE_RESTORING_EVENTS = frozenset({DISPUTE_WON, "dispute.cancelled", "dispute.expired"})
#: Cancellation stops renewal; it does not take back the period already paid.
SUBSCRIPTION_CANCELLED = "subscription.cancelled"


def _parse_moment(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _first(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        cursor: Any = payload
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if cursor:
            return cursor
    return None


def _cart_product(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    cart = data.get("product_cart") if isinstance(data, dict) else None
    if isinstance(cart, list):
        for item in cart:
            if isinstance(item, dict) and item.get("product_id"):
                return str(item["product_id"])
    return None


def parse_event(event_id: str, payload: dict[str, Any]) -> BillingEvent:
    """Pull the fields entitlement handling needs out of a provider payload."""
    event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
    email = _first(payload, ("data", "customer", "email"), ("data", "customer_email"))
    payment_id = _first(payload, ("data", "payment_id"))
    subscription_id = _first(payload, ("data", "subscription_id"))
    product_id = _first(payload, ("data", "product_id")) or _cart_product(payload)
    customer_id = _first(
        payload, ("data", "customer", "customer_id"), ("data", "customer_id")
    )
    subject = _first(payload, ("data", "metadata", "subject"))
    period_end = _parse_moment(_first(payload, ("data", "next_billing_date")))
    return BillingEvent(
        event_id=event_id,
        event_type=event_type,
        email=str(email) if email else None,
        payment_id=str(payment_id) if payment_id else None,
        subscription_id=str(subscription_id) if subscription_id else None,
        product_id=str(product_id) if product_id else None,
        customer_id=str(customer_id) if customer_id else None,
        subject=str(subject) if subject else None,
        period_end=period_end,
        payload=payload,
        occurred_at=_parse_moment(payload.get("timestamp")),
        is_partial=_first(payload, ("data", "is_partial")) is True,
    )


#: Payload fields the ledger never needs, removed before a delivery is stored.
#: A payment carries the billing address and card details; holding them would
#: make this database a target for no benefit, since the provider keeps them.
LEDGER_REDACTED_FIELDS = frozenset(
    {
        "billing",
        "card_exp_month",
        "card_exp_year",
        "card_holder_name",
        "card_issuing_country",
        "card_last_four",
        "card_network",
        "card_type",
        "payment_method",
        "payment_method_id",
        "tax_id",
        "custom_field_responses",
    }
)


def ledger_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The delivery as it should be kept: everything but payment details."""
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    kept = {key: value for key, value in data.items() if key not in LEDGER_REDACTED_FIELDS}
    customer = kept.get("customer")
    if isinstance(customer, dict):
        kept["customer"] = {
            key: value for key, value in customer.items() if key != "phone_number"
        }
    return {**payload, "data": kept}


def subscription_expiry(event: BillingEvent, now: datetime | None = None) -> datetime:
    """When a subscription grant lapses unless a renewal extends it."""
    moment = now or datetime.now(timezone.utc)
    period_end = event.period_end or (moment + DEFAULT_PERIOD)
    return period_end + RENEWAL_GRACE
