"""Jobs lost to a restart are closed, not left running for ever."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sdebris.api.app import create_app
from sdebris.ontology.database import Database
from sdebris.ontology.orm import ScreeningJobEventRecord, ScreeningJobRecord


def test_jobs_interrupted_by_a_restart_are_failed_at_startup(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'orphans.sqlite'}"
    database = Database(url)
    database.initialize()
    with database.session_factory() as session:
        for status in ("queued", "running", "succeeded"):
            session.add(
                ScreeningJobRecord(
                    actor="alice@localhost", command="screen 25544",
                    request_payload={"norad_id": "25544"}, status=status,
                )
            )
        session.commit()

    with TestClient(create_app(url)):
        pass  # startup runs here

    with database.session_factory() as session:
        statuses = sorted(job.status for job in session.query(ScreeningJobRecord))
        assert statuses == ["failed", "failed", "succeeded"]
        failed = session.query(ScreeningJobRecord).filter_by(status="failed").all()
        assert all("restart" in job.message for job in failed)
        # A closing event, so an open progress stream ends instead of hanging.
        stages = {event.stage for event in session.query(ScreeningJobEventRecord)}
        assert "failed" in stages
