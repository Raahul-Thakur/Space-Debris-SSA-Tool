"""Validated API contracts for ontology objects and operational actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sdebris.ontology.enums import (
    ApprovalStatus,
    DeliveryStatus,
    EventStatus,
    JobStatus,
    ManeuverStatus,
    ObjectStatus,
    OrbitClass,
    OperatorRole,
    Priority,
    RiskTier,
    ScreeningRunStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ScreeningJobCreate(BaseModel):
    norad_id: str = Field(pattern=r"^\d{1,9}$")
    group: str = Field(default="iridium-33-debris", min_length=1, max_length=128)
    window_hours: float = Field(default=72, gt=0, le=168)
    step_sec: int = Field(default=60, ge=10, le=900)
    threshold_km: float = Field(default=25, gt=0, le=1000)
    persist_ontology: bool = True
    refresh_catalog: bool = True
    timeout_seconds: int = Field(default=900, ge=30, le=3600)
    actor: str = Field(default="operator", min_length=1, max_length=255)
    command: str | None = Field(default=None, max_length=2048)


class ScreeningJobView(ORMModel):
    id: str
    actor: str
    command: str
    status: str
    stage: str
    progress: float
    message: str
    request_payload: dict[str, Any]
    result_payload: dict[str, Any]
    error_message: str | None
    cancel_requested: bool
    ontology_run_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ScreeningJobEventView(ORMModel):
    id: str
    job_id: str
    sequence: int
    stage: str
    progress: float
    message: str
    payload: dict[str, Any]
    created_at: datetime


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=2048)
    confirmed: bool = False


class CommandPlan(BaseModel):
    action: str
    arguments: dict[str, Any]
    required_role: OperatorRole
    asynchronous: bool = False


class CommandResponse(BaseModel):
    execution_id: str
    plan: CommandPlan
    status: JobStatus | str
    result: dict[str, Any] = Field(default_factory=dict)
    job: ScreeningJobView | None = None


class MonitoredObjectView(ORMModel):
    id: str
    space_object_id: str
    norad_id: str
    name: str
    added_by: str
    active: bool
    created_at: datetime
    updated_at: datetime


class TrajectoryPoint(BaseModel):
    timestamp: datetime
    x_km: float
    y_km: float
    z_km: float
    valid: bool


class TrajectoryResponse(BaseModel):
    norad_id: str
    name: str
    frame: str = "TEME"
    points: list[TrajectoryPoint]


class SpaceObjectCreate(BaseModel):
    norad_id: str = Field(pattern=r"^\d{1,9}$")
    name: str = Field(min_length=1, max_length=255)
    owner: str | None = Field(default=None, max_length=255)
    orbit_class: OrbitClass = OrbitClass.UNKNOWN
    status: ObjectStatus = ObjectStatus.UNKNOWN
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class SpaceObjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    owner: str | None = Field(default=None, max_length=255)
    orbit_class: OrbitClass | None = None
    status: ObjectStatus | None = None
    metadata_json: dict[str, Any] | None = None


class SpaceObjectView(ORMModel):
    id: str
    norad_id: str
    name: str
    owner: str | None
    orbit_class: str
    status: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ElementSetCreate(BaseModel):
    line1: str = Field(min_length=60, max_length=80)
    line2: str = Field(min_length=60, max_length=80)
    source: str = Field(min_length=1, max_length=128)
    quality: float | None = Field(default=None, ge=0, le=1)
    parser_version: str = Field(default="sdebris-0.1", min_length=1, max_length=64)
    raw_payload_uri: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_tle_lines(self) -> ElementSetCreate:
        if not self.line1.startswith("1 "):
            raise ValueError("line1 must begin with '1 '")
        if not self.line2.startswith("2 "):
            raise ValueError("line2 must begin with '2 '")
        return self


class ElementSetView(ORMModel):
    id: str
    space_object_id: str
    line1: str
    line2: str
    epoch: datetime
    source: str
    quality: float | None
    ingested_at: datetime
    parser_version: str
    content_sha256: str
    raw_payload_uri: str | None


class ScreeningRunCreate(BaseModel):
    propagator: str = "SGP4"
    propagator_version: str = Field(min_length=1, max_length=64)
    configuration: dict[str, Any] = Field(default_factory=dict)
    input_versions: dict[str, Any] = Field(default_factory=dict)


class ScreeningRunView(ORMModel):
    id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    propagator: str
    propagator_version: str
    configuration: dict[str, Any]
    input_versions: dict[str, Any]
    error_message: str | None


class ScreeningRunUpdate(BaseModel):
    status: ScreeningRunStatus
    error_message: str | None = None


class ConjunctionEventCreate(BaseModel):
    primary_norad_id: str = Field(pattern=r"^\d{1,9}$")
    secondary_norad_id: str = Field(pattern=r"^\d{1,9}$")
    screening_run_id: str | None = None
    tca: datetime
    miss_distance_km: float = Field(ge=0)
    relative_speed_km_s: float = Field(ge=0)
    radial_km: float | None = None
    along_track_km: float | None = None
    cross_track_km: float | None = None
    status: EventStatus = EventStatus.DETECTED

    @model_validator(mode="after")
    def distinct_objects(self) -> ConjunctionEventCreate:
        if self.primary_norad_id == self.secondary_norad_id:
            raise ValueError("primary and secondary objects must differ")
        return self


class ConjunctionEventView(ORMModel):
    id: str
    screening_run_id: str | None
    primary_object_id: str
    secondary_object_id: str
    tca: datetime
    miss_distance_km: float
    relative_speed_km_s: float
    radial_km: float | None
    along_track_km: float | None
    cross_track_km: float | None
    status: str
    created_at: datetime
    updated_at: datetime


class RiskAssessmentCreate(BaseModel):
    tier: RiskTier
    probability_of_collision: float = Field(ge=0, le=1)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    model_version: str = Field(min_length=1, max_length=128)
    explanation: str = Field(min_length=1)


class RiskAssessmentView(ORMModel):
    id: str
    event_id: str
    tier: str
    probability_of_collision: float
    uncertainty: dict[str, Any]
    model_version: str
    explanation: str
    created_at: datetime


class MonitoringCaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    priority: Priority = Priority.P2
    assignee: str | None = Field(default=None, max_length=255)
    due_at: datetime | None = None


class MonitoringCaseView(ORMModel):
    id: str
    event_id: str
    title: str
    status: str
    priority: str
    assignee: str | None
    due_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OpenCaseRequest(MonitoringCaseCreate):
    actor: str = Field(min_length=1, max_length=255)
    justification: str = Field(min_length=3)


class CaseActionRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=255)
    justification: str = Field(min_length=3)
    assignee: str | None = Field(default=None, max_length=255)
    priority: Priority | None = None
    data_versions: dict[str, Any] = Field(default_factory=dict)
    model_versions: dict[str, Any] = Field(default_factory=dict)
    approval_status: ApprovalStatus = ApprovalStatus.NOT_REQUIRED


class AlertCreate(BaseModel):
    event_id: str
    rule: str = Field(min_length=1, max_length=255)
    channel: str = Field(min_length=1, max_length=64)
    delivery_status: DeliveryStatus = DeliveryStatus.PENDING


class AlertView(ORMModel):
    id: str
    event_id: str
    rule: str
    channel: str
    delivery_status: str
    created_at: datetime
    delivered_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None


class AcknowledgeAlertRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=255)
    justification: str = Field(min_length=3)


class OperatorDecisionCreate(BaseModel):
    selected_action: str = Field(min_length=1, max_length=255)
    justification: str = Field(min_length=3)
    actor: str = Field(min_length=1, max_length=255)
    approver: str | None = Field(default=None, max_length=255)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    data_versions: dict[str, Any] = Field(default_factory=dict)
    model_versions: dict[str, Any] = Field(default_factory=dict)


class OperatorDecisionView(ORMModel):
    id: str
    case_id: str
    selected_action: str
    justification: str
    actor: str
    approver: str | None
    approval_status: str
    created_at: datetime


class ManeuverScenarioCreate(BaseModel):
    space_object_norad_id: str = Field(pattern=r"^\d{1,9}$")
    proposed_at: datetime
    delta_v_r_m_s: float
    delta_v_i_m_s: float
    delta_v_c_m_s: float
    simulation_model_version: str = Field(min_length=1, max_length=128)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(min_length=1, max_length=255)
    justification: str = Field(min_length=3)


class ManeuverScenarioUpdate(BaseModel):
    resulting_miss_distance_km: float = Field(ge=0)
    resulting_probability_of_collision: float = Field(ge=0, le=1)
    status: ManeuverStatus = ManeuverStatus.SIMULATED


class ManeuverScenarioView(ORMModel):
    id: str
    event_id: str
    space_object_id: str
    proposed_at: datetime
    delta_v_r_m_s: float
    delta_v_i_m_s: float
    delta_v_c_m_s: float
    resulting_miss_distance_km: float | None
    resulting_probability_of_collision: float | None
    status: str
    simulation_model_version: str
    assumptions: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SensorObservationCreate(BaseModel):
    sensor: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    frame: str = Field(min_length=1, max_length=32)
    position_km: list[float]
    velocity_km_s: list[float] | None = None
    quality: float | None = Field(default=None, ge=0, le=1)
    source: str = Field(min_length=1, max_length=255)

    @field_validator("position_km")
    @classmethod
    def position_has_three_components(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("position_km must contain exactly three components")
        return value

    @field_validator("velocity_km_s")
    @classmethod
    def velocity_has_three_components(
        cls, value: list[float] | None
    ) -> list[float] | None:
        if value is not None and len(value) != 3:
            raise ValueError("velocity_km_s must contain exactly three components")
        return value


class SensorObservationView(ORMModel):
    id: str
    space_object_id: str
    sensor: str
    observed_at: datetime
    frame: str
    position_km: list[float]
    velocity_km_s: list[float] | None
    quality: float | None
    source: str
    ingested_at: datetime


class AuditActionView(ORMModel):
    id: str
    action_type: str
    actor: str
    occurred_at: datetime
    entity_type: str
    entity_id: str
    input_payload: dict[str, Any]
    previous_state: dict[str, Any]
    new_state: dict[str, Any]
    data_versions: dict[str, Any]
    model_versions: dict[str, Any]
    justification: str
    approval_status: str
    correlation_id: str


class LineageEdgeView(ORMModel):
    id: str
    upstream_type: str
    upstream_id: str
    downstream_type: str
    downstream_id: str
    relationship: str
    transformation: str | None
    run_id: str | None
    created_at: datetime


class OntologyDescription(BaseModel):
    object_types: dict[str, list[str]]
    relationships: list[str]
    actions: list[str]
