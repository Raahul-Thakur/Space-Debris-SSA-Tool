import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from sdebris.api.app import create_app
from sdebris.ontology.enums import OperatorRole


def _run(coro) -> None:
    asyncio.run(coro)


async def _seed_event(client: httpx.AsyncClient) -> str:
    for norad, name in (("25544", "ISS"), ("99999", "TEST DEBRIS")):
        response = await client.post(
            "/objects",
            json={"norad_id": norad, "name": name, "orbit_class": "LEO", "status": "active"},
        )
        assert response.status_code == 201, response.text
    run = await client.post(
        "/screening-runs",
        json={
            "propagator_version": "sgp4-test",
            "configuration": {"window_hours": 24},
            "input_versions": {},
        },
    )
    assert run.status_code == 201, run.text
    event = await client.post(
        "/events",
        json={
            "primary_norad_id": "25544",
            "secondary_norad_id": "99999",
            "screening_run_id": run.json()["id"],
            "tca": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            "miss_distance_km": 0.8,
            "relative_speed_km_s": 11.2,
        },
    )
    assert event.status_code == 201, event.text
    return event.json()["id"]


def test_activity_feed_reports_events_and_advances_cursor(tmp_path) -> None:
    async def scenario() -> None:
        app = create_app(f"sqlite:///{(tmp_path / 'activity.db').as_posix()}")
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            assert (await client.get("/activity")).status_code == 401

            token = app.state.authenticator.issue_development_token(
                subject="feed-test", role=OperatorRole.ADMIN
            )
            client.headers["Authorization"] = f"Bearer {token}"

            event_id = await _seed_event(client)
            assessment = await client.post(
                f"/events/{event_id}/assessments",
                json={
                    "tier": "critical",
                    "probability_of_collision": 1e-3,
                    "explanation": "test",
                    "model_version": "test-v1",
                    "inputs": {},
                },
            )
            assert assessment.status_code == 201, assessment.text

            feed = (await client.get("/activity")).json()
            kinds = {item["kind"] for item in feed["items"]}
            assert "conjunction" in kinds

            conjunction = next(
                item for item in feed["items"] if item["kind"] == "conjunction"
            )
            assert conjunction["severity"] == "critical"
            assert conjunction["payload"]["tier"] == "critical"
            assert conjunction["norad_id"] == "25544"

            # The cursor must exclude everything already delivered.
            resumed = (
                await client.get("/activity", params={"since": feed["cursor"]})
            ).json()
            assert resumed["items"] == []

            # A command execution lands in the same unified stream.
            await client.post("/commands/execute", json={"command": "events list"})
            after_command = (
                await client.get("/activity", params={"since": feed["cursor"]})
            ).json()
            assert any(
                item["kind"] == "command" for item in after_command["items"]
            )

    _run(scenario())


def test_activity_feed_rejects_a_malformed_cursor(tmp_path) -> None:
    async def scenario() -> None:
        app = create_app(f"sqlite:///{(tmp_path / 'cursor.db').as_posix()}")
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            client.headers["Authorization"] = (
                f"Bearer {app.state.authenticator.issue_development_token()}"
            )
            bad = await client.get("/activity", params={"since": "yesterday"})
            assert bad.status_code == 422

            naive = (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).replace(tzinfo=None)
            ok = await client.get(
                "/activity", params={"since": naive.isoformat()}
            )
            assert ok.status_code == 200

    _run(scenario())


def test_a_client_far_behind_gets_the_newest_items_in_few_queries(tmp_path) -> None:
    """Collectors took the oldest 200 after the cursor, dropping the newest,
    and looked up each event's assessment and objects one at a time."""
    from datetime import timedelta

    from sqlalchemy import event as sa_event

    from sdebris.activity import collect_activity
    from sdebris.auth import Principal
    from sdebris.ontology.database import Database
    from sdebris.ontology.orm import (
        ConjunctionEventRecord,
        RiskAssessmentRecord,
        ScreeningRunRecord,
        SpaceObjectRecord,
    )

    database = Database(f"sqlite:///{(tmp_path / 'far.db').as_posix()}")
    database.initialize()
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with database.session_factory() as session:
        a = SpaceObjectRecord(norad_id="25544", name="ISS")
        b = SpaceObjectRecord(norad_id="99999", name="DEB")
        run = ScreeningRunRecord(propagator_version="t", configuration={}, input_versions={})
        session.add_all([a, b, run])
        session.flush()
        for n in range(250):
            event = ConjunctionEventRecord(
                screening_run_id=run.id, primary_object_id=a.id, secondary_object_id=b.id,
                tca=base + timedelta(days=30, minutes=n), miss_distance_km=1.0 + n,
                relative_speed_km_s=10.0, created_at=base + timedelta(minutes=n),
            )
            session.add(event)
            session.flush()
            session.add(RiskAssessmentRecord(
                event_id=event.id, tier="watch", probability_of_collision=1e-6,
                explanation="t", model_version="t",
            ))
        session.commit()

    queries = {"n": 0}
    sa_event.listen(
        database.engine, "before_cursor_execute",
        lambda *args, **kwargs: queries.__setitem__("n", queries["n"] + 1),
    )
    principal = Principal(subject="a", email="a@localhost", role=OperatorRole.ANALYST)
    with database.session_factory() as session:
        items = collect_activity(session, base - timedelta(days=1), 50, principal=principal)

    conjunctions = [item for item in items if item.kind == "conjunction"]
    assert len(conjunctions) == 50
    newest = max(item.payload["miss_distance_km"] for item in conjunctions)
    assert newest == 250.0, "the newest event must be in the feed"
    assert all(item.detail == "ISS / DEB" for item in conjunctions)
    assert queries["n"] <= 12, f"{queries['n']} queries for one read"
