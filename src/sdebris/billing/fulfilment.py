"""Turning a verified billing event into a change of entitlement.

Every decision about who has paid for what is made here, so the webhook
endpoint only verifies and records. The rules, in the order they bite:

* Only a configured product grants anything. A payment for some other
  product the business sells later must not unlock Pro by accident.
* A subscription is granted from its own events, keyed on the subscription,
  so its first payment and every renewal extend one grant.
* A one-time purchase is granted from ``payment.succeeded`` and only if it
  bought the lifetime product.
* Cancelling ends renewal, not the period already paid for.
* A refund or lost dispute names only a payment. The ledger remembers which
  subscription each payment belonged to, which is how a refunded renewal
  withdraws the subscription's grant rather than missing it.
* A full refund or a lost dispute on a subscription also cancels it with the
  provider. Withdrawing access alone left it renewing: the customer was
  charged again a month later, and the renewal handed Pro back.
* A partial refund is a goodwill credit, so access stays.
* Events arrive out of order and are retried. Each grant remembers when the
  last event applied to it happened, and an older event is ignored, so a late
  retry of ``subscription.active`` cannot revive a cancelled grant. A
  refunded grant is final.
* The founding-seat cap is hard: see ``seats``. A founding payment with no
  reserved seat and none free is refunded instead of granted.

Calls to the provider (cancel, refund) raise ``BillingUnavailable`` when they
fail. The endpoint then rolls back and answers with an error, so the provider
redelivers the event and the whole decision is taken again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdebris.billing import seats
from sdebris.billing.dodo import BillingUnavailable
from sdebris.billing.entitlements import as_utc, end_at, grant, restore, revoke
from sdebris.billing.plans import Plan
from sdebris.billing.webhooks import (
    DISPUTE_RESTORING_EVENTS,
    REVERSAL_EVENTS,
    SUBSCRIPTION_CANCELLED,
    SUBSCRIPTION_ENDING_EVENTS,
    SUBSCRIPTION_GRANTING_EVENTS,
    BillingEvent,
    subscription_expiry,
)
from sdebris.ontology.orm import BillingEventRecord, EntitlementRecord

logger = logging.getLogger("sdebris.billing")


class ProviderActions(Protocol):
    """The provider calls an event can require. ``DodoClient`` is one."""

    def cancel_subscription(self, subscription_id: str, *, comment: str) -> str: ...

    def refund_payment(self, payment_id: str, *, reason: str) -> str: ...


#: Reversals that end the customer relationship, so a subscription they hit
#: is cancelled with the provider as well as withdrawn here.
CANCELLING_REVERSALS = frozenset({"refund.succeeded", "dispute.lost"})

#: A grant in this state is never reactivated by a later subscription event.
FINAL_STATUSES = frozenset({"refunded"})


def _no_provider() -> ProviderActions:
    raise BillingUnavailable("billing is not configured on this deployment")


@dataclass(frozen=True, slots=True)
class Products:
    """The provider product ids this deployment sells."""

    subscription: str | None
    lifetime: str | None

    def sells(self, product_id: str | None) -> bool:
        return bool(product_id) and product_id in {self.subscription, self.lifetime}


def _grant_metadata(event: BillingEvent, **extra: object) -> dict[str, object]:
    metadata: dict[str, object] = {"event_type": event.event_type, **extra}
    if event.product_id:
        metadata["product_id"] = event.product_id
    if event.customer_id:
        metadata["customer_id"] = event.customer_id
    return metadata


def _grant_for(session: Session, external_ref: str) -> EntitlementRecord | None:
    return session.scalar(
        select(EntitlementRecord).where(EntitlementRecord.external_ref == external_ref)
    )


def _last_applied(record: EntitlementRecord | None) -> datetime | None:
    if record is None:
        return None
    value = (record.metadata_json or {}).get("last_event_at")
    if not isinstance(value, str):
        return None
    try:
        return as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _is_stale(record: EntitlementRecord | None, event: BillingEvent) -> bool:
    """Whether a newer event has already been applied to this grant.

    An event with no timestamp cannot be ordered, so it is applied as before.
    """
    last = _last_applied(record)
    return last is not None and event.occurred_at is not None and event.occurred_at < last


def _stamp(record: EntitlementRecord | None, event: BillingEvent) -> None:
    if record is None or event.occurred_at is None:
        return
    last = _last_applied(record)
    if last is None or event.occurred_at > last:
        record.metadata_json = {
            **(record.metadata_json or {}),
            "last_event_at": event.occurred_at.isoformat(),
        }


def _reversed_ref(session: Session, provider: str, payment_id: str) -> str:
    """The grant key a reversed payment paid for.

    A lifetime grant is keyed on the payment itself. A subscription grant is
    keyed on the subscription, found through the payment's earlier delivery.
    """
    subscription_id = session.scalar(
        select(BillingEventRecord.subscription_id)
        .where(
            BillingEventRecord.provider == provider,
            BillingEventRecord.payment_id == payment_id,
            BillingEventRecord.subscription_id.is_not(None),
        )
        .limit(1)
    )
    return subscription_id or payment_id


def apply_event(
    session: Session,
    event: BillingEvent,
    *,
    provider: str,
    products: Products,
    founding_seats: int,
    actions: Callable[[], ProviderActions] = _no_provider,
) -> str:
    """Apply one event and return a short outcome for the ledger.

    ``actions`` builds the provider client, and is called only when an event
    needs a cancellation or refund, so a deployment without an API key still
    records every other event.
    """
    kind = event.event_type

    if kind in SUBSCRIPTION_GRANTING_EVENTS:
        if not (event.email and event.subscription_id):
            return "ignored-incomplete"
        if not products.subscription or event.product_id != products.subscription:
            return "ignored-unknown-product"
        existing = _grant_for(session, event.subscription_id)
        if _is_stale(existing, event):
            return "ignored-stale"
        if existing is not None and existing.status in FINAL_STATUSES:
            return "ignored-refunded"
        if existing is not None and existing.status == "disputed":
            # Paid for, but suspended until the dispute settles: extend the
            # period without handing access back.
            existing.expires_at = subscription_expiry(event)
            _stamp(existing, event)
            return "extended-while-disputed"
        record = grant(
            session,
            email=event.email,
            plan=Plan.PRO,
            source=provider,
            external_ref=event.subscription_id,
            expires_at=subscription_expiry(event),
            metadata=_grant_metadata(event, lifetime=False, cancelled=False),
            subject=event.subject,
        )
        _stamp(record, event)
        return "granted"

    if kind == "payment.succeeded":
        if event.subscription_id:
            # Recorded in the ledger for refund lookups; the subscription's
            # own events carry the grant.
            return "recorded"
        if not (event.email and event.payment_id):
            return "ignored-incomplete"
        if not products.lifetime or event.product_id != products.lifetime:
            return "ignored-unknown-product"
        seats.lock(session)
        hold = seats.held_for(session, event.subject) if event.subject else None
        reserved = hold is not None and seats.active_hold(session, event.subject) is not None
        already_granted = _grant_for(session, event.payment_id) is not None
        if (
            not reserved
            and not already_granted
            and seats.seats_remaining(session, founding_seats, excluding=event.subject) <= 0
        ):
            # No live reservation and no free seat: a purchase that went
            # around checkout (a payment link), or one paid after its hold
            # lapsed and the seat went to someone else. Refunded, not granted.
            actions().refund_payment(
                event.payment_id,
                reason="All founding seats were taken. Refunded in full.",
            )
            if hold is not None:
                seats.release(session, hold)
            logger.warning("refunded founding purchase %s: no seat left", event.payment_id)
            return "refunded-over-cap"
        grant(
            session,
            email=event.email,
            plan=Plan.PRO,
            source=provider,
            external_ref=event.payment_id,
            expires_at=None,
            metadata=_grant_metadata(event, lifetime=True),
            subject=event.subject,
        )
        if hold is not None:
            seats.release(session, hold)
        return "granted-lifetime"

    if kind == SUBSCRIPTION_CANCELLED and event.subscription_id:
        existing = _grant_for(session, event.subscription_id)
        if _is_stale(existing, event):
            return "ignored-stale"
        if event.period_end is None:
            # Nothing says when the paid period ends; the grant already lapses
            # at the last renewal date plus grace, which is the right answer.
            _stamp(existing, event)
            return "cancel-noted"
        record = end_at(session, external_ref=event.subscription_id, ends_at=event.period_end)
        _stamp(record, event)
        return "ends-at-period-end" if record else "cancel-no-match"

    if kind in SUBSCRIPTION_ENDING_EVENTS and event.subscription_id:
        existing = _grant_for(session, event.subscription_id)
        if _is_stale(existing, event):
            return "ignored-stale"
        if existing is not None and existing.status in FINAL_STATUSES:
            _stamp(existing, event)
            return "already-ended"
        record = revoke(
            session,
            external_ref=event.subscription_id,
            status=SUBSCRIPTION_ENDING_EVENTS[kind],
        )
        _stamp(record, event)
        return "revoked" if record else _no_match(kind, event.subscription_id)

    if kind in REVERSAL_EVENTS and event.payment_id:
        ref = _reversed_ref(session, provider, event.payment_id)
        existing = _grant_for(session, ref)
        if existing is None:
            return _no_match(kind, event.payment_id)
        if _is_stale(existing, event):
            return "ignored-stale"
        if kind == "refund.succeeded" and event.is_partial:
            _stamp(existing, event)
            return "partial-refund-kept"
        revoke(session, external_ref=ref, status=REVERSAL_EVENTS[kind])
        _stamp(existing, event)
        is_subscription = ref != event.payment_id
        if kind in CANCELLING_REVERSALS and is_subscription:
            actions().cancel_subscription(
                ref, comment=f"{kind} on payment {event.payment_id}; cancelled so it does not renew."
            )
            return "revoked-and-cancelled"
        return "revoked"

    if kind in DISPUTE_RESTORING_EVENTS and event.payment_id:
        ref = _reversed_ref(session, provider, event.payment_id)
        existing = _grant_for(session, ref)
        if _is_stale(existing, event):
            return "ignored-stale"
        record = restore(session, external_ref=ref, from_status="disputed")
        _stamp(existing, event)
        return "restored" if record else "restore-no-match"

    return "ignored"


def _no_match(kind: str, reference: str) -> str:
    """An event for a grant this deployment never made. Worth a look."""
    logger.warning("%s for %s matched no grant", kind, reference)
    return "revoke-no-match"
