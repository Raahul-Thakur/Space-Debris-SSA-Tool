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
