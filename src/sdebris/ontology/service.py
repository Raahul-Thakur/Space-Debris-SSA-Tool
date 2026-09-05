"""Transactional ontology repository and governed operational actions."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import desc, inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sdebris.models import parse_tle_epoch
from sdebris.ontology.enums import (
    ActionType,
    CaseStatus,
    DeliveryStatus,
    EventStatus,
    Priority,
)
from sdebris.ontology.orm import (
    AlertRecord,
    AuditActionRecord,
    ConjunctionEventRecord,
    ElementSetRecord,
    LineageEdgeRecord,
    ManeuverScenarioRecord,
    MonitoringCaseRecord,
    OperatorDecisionRecord,
    RiskAssessmentRecord,
    ScreeningRunRecord,
    SensorObservationRecord,
    SpaceObjectRecord,
    utcnow,
)
from sdebris.ontology.schemas import (
    AcknowledgeAlertRequest,
    AlertCreate,
    CaseActionRequest,
    ConjunctionEventCreate,
    ElementSetCreate,
    ManeuverScenarioCreate,
    MonitoringCaseCreate,
    OperatorDecisionCreate,
    RiskAssessmentCreate,
    ScreeningRunCreate,
    SensorObservationCreate,
    SpaceObjectCreate,
    SpaceObjectUpdate,
)

RecordT = TypeVar("RecordT")


class OntologyError(RuntimeError):
    pass


class NotFoundError(OntologyError):
    pass


class ConflictError(OntologyError):
    pass


class InvalidActionError(OntologyError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def record_state(record: Any) -> dict[str, Any]:
    return {
        column.key: _json_value(getattr(record, column.key))
        for column in inspect(record).mapper.column_attrs
    }


class OntologyService:
    def __init__(self, session: Session, *, auto_commit: bool = True) -> None:
        self.session = session
        self.auto_commit = auto_commit

    def _get(self, model: type[RecordT], record_id: str, label: str) -> RecordT:
        record = self.session.get(model, record_id)
        if record is None:
            raise NotFoundError(f"{label} {record_id} was not found")
        return record

    def _commit(self) -> None:
        try:
            if self.auto_commit:
                self.session.commit()
            else:
                self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError("The operation conflicts with an existing record") from exc

    def _lineage(
        self,
        upstream_type: str,
        upstream_id: str,
        downstream_type: str,
        downstream_id: str,
        relationship: str,
        *,
        transformation: str | None = None,
        run_id: str | None = None,
    ) -> LineageEdgeRecord:
        edge = LineageEdgeRecord(
            upstream_type=upstream_type,
            upstream_id=upstream_id,
            downstream_type=downstream_type,
            downstream_id=downstream_id,
            relationship=relationship,
            transformation=transformation,
            run_id=run_id,
        )
        self.session.add(edge)
        return edge

    def _audit(
        self,
        action_type: ActionType,
        actor: str,
        entity_type: str,
        entity_id: str,
        request: CaseActionRequest | OperatorDecisionCreate,
        previous_state: dict[str, Any],
        new_state: dict[str, Any],
        input_payload: dict[str, Any],
    ) -> AuditActionRecord:
        audit = AuditActionRecord(
            action_type=action_type.value,
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            input_payload=input_payload,
            previous_state=previous_state,
            new_state=new_state,
            data_versions=request.data_versions,
            model_versions=request.model_versions,
            justification=request.justification,
            approval_status=request.approval_status.value,
        )
        self.session.add(audit)
        return audit

    # ---------------------------------------------------------------- objects
    def create_space_object(self, payload: SpaceObjectCreate) -> SpaceObjectRecord:
        existing = self.get_space_object_by_norad(payload.norad_id, required=False)
        if existing is not None:
            raise ConflictError(f"NORAD {payload.norad_id} already exists")
        record = SpaceObjectRecord(
            norad_id=payload.norad_id,
            name=payload.name,
            owner=payload.owner,
            orbit_class=payload.orbit_class.value,
            status=payload.status.value,
            metadata_json=payload.metadata_json,
        )
        self.session.add(record)
        self._commit()
        return record

    def update_space_object(
        self, norad_id: str, payload: SpaceObjectUpdate
    ) -> SpaceObjectRecord:
        record = self.get_space_object_by_norad(norad_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(record, key, value.value if hasattr(value, "value") else value)
        self._commit()
        return record

    def get_space_object_by_norad(
        self, norad_id: str, *, required: bool = True
    ) -> SpaceObjectRecord | None:
        record = self.session.scalar(
            select(SpaceObjectRecord).where(SpaceObjectRecord.norad_id == str(norad_id))
        )
        if record is None and required:
            raise NotFoundError(f"NORAD {norad_id} was not found")
        return record

    def list_space_objects(self, limit: int = 100, offset: int = 0) -> list[SpaceObjectRecord]:
        return list(
            self.session.scalars(
                select(SpaceObjectRecord)
                .order_by(SpaceObjectRecord.norad_id)
                .offset(offset)
                .limit(limit)
            )
        )

    # ------------------------------------------------------------ element sets
    def add_element_set(
        self, norad_id: str, payload: ElementSetCreate
    ) -> ElementSetRecord:
        space_object = self.get_space_object_by_norad(norad_id)
        tle_norad = payload.line1[2:7].strip()
        if tle_norad != str(norad_id):
            raise InvalidActionError(
                f"TLE belongs to NORAD {tle_norad}, not requested NORAD {norad_id}"
            )
        digest = hashlib.sha256(
            f"{payload.line1}\n{payload.line2}".encode("utf-8")
        ).hexdigest()
        existing = self.session.scalar(
            select(ElementSetRecord).where(
                ElementSetRecord.space_object_id == space_object.id,
                ElementSetRecord.content_sha256 == digest,
            )
        )
        if existing is not None:
            return existing
        record = ElementSetRecord(
            space_object_id=space_object.id,
            line1=payload.line1,
            line2=payload.line2,
            epoch=parse_tle_epoch(payload.line1),
            source=payload.source,
            quality=payload.quality,
            parser_version=payload.parser_version,
            content_sha256=digest,
            raw_payload_uri=payload.raw_payload_uri,
        )
        self.session.add(record)
        self.session.flush()
        self._lineage(
            "SpaceObject",
            space_object.id,
            "ElementSet",
            record.id,
            "has_element_set",
            transformation=payload.parser_version,
        )
        self._commit()
        return record

    def list_element_sets(self, norad_id: str, limit: int = 100) -> list[ElementSetRecord]:
        space_object = self.get_space_object_by_norad(norad_id)
        return list(
            self.session.scalars(
                select(ElementSetRecord)
                .where(ElementSetRecord.space_object_id == space_object.id)
                .order_by(desc(ElementSetRecord.epoch))
                .limit(limit)
            )
        )

    # ----------------------------------------------------------- screening/run
    def create_screening_run(self, payload: ScreeningRunCreate) -> ScreeningRunRecord:
        record = ScreeningRunRecord(
            propagator=payload.propagator,
            propagator_version=payload.propagator_version,
            configuration=payload.configuration,
            input_versions=payload.input_versions,
        )
        self.session.add(record)
        self._commit()
        return record

    def create_event(self, payload: ConjunctionEventCreate) -> ConjunctionEventRecord:
        primary = self.get_space_object_by_norad(payload.primary_norad_id)
        secondary = self.get_space_object_by_norad(payload.secondary_norad_id)
        if payload.screening_run_id:
            self._get(ScreeningRunRecord, payload.screening_run_id, "Screening run")
        record = ConjunctionEventRecord(
            screening_run_id=payload.screening_run_id,
            primary_object_id=primary.id,
            secondary_object_id=secondary.id,
            tca=payload.tca,
            miss_distance_km=payload.miss_distance_km,
            relative_speed_km_s=payload.relative_speed_km_s,
            radial_km=payload.radial_km,
            along_track_km=payload.along_track_km,
            cross_track_km=payload.cross_track_km,
            status=payload.status.value,
        )
        self.session.add(record)
        self.session.flush()
        for obj in (primary, secondary):
            self._lineage(
                "SpaceObject",
                obj.id,
                "ConjunctionEvent",
                record.id,
                "involved_in",
                run_id=payload.screening_run_id,
            )
        if payload.screening_run_id:
            self._lineage(
                "ScreeningRun",
                payload.screening_run_id,
                "ConjunctionEvent",
                record.id,
                "produced",
                transformation="conjunction-screening",
                run_id=payload.screening_run_id,
            )
        self._commit()
        return record

    def list_events(
        self,
        *,
        status: str | None = None,
        norad_id: str | None = None,
        limit: int = 100,
    ) -> list[ConjunctionEventRecord]:
        statement = select(ConjunctionEventRecord).order_by(ConjunctionEventRecord.tca)
        if status:
            statement = statement.where(ConjunctionEventRecord.status == status)
        if norad_id:
            space_object = self.get_space_object_by_norad(norad_id)
            statement = statement.where(
                or_(
                    ConjunctionEventRecord.primary_object_id == space_object.id,
                    ConjunctionEventRecord.secondary_object_id == space_object.id,
                )
            )
        return list(self.session.scalars(statement.limit(limit)))

    def add_assessment(
        self, event_id: str, payload: RiskAssessmentCreate
    ) -> RiskAssessmentRecord:
        self._get(ConjunctionEventRecord, event_id, "Conjunction event")
        record = RiskAssessmentRecord(
            event_id=event_id,
            tier=payload.tier.value,
            probability_of_collision=payload.probability_of_collision,
            uncertainty=payload.uncertainty,
            model_version=payload.model_version,
            explanation=payload.explanation,
        )
        self.session.add(record)
        self.session.flush()
        self._lineage(
            "ConjunctionEvent",
            event_id,
            "RiskAssessment",
            record.id,
            "has_assessment",
            transformation=payload.model_version,
        )
        self._commit()
        return record

    # -------------------------------------------------------------- operations
    def open_case(
        self,
        event_id: str,
        payload: MonitoringCaseCreate,
        *,
        actor: str,
        justification: str,
    ) -> MonitoringCaseRecord:
        event = self._get(ConjunctionEventRecord, event_id, "Conjunction event")
        record = MonitoringCaseRecord(
            event_id=event_id,
            title=payload.title,
            priority=payload.priority.value,
            assignee=payload.assignee,
            due_at=payload.due_at,
        )
        event.status = EventStatus.UNDER_REVIEW.value
        self.session.add(record)
        self.session.flush()
        self._lineage(
            "ConjunctionEvent", event_id, "MonitoringCase", record.id, "opens"
        )
        request = CaseActionRequest(actor=actor, justification=justification)
        self._audit(
            ActionType.OPEN_CASE,
            actor,
            "MonitoringCase",
            record.id,
            request,
            {},
            record_state(record),
            payload.model_dump(mode="json"),
        )
        self._commit()
        return record

    def list_cases(self, status: str | None = None) -> list[MonitoringCaseRecord]:
        statement = select(MonitoringCaseRecord).order_by(
            MonitoringCaseRecord.priority, MonitoringCaseRecord.created_at
        )
        if status:
            statement = statement.where(MonitoringCaseRecord.status == status)
        return list(self.session.scalars(statement))

    def apply_case_action(
        self, case_id: str, action: ActionType, payload: CaseActionRequest
    ) -> MonitoringCaseRecord:
        case = self._get(MonitoringCaseRecord, case_id, "Monitoring case")
        previous = record_state(case)
        if action is ActionType.ASSIGN_CASE:
            if not payload.assignee:
                raise InvalidActionError("assign_case requires an assignee")
            case.assignee = payload.assignee
            case.status = CaseStatus.INVESTIGATING.value
        elif action is ActionType.ESCALATE_EVENT:
            case.priority = (payload.priority or Priority.P0).value
            case.status = CaseStatus.INVESTIGATING.value
            event = self._get(ConjunctionEventRecord, case.event_id, "Conjunction event")
            event.status = EventStatus.UNDER_REVIEW.value
        elif action is ActionType.CLOSE_CASE:
            case.status = CaseStatus.CLOSED.value
            case.closed_at = utcnow()
            event = self._get(ConjunctionEventRecord, case.event_id, "Conjunction event")
            event.status = EventStatus.CLOSED.value
        elif action in {
            ActionType.REQUEST_ORBIT_REFRESH,
            ActionType.RERUN_SCREENING,
            ActionType.NOTIFY_OWNER,
        }:
            pass  # Request is captured immutably; a worker consumes it later.
        else:
            raise InvalidActionError(f"{action.value} is not a supported case action")
        self.session.flush()
        self._audit(
            action,
            payload.actor,
            "MonitoringCase",
            case.id,
            payload,
            previous,
            record_state(case),
            payload.model_dump(mode="json"),
        )
        self._commit()
        return case

    def create_alert(self, payload: AlertCreate) -> AlertRecord:
        self._get(ConjunctionEventRecord, payload.event_id, "Conjunction event")
        record = AlertRecord(
            event_id=payload.event_id,
            rule=payload.rule,
            channel=payload.channel,
            delivery_status=payload.delivery_status.value,
        )
        self.session.add(record)
        self._commit()
        return record

    def acknowledge_alert(
        self, alert_id: str, payload: AcknowledgeAlertRequest
    ) -> AlertRecord:
        alert = self._get(AlertRecord, alert_id, "Alert")
        previous = record_state(alert)
        alert.delivery_status = DeliveryStatus.ACKNOWLEDGED.value
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by = payload.actor
        self.session.flush()
        request = CaseActionRequest(actor=payload.actor, justification=payload.justification)
        self._audit(
            ActionType.ACKNOWLEDGE_ALERT,
            payload.actor,
            "Alert",
            alert.id,
            request,
            previous,
            record_state(alert),
            payload.model_dump(mode="json"),
        )
        self._commit()
        return alert

    def record_decision(
        self, case_id: str, payload: OperatorDecisionCreate
    ) -> OperatorDecisionRecord:
        self._get(MonitoringCaseRecord, case_id, "Monitoring case")
        decision = OperatorDecisionRecord(
            case_id=case_id,
            selected_action=payload.selected_action,
            justification=payload.justification,
            actor=payload.actor,
            approver=payload.approver,
            approval_status=payload.approval_status.value,
        )
        self.session.add(decision)
        self.session.flush()
        self._lineage(
            "MonitoringCase", case_id, "OperatorDecision", decision.id, "contains"
        )
        self._audit(
            ActionType.RECORD_DECISION,
            payload.actor,
            "OperatorDecision",
            decision.id,
            payload,
            {},
            record_state(decision),
            payload.model_dump(mode="json"),
        )
        self._commit()
        return decision

    def create_maneuver(
        self, event_id: str, payload: ManeuverScenarioCreate
    ) -> ManeuverScenarioRecord:
        self._get(ConjunctionEventRecord, event_id, "Conjunction event")
        space_object = self.get_space_object_by_norad(payload.space_object_norad_id)
        record = ManeuverScenarioRecord(
            event_id=event_id,
            space_object_id=space_object.id,
            proposed_at=payload.proposed_at,
            delta_v_r_m_s=payload.delta_v_r_m_s,
            delta_v_i_m_s=payload.delta_v_i_m_s,
            delta_v_c_m_s=payload.delta_v_c_m_s,
            simulation_model_version=payload.simulation_model_version,
            assumptions=payload.assumptions,
        )
        self.session.add(record)
        self.session.flush()
        self._lineage(
            "ManeuverScenario", record.id, "ConjunctionEvent", event_id, "mitigates"
        )
        request = CaseActionRequest(
            actor=payload.actor,
            justification=payload.justification,
            model_versions={"simulation": payload.simulation_model_version},
        )
        self._audit(
            ActionType.CREATE_MANEUVER_SCENARIO,
            payload.actor,
            "ManeuverScenario",
            record.id,
            request,
            {},
            record_state(record),
            payload.model_dump(mode="json"),
        )
        self._commit()
        return record

    def add_observation(
        self, norad_id: str, payload: SensorObservationCreate
    ) -> SensorObservationRecord:
        space_object = self.get_space_object_by_norad(norad_id)
        record = SensorObservationRecord(
            space_object_id=space_object.id,
            **payload.model_dump(),
        )
        self.session.add(record)
        self.session.flush()
        self._lineage(
            "SpaceObject",
            space_object.id,
            "SensorObservation",
            record.id,
            "has_observation",
            transformation=payload.source,
        )
        self._commit()
        return record

    # -------------------------------------------------------------- governance
    def list_audit_actions(
        self, entity_type: str | None = None, entity_id: str | None = None
    ) -> list[AuditActionRecord]:
        statement = select(AuditActionRecord).order_by(desc(AuditActionRecord.occurred_at))
        if entity_type:
            statement = statement.where(AuditActionRecord.entity_type == entity_type)
        if entity_id:
            statement = statement.where(AuditActionRecord.entity_id == entity_id)
        return list(self.session.scalars(statement.limit(500)))

    def lineage_for(self, entity_type: str, entity_id: str) -> list[LineageEdgeRecord]:
        return list(
            self.session.scalars(
                select(LineageEdgeRecord)
                .where(
                    or_(
                        (
                            (LineageEdgeRecord.upstream_type == entity_type)
                            & (LineageEdgeRecord.upstream_id == entity_id)
                        ),
                        (
                            (LineageEdgeRecord.downstream_type == entity_type)
                            & (LineageEdgeRecord.downstream_id == entity_id)
                        ),
                    )
                )
                .order_by(LineageEdgeRecord.created_at)
            )
        )
