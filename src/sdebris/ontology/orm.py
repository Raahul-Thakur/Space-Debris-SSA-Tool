"""SQLAlchemy mappings for the strongly typed SSA ontology."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class SpaceObjectRecord(TimestampMixin, Base):
    __tablename__ = "space_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    norad_id: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(255))
    orbit_class: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    element_sets: Mapped[list[ElementSetRecord]] = relationship(
        back_populates="space_object", cascade="all, delete-orphan"
    )


class ElementSetRecord(Base):
    __tablename__ = "element_sets"
    __table_args__ = (
        UniqueConstraint("space_object_id", "content_sha256", name="uq_element_object_content"),
        Index("ix_element_object_epoch", "space_object_id", "epoch"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), nullable=False, index=True
    )
    line1: Mapped[str] = mapped_column(String(80), nullable=False)
    line2: Mapped[str] = mapped_column(String(80), nullable=False)
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    quality: Mapped[float | None] = mapped_column(Float)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload_uri: Mapped[str | None] = mapped_column(String(1024))

    space_object: Mapped[SpaceObjectRecord] = relationship(back_populates="element_sets")


class ScreeningRunRecord(Base):
    __tablename__ = "screening_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    propagator: Mapped[str] = mapped_column(String(64), default="SGP4", nullable=False)
    propagator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    input_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class EphemerisSampleRecord(Base):
    __tablename__ = "ephemeris_samples"
    __table_args__ = (
        UniqueConstraint(
            "screening_run_id",
            "space_object_id",
            "timestamp",
            name="uq_ephemeris_run_object_time",
        ),
        Index("ix_ephemeris_object_time", "space_object_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    screening_run_id: Mapped[str] = mapped_column(
        ForeignKey("screening_runs.id"), nullable=False, index=True
    )
    space_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), nullable=False, index=True
    )
    element_set_id: Mapped[str] = mapped_column(
        ForeignKey("element_sets.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frame: Mapped[str] = mapped_column(String(32), default="TEME", nullable=False)
    x_km: Mapped[float] = mapped_column(Float, nullable=False)
    y_km: Mapped[float] = mapped_column(Float, nullable=False)
    z_km: Mapped[float] = mapped_column(Float, nullable=False)
    vx_km_s: Mapped[float] = mapped_column(Float, nullable=False)
    vy_km_s: Mapped[float] = mapped_column(Float, nullable=False)
    vz_km_s: Mapped[float] = mapped_column(Float, nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ConjunctionEventRecord(TimestampMixin, Base):
    __tablename__ = "conjunction_events"
    __table_args__ = (
        UniqueConstraint(
            "screening_run_id",
            "primary_object_id",
            "secondary_object_id",
            "tca",
            name="uq_event_run_pair_tca",
        ),
        Index("ix_event_tca_status", "tca", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    screening_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("screening_runs.id"), index=True
    )
    primary_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), nullable=False, index=True
    )
    secondary_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), nullable=False, index=True
    )
    tca: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    miss_distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    relative_speed_km_s: Mapped[float] = mapped_column(Float, nullable=False)
    radial_km: Mapped[float | None] = mapped_column(Float)
    along_track_km: Mapped[float | None] = mapped_column(Float)
    cross_track_km: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="detected", nullable=False)

    primary: Mapped[SpaceObjectRecord] = relationship(
        foreign_keys=[primary_object_id]
    )
    secondary: Mapped[SpaceObjectRecord] = relationship(
        foreign_keys=[secondary_object_id]
    )
    assessments: Mapped[list[RiskAssessmentRecord]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class RiskAssessmentRecord(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (Index("ix_assessment_event_created", "event_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("conjunction_events.id"), nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    probability_of_collision: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    event: Mapped[ConjunctionEventRecord] = relationship(back_populates="assessments")


class MonitoringCaseRecord(TimestampMixin, Base):
    __tablename__ = "monitoring_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("conjunction_events.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(8), default="P2", nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(255))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SensorObservationRecord(Base):
    __tablename__ = "sensor_observations"
    __table_args__ = (Index("ix_observation_object_time", "space_object_id", "observed_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), nullable=False, index=True
    )
    sensor: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frame: Mapped[str] = mapped_column(String(32), nullable=False)
    position_km: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    velocity_km_s: Mapped[list[float] | None] = mapped_column(JSON)
    quality: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ManeuverScenarioRecord(TimestampMixin, Base):
    __tablename__ = "maneuver_scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("conjunction_events.id"), nullable=False, index=True
    )
    space_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), nullable=False
    )
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delta_v_r_m_s: Mapped[float] = mapped_column(Float, nullable=False)
    delta_v_i_m_s: Mapped[float] = mapped_column(Float, nullable=False)
    delta_v_c_m_s: Mapped[float] = mapped_column(Float, nullable=False)
    resulting_miss_distance_km: Mapped[float | None] = mapped_column(Float)
    resulting_probability_of_collision: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    simulation_model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("conjunction_events.id"), nullable=False, index=True
    )
    rule: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(255))


class OperatorDecisionRecord(Base):
    __tablename__ = "operator_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("monitoring_cases.id"), nullable=False, index=True
    )
    selected_action: Mapped[str] = mapped_column(String(255), nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    approver: Mapped[str | None] = mapped_column(String(255))
    approval_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AuditActionRecord(Base):
    __tablename__ = "audit_actions"
    __table_args__ = (
        Index("ix_audit_entity_time", "entity_type", "entity_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    previous_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    data_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    model_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    approval_status: Mapped[str] = mapped_column(
        String(32), default="not_required", nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(64), default=new_id, nullable=False)


class LineageEdgeRecord(Base):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        Index("ix_lineage_upstream", "upstream_type", "upstream_id"),
        Index("ix_lineage_downstream", "downstream_type", "downstream_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    upstream_type: Mapped[str] = mapped_column(String(64), nullable=False)
    upstream_id: Mapped[str] = mapped_column(String(36), nullable=False)
    downstream_type: Mapped[str] = mapped_column(String(64), nullable=False)
    downstream_id: Mapped[str] = mapped_column(String(36), nullable=False)
    relationship: Mapped[str] = mapped_column(String(128), nullable=False)
    transformation: Mapped[str | None] = mapped_column(String(255))
    run_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class MonitoredObjectRecord(Base):
    __tablename__ = "monitored_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    space_object_id: Mapped[str] = mapped_column(
        ForeignKey("space_objects.id"), unique=True, nullable=False, index=True
    )
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    space_object: Mapped[SpaceObjectRecord] = relationship()


class ScreeningJobRecord(Base):
    __tablename__ = "screening_jobs"
    __table_args__ = (Index("ix_screening_job_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    message: Mapped[str] = mapped_column(String(512), default="Queued", nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ontology_run_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScreeningJobEventRecord(Base):
    __tablename__ = "screening_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),
        Index("ix_job_event_job_sequence", "job_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("screening_jobs.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class CommandExecutionRecord(Base):
    __tablename__ = "command_executions"
    __table_args__ = (Index("ix_command_actor_created", "actor", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_command: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_action: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("screening_jobs.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
