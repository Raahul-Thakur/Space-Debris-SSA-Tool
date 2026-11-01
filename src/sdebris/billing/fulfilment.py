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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdebris.billing.entitlements import count_lifetime_grants, end_at, grant, restore, revoke
from sdebris.billing.plans import Plan
from sdebris.billing.webhooks import (
    DISPUTE_WON,
    REVERSAL_EVENTS,
    SUBSCRIPTION_CANCELLED,
    SUBSCRIPTION_ENDING_EVENTS,
    SUBSCRIPTION_GRANTING_EVENTS,
    BillingEvent,
    subscription_expiry,
)
from sdebris.ontology.orm import BillingEventRecord

logger = logging.getLogger("sdebris.billing")


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
) -> str:
    """Apply one event and return a short outcome for the ledger."""
    kind = event.event_type

    if kind in SUBSCRIPTION_GRANTING_EVENTS:
        if not (event.email and event.subscription_id):
            return "ignored-incomplete"
        if not products.subscription or event.product_id != products.subscription:
            return "ignored-unknown-product"
        grant(
            session,
            email=event.email,
            plan=Plan.PRO,
            source=provider,
            external_ref=event.subscription_id,
            expires_at=subscription_expiry(event),
            metadata=_grant_metadata(event, lifetime=False, cancelled=False),
            subject=event.subject,
        )
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
        over_cap = count_lifetime_grants(session) >= founding_seats
        if over_cap:
            # The cap is enforced when a checkout is created. Money that has
            # already changed hands is always honoured, but worth knowing about.
            logger.warning("lifetime purchase %s arrived after seats ran out", event.payment_id)
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
        return "granted-lifetime-over-cap" if over_cap else "granted-lifetime"

    if kind == SUBSCRIPTION_CANCELLED and event.subscription_id:
        if event.period_end is None:
            # Nothing says when the paid period ends; the grant already lapses
            # at the last renewal date plus grace, which is the right answer.
            return "cancel-noted"
        record = end_at(session, external_ref=event.subscription_id, ends_at=event.period_end)
        return "ends-at-period-end" if record else "cancel-no-match"

    if kind in SUBSCRIPTION_ENDING_EVENTS and event.subscription_id:
        record = revoke(
            session,
            external_ref=event.subscription_id,
            status=SUBSCRIPTION_ENDING_EVENTS[kind],
        )
        return "revoked" if record else "revoke-no-match"

    if kind in REVERSAL_EVENTS and event.payment_id:
        ref = _reversed_ref(session, provider, event.payment_id)
        record = revoke(session, external_ref=ref, status=REVERSAL_EVENTS[kind])
        return "revoked" if record else "revoke-no-match"

    if kind == DISPUTE_WON and event.payment_id:
        ref = _reversed_ref(session, provider, event.payment_id)
        record = restore(session, external_ref=ref, from_status="disputed")
        return "restored" if record else "restore-no-match"

    return "ignored"
