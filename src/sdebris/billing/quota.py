"""Usage accounting and the checks that enforce a plan's limits.

Usage is derived from records the platform already writes — screening jobs and
monitored objects both carry the acting principal — so there is no separate
counter to drift out of step with reality.

Note that the ontology is currently shared rather than per-tenant: everyone
sees the same monitored objects and events. Quotas are therefore per-principal
accounting over a common workspace, not isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sdebris.auth import Principal
from sdebris.billing.plans import Plan, PlanLimits, limits_for
from sdebris.ontology.orm import MonitoredObjectRecord, ScreeningJobRecord

#: Payment Required. The request was understood and permitted by role; the
#: principal has simply used up what their plan allows.
QUOTA_STATUS = 402


def month_start(now: datetime | None = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    return moment.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )


@dataclass(frozen=True, slots=True)
class Usage:
    screening_runs_this_month: int
    monitored_objects: int


def usage_for(session: Session, principal: Principal, now: datetime | None = None) -> Usage:
    since = month_start(now)
    runs = session.scalar(
        select(func.count(ScreeningJobRecord.id)).where(
            ScreeningJobRecord.actor == principal.actor,
            ScreeningJobRecord.created_at >= since,
        )
    )
    monitored = session.scalar(
        select(func.count(MonitoredObjectRecord.id)).where(
            MonitoredObjectRecord.added_by == principal.actor,
            MonitoredObjectRecord.active.is_(True),
        )
    )
    return Usage(
        screening_runs_this_month=int(runs or 0),
        monitored_objects=int(monitored or 0),
    )


def _exceeded(message: str, plan: Plan) -> HTTPException:
    upgrade = "" if plan is Plan.PRO else " Upgrade to Pro for a higher limit."
    return HTTPException(status_code=QUOTA_STATUS, detail=f"{message}{upgrade}")


def check_screening_allowed(
    session: Session,
    principal: Principal,
    plan: Plan,
    *,
    window_hours: float,
    now: datetime | None = None,
) -> None:
    """Raise if this screening run would breach the plan."""
    limits: PlanLimits = limits_for(plan)

    if (
        limits.max_window_hours is not None
        and window_hours > limits.max_window_hours
    ):
        raise _exceeded(
            f"The {plan.label} plan screens windows up to "
            f"{limits.max_window_hours:g}h; this run asked for {window_hours:g}h.",
            plan,
        )

    if limits.screening_runs_per_month is None:
        return
    used = usage_for(session, principal, now).screening_runs_this_month
    if used >= limits.screening_runs_per_month:
        raise _exceeded(
            f"The {plan.label} plan allows "
            f"{limits.screening_runs_per_month} screening runs per month, and "
            f"{used} have been used.",
            plan,
        )


def check_monitoring_allowed(
    session: Session, principal: Principal, plan: Plan
) -> None:
    """Raise if adding one more monitored object would breach the plan."""
    limits = limits_for(plan)
    if limits.monitored_objects is None:
        return
    used = usage_for(session, principal).monitored_objects
    if used >= limits.monitored_objects:
        raise _exceeded(
            f"The {plan.label} plan tracks up to {limits.monitored_objects} "
            f"objects at once, and {used} are already on the watch list.",
            plan,
        )
