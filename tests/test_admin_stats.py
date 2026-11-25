"""The admin usage figures: aggregate counts, correct buckets, admins only.

The aggregates run on SQLite here. Setting ``SDEBRIS_TEST_POSTGRES_URL`` (a
throwaway database: its tables are dropped) runs the same assertions on
PostgreSQL, where the percentile query takes a different path.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sdebris.api.app import create_app
from sdebris.ontology.database import Database
from sdebris.ontology.orm import (
    Base,
    CommandExecutionRecord,
    ConjunctionEventRecord,
    MonitoredObjectRecord,
    ScreeningJobRecord,
    SpaceObjectRecord,
    WaitlistEntryRecord,
)
from sdebris.usage import usage_stats

#: A Wednesday, so the current week began on Monday 23 November.
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)

POSTGRES_URL = os.getenv("SDEBRIS_TEST_POSTGRES_URL")


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "postgresql",
            marks=pytest.mark.skipif(
                not POSTGRES_URL, reason="set SDEBRIS_TEST_POSTGRES_URL to run on PostgreSQL"
            ),
        ),
    ]
)
def database(request, tmp_path):
    url = f"sqlite:///{tmp_path / 'stats.sqlite'}" if request.param == "sqlite" else POSTGRES_URL
    db = Database(url)
    Base.metadata.drop_all(db.engine)
    db.initialize()
    yield db
    if request.param != "sqlite":
        Base.metadata.drop_all(db.engine)
    db.engine.dispose()


def _command(actor: str, at: datetime) -> CommandExecutionRecord:
    return CommandExecutionRecord(
        actor=actor, role="analyst", raw_command="list objects", parsed_action="list",
        status="completed", created_at=at,
    )


def _job(
    actor: str,
    at: datetime,
    status: str = "succeeded",
    seconds: float | None = None,
    started: bool = True,
) -> ScreeningJobRecord:
    return ScreeningJobRecord(
        actor=actor, command="screen", status=status, request_payload={},
        created_at=at,
        started_at=at if started else None,
        completed_at=at + timedelta(seconds=seconds) if seconds is not None else None,
    )


def _seed(db: Database) -> None:
    ago = lambda **kw: NOW - timedelta(**kw)
    with db.session_factory() as session:
        iss = SpaceObjectRecord(norad_id="25544", name="ISS")
        debris = SpaceObjectRecord(norad_id="99999", name="DEBRIS")
        session.add_all([iss, debris])
        session.flush()
        session.add_all(
            [
                # alice: first seen 20 days ago, active today and 3 days ago.
                _command("alice@example.com", ago(days=20)),
                _command("alice@example.com", ago(hours=2)),
                _job("alice@example.com", ago(days=3), seconds=10),
                _job("alice@example.com", ago(days=3, minutes=5), seconds=20),
                _job("alice@example.com", ago(hours=1), status="queued"),
                # bob: first seen 10 days ago, last active 5 days ago.
                _job("bob@example.com", ago(days=10), status="failed", seconds=5),
                _command("bob@example.com", ago(days=5)),
                _job("bob@example.com", ago(days=4), seconds=30),
                _job("bob@example.com", ago(days=4, hours=1), seconds=40, started=False),
                _job("bob@example.com", ago(days=2), seconds=100),
                # carol: only ever watched an object, 40 days ago.
                MonitoredObjectRecord(
                    space_object_id=iss.id, added_by="carol@example.com", created_at=ago(days=40)
                ),
                # dave: active long ago, before both series start.
                _command("dave@example.com", ago(days=200)),
                _job("dave@example.com", ago(days=45), seconds=999),
                # The platform's own watch list is not an account.
                MonitoredObjectRecord(space_object_id=debris.id, added_by=None),
                ConjunctionEventRecord(
                    primary_object_id=iss.id, secondary_object_id=debris.id,
                    tca=NOW + timedelta(days=1), miss_distance_km=1, relative_speed_km_s=7,
                ),
                ConjunctionEventRecord(
                    primary_object_id=iss.id, secondary_object_id=debris.id,
                    tca=NOW + timedelta(days=2), miss_distance_km=1, relative_speed_km_s=7,
                ),
                ConjunctionEventRecord(
                    primary_object_id=iss.id, secondary_object_id=debris.id,
                    tca=NOW - timedelta(days=1), miss_distance_km=1, relative_speed_km_s=7,
                ),
                WaitlistEntryRecord(email="a@example.com", interest="founding"),
                WaitlistEntryRecord(email="b@example.com", interest="founding"),
                WaitlistEntryRecord(email="c@example.com"),
            ]
        )
        session.commit()


def _stats(db: Database) -> dict:
    _seed(db)
    with db.session_factory() as session:
        return usage_stats(session, now=NOW)


def test_active_accounts_count_each_account_once_per_window(database) -> None:
    accounts = _stats(database)["accounts"]
    assert accounts["active"] == {"1d": 1, "7d": 2, "30d": 2}
    assert accounts["total"] == 4


def test_new_accounts_are_counted_in_the_week_they_were_first_seen(database) -> None:
    weeks = _stats(database)["accounts"]["new_per_week"]
    assert len(weeks) == 12
    assert weeks[-1]["week_start"] == "2026-11-23"
    assert weeks[0]["week_start"] == "2026-09-07"
    counts = {week["week_start"]: week["count"] for week in weeks if week["count"]}
    # alice's first sighting, not her latest; dave is older than the series.
    assert counts == {"2026-10-12": 1, "2026-11-02": 1, "2026-11-09": 1}


def test_screenings_per_day_are_split_by_status(database) -> None:
    jobs = _stats(database)["screening_jobs"]
    days = {day["date"]: day for day in jobs["per_day"]}
    assert len(jobs["per_day"]) == 30
    assert jobs["per_day"][-1]["date"] == "2026-11-25"
    assert days["2026-11-25"]["by_status"] == {"queued": 1}
    assert days["2026-11-22"] == {"date": "2026-11-22", "total": 2, "by_status": {"succeeded": 2}}
    assert days["2026-11-15"]["by_status"] == {"failed": 1}
    assert jobs["last_30_days"] == {
        "total": 7, "by_status": {"succeeded": 5, "failed": 1, "queued": 1}
    }
    assert jobs["total"] == 8
    assert jobs["this_month"] == 7


def test_job_durations_use_succeeded_jobs_in_the_window(database) -> None:
    durations = _stats(database)["screening_jobs"]["duration_last_30_days"]
    # 10, 20, 30, 40, 100 seconds; the failed job and dave's old one are out.
    assert durations == {"samples": 5, "median_seconds": 30.0, "p95_seconds": 100.0}


def test_commands_conjunctions_waitlist_and_watch_lists(database) -> None:
    stats = _stats(database)
    days = {day["date"]: day["count"] for day in stats["commands"]["per_day"]}
    assert days["2026-11-25"] == 1 and days["2026-11-20"] == 1 and days["2026-11-05"] == 1
    assert sum(days.values()) == 3
    assert stats["commands"]["total"] == 4
    assert stats["conjunction_events"] == {"stored": 3, "upcoming": 2}
    assert stats["waitlist"] == {
        "total": 3, "by_interest": {"founding": 2, "unspecified": 1}
    }
    assert stats["monitored_objects"] == {
        "total": 2, "active": 2, "by_accounts": 1, "platform": 1
    }
    assert stats["as_of"] == NOW.isoformat()


def test_no_account_is_named_in_the_answer(database) -> None:
    body = json.dumps(_stats(database))
    assert "example.com" not in body


def test_an_empty_service_reports_zeros_not_errors(database) -> None:
    with database.session_factory() as session:
        stats = usage_stats(session, now=NOW)
    assert stats["accounts"]["total"] == 0
    assert stats["screening_jobs"]["duration_last_30_days"]["median_seconds"] is None
    assert all(week["count"] == 0 for week in stats["accounts"]["new_per_week"])


# ------------------------------------------------------------------ endpoint
def _headers(client: TestClient, subject: str, role: str) -> dict[str, str]:
    body = client.post(
        "/auth/development-token", params={"subject": subject, "role": role}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def test_only_an_administrator_can_read_the_stats(tmp_path) -> None:
    with TestClient(create_app(f"sqlite:///{tmp_path / 'api.sqlite'}")) as client:
        assert client.get("/admin/stats").status_code == 401
        operator = _headers(client, "op", "operator")
        assert client.get("/admin/stats", headers=operator).status_code == 403
        response = client.get("/admin/stats", headers=_headers(client, "root", "admin"))
    assert response.status_code == 200
    body = response.json()
    assert {"as_of", "accounts", "screening_jobs", "commands", "conjunction_events",
            "waitlist", "monitored_objects", "latency"} <= set(body)


def test_latency_is_keyed_by_route_template_not_raw_path(tmp_path) -> None:
    with TestClient(create_app(f"sqlite:///{tmp_path / 'api.sqlite'}")) as client:
        for _ in range(3):
            client.get("/objects/31337")
        client.get("/health")
        latency = client.get(
            "/admin/stats", headers=_headers(client, "root", "admin")
        ).json()["latency"]
    routes = {route["route"]: route for route in latency["routes"]}
    assert routes["GET /objects/{norad_id}"]["requests"] == 3
    assert routes["GET /objects/{norad_id}"]["client_error_rate"] == 1.0
    assert routes["GET /health"]["error_rate"] == 0.0
    assert "31337" not in json.dumps(latency)
    assert "process" in latency["scope"]
