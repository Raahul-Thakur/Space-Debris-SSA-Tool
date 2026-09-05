"""Bridge existing screening outputs into the persistent operational ontology."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version

from sqlalchemy.orm import Session

from sdebris.config import Config
from sdebris.models import SpaceObject
from sdebris.ontology.enums import Priority, ScreeningRunStatus
from sdebris.ontology.orm import utcnow
from sdebris.ontology.schemas import (
    ConjunctionEventCreate,
    ElementSetCreate,
    MonitoringCaseCreate,
    RiskAssessmentCreate,
    ScreeningRunCreate,
    SpaceObjectCreate,
)
from sdebris.ontology.service import OntologyService
from sdebris.screening.screen import ScreeningResult


@dataclass(frozen=True)
class PersistenceSummary:
    screening_run_id: str
    objects_versioned: int
    events_created: int
    cases_opened: int


def persist_screening_result(
    session: Session,
    result: ScreeningResult,
    catalog: list[SpaceObject],
    config: Config,
) -> PersistenceSummary:
    """Persist a completed screening result with input versions and lineage."""
    # A catalog can contain thousands of objects. Flush records as they are
    # created, but commit the complete run atomically only once at the end.
    service = OntologyService(session, auto_commit=False)
    input_versions: dict[str, str] = {}

    for obj in catalog:
        ontology_object = service.get_space_object_by_norad(obj.norad_id, required=False)
        if ontology_object is None:
            ontology_object = service.create_space_object(
                SpaceObjectCreate(
                    norad_id=obj.norad_id,
                    name=obj.name,
                    status="active",
                    metadata_json={"source_model": "TLE"},
                )
            )
        element = service.add_element_set(
            obj.norad_id,
            ElementSetCreate(
                line1=obj.line1,
                line2=obj.line2,
                source="screening-input",
                parser_version="sdebris-tle-v1",
            ),
        )
        input_versions[obj.norad_id] = element.id

    run = service.create_screening_run(
        ScreeningRunCreate(
            propagator="SGP4",
            propagator_version=version("sgp4"),
            configuration=config.model_dump(mode="json"),
            input_versions=input_versions,
        )
    )
    run.status = ScreeningRunStatus.SUCCEEDED.value
    run.completed_at = utcnow()
    session.flush()

    cases_opened = 0
    for event in result.events:
        event_record = service.create_event(
            ConjunctionEventCreate(
                primary_norad_id=event.target_norad,
                secondary_norad_id=event.secondary_norad,
                screening_run_id=run.id,
                tca=event.tca,
                miss_distance_km=event.miss_distance_km,
                relative_speed_km_s=event.relative_speed_km_s,
                radial_km=event.radial_km,
                along_track_km=event.along_track_km,
                cross_track_km=event.cross_track_km,
            )
        )
        service.add_assessment(
            event_record.id,
            RiskAssessmentCreate(
                tier=event.risk_tier,
                probability_of_collision=event.probability_of_collision,
                uncertainty={
                    "source": "synthetic_age_weighted_RIC",
                    "target_tle_age_days": event.target_tle_age_days,
                    "secondary_tle_age_days": event.secondary_tle_age_days,
                    "secondary_stale": event.secondary_stale,
                },
                model_version="foster-chan-v1",
                explanation=event.risk_reason,
            ),
        )
        if event.risk_tier == "critical":
            service.open_case(
                event_record.id,
                MonitoringCaseCreate(
                    title=f"Review {event.target_name} / {event.secondary_name}",
                    priority=Priority.P0,
                ),
                actor="screening-engine",
                justification="Critical conjunction threshold was exceeded.",
            )
            cases_opened += 1

    session.commit()
    return PersistenceSummary(
        screening_run_id=run.id,
        objects_versioned=len(input_versions),
        events_created=len(result.events),
        cases_opened=cases_opened,
    )
