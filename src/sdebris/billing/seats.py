"""The founding-seat cap, enforced as a hard limit.

A seat is either paid for (an active grant that never expires) or reserved
(a hold taken when a founding checkout starts, valid while that checkout
could still be paid). Both count against the cap. Checkout refuses once the
two together reach it, and a founding payment that arrives with no hold and
no free seat is refunded rather than granted: that is a purchase which went
around checkout, such as a Dodo payment link.

Taking and checking seats happens under one lock, so two buyers cannot both
see seat 100 as free. On Postgres that is a transaction-scoped advisory lock;
SQLite, used in development and tests, already serialises writers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from sdebris.billing.entitlements import as_utc, count_lifetime_grants
from sdebris.ontology.orm import FoundingSeatHoldRecord

#: How long a reserved seat waits for its checkout to be paid. Dodo does not
#: publish a checkout lifetime, so this is generous: an abandoned checkout
#: costs other buyers an hour. A purchase paid after its hold lapsed is still
#: honoured if a seat is free, and refunded if not.
HOLD_DURATION = timedelta(minutes=60)

#: Arbitrary, but fixed: every process must take the same advisory lock.
_LOCK_KEY = 4_712_550_861


def lock(session: Session) -> None:
    """Serialise seat accounting until the current transaction ends."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _unreleased(session: Session) -> list[FoundingSeatHoldRecord]:
    # Filtered in Python because SQLite stores these without a zone, and the
    # table only ever holds a handful of live rows.
    return list(
        session.scalars(
            select(FoundingSeatHoldRecord).where(FoundingSeatHoldRecord.released_at.is_(None))
        )
    )


def active_hold(
    session: Session, subject: str, now: datetime | None = None
) -> FoundingSeatHoldRecord | None:
    """``subject``'s reservation, if it has not lapsed."""
    moment = _now(now)
    for hold in _unreleased(session):
        if hold.subject == subject and as_utc(hold.expires_at) > moment:
            return hold
    return None


def held_for(session: Session, subject: str) -> FoundingSeatHoldRecord | None:
    """``subject``'s unused reservation, lapsed or not, so it can be released."""
    for hold in _unreleased(session):
        if hold.subject == subject:
            return hold
    return None


def seats_remaining(
    session: Session,
    cap: int,
    now: datetime | None = None,
    *,
    excluding: str | None = None,
) -> int:
    """Seats neither paid for nor reserved, ignoring ``excluding``'s own hold."""
    moment = _now(now)
    reserved = sum(
        1
        for hold in _unreleased(session)
        if as_utc(hold.expires_at) > moment and hold.subject != excluding
    )
    return max(0, cap - count_lifetime_grants(session) - reserved)


def reserve(
    session: Session, subject: str, email: str | None, now: datetime | None = None
) -> FoundingSeatHoldRecord:
    """Take a seat for ``subject``, or renew the one they already hold.

    The caller checks ``seats_remaining`` first, under ``lock``.
    """
    moment = _now(now)
    hold = active_hold(session, subject, moment)
    if hold is None:
        hold = FoundingSeatHoldRecord(subject=subject, email=email)
        session.add(hold)
    hold.expires_at = moment + HOLD_DURATION
    session.flush()
    return hold


def release(session: Session, hold: FoundingSeatHoldRecord, now: datetime | None = None) -> None:
    hold.released_at = _now(now)
    session.flush()
