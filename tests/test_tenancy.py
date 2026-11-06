"""One principal's work must not be visible or mutable by another.

The ontology was a single shared workspace until now, which is why new
accounts were held at ``viewer``. These tests are the evidence for raising
that default: they exercise the boundary from both sides, and several of them
would have passed trivially before the scoping existed, so each one asserts
that the *other* principal is excluded rather than only that the owner is
included.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sdebris.api.app import create_app
from sdebris.auth import Principal
from sdebris.ontology.enums import OperatorRole
from sdebris.ontology.orm import ScreeningJobRecord
from sdebris.tenancy import owns, scope, sees_everything, visibility_filter

ALICE = Principal(subject="alice", email="alice@example.com", role=OperatorRole.ANALYST)
BOB = Principal(subject="bob", email="bob@example.com", role=OperatorRole.ANALYST)
ROOT = Principal(subject="root", email="root@example.com", role=OperatorRole.ADMIN)


# ------------------------------------------------------------------ the rules
def test_an_administrator_is_not_filtered() -> None:
    assert sees_everything(ROOT)
    assert visibility_filter(ScreeningJobRecord.actor, ROOT) is None


def test_an_ordinary_principal_is_filtered() -> None:
    assert not sees_everything(ALICE)
    assert visibility_filter(ScreeningJobRecord.actor, ALICE) is not None


def test_an_anonymous_caller_sees_only_platform_rows() -> None:
    rendered = str(visibility_filter(ScreeningJobRecord.actor, None))
    assert "IS NULL" in rendered
    assert "=" not in rendered, "anonymous must not be matched against an actor"


def test_scoping_an_administrator_leaves_the_query_alone() -> None:
    from sqlalchemy import select

    plain = select(ScreeningJobRecord)
    assert str(scope(plain, ScreeningJobRecord.actor, ROOT)) == str(plain)


# --------------------------------------------------------------- the ownership
def test_a_principal_owns_their_own_row() -> None:
    assert owns("alice@example.com", ALICE)


def test_a_principal_does_not_own_someone_elses_row() -> None:
    assert not owns("bob@example.com", ALICE)


def test_an_administrator_owns_every_row() -> None:
    assert owns("bob@example.com", ROOT)


def test_a_platform_row_is_readable_by_anyone_signed_in() -> None:
    assert owns(None, ALICE)


def test_a_platform_row_is_not_writable_by_whoever_finds_it() -> None:
    """Readable is not the same as mutable: the public picture is not a free-for-all."""
    assert not owns(None, ALICE, platform_is_public=False)


def test_an_anonymous_caller_owns_nothing() -> None:
    assert not owns(None, None)
    assert not owns("alice@example.com", None)


# ------------------------------------------------------------- over the wire
@pytest.fixture()
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'tenancy.sqlite'}")
    with TestClient(app) as test_client:
        yield test_client


def _headers(client: TestClient, subject: str, role: str) -> dict[str, str]:
    """A development token for a named principal.

    The dev issuer derives the email as ``{subject}@localhost``, so distinct
    subjects are distinct actors.
    """
    body = client.post(
        "/auth/development-token", params={"subject": subject, "role": role}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _start_job(client: TestClient, headers: dict[str, str]) -> str | None:
    response = client.post(
        "/screening-jobs",
        headers=headers,
        json={"norad_id": "25544", "window_hours": 1, "threshold_km": 25},
    )
    assert response.status_code in (200, 201, 202), response.text
    return response.json()["id"]


def test_a_job_is_absent_from_another_principals_listing(client: TestClient) -> None:
    alice = _headers(client, "alice", "analyst")
    bob = _headers(client, "bob", "analyst")
    job_id = _start_job(client, alice)

    mine = [job["id"] for job in client.get("/screening-jobs", headers=alice).json()]
    theirs = [job["id"] for job in client.get("/screening-jobs", headers=bob).json()]
    assert job_id in mine
    assert job_id not in theirs


def test_fetching_another_principals_job_by_id_is_a_404(client: TestClient) -> None:
    """404 rather than 403: confirming the id exists is itself a disclosure."""
    alice = _headers(client, "alice", "analyst")
    bob = _headers(client, "bob", "analyst")
    job_id = _start_job(client, alice)

    assert client.get(f"/screening-jobs/{job_id}", headers=alice).status_code == 200
    assert client.get(f"/screening-jobs/{job_id}", headers=bob).status_code == 404


def test_cancelling_another_principals_job_is_refused(client: TestClient) -> None:
    alice = _headers(client, "alice", "analyst")
    bob = _headers(client, "bob", "analyst")
    job_id = _start_job(client, alice)

    assert (
        client.post(f"/screening-jobs/{job_id}/cancel", headers=bob).status_code == 404
    )


def test_streaming_another_principals_job_is_refused(client: TestClient) -> None:
    alice = _headers(client, "alice", "analyst")
    bob = _headers(client, "bob", "analyst")
    job_id = _start_job(client, alice)

    assert (
        client.get(f"/screening-jobs/{job_id}/events", headers=bob).status_code == 404
    )


def test_an_administrator_sees_another_principals_job(client: TestClient) -> None:
    alice = _headers(client, "alice", "analyst")
    root = _headers(client, "root", "admin")
    job_id = _start_job(client, alice)

    assert client.get(f"/screening-jobs/{job_id}", headers=root).status_code == 200
    assert job_id in [
        job["id"] for job in client.get("/screening-jobs", headers=root).json()
    ]


# -------------------------------------------------------- curation is admin
CURATION_WRITES = [
    ("/objects", {"norad_id": "99999", "name": "FORGED", "orbit_class": "LEO"}),
    (
        "/events",
        {
            "screening_run_id": "run-1",
            "primary_norad_id": "25544",
            "secondary_norad_id": "99999",
            "tca": "2026-10-09T00:00:00+00:00",
            "miss_distance_km": 1.0,
            "relative_speed_km_s": 10.0,
        },
    ),
]


@pytest.mark.parametrize(("path", "payload"), CURATION_WRITES)
def test_an_analyst_cannot_write_global_reference_data(
    client: TestClient, path: str, payload: dict
) -> None:
    """Reference data is shared by every reader, so one bad write harms everyone."""
    analyst = _headers(client, "alice", "analyst")
    response = client.post(path, headers=analyst, json=payload)
    assert response.status_code == 403, response.text
    assert "admin" in response.json()["detail"]


@pytest.mark.parametrize(("path", "payload"), CURATION_WRITES)
def test_an_administrator_still_curates(
    client: TestClient, path: str, payload: dict
) -> None:
    """The gate must be the role, not a broken endpoint."""
    root = _headers(client, "root", "admin")
    assert client.post(path, headers=root, json=payload).status_code != 403


# --------------------------------------------------- the platform's own rows
def test_the_public_watch_list_survives_serialisation(client: TestClient) -> None:
    """A platform-owned watch entry has no adder, and the view must allow that.

    Caught in production rather than here the first time: every test fixture
    created watch entries through an authenticated caller, so `added_by` was
    never NULL and the response model's `str` held. Against a real database
    with a seeded public catalogue it raised a ResponseValidationError for
    every row.
    """
    from sdebris.ontology.orm import MonitoredObjectRecord, SpaceObjectRecord

    app_state = client.app.state
    with app_state.database.session_factory() as session:
        obj = SpaceObjectRecord(norad_id="11111", name="PLATFORM SAT")
        session.add(obj)
        session.flush()
        session.add(MonitoredObjectRecord(space_object_id=obj.id, added_by=None))
        session.commit()

    response = client.get("/monitoring")
    assert response.status_code == 200, response.text
    rows = response.json()
    assert any(row["added_by"] is None for row in rows)


def test_the_cacheable_watch_list_never_includes_an_accounts_own_objects(
    client: TestClient,
) -> None:
    """``/monitoring/platform`` is served from a cache every visitor shares.

    So it must answer the same for everyone, whoever asks: the platform's rows
    and nothing a principal added, even when the caller is that principal.
    """
    from sdebris.ontology.orm import MonitoredObjectRecord, SpaceObjectRecord

    with client.app.state.database.session_factory() as session:
        public = SpaceObjectRecord(norad_id="33333", name="PLATFORM SAT")
        private = SpaceObjectRecord(norad_id="44444", name="PRIVATE SAT")
        session.add_all([public, private])
        session.flush()
        session.add(MonitoredObjectRecord(space_object_id=public.id, added_by=None))
        session.add(
            MonitoredObjectRecord(space_object_id=private.id, added_by="alice@localhost")
        )
        session.commit()

    alice = _headers(client, "alice", "analyst")
    own = {row["norad_id"] for row in client.get("/monitoring", headers=alice).json()}
    assert {"33333", "44444"} <= own

    for headers in (alice, {}):
        response = client.get("/monitoring/platform", headers=headers)
        assert response.status_code == 200, response.text
        ids = {row["norad_id"] for row in response.json()}
        assert "33333" in ids
        assert "44444" not in ids


def test_watching_an_object_does_not_take_it_from_another_principal(
    client: TestClient,
) -> None:
    """Two principals may track the same object; neither reassigns the other's row.

    The watch-list upsert matched on the object alone, so `monitor add` for an
    object someone else already tracked rewrote *their* row's owner instead of
    creating one. With the platform seeding a public catalogue, the first
    signed-in user to add a popular object would have silently removed it from
    the public globe.
    """
    from sdebris.ontology.orm import MonitoredObjectRecord, SpaceObjectRecord

    with client.app.state.database.session_factory() as session:
        obj = SpaceObjectRecord(norad_id="22222", name="SHARED SAT")
        session.add(obj)
        session.flush()
        session.add(MonitoredObjectRecord(space_object_id=obj.id, added_by=None))
        session.commit()
        object_id = obj.id

    alice = _headers(client, "alice", "analyst")
    response = client.post(
        "/commands/execute", headers=alice, json={"command": "monitor add 22222"}
    )
    assert response.status_code in (200, 201, 202), response.text

    with client.app.state.database.session_factory() as session:
        owners = sorted(
            row.added_by or "<platform>"
            for row in session.query(MonitoredObjectRecord).filter_by(
                space_object_id=object_id
            )
        )
    assert owners == ["<platform>", "alice@localhost"], owners


# ------------------------------------------------------------ the activity feed
def _feed_text(client: TestClient, headers: dict[str, str]) -> str:
    response = client.get("/activity", headers=headers, params={"limit": 200})
    assert response.status_code == 200, response.text
    return response.text


def test_the_activity_feed_hides_another_principals_work(client: TestClient) -> None:
    """The feed used to stream every account's commands, jobs and watch list.

    A viewer saw other people's email addresses and exactly which objects they
    were screening, contrary to what the privacy page promises.
    """
    alice = _headers(client, "alice", "analyst")
    bob = _headers(client, "bob", "viewer")
    job_id = _start_job(client, alice)
    command = client.post(
        "/commands/execute", headers=alice, json={"command": "events list --tier watch"}
    )
    assert command.status_code in (200, 201, 202), command.text

    theirs = _feed_text(client, bob)
    assert "alice@localhost" not in theirs
    assert job_id not in theirs
    assert "events list --tier watch" not in theirs

    mine = _feed_text(client, alice)
    assert job_id in mine
    assert "events list --tier watch" in mine


def test_an_administrator_still_sees_the_whole_feed(client: TestClient) -> None:
    alice = _headers(client, "alice", "analyst")
    root = _headers(client, "root", "admin")
    job_id = _start_job(client, alice)
    assert job_id in _feed_text(client, root)


# -------------------------------------------------- acting on someone's case
def _event(client: TestClient) -> str:
    admin = _headers(client, "seed", "admin")
    for norad, name in (("25544", "ISS"), ("99999", "DEBRIS")):
        client.post("/objects", headers=admin,
                    json={"norad_id": norad, "name": name, "orbit_class": "LEO", "status": "active"})
    run = client.post("/screening-runs", headers=admin,
                      json={"propagator_version": "t", "configuration": {}, "input_versions": {}}).json()
    event = client.post("/events", headers=admin, json={
        "primary_norad_id": "25544", "secondary_norad_id": "99999",
        "screening_run_id": run["id"], "tca": "2026-12-01T00:00:00+00:00",
        "miss_distance_km": 0.8, "relative_speed_km_s": 11.0,
    })
    assert event.status_code == 201, event.text
    return event.json()["id"]


def _open_case(client: TestClient, headers: dict[str, str], event_id: str) -> str:
    response = client.post(f"/events/{event_id}/cases", headers=headers, json={
        "title": "Watch this", "priority": "P2", "actor": "ignored", "justification": "opening",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_an_operator_cannot_close_another_operators_case(client: TestClient) -> None:
    event_id = _event(client)
    alice = _headers(client, "alice", "operator")
    bob = _headers(client, "bob", "operator")
    case_id = _open_case(client, alice, event_id)
    body = {"actor": "ignored", "justification": "closing it"}

    assert client.post(f"/cases/{case_id}/actions/close_case", headers=bob, json=body).status_code == 404
    decision = {"selected_action": "accept", "justification": "fine", "actor": "x"}
    assert client.post(f"/cases/{case_id}/decisions", headers=bob, json=decision).status_code == 404
    assert client.post(f"/cases/{case_id}/actions/close_case", headers=alice, json=body).status_code == 200


def test_the_console_cannot_reassign_another_operators_case(client: TestClient) -> None:
    event_id = _event(client)
    alice = _headers(client, "alice", "operator")
    bob = _headers(client, "bob", "operator")
    case_id = _open_case(client, alice, event_id)
    response = client.post("/commands/execute", headers=bob,
                           json={"command": f"case assign {case_id} bob"})
    assert response.status_code != 200 or response.json().get("status") == "failed", response.text
    cases = client.get("/cases", headers=alice).json()
    assert next(case for case in cases if case["id"] == case_id)["assignee"] != "bob"


def test_an_administrator_can_act_on_any_case(client: TestClient) -> None:
    event_id = _event(client)
    alice = _headers(client, "alice", "operator")
    root = _headers(client, "root", "admin")
    case_id = _open_case(client, alice, event_id)
    body = {"actor": "ignored", "justification": "escalating", "priority": "P1"}
    assert client.post(f"/cases/{case_id}/actions/escalate_event", headers=root, json=body).status_code == 200


def test_an_operator_cannot_acknowledge_another_operators_alert(client: TestClient) -> None:
    event_id = _event(client)
    alice = _headers(client, "alice", "operator")
    bob = _headers(client, "bob", "operator")
    alert = client.post("/alerts", headers=alice,
                        json={"event_id": event_id, "rule": "critical", "channel": "email"})
    assert alert.status_code == 201, alert.text
    body = {"actor": "ignored", "justification": "seen it"}
    alert_id = alert.json()["id"]
    assert client.post(f"/alerts/{alert_id}/acknowledge", headers=bob, json=body).status_code == 404
    assert client.post(f"/alerts/{alert_id}/acknowledge", headers=alice, json=body).status_code == 200
