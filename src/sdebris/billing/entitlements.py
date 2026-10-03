"""Resolving and recording what a principal has paid for."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdebris.auth import Principal
from sdebris.billing.plans import Plan, parse_plan
from sdebris.ontology.orm import EntitlementRecord

#: Statuses that still confer access. Anything else is treated as free.
ACTIVE_STATUSES = frozenset({"active"})


def normalise_email(email: str | None) -> str | None:
    return email.strip().lower() or None if email else None


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite round-trips datetimes without tzinfo; treat those as UTC.

    Public because anything serialising an entitlement has to go through it —
    an expiry sent to a client without a zone is ambiguous.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _is_current(record: EntitlementRecord, now: datetime) -> bool:
    if record.status not in ACTIVE_STATUSES:
        return False
    expires_at = as_utc(record.expires_at)
    # A null expiry is lifetime access.
    return expires_at is None or expires_at > now


def active_entitlement(
    session: Session, principal: Principal, now: datetime | None = None
) -> EntitlementRecord | None:
    """The principal's current grant, if any.

    Matched on email first, because that is what the payment provider knows.
    The auth subject is recorded on the way through so later lookups work even
    if the person changes the address on their account.
    """
    moment = now or datetime.now(timezone.utc)
    email = normalise_email(principal.email)
    candidates: list[EntitlementRecord] = []
    if email:
        candidates.extend(
            session.scalars(
                select(EntitlementRecord).where(EntitlementRecord.email == email)
            )
        )
    candidates.extend(
        session.scalars(
            select(EntitlementRecord).where(
                EntitlementRecord.subject == principal.subject
            )
        )
    )

    current = [record for record in candidates if _is_current(record, moment)]
    if not current:
        return None
    # Prefer the grant that lasts longest; lifetime grants sort last.
    current.sort(
        key=lambda record: (as_utc(record.expires_at) is not None, as_utc(record.expires_at) or moment),
        reverse=True,
    )
    best = current[0]
    if best.subject is None:
        best.subject = principal.subject
    return best


def plan_for(
    session: Session, principal: Principal, now: datetime | None = None
) -> Plan:
    record = active_entitlement(session, principal, now)
    return parse_plan(record.plan) if record else Plan.FREE


def grant(
    session: Session,
    *,
    email: str,
    plan: Plan,
    source: str,
    external_ref: str | None,
    expires_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> EntitlementRecord:
    """Create or refresh a grant.

    Keyed on ``external_ref`` so a provider redelivering the same payment
    renews the grant instead of stacking a second one.
    """
    normalised = normalise_email(email)
    if not normalised:
        raise ValueError("an entitlement needs an email address")

    existing = None
    if external_ref:
        existing = session.scalar(
            select(EntitlementRecord).where(
                EntitlementRecord.external_ref == external_ref
            )
        )
    if existing is None:
        existing = EntitlementRecord(email=normalised, external_ref=external_ref)
        session.add(existing)

    existing.email = normalised
    existing.plan = plan.value
    existing.status = "active"
    existing.source = source
    existing.granted_at = datetime.now(timezone.utc)
    existing.expires_at = expires_at
    existing.metadata_json = metadata or {}
    session.flush()
    return existing


def count_lifetime_grants(session: Session) -> int:
    """Active grants that never expire, i.e. founding seats taken."""
    return int(
        session.scalar(
            select(func.count(EntitlementRecord.id)).where(
                EntitlementRecord.status.in_(tuple(ACTIVE_STATUSES)),
                EntitlementRecord.expires_at.is_(None),
            )
        )
        or 0
    )


def revoke(
    session: Session, *, external_ref: str, status: str
) -> EntitlementRecord | None:
    """Mark a grant inactive after a refund, cancellation or chargeback."""
    record = session.scalar(
        select(EntitlementRecord).where(EntitlementRecord.external_ref == external_ref)
    )
    if record is None:
        return None
    record.status = status
    session.flush()
    return record
