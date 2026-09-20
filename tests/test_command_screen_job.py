"""`screen` goes through two database connections and must not self-deadlock."""

from __future__ import annotations

import asyncio

import httpx

from sdebris.api.app import create_app
from sdebris.ontology.enums import JobStatus, OperatorRole


def test_screen_command_queues_a_job_on_sqlite(tmp_path) -> None:
    async def scenario() -> None:
        app = create_app(f"sqlite:///{(tmp_path / 'screen.db').as_posix()}")
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            client.headers["Authorization"] = (
                "Bearer "
                + app.state.authenticator.issue_development_token(
                    subject="screen-test", role=OperatorRole.ANALYST
                )
            )
            response = await client.post(
                "/commands/execute",
                json={
                    "command": "screen 25544 --window 1h --threshold 5km --cached"
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == JobStatus.QUEUED.value
            job_id = body["job"]["id"]

            # The audit record is committed and linked to the queued job.
            listed = await client.get("/screening-jobs")
            assert any(job["id"] == job_id for job in listed.json())

            # And the queued job shows up in the unified activity feed.
            feed = (await client.get("/activity")).json()
            assert any(
                item["kind"] == "job" and item["entity_id"] == job_id
                for item in feed["items"]
            )

    asyncio.run(scenario())
