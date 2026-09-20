"""Unified real-time activity feed across the operational ontology.

The dashboard renders a single chronological stream rather than polling each
table on its own. Every item carries a monotonically increasing ``occurred_at``
cursor so a client can resume without replaying what it already rendered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdebris.ontology.orm import (
    AlertRecord,
    AuditActionRecord,
    CommandExecutionRecord,
    ConjunctionEventRecord,
    MonitoredObjectRecord,
    RiskAssessmentRecord,
    ScreeningJobEventRecord,
    ScreeningJobRecord,
    SpaceObjectRecord,
)

#: Highest number of items a single feed read may return.
MAX_FEED_ITEMS = 200

_TIER_SEVERITY = {"critical": "critical", "watch": "watch", "nominal": "nominal"}
_JOB_SEVERITY = {
    "failed": "critical",
    "cancelled": "watch",
    "complete": "nominal",
}
#: Feed headlines for each screening stage; unknown stages fall back to the raw
#: stage name so a new pipeline step still reads sensibly.
_JOB_STAGE_TITLES = {
    "queued": "Screening queued",
    "catalog": "Catalog synchronization",
    "propagation": "Catalog propagation",
    "screening": "Conjunction screening",
    "ontology": "Ontology persistence",
    "complete": "Screening complete",
    "failed": "Screening failed",
    "cancelled": "Screening cancelled",
}


@dataclass(slots=True)
class ActivityItem:
    """One entry in the operator-facing live feed."""

    id: str
    kind: str
    severity: str
    title: str
    detail: str
    occurred_at: datetime
    entity_type: str
    entity_id: str
    norad_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "occurred_at": _iso(self.occurred_at),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "norad_id": self.norad_id,
            "payload": self.payload,
        }


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _aware(value: datetime) -> datetime:
    """SQLite round-trips datetimes without a tzinfo; treat those as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _label(session: Session, object_id: str | None) -> tuple[str, str | None]:
    if object_id is None:
        return "Unknown", None
    record = session.get(SpaceObjectRecord, object_id)
    if record is None:
        return "Unknown", None
    return record.name, record.norad_id


def _conjunction_items(session: Session, since: datetime) -> list[ActivityItem]:
    rows = session.scalars(
        select(ConjunctionEventRecord)
        .where(ConjunctionEventRecord.created_at > since)
        .order_by(ConjunctionEventRecord.created_at)
        .limit(MAX_FEED_ITEMS)
    )
    items: list[ActivityItem] = []
    for event in rows:
        assessment = session.scalar(
            select(RiskAssessmentRecord)
            .where(RiskAssessmentRecord.event_id == event.id)
            .order_by(RiskAssessmentRecord.created_at.desc())
            .limit(1)
        )
        tier = assessment.tier if assessment else "unassessed"
        primary_name, primary_norad = _label(session, event.primary_object_id)
        secondary_name, _ = _label(session, event.secondary_object_id)
        items.append(
            ActivityItem(
                id=f"event:{event.id}",
                kind="conjunction",
                severity=_TIER_SEVERITY.get(tier, "info"),
                title=f"Conjunction {event.miss_distance_km:.3f} km",
                detail=f"{primary_name} / {secondary_name}",
                occurred_at=_aware(event.created_at),
                entity_type="ConjunctionEvent",
                entity_id=event.id,
                norad_id=primary_norad,
                payload={
                    "tca": _iso(event.tca),
                    "miss_distance_km": event.miss_distance_km,
                    "relative_speed_km_s": event.relative_speed_km_s,
                    "tier": tier,
                    "probability_of_collision": (
                        assessment.probability_of_collision if assessment else None
                    ),
                },
            )
        )
    return items


def _alert_items(session: Session, since: datetime) -> list[ActivityItem]:
    rows = session.scalars(
        select(AlertRecord)
        .where(AlertRecord.created_at > since)
        .order_by(AlertRecord.created_at)
        .limit(MAX_FEED_ITEMS)
    )
    return [
        ActivityItem(
            id=f"alert:{alert.id}",
            kind="alert",
            severity="critical" if alert.acknowledged_at is None else "nominal",
            title=f"Alert dispatched via {alert.channel}",
            detail=alert.rule,
            occurred_at=_aware(alert.created_at),
            entity_type="Alert",
            entity_id=alert.id,
            payload={
                "delivery_status": alert.delivery_status,
                "acknowledged": alert.acknowledged_at is not None,
                "event_id": alert.event_id,
            },
        )
        for alert in rows
    ]


def _job_items(session: Session, since: datetime) -> list[ActivityItem]:
    # A job emits one progress record per transition, so the event table is the
    # feed source: the job row itself only ever holds the latest state.
    rows = session.execute(
        select(ScreeningJobEventRecord, ScreeningJobRecord)
        .join(
            ScreeningJobRecord,
            ScreeningJobRecord.id == ScreeningJobEventRecord.job_id,
        )
        .where(ScreeningJobEventRecord.created_at > since)
        .order_by(ScreeningJobEventRecord.created_at)
        .limit(MAX_FEED_ITEMS)
    ).all()
    return [
        ActivityItem(
            id=f"job:{event.job_id}:{event.sequence}",
            kind="job",
            severity=_JOB_SEVERITY.get(event.stage, "info"),
            title=_JOB_STAGE_TITLES.get(event.stage, f"Screening {event.stage}"),
            detail=event.message or job.command,
            occurred_at=_aware(event.created_at),
            entity_type="ScreeningJob",
            entity_id=event.job_id,
            norad_id=str(job.request_payload.get("norad_id") or "") or None,
            payload={
                "status": job.status,
                "stage": event.stage,
                "progress": event.progress,
                "command": job.command,
            },
        )
        for event, job in rows
    ]


def _command_items(session: Session, since: datetime) -> list[ActivityItem]:
    rows = session.scalars(
        select(CommandExecutionRecord)
        .where(CommandExecutionRecord.created_at > since)
        .order_by(CommandExecutionRecord.created_at)
        .limit(MAX_FEED_ITEMS)
    )
    return [
        ActivityItem(
            id=f"command:{execution.id}",
            kind="command",
            severity="critical" if execution.error_message else "info",
            title=f"{execution.actor} ran {execution.parsed_action}",
            detail=execution.error_message or execution.raw_command,
            occurred_at=_aware(execution.created_at),
            entity_type="CommandExecution",
            entity_id=execution.id,
            payload={"status": execution.status, "role": execution.role},
        )
        for execution in rows
    ]


def _monitoring_items(session: Session, since: datetime) -> list[ActivityItem]:
    rows = session.execute(
        select(MonitoredObjectRecord, SpaceObjectRecord)
        .join(SpaceObjectRecord)
        .where(MonitoredObjectRecord.updated_at > since)
        .order_by(MonitoredObjectRecord.updated_at)
        .limit(MAX_FEED_ITEMS)
    ).all()
    return [
        ActivityItem(
            id=f"monitor:{monitor.id}:{'on' if monitor.active else 'off'}",
            kind="monitoring",
            severity="info",
            title=f"{obj.name} {'added to' if monitor.active else 'removed from'} watch",
            detail=f"NORAD {obj.norad_id} · {monitor.added_by}",
            occurred_at=_aware(monitor.updated_at),
            entity_type="MonitoredObject",
            entity_id=monitor.id,
            norad_id=obj.norad_id,
            payload={"active": monitor.active},
        )
        for monitor, obj in rows
    ]


def _audit_items(session: Session, since: datetime) -> list[ActivityItem]:
    rows = session.scalars(
        select(AuditActionRecord)
        .where(AuditActionRecord.occurred_at > since)
        .order_by(AuditActionRecord.occurred_at)
        .limit(MAX_FEED_ITEMS)
    )
    return [
        ActivityItem(
            id=f"audit:{audit.id}",
            kind="governance",
            severity="watch" if audit.approval_status == "pending" else "info",
            title=f"{audit.action_type} on {audit.entity_type}",
            detail=audit.justification or f"{audit.actor} recorded a governed action",
            occurred_at=_aware(audit.occurred_at),
            entity_type=audit.entity_type,
            entity_id=audit.entity_id,
            payload={
                "actor": audit.actor,
                "approval_status": audit.approval_status,
                "correlation_id": audit.correlation_id,
            },
        )
        for audit in rows
    ]


_COLLECTORS = (
    _conjunction_items,
    _alert_items,
    _job_items,
    _command_items,
    _monitoring_items,
    _audit_items,
)


def collect_activity(
    session: Session, since: datetime, limit: int = 50
) -> list[ActivityItem]:
    """Return feed items recorded strictly after ``since``, oldest first."""
    cutoff = _aware(since)
    items: list[ActivityItem] = []
    for collector in _COLLECTORS:
        items.extend(collector(session, cutoff))
    items.sort(key=lambda item: (item.occurred_at, item.id))
    # The newest items matter most when a client has fallen far behind, so the
    # tail is kept and then re-presented in chronological order.
    return items[-min(limit, MAX_FEED_ITEMS) :]


def feed_cursor(items: list[ActivityItem], fallback: datetime) -> str:
    """Cursor a client should send on its next read."""
    latest = max((item.occurred_at for item in items), default=_aware(fallback))
    return _iso(latest)
