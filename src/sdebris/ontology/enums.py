"""Controlled vocabulary for the SSA operational ontology."""

from __future__ import annotations

from enum import Enum


class StringEnum(str, Enum):
    """Enum whose values serialize naturally through JSON and SQL string columns."""


class ObjectStatus(StringEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DECAYED = "decayed"
    UNKNOWN = "unknown"


class OrbitClass(StringEnum):
    LEO = "LEO"
    MEO = "MEO"
    GEO = "GEO"
    HEO = "HEO"
    UNKNOWN = "unknown"


class RiskTier(StringEnum):
    CRITICAL = "critical"
    WATCH = "watch"
    NOMINAL = "nominal"


class EventStatus(StringEnum):
    DETECTED = "detected"
    UNDER_REVIEW = "under_review"
    MITIGATED = "mitigated"
    CLOSED = "closed"


class CaseStatus(StringEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    CLOSED = "closed"


class Priority(StringEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ApprovalStatus(StringEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DeliveryStatus(StringEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    ACKNOWLEDGED = "acknowledged"


class ManeuverStatus(StringEnum):
    DRAFT = "draft"
    SIMULATED = "simulated"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ScreeningRunStatus(StringEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(StringEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperatorRole(StringEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    OPERATOR = "operator"
    ADMIN = "admin"


class ActionType(StringEnum):
    ACKNOWLEDGE_ALERT = "acknowledge_alert"
    OPEN_CASE = "open_case"
    ASSIGN_CASE = "assign_case"
    REQUEST_ORBIT_REFRESH = "request_orbit_refresh"
    RERUN_SCREENING = "rerun_screening"
    ESCALATE_EVENT = "escalate_event"
    CREATE_MANEUVER_SCENARIO = "create_maneuver_scenario"
    APPROVE_RECOMMENDATION = "approve_recommendation"
    REJECT_RECOMMENDATION = "reject_recommendation"
    NOTIFY_OWNER = "notify_owner"
    CLOSE_CASE = "close_case"
    RECORD_DECISION = "record_decision"
