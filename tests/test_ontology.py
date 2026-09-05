from datetime import datetime, timezone

from sdebris.ontology import Database, OntologyService
from sdebris.config import load_config
from sdebris.models import SpaceObject
from sdebris.ontology import persist_screening_result
from sdebris.ontology.enums import ActionType
from sdebris.ontology.schemas import (
    CaseActionRequest,
    ConjunctionEventCreate,
    ElementSetCreate,
    MonitoringCaseCreate,
    OperatorDecisionCreate,
    RiskAssessmentCreate,
    ScreeningRunCreate,
    SpaceObjectCreate,
)
from sdebris.screening.screen import ConjunctionEvent, ScreeningResult

ISS_L1 = "1 25544U 98067A   24001.00000000  .00016717  00000+0  10270-3 0  9003"
ISS_L2 = "2 25544  51.6421  10.3493 0006703  88.3949  31.2568 15.50015354  9008"


def _service(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'ontology.db').as_posix()}")
    database.initialize()
    session = database.session_factory()
    return database, session, OntologyService(session)


def test_element_sets_are_append_only_and_lineaged(tmp_path) -> None:
    database, session, service = _service(tmp_path)
    try:
        obj = service.create_space_object(
            SpaceObjectCreate(norad_id="25544", name="ISS", orbit_class="LEO")
        )
        first = service.add_element_set(
            "25544",
            ElementSetCreate(line1=ISS_L1, line2=ISS_L2, source="test"),
        )
        duplicate = service.add_element_set(
            "25544",
            ElementSetCreate(line1=ISS_L1, line2=ISS_L2, source="test"),
        )
        newer_line1 = ISS_L1.replace("24001.00000000", "24002.00000000")
        second = service.add_element_set(
            "25544",
            ElementSetCreate(line1=newer_line1, line2=ISS_L2, source="test"),
        )

        assert duplicate.id == first.id
        assert second.id != first.id
        assert len(service.list_element_sets("25544")) == 2
        lineage = service.lineage_for("SpaceObject", obj.id)
        assert [edge.relationship for edge in lineage] == [
            "has_element_set",
            "has_element_set",
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_operational_actions_capture_before_after_audit(tmp_path) -> None:
    database, session, service = _service(tmp_path)
    try:
        service.create_space_object(
            SpaceObjectCreate(norad_id="25544", name="ISS", orbit_class="LEO")
        )
        service.create_space_object(
            SpaceObjectCreate(norad_id="99999", name="TEST DEBRIS", orbit_class="LEO")
        )
        run = service.create_screening_run(
            ScreeningRunCreate(
                propagator_version="sgp4-test",
                configuration={"window_hours": 24},
                input_versions={"25544": "element-a", "99999": "element-b"},
            )
        )
        event = service.create_event(
            ConjunctionEventCreate(
                primary_norad_id="25544",
                secondary_norad_id="99999",
                screening_run_id=run.id,
                tca=datetime(2026, 1, 1, tzinfo=timezone.utc),
                miss_distance_km=0.8,
                relative_speed_km_s=12.0,
            )
        )
        assessment = service.add_assessment(
            event.id,
            RiskAssessmentCreate(
                tier="critical",
                probability_of_collision=2e-4,
                model_version="foster-chan-v1",
                explanation="Miss distance and Pc exceed critical thresholds.",
            ),
        )
        case = service.open_case(
            event.id,
            MonitoringCaseCreate(title="Review ISS encounter", priority="P0"),
            actor="system",
            justification="Critical screening result",
        )
        assigned = service.apply_case_action(
            case.id,
            ActionType.ASSIGN_CASE,
            CaseActionRequest(
                actor="ops-lead",
                assignee="analyst-1",
                justification="Analyst is on the current shift",
                data_versions={"screening_run": run.id},
                model_versions={"risk": assessment.model_version},
            ),
        )
        decision = service.record_decision(
            case.id,
            OperatorDecisionCreate(
                selected_action="continue_tracking",
                justification="Await a fresher element set before scenario planning",
                actor="analyst-1",
                approver="ops-lead",
                approval_status="approved",
                data_versions={"screening_run": run.id},
                model_versions={"risk": assessment.model_version},
            ),
        )

        assert assigned.assignee == "analyst-1"
        assert assigned.status == "investigating"
        assert decision.case_id == case.id
        audits = service.list_audit_actions()
        assert [audit.action_type for audit in audits] == [
            "record_decision",
            "assign_case",
            "open_case",
        ]
        assign_audit = audits[1]
        assert assign_audit.previous_state["assignee"] is None
        assert assign_audit.new_state["assignee"] == "analyst-1"
        assert assign_audit.data_versions["screening_run"] == run.id
        case_lineage = service.lineage_for("MonitoringCase", case.id)
        assert {edge.relationship for edge in case_lineage} == {"opens", "contains"}
    finally:
        session.close()
        database.engine.dispose()


def test_screening_bridge_versions_inputs_and_opens_critical_case(tmp_path) -> None:
    database, session, service = _service(tmp_path)
    try:
        secondary_l1 = ISS_L1.replace("25544", "99999")
        secondary_l2 = ISS_L2.replace("25544", "99999")
        catalog = [
            SpaceObject("25544", "ISS", ISS_L1, ISS_L2),
            SpaceObject("99999", "TEST DEBRIS", secondary_l1, secondary_l2),
        ]
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        event = ConjunctionEvent(
            target_norad="25544",
            target_name="ISS",
            secondary_norad="99999",
            secondary_name="TEST DEBRIS",
            tca=now,
            miss_distance_km=0.5,
            relative_speed_km_s=12.0,
            radial_km=0.1,
            along_track_km=0.2,
            cross_track_km=0.1,
            probability_of_collision=2e-4,
            risk_tier="critical",
            risk_reason="critical test event",
            target_tle_age_days=1.0,
            secondary_tle_age_days=2.0,
            secondary_stale=False,
        )
        result = ScreeningResult(
            target_norad="25544",
            target_name="ISS",
            generated_at=now,
            window_start=now,
            window_hours=24,
            step_sec=60,
            report_threshold_km=25,
            n_screened=1,
            n_stale=0,
            events=[event],
        )

        summary = persist_screening_result(session, result, catalog, load_config())

        assert summary.objects_versioned == 2
        assert summary.events_created == 1
        assert summary.cases_opened == 1
        assert len(service.list_cases()) == 1
        assert len(service.list_audit_actions()) == 1
    finally:
        session.close()
        database.engine.dispose()
