"""What one screening, one account and one connection may cost.

Each limit here closed a way for a single free account to take down the
one-CPU, 512 MB instance the API runs on.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from sdebris.api.app import MAX_STREAMS_PER_ACCOUNT, StreamSlots, create_app
from sdebris.catalog_groups import SCREENING_GROUPS
from sdebris.commands import CommandParseError, parse_command
from sdebris.jobs.manager import MAX_SCREENING_SAMPLES, screening_samples
from sdebris.ontology.schemas import ScreeningJobCreate


@pytest.fixture()
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'limits.sqlite'}")
    with TestClient(app) as test_client:
        yield test_client


def _headers(client: TestClient, subject: str, role: str = "analyst") -> dict[str, str]:
    body = client.post(
        "/auth/development-token", params={"subject": subject, "role": role}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


# ----------------------------------------------------------- catalogue groups
def test_a_huge_catalogue_group_is_refused_by_name() -> None:
    """`--group active` was about 11,000 objects: enough to exhaust memory."""
    with pytest.raises(CommandParseError, match="unknown catalogue group 'active'"):
        parse_command("screen 25544 --group active")
    with pytest.raises(ValueError):
        ScreeningJobCreate(norad_id="25544", group="active")


@pytest.mark.parametrize("group", sorted(SCREENING_GROUPS))
def test_every_listed_group_is_accepted(group: str) -> None:
    assert parse_command(f"screen 25544 --group {group}").arguments["group"] == group


def test_an_invalid_step_is_a_parse_error_not_a_server_error() -> None:
    with pytest.raises(CommandParseError, match="step_sec"):
        parse_command("screen 25544 --step 5s")


# ------------------------------------------------------------------ job size
def test_the_scheduled_screening_fits_well_inside_the_size_cap() -> None:
    # The CI pipeline: about 110 debris objects, 72 h, 60 s.
    assert screening_samples(111, 72, 60) < MAX_SCREENING_SAMPLES / 5


def test_a_catalogue_like_active_does_not_fit() -> None:
    assert screening_samples(11_000, 72, 60) > MAX_SCREENING_SAMPLES


# -------------------------------------------------------------- job slots
def test_one_account_runs_one_screening_at_a_time(client: TestClient) -> None:
    alice = _headers(client, "alice")
    job = {"norad_id": "25544", "window_hours": 1, "threshold_km": 25, "refresh_catalog": False}
    first = client.post("/screening-jobs", headers=alice, json=job)
    assert first.status_code == 202, first.text
    # Hold the first job in "queued" by checking before the worker finishes it.
    second = client.post("/screening-jobs", headers=alice, json=job)
    if client.get(f"/screening-jobs/{first.json()['id']}", headers=alice).json()["status"] in (
        "queued", "running"
    ):
        assert second.status_code == 429
        assert "already have a screening running" in second.json()["detail"]


def test_parallel_requests_cannot_both_take_the_last_run(tmp_path, monkeypatch) -> None:
    """Quota was checked, then the job inserted later, so parallel calls overran it."""
    from sdebris.billing.plans import PLAN_LIMITS, Plan

    monkeypatch.setattr("sdebris.api.app.MAX_ACTIVE_JOBS_PER_ACCOUNT", 100)
    monkeypatch.setattr("sdebris.api.app.MAX_ACTIVE_JOBS", 100)
    allowance = PLAN_LIMITS[Plan.FREE].screening_runs_per_month
    app = create_app(f"sqlite:///{tmp_path / 'race.sqlite'}")
    job = {"norad_id": "25544", "window_hours": 1, "threshold_km": 25, "refresh_catalog": False}
    with TestClient(app) as client:
        headers = _headers(client, "racer")
        barrier = threading.Barrier(allowance + 4)
        codes: list[int] = []

        def go() -> None:
            barrier.wait()
            codes.append(client.post("/screening-jobs", headers=headers, json=job).status_code)

        threads = [threading.Thread(target=go) for _ in range(allowance + 4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert codes.count(202) == allowance
    assert codes.count(202) + codes.count(402) == len(codes)


# -------------------------------------------------------------- live streams
def test_stream_slots_cap_each_account_and_the_total() -> None:
    slots = StreamSlots(per_account=2, total=3)
    assert slots.acquire("a") and slots.acquire("a")
    assert not slots.acquire("a"), "a third stream for one account"
    assert slots.acquire("b")
    assert not slots.acquire("c"), "over the instance total"
    slots.release("a")
    assert slots.acquire("c")


def test_too_many_streams_for_one_account_are_refused(client: TestClient) -> None:
    headers = _headers(client, "streamer")
    slots: StreamSlots = client.app.state.streams
    for _ in range(MAX_STREAMS_PER_ACCOUNT):
        assert slots.acquire("streamer@localhost")
    response = client.get("/stream/activity", headers=headers)
    assert response.status_code == 429
    assert "Retry-After" in response.headers
