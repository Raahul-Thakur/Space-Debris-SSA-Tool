"""FastAPI surface for the SSA ontology and governed operational actions."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from sdebris import __version__
from sdebris.activity import MAX_FEED_ITEMS, collect_activity, feed_cursor
from sdebris.auth import Authenticator, PrincipalDep, require_role
from sdebris.commands import CommandParseError, parse_command
from sdebris.commands.parser import COMMAND_HELP
from sdebris.config import load_config
from sdebris.ingest.celestrak import CelesTrakClient
from sdebris.jobs import ScreeningJobManager
from sdebris.models import SpaceObject
from sdebris.monitoring import seed_well_known_objects
from sdebris.ontology import (
    ConflictError,
    Database,
    InvalidActionError,
    NotFoundError,
    OntologyService,
)
from sdebris.ontology.enums import ActionType, JobStatus, OperatorRole
from sdebris.ontology.orm import (
    CommandExecutionRecord,
    ConjunctionEventRecord,
    ElementSetRecord,
    MonitoredObjectRecord,
    RiskAssessmentRecord,
    ScreeningJobEventRecord,
    ScreeningJobRecord,
    SpaceObjectRecord,
)
from sdebris.ontology.schemas import (
    AcknowledgeAlertRequest,
    AlertCreate,
    AlertView,
    AuditActionView,
    CaseActionRequest,
    CommandRequest,
    CommandResponse,
    ConjunctionEventCreate,
    ConjunctionEventView,
    ElementSetCreate,
    ElementSetView,
    LineageEdgeView,
    ManeuverScenarioCreate,
    ManeuverScenarioView,
    MonitoringCaseView,
    MonitoredObjectView,
    OntologyDescription,
    OpenCaseRequest,
    OperatorDecisionCreate,
    OperatorDecisionView,
    RiskAssessmentCreate,
    RiskAssessmentView,
    ScreeningRunCreate,
    ScreeningRunView,
    ScreeningJobCreate,
    ScreeningJobEventView,
    ScreeningJobView,
    SensorObservationCreate,
    SensorObservationView,
    SpaceObjectCreate,
    SpaceObjectUpdate,
    SpaceObjectView,
    TrajectoryPoint,
    TrajectoryResponse,
)
from sdebris.propagation import make_time_grid, propagate_objects
from sdebris.runtime import configure_logging, request_log_middleware, validate_environment


#: Seconds between activity-feed reads on an open SSE connection.
ACTIVITY_POLL_SECONDS = 2.0
#: How far back a client with no cursor is replayed when it first connects.
ACTIVITY_REPLAY_HOURS = 6

ONTOLOGY = OntologyDescription(
    object_types={
        "SpaceObject": ["norad_id", "owner", "orbit_class", "status"],
        "ElementSet": ["epoch", "source", "quality", "ingested_at", "content_sha256"],
        "Ephemeris": ["timestamp", "position", "velocity", "frame", "run"],
        "ConjunctionEvent": ["primary", "secondary", "tca", "miss_distance", "status"],
        "RiskAssessment": ["tier", "probability_of_collision", "model_version"],
        "MonitoringCase": ["status", "priority", "assignee", "due_at"],
        "SensorObservation": ["sensor", "observed_at", "state", "quality"],
        "ManeuverScenario": ["delta_v", "proposed_at", "resulting_risk", "status"],
        "Alert": ["rule", "channel", "delivery_status", "acknowledgement"],
        "OperatorDecision": ["selected_action", "justification", "approval_status"],
    },
    relationships=[
        "SpaceObject has ElementSet",
        "SpaceObject involved_in ConjunctionEvent",
        "ConjunctionEvent has RiskAssessment",
        "ConjunctionEvent opens MonitoringCase",
        "MonitoringCase contains OperatorDecision",
        "ManeuverScenario mitigates ConjunctionEvent",
    ],
    actions=[action.value for action in ActionType],
)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def _assessed_events(session: Session, tier: str | None = None) -> dict[str, object]:
    """Conjunctions joined to their latest risk tier, ordered by TCA."""
    statement = (
        select(ConjunctionEventRecord, RiskAssessmentRecord)
        .outerjoin(
            RiskAssessmentRecord,
            RiskAssessmentRecord.event_id == ConjunctionEventRecord.id,
        )
        .order_by(ConjunctionEventRecord.tca)
        .limit(100)
    )
    if tier:
        statement = statement.where(RiskAssessmentRecord.tier == tier)
    rows = session.execute(statement).all()
    return {
        "events": [
            {
                "id": event.id,
                "tca": event.tca.isoformat(),
                "miss_distance_km": event.miss_distance_km,
                "tier": assessment.tier if assessment else "unassessed",
                "probability_of_collision": (
                    assessment.probability_of_collision if assessment else None
                ),
            }
            for event, assessment in rows
        ]
    }


def _event_explanation(event_id: str, session: Session) -> dict[str, object]:
    event = session.get(ConjunctionEventRecord, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    assessment = session.scalar(
        select(RiskAssessmentRecord)
        .where(RiskAssessmentRecord.event_id == event_id)
        .order_by(RiskAssessmentRecord.created_at.desc())
        .limit(1)
    )
    primary = session.get(SpaceObjectRecord, event.primary_object_id)
    secondary = session.get(SpaceObjectRecord, event.secondary_object_id)
    return {
        "event_id": event.id,
        "primary": {
            "norad_id": primary.norad_id if primary else None,
            "name": primary.name if primary else "Unknown",
        },
        "secondary": {
            "norad_id": secondary.norad_id if secondary else None,
            "name": secondary.name if secondary else "Unknown",
        },
        "tca": event.tca.isoformat(),
        "miss_distance_km": event.miss_distance_km,
        "relative_speed_km_s": event.relative_speed_km_s,
        "tier": assessment.tier if assessment else "unassessed",
        "probability_of_collision": (
            assessment.probability_of_collision if assessment else None
        ),
        "explanation": (
            assessment.explanation
            if assessment
            else "This event has not yet received a risk assessment."
        ),
        "model_version": assessment.model_version if assessment else None,
    }


def _refresh_orbit(norad_id: str, session: Session) -> dict[str, object]:
    config = load_config()
    fetched = CelesTrakClient(
        base_url=config.ingestion.base_url
    ).fetch_catnr(norad_id)
    if not fetched:
        raise HTTPException(status_code=404, detail=f"NORAD {norad_id} not found")
    domain_object = fetched[0]
    service = OntologyService(session)
    obj = service.get_space_object_by_norad(norad_id, required=False)
    if obj is None:
        obj = service.create_space_object(
            SpaceObjectCreate(
                norad_id=norad_id,
                name=domain_object.name,
                status="active",
                metadata_json={"source_model": "TLE"},
            )
        )
    element = service.add_element_set(
        norad_id,
        ElementSetCreate(
            line1=domain_object.line1,
            line2=domain_object.line2,
            source=f"catnr:{norad_id}",
            parser_version="sdebris-tle-v1",
        ),
    )
    return {
        "norad_id": norad_id,
        "name": obj.name,
        "element_set_id": element.id,
        "epoch": element.epoch.isoformat(),
    }


def _execute_immediate_action(
    action: str, arguments: dict[str, object], actor: str, session: Session
) -> dict[str, object]:
    if action == "orbit.refresh":
        return _refresh_orbit(str(arguments["norad_id"]), session)
    if action == "monitor.add":
        norad_id = str(arguments["norad_id"])
        obj = session.scalar(
            select(SpaceObjectRecord).where(SpaceObjectRecord.norad_id == norad_id)
        )
        if obj is None:
            _refresh_orbit(norad_id, session)
            obj = session.scalar(
                select(SpaceObjectRecord).where(SpaceObjectRecord.norad_id == norad_id)
            )
        existing = session.scalar(
            select(MonitoredObjectRecord).where(
                MonitoredObjectRecord.space_object_id == obj.id
            )
        )
        if existing:
            existing.active = True
            existing.added_by = actor
            monitor = existing
        else:
            monitor = MonitoredObjectRecord(space_object_id=obj.id, added_by=actor)
            session.add(monitor)
        session.flush()
        return {"monitor_id": monitor.id, "norad_id": norad_id, "name": obj.name}
    if action == "monitor.seed-known":
        return seed_well_known_objects(session, actor)
    if action == "events.list":
        tier = arguments.get("tier")
        return _assessed_events(session, None if tier is None else str(tier))
    if action == "event.explain":
        return _event_explanation(str(arguments["event_id"]), session)
    if action == "case.assign":
        case = OntologyService(session).apply_case_action(
            str(arguments["case_id"]),
            ActionType.ASSIGN_CASE,
            CaseActionRequest(
                actor=actor,
                justification="Assigned from governed command console.",
                assignee=str(arguments["assignee"]),
            ),
        )
        return {"case_id": case.id, "status": case.status, "assignee": case.assignee}
    if action == "case.close":
        case = OntologyService(session).apply_case_action(
            str(arguments["case_id"]),
            ActionType.CLOSE_CASE,
            CaseActionRequest(
                actor=actor,
                justification=str(arguments["reason"]),
            ),
        )
        return {"case_id": case.id, "status": case.status}
    raise HTTPException(status_code=422, detail=f"unsupported action: {action}")


def create_app(database_url: str | None = None) -> FastAPI:
    configure_logging()
    validate_environment()
    database = Database(database_url)
    jobs = ScreeningJobManager(database.session_factory)
    authenticator = Authenticator()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.initialize()
        yield
        jobs.shutdown()
        database.engine.dispose()

    app = FastAPI(
        title="Space Debris SSA Ontology API",
        version=__version__,
        description=(
            "Typed operational objects, lineage, cases, decisions, and governed actions "
            "for space situational awareness."
        ),
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.jobs = jobs
    app.state.authenticator = authenticator
    app.middleware("http")(request_log_middleware)
    allowed_origins = os.getenv(
        "SDEBRIS_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    # Vercel gives every preview deployment its own hostname, which cannot be
    # enumerated ahead of time. This optional pattern lets those origins through
    # without widening the allowlist to everything; it is unset by default.
    origin_regex = os.getenv("SDEBRIS_CORS_ORIGIN_REGEX", "").strip() or None
    if origin_regex is not None:
        try:
            re.compile(origin_regex)
        except re.error as exc:
            raise RuntimeError(
                f"SDEBRIS_CORS_ORIGIN_REGEX is not a valid regular expression: {exc}"
            ) from exc
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_handler(_request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidActionError)
    async def invalid_action_handler(
        _request: Request, exc: InvalidActionError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    def ready(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ready", "version": __version__}

    @app.get("/auth/me")
    def auth_me(principal: PrincipalDep) -> dict[str, str | None]:
        return {
            "subject": principal.subject,
            "email": principal.email,
            "role": principal.role.value,
        }

    @app.post("/auth/development-token")
    def development_token() -> dict[str, str]:
        return {"access_token": authenticator.issue_development_token()}

    @app.get("/ontology", response_model=OntologyDescription)
    def describe_ontology() -> OntologyDescription:
        return ONTOLOGY

    @app.get("/methodology")
    def methodology() -> dict[str, object]:
        return {
            "operational_use": False,
            "purpose": "Education, portfolio demonstration, and community review",
            "orbit_source": "Public two-line element sets (TLE)",
            "propagator": "SGP4 in the TEME frame",
            "covariance": "Synthetic age-weighted RIC covariance",
            "probability_model": "Illustrative Foster/Chan-style estimate",
            "limitations": [
                "No authoritative covariance messages are ingested",
                "TLE accuracy degrades with age and maneuver activity",
                "Results must not drive operational collision-avoidance decisions",
            ],
            "documentation": "/docs/methodology",
        }

    # --------------------------------------------------------------- objects
    @app.post("/objects", response_model=SpaceObjectView, status_code=201)
    def create_object(payload: SpaceObjectCreate, session: SessionDep, principal: PrincipalDep):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).create_space_object(payload)

    @app.get("/objects", response_model=list[SpaceObjectView])
    def list_objects(
        session: SessionDep,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ):
        return OntologyService(session).list_space_objects(limit, offset)

    @app.get("/objects/{norad_id}", response_model=SpaceObjectView)
    def get_object(norad_id: str, session: SessionDep):
        return OntologyService(session).get_space_object_by_norad(norad_id)

    @app.patch("/objects/{norad_id}", response_model=SpaceObjectView)
    def update_object(
        norad_id: str, payload: SpaceObjectUpdate, session: SessionDep, principal: PrincipalDep
    ):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).update_space_object(norad_id, payload)

    @app.post(
        "/objects/{norad_id}/element-sets",
        response_model=ElementSetView,
        status_code=201,
    )
    def add_element_set(
        norad_id: str, payload: ElementSetCreate, session: SessionDep, principal: PrincipalDep
    ):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).add_element_set(norad_id, payload)

    @app.get(
        "/objects/{norad_id}/element-sets", response_model=list[ElementSetView]
    )
    def list_element_sets(
        norad_id: str,
        session: SessionDep,
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return OntologyService(session).list_element_sets(norad_id, limit)

    @app.post(
        "/objects/{norad_id}/observations",
        response_model=SensorObservationView,
        status_code=201,
    )
    def add_observation(
        norad_id: str, payload: SensorObservationCreate, session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).add_observation(norad_id, payload)

    # --------------------------------------------------------------- analysis
    @app.post("/screening-runs", response_model=ScreeningRunView, status_code=201)
    def create_screening_run(
        payload: ScreeningRunCreate, session: SessionDep, principal: PrincipalDep
    ):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).create_screening_run(payload)

    @app.post("/events", response_model=ConjunctionEventView, status_code=201)
    def create_event(
        payload: ConjunctionEventCreate, session: SessionDep, principal: PrincipalDep
    ):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).create_event(payload)

    @app.get("/events/assessed")
    def list_assessed_events(
        session: SessionDep, principal: PrincipalDep, tier: str | None = None
    ) -> dict[str, object]:
        """Read-only equivalent of `events list`, for dashboard polling."""
        require_role(principal, OperatorRole.VIEWER)
        return _assessed_events(session, tier)

    @app.get("/events", response_model=list[ConjunctionEventView])
    def list_events(
        session: SessionDep,
        status: str | None = None,
        norad_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        return OntologyService(session).list_events(
            status=status, norad_id=norad_id, limit=limit
        )

    # ---------------------------------------------------------- command center
    @app.post("/screening-jobs", response_model=ScreeningJobView, status_code=202)
    def create_screening_job(payload: ScreeningJobCreate, principal: PrincipalDep):
        require_role(principal, OperatorRole.ANALYST)
        payload = payload.model_copy(update={"actor": principal.actor})
        return jobs.create(payload)

    @app.get("/screening-jobs", response_model=list[ScreeningJobView])
    def list_screening_jobs(
        session: SessionDep,
        principal: PrincipalDep,
        limit: int = Query(default=25, ge=1, le=200),
    ):
        return list(
            session.scalars(
                select(ScreeningJobRecord)
                .order_by(ScreeningJobRecord.created_at.desc())
                .limit(limit)
            )
        )

    @app.get("/screening-jobs/{job_id}", response_model=ScreeningJobView)
    def get_screening_job(job_id: str, session: SessionDep, principal: PrincipalDep):
        job = session.get(ScreeningJobRecord, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="screening job not found")
        return job

    @app.post("/screening-jobs/{job_id}/cancel", response_model=ScreeningJobView)
    def cancel_screening_job(job_id: str, principal: PrincipalDep):
        require_role(principal, OperatorRole.ANALYST)
        job = jobs.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="screening job not found")
        return job

    @app.get("/screening-jobs/{job_id}/events")
    async def stream_screening_job_events(
        job_id: str, request: Request, principal: PrincipalDep
    ):
        with database.session_factory() as session:
            if session.get(ScreeningJobRecord, job_id) is None:
                raise HTTPException(status_code=404, detail="screening job not found")

        async def event_stream():
            last_sequence = 0
            while not await request.is_disconnected():
                with database.session_factory() as session:
                    events = list(
                        session.scalars(
                            select(ScreeningJobEventRecord)
                            .where(
                                ScreeningJobEventRecord.job_id == job_id,
                                ScreeningJobEventRecord.sequence > last_sequence,
                            )
                            .order_by(ScreeningJobEventRecord.sequence)
                        )
                    )
                    job = session.get(ScreeningJobRecord, job_id)
                    for event in events:
                        last_sequence = event.sequence
                        data = ScreeningJobEventView.model_validate(event).model_dump(
                            mode="json"
                        )
                        yield (
                            f"id: {event.sequence}\nevent: progress\n"
                            f"data: {json.dumps(data)}\n\n"
                        )
                    terminal = job and job.status in {
                        JobStatus.SUCCEEDED.value,
                        JobStatus.FAILED.value,
                        JobStatus.CANCELLED.value,
                    }
                if terminal and not events:
                    break
                yield ": keep-alive\n\n"
                await asyncio.sleep(0.75)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/commands/help")
    def command_help() -> dict[str, object]:
        return {
            "commands": COMMAND_HELP,
            "security": "Commands are parsed against an allowlist and never passed to a shell.",
        }

    @app.post("/commands/execute", response_model=CommandResponse)
    def execute_command(
        payload: CommandRequest, principal: PrincipalDep, session: SessionDep
    ):
        try:
            plan = parse_command(payload.command, principal.role)
        except PermissionError as exc:
            session.add(
                CommandExecutionRecord(
                    actor=principal.actor,
                    role=principal.role.value,
                    raw_command=payload.command,
                    parsed_action="rejected",
                    arguments={},
                    status=JobStatus.FAILED.value,
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except CommandParseError as exc:
            session.add(
                CommandExecutionRecord(
                    actor=principal.actor,
                    role=principal.role.value,
                    raw_command=payload.command,
                    parsed_action="rejected",
                    arguments={},
                    status=JobStatus.FAILED.value,
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if plan.action == "case.close" and not payload.confirmed:
            session.add(
                CommandExecutionRecord(
                    actor=principal.actor,
                    role=principal.role.value,
                    raw_command=payload.command,
                    parsed_action=plan.action,
                    arguments=plan.arguments,
                    status=JobStatus.FAILED.value,
                    error_message="explicit confirmation required",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            raise HTTPException(
                status_code=409,
                detail="case.close is consequential and requires explicit confirmation",
            )

        execution = CommandExecutionRecord(
            actor=principal.actor,
            role=principal.role.value,
            raw_command=payload.command,
            parsed_action=plan.action,
            arguments=plan.arguments,
            status=JobStatus.RUNNING.value,
        )
        session.add(execution)
        session.flush()

        if plan.action == "screen":
            job_payload = ScreeningJobCreate(
                **plan.arguments, actor=principal.actor, command=payload.command
            )
            # The job manager writes on its own connection. Release this
            # request's write transaction first: holding both at once
            # self-deadlocks on SQLite, which allows a single writer.
            session.commit()
            job = jobs.create(job_payload)
            execution.status = JobStatus.QUEUED.value
            execution.job_id = job.id
            execution.result_payload = {"job_id": job.id}
            session.commit()
            return CommandResponse(
                execution_id=execution.id,
                plan=plan,
                status=JobStatus.QUEUED,
                result={"job_id": job.id},
                job=ScreeningJobView.model_validate(job),
            )

        try:
            result = _execute_immediate_action(
                plan.action, plan.arguments, principal.actor, session
            )
            execution.status = JobStatus.SUCCEEDED.value
            execution.result_payload = result
            execution.completed_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as exc:
            execution.status = JobStatus.FAILED.value
            execution.error_message = str(exc)
            execution.completed_at = datetime.now(timezone.utc)
            session.commit()
            raise
        return CommandResponse(
            execution_id=execution.id,
            plan=plan,
            status=JobStatus.SUCCEEDED,
            result=result,
        )

    @app.get("/monitoring", response_model=list[MonitoredObjectView])
    def list_monitoring(session: SessionDep):
        rows = session.execute(
            select(MonitoredObjectRecord, SpaceObjectRecord)
            .join(SpaceObjectRecord)
            .where(MonitoredObjectRecord.active.is_(True))
            .order_by(MonitoredObjectRecord.created_at)
        ).all()
        return [
            {
                "id": monitor.id,
                "space_object_id": obj.id,
                "norad_id": obj.norad_id,
                "name": obj.name,
                "added_by": monitor.added_by,
                "active": monitor.active,
                "created_at": monitor.created_at,
                "updated_at": monitor.updated_at,
            }
            for monitor, obj in rows
        ]

    @app.get("/objects/{norad_id}/trajectory", response_model=TrajectoryResponse)
    def object_trajectory(
        norad_id: str,
        session: SessionDep,
        window_hours: float = Query(default=3, gt=0, le=24),
        step_sec: int = Query(default=120, ge=10, le=900),
    ):
        obj = session.scalar(
            select(SpaceObjectRecord).where(SpaceObjectRecord.norad_id == norad_id)
        )
        if obj is None:
            raise HTTPException(status_code=404, detail="object not found")
        element = session.scalar(
            select(ElementSetRecord)
            .where(ElementSetRecord.space_object_id == obj.id)
            .order_by(ElementSetRecord.epoch.desc())
            .limit(1)
        )
        if element is None:
            raise HTTPException(status_code=404, detail="object has no element set")
        domain_object = SpaceObject(norad_id, obj.name, element.line1, element.line2)
        times = make_time_grid(window_hours=window_hours, step_sec=step_sec)
        ephemeris = propagate_objects([domain_object], times)
        points = [
            TrajectoryPoint(
                timestamp=timestamp.to_pydatetime(),
                x_km=float(ephemeris.positions[0, index, 0]),
                y_km=float(ephemeris.positions[0, index, 1]),
                z_km=float(ephemeris.positions[0, index, 2]),
                valid=bool(ephemeris.valid[0, index]),
            )
            for index, timestamp in enumerate(times)
        ]
        return TrajectoryResponse(norad_id=norad_id, name=obj.name, points=points)

    @app.get("/events/{event_id}/explanation")
    def explain_event(event_id: str, session: SessionDep) -> dict[str, object]:
        return _event_explanation(event_id, session)

    @app.post(
        "/events/{event_id}/assessments",
        response_model=RiskAssessmentView,
        status_code=201,
    )
    def add_assessment(
        event_id: str, payload: RiskAssessmentCreate, session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.ANALYST)
        return OntologyService(session).add_assessment(event_id, payload)

    @app.post(
        "/events/{event_id}/maneuvers",
        response_model=ManeuverScenarioView,
        status_code=201,
    )
    def create_maneuver(
        event_id: str, payload: ManeuverScenarioCreate, session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.OPERATOR)
        payload = payload.model_copy(update={"actor": principal.actor})
        return OntologyService(session).create_maneuver(event_id, payload)

    # -------------------------------------------------------------- operations
    @app.post(
        "/events/{event_id}/cases",
        response_model=MonitoringCaseView,
        status_code=201,
    )
    def open_case(
        event_id: str, payload: OpenCaseRequest, session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.OPERATOR)
        case_payload = payload.model_dump(exclude={"actor", "justification"})
        from sdebris.ontology.schemas import MonitoringCaseCreate

        return OntologyService(session).open_case(
            event_id,
            MonitoringCaseCreate.model_validate(case_payload),
            actor=principal.actor,
            justification=payload.justification,
        )

    @app.get("/cases", response_model=list[MonitoringCaseView])
    def list_cases(session: SessionDep, status: str | None = None):
        return OntologyService(session).list_cases(status)

    @app.post(
        "/cases/{case_id}/actions/{action}",
        response_model=MonitoringCaseView,
    )
    def apply_case_action(
        case_id: str,
        action: ActionType,
        payload: CaseActionRequest,
        session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.OPERATOR)
        payload = payload.model_copy(update={"actor": principal.actor})
        return OntologyService(session).apply_case_action(case_id, action, payload)

    @app.post(
        "/cases/{case_id}/decisions",
        response_model=OperatorDecisionView,
        status_code=201,
    )
    def record_decision(
        case_id: str, payload: OperatorDecisionCreate, session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.OPERATOR)
        payload = payload.model_copy(update={"actor": principal.actor})
        return OntologyService(session).record_decision(case_id, payload)

    @app.post("/alerts", response_model=AlertView, status_code=201)
    def create_alert(
        payload: AlertCreate, session: SessionDep, principal: PrincipalDep
    ):
        require_role(principal, OperatorRole.OPERATOR)
        return OntologyService(session).create_alert(payload)

    @app.post("/alerts/{alert_id}/acknowledge", response_model=AlertView)
    def acknowledge_alert(
        alert_id: str, payload: AcknowledgeAlertRequest, session: SessionDep,
        principal: PrincipalDep,
    ):
        require_role(principal, OperatorRole.OPERATOR)
        payload = payload.model_copy(update={"actor": principal.actor})
        return OntologyService(session).acknowledge_alert(alert_id, payload)

    # ------------------------------------------------------------ live feed
    def _activity_cutoff(since: str | None) -> datetime:
        """Parse a client cursor, defaulting to a short replay window."""
        if since is None:
            return datetime.now(timezone.utc) - timedelta(hours=ACTIVITY_REPLAY_HOURS)
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="since must be an ISO-8601 timestamp"
            ) from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @app.get("/activity")
    def list_activity(
        session: SessionDep,
        principal: PrincipalDep,
        since: str | None = None,
        limit: int = Query(default=50, ge=1, le=MAX_FEED_ITEMS),
    ) -> dict[str, object]:
        cutoff = _activity_cutoff(since)
        items = collect_activity(session, cutoff, limit)
        return {
            "items": [item.as_dict() for item in items],
            "cursor": feed_cursor(items, cutoff),
            "server_time": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/stream/activity")
    async def stream_activity(
        request: Request,
        principal: PrincipalDep,
        since: str | None = None,
        limit: int = Query(default=50, ge=1, le=MAX_FEED_ITEMS),
    ):
        cutoff = _activity_cutoff(since)

        async def event_stream():
            watermark = cutoff
            while not await request.is_disconnected():
                with database.session_factory() as session:
                    items = collect_activity(session, watermark, limit)
                if items:
                    watermark = max(item.occurred_at for item in items)
                    for item in items:
                        yield (
                            f"id: {item.id}\nevent: activity\n"
                            f"data: {json.dumps(item.as_dict())}\n\n"
                        )
                else:
                    yield (
                        f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
                    )
                await asyncio.sleep(ACTIVITY_POLL_SECONDS)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # -------------------------------------------------------------- governance
    @app.get("/audit-actions", response_model=list[AuditActionView])
    def list_audit_actions(
        session: SessionDep,
        principal: PrincipalDep,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ):
        require_role(principal, OperatorRole.ADMIN)
        return OntologyService(session).list_audit_actions(entity_type, entity_id)

    @app.get(
        "/lineage/{entity_type}/{entity_id}", response_model=list[LineageEdgeView]
    )
    def get_lineage(entity_type: str, entity_id: str, session: SessionDep):
        return OntologyService(session).lineage_for(entity_type, entity_id)

    return app


app = create_app()


def run() -> None:
    uvicorn.run("sdebris.api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
