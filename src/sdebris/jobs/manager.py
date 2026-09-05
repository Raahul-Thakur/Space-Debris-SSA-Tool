"""In-process screening worker with database-backed state and progress."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from threading import Lock
from time import monotonic
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from sdebris.config import load_config
from sdebris.ingest import refresh_catalog
from sdebris.ontology.bridge import persist_screening_result
from sdebris.ontology.enums import JobStatus
from sdebris.ontology.orm import (
    CommandExecutionRecord,
    ScreeningJobEventRecord,
    ScreeningJobRecord,
)
from sdebris.ontology.schemas import ScreeningJobCreate
from sdebris.screening import screen_target


class JobCancelled(RuntimeError):
    pass


class JobTimedOut(RuntimeError):
    pass


class ScreeningJobManager:
    """Runs only the known screening operation; no shell is involved."""

    def __init__(
        self,
        session_factory: sessionmaker,
        max_workers: int = 2,
        *,
        enable_executor: bool = True,
    ) -> None:
        self.session_factory = session_factory
        self.backend = os.getenv("SDEBRIS_JOB_BACKEND", "thread").lower()
        self.executor = (
            ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ssa-job")
            if enable_executor and self.backend == "thread"
            else None
        )
        self._event_lock = Lock()

    def shutdown(self) -> None:
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)

    def create(self, payload: ScreeningJobCreate) -> ScreeningJobRecord:
        request_payload = payload.model_dump(mode="json", exclude={"command"})
        command = payload.command or (
            f"screen {payload.norad_id} --window {payload.window_hours:g}h "
            f"--threshold {payload.threshold_km:g}km"
        )
        with self.session_factory() as session:
            job = ScreeningJobRecord(
                actor=payload.actor,
                command=command,
                request_payload=request_payload,
            )
            session.add(job)
            session.flush()
            self._append_event(session, job, "queued", 0, "Screening job queued")
            session.commit()
            session.refresh(job)
            job_id = job.id
        if self.backend == "redis":
            from sdebris.jobs.tasks import run_screening_job

            run_screening_job.send(job_id)
        elif self.executor:
            self.executor.submit(self._run, job_id)
        else:
            raise RuntimeError("screening job executor is not available")
        return job

    def cancel(self, job_id: str) -> ScreeningJobRecord | None:
        with self.session_factory() as session:
            job = session.get(ScreeningJobRecord, job_id)
            if job is None:
                return None
            if job.status in {
                JobStatus.SUCCEEDED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            }:
                return job
            job.cancel_requested = True
            job.message = "Cancellation requested"
            self._append_event(
                session, job, job.stage, job.progress, "Cancellation requested by operator"
            )
            session.commit()
            session.refresh(job)
            return job

    def _append_event(
        self,
        session,
        job: ScreeningJobRecord,
        stage: str,
        progress: float,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._event_lock:
            sequence = (
                session.scalar(
                    select(func.max(ScreeningJobEventRecord.sequence)).where(
                        ScreeningJobEventRecord.job_id == job.id
                    )
                )
                or 0
            ) + 1
            session.add(
                ScreeningJobEventRecord(
                    job_id=job.id,
                    sequence=sequence,
                    stage=stage,
                    progress=progress,
                    message=message,
                    payload=payload or {},
                )
            )

    def _progress(
        self,
        job_id: str,
        stage: str,
        progress: float,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.session_factory() as session:
            job = session.get(ScreeningJobRecord, job_id)
            if job is None:
                raise RuntimeError(f"job {job_id} disappeared")
            if job.cancel_requested:
                raise JobCancelled()
            job.status = JobStatus.RUNNING.value
            job.stage = stage
            job.progress = progress
            job.message = message
            job.started_at = job.started_at or datetime.now(timezone.utc)
            self._append_event(session, job, stage, progress, message, payload)
            session.commit()

    def _run(self, job_id: str) -> None:
        cache = None
        try:
            with self.session_factory() as session:
                job = session.get(ScreeningJobRecord, job_id)
                if job is None:
                    return
                request = ScreeningJobCreate.model_validate(job.request_payload)
            deadline = monotonic() + request.timeout_seconds

            config = load_config()
            config = config.model_copy(
                update={
                    "propagation": config.propagation.model_copy(
                        update={
                            "window_hours": request.window_hours,
                            "step_sec": request.step_sec,
                        }
                    ),
                    "screening": config.screening.model_copy(
                        update={"report_threshold_km": request.threshold_km}
                    ),
                }
            )
            self._progress(job_id, "catalog", 0.12, "Synchronizing orbital catalog")
            if request.refresh_catalog:
                cache = refresh_catalog(
                    config,
                    group=request.group,
                    extra_norad_ids=[request.norad_id],
                    offline_ok=True,
                )
            else:
                from sdebris.ingest.cache import TLECache

                cache = TLECache(config.resolve_path(config.ingestion.cache_path))
            catalog = cache.all()
            target = cache.get(request.norad_id)
            self._ensure_time(deadline)
            if target is None:
                raise ValueError(f"NORAD {request.norad_id} is not available in the catalog")
            self._progress(
                job_id,
                "catalog",
                0.28,
                f"Catalog synchronized · {len(catalog)} objects",
                {"objects": len(catalog)},
            )
            self._progress(job_id, "propagation", 0.42, "Propagating catalog in TEME")
            result = screen_target(target, catalog, config)
            self._ensure_time(deadline)
            self._progress(
                job_id,
                "screening",
                0.78,
                f"Conjunction screening completed · {len(result.events)} events",
                {"events": len(result.events), "objects": result.n_screened},
            )

            summary = None
            if request.persist_ontology:
                self._progress(job_id, "ontology", 0.88, "Persisting ontology results")
                with self.session_factory() as session:
                    summary = persist_screening_result(session, result, catalog, config)
                self._ensure_time(deadline)

            result_payload = result.metadata()
            if summary:
                result_payload["ontology_run_id"] = summary.screening_run_id
                result_payload["cases_opened"] = summary.cases_opened
            with self.session_factory() as session:
                job = session.get(ScreeningJobRecord, job_id)
                if job is None:
                    return
                if job.cancel_requested:
                    raise JobCancelled()
                job.status = JobStatus.SUCCEEDED.value
                job.stage = "complete"
                job.progress = 1
                job.message = "Screening completed"
                job.result_payload = result_payload
                job.ontology_run_id = summary.screening_run_id if summary else None
                job.completed_at = datetime.now(timezone.utc)
                self._complete_commands(
                    session, job_id, JobStatus.SUCCEEDED, result_payload
                )
                self._append_event(
                    session, job, "complete", 1, "Screening completed", result_payload
                )
                session.commit()
        except JobCancelled:
            self._finish_cancelled(job_id)
        except Exception as exc:  # persisted for operator inspection
            with self.session_factory() as session:
                job = session.get(ScreeningJobRecord, job_id)
                if job is not None:
                    job.status = JobStatus.FAILED.value
                    job.stage = "failed"
                    job.message = "Screening failed"
                    job.error_message = str(exc)
                    job.completed_at = datetime.now(timezone.utc)
                    self._complete_commands(
                        session,
                        job_id,
                        JobStatus.FAILED,
                        {},
                        error_message=str(exc),
                    )
                    self._append_event(
                        session, job, "failed", job.progress, "Screening failed", {"error": str(exc)}
                    )
                    session.commit()
        finally:
            if cache is not None:
                cache.close()

    @staticmethod
    def _ensure_time(deadline: float) -> None:
        if monotonic() > deadline:
            raise JobTimedOut("screening job exceeded its configured timeout")

    def _finish_cancelled(self, job_id: str) -> None:
        with self.session_factory() as session:
            job = session.get(ScreeningJobRecord, job_id)
            if job is None:
                return
            job.status = JobStatus.CANCELLED.value
            job.stage = "cancelled"
            job.message = "Screening cancelled"
            job.completed_at = datetime.now(timezone.utc)
            self._complete_commands(session, job_id, JobStatus.CANCELLED, {})
            self._append_event(
                session, job, "cancelled", job.progress, "Screening cancelled"
            )
            session.commit()

    def _complete_commands(
        self,
        session,
        job_id: str,
        status: JobStatus,
        result: dict[str, Any],
        error_message: str | None = None,
    ) -> None:
        executions = session.scalars(
            select(CommandExecutionRecord).where(
                CommandExecutionRecord.job_id == job_id
            )
        )
        for execution in executions:
            execution.status = status.value
            execution.result_payload = result
            execution.error_message = error_message
            execution.completed_at = datetime.now(timezone.utc)
