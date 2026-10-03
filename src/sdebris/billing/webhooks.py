"""Verification and interpretation of billing provider webhooks.

Dodo Payments signs deliveries with the `Standard Webhooks
<https://www.standardwebhooks.com>`_ scheme: three headers carrying an event
id, a timestamp and one or more versioned HMAC-SHA256 signatures over
``{id}.{timestamp}.{body}``.

Verify the header names and event names against the provider's current
documentation before going live — they are the part most likely to have moved.
The signature algorithm is the published standard and is stable.
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
    external_ref: str | None
    product_id: str | None
    #: End of the paid period for a recurring purchase, if the provider sent one.
    period_end: datetime | None
    payload: dict[str, Any]

    @property
    def is_subscription(self) -> bool:
        return self.event_type.startswith("subscription.")


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


#: Provider event names that grant access, mapped to whether they recur.
GRANTING_EVENTS = {
    "payment.succeeded": False,
    "subscription.active": True,
    "subscription.renewed": True,
}
#: Event names that withdraw access, mapped to the status to record.
REVOKING_EVENTS = {
    "payment.failed": "failed",
    "payment.refunded": "refunded",
    "refund.succeeded": "refunded",
    "dispute.opened": "disputed",
    "subscription.cancelled": "cancelled",
    "subscription.canceled": "cancelled",
    "subscription.expired": "expired",
    "subscription.failed": "failed",
    "subscription.on_hold": "on_hold",
}


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


def parse_event(event_id: str, payload: dict[str, Any]) -> BillingEvent:
    """Pull the fields entitlement handling needs out of a provider payload.

    Providers move things between the envelope and `data`, so each field is
    looked for in the documented place and the obvious alternatives.
    """
    event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
    email = _first(
        payload,
        ("data", "customer", "email"),
        ("data", "customer_email"),
        ("data", "email"),
        ("customer", "email"),
        ("email",),
    )
    external_ref = _first(
        payload,
        ("data", "subscription_id"),
        ("data", "payment_id"),
        ("data", "id"),
        ("subscription_id",),
        ("payment_id",),
    )
    product_id = _first(
        payload,
        ("data", "product_id"),
        ("data", "product", "product_id"),
        ("data", "product", "id"),
        ("product_id",),
    )
    period_end = _parse_moment(
        _first(
            payload,
            ("data", "next_billing_date"),
            ("data", "current_period_end"),
            ("data", "expires_at"),
        )
    )
    return BillingEvent(
        event_id=event_id,
        event_type=event_type,
        email=str(email) if email else None,
        external_ref=str(external_ref) if external_ref else None,
        product_id=str(product_id) if product_id else None,
        period_end=period_end,
        payload=payload,
    )


def grant_expiry(
    event: BillingEvent, *, lifetime_product_id: str | None, now: datetime | None = None
) -> datetime | None:
    """When the grant this event buys should lapse; ``None`` means never.

    A purchase counts as lifetime only when it matches the configured lifetime
    product. Everything else is treated as a period that has to be renewed, so
    a misconfiguration under-grants rather than handing out free forever.
    """
    if (
        lifetime_product_id
        and event.product_id
        and event.product_id == lifetime_product_id
    ):
        return None
    moment = now or datetime.now(timezone.utc)
    period_end = event.period_end or (moment + DEFAULT_PERIOD)
    return period_end + RENEWAL_GRACE
