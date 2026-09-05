import asyncio
from datetime import datetime, timezone

import httpx

from sdebris.api.app import create_app
from sdebris.ontology.enums import OperatorRole


def test_ontology_api_end_to_end(tmp_path) -> None:
    async def scenario() -> None:
        database_url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
        app = create_app(database_url)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                assert (await client.get("/health")).json()["status"] == "ok"
                anonymous = await client.post(
                    "/commands/execute", json={"command": "events list"}
                )
                assert anonymous.status_code == 401
                token = app.state.authenticator.issue_development_token(
                    subject="test-operator", role=OperatorRole.ADMIN
                )
                client.headers["Authorization"] = f"Bearer {token}"
                description = (await client.get("/ontology")).json()
                assert "SpaceObject" in description["object_types"]
                assert "assign_case" in description["actions"]

                for norad, name in (("25544", "ISS"), ("99999", "TEST DEBRIS")):
                    response = await client.post(
                        "/objects",
                        json={
                            "norad_id": norad,
                            "name": name,
                            "orbit_class": "LEO",
                            "status": "active",
                        },
                    )
                    assert response.status_code == 201, response.text

                run_response = await client.post(
                    "/screening-runs",
                    json={
                        "propagator_version": "sgp4-test",
                        "configuration": {"window_hours": 24},
                        "input_versions": {},
                    },
                )
                assert run_response.status_code == 201
                run_id = run_response.json()["id"]

                event_response = await client.post(
                    "/events",
                    json={
                        "primary_norad_id": "25544",
                        "secondary_norad_id": "99999",
                        "screening_run_id": run_id,
                        "tca": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                        "miss_distance_km": 0.9,
                        "relative_speed_km_s": 11.5,
                    },
                )
                assert event_response.status_code == 201, event_response.text
                event_id = event_response.json()["id"]

                assessment_response = await client.post(
                    f"/events/{event_id}/assessments",
                    json={
                        "tier": "critical",
                        "probability_of_collision": 0.0002,
                        "model_version": "foster-chan-v1",
                        "explanation": "Critical threshold exceeded.",
                    },
                )
                assert assessment_response.status_code == 201

                case_response = await client.post(
                    f"/events/{event_id}/cases",
                    json={
                        "title": "Investigate ISS encounter",
                        "priority": "P0",
                        "actor": "system",
                        "justification": "Critical assessment created",
                    },
                )
                assert case_response.status_code == 201, case_response.text
                case_id = case_response.json()["id"]

                assign_response = await client.post(
                    f"/cases/{case_id}/actions/assign_case",
                    json={
                        "actor": "ops-lead",
                        "assignee": "analyst-1",
                        "justification": "Assign to the current orbital analyst",
                        "data_versions": {"screening_run": run_id},
                    },
                )
                assert assign_response.status_code == 200, assign_response.text
                assert assign_response.json()["assignee"] == "analyst-1"

                explain_response = await client.post(
                    "/commands/execute",
                    json={
                        "command": f"event explain {event_id}",
                    },
                )
                assert explain_response.status_code == 200, explain_response.text
                assert explain_response.json()["result"]["tier"] == "critical"

                viewer_token = app.state.authenticator.issue_development_token(
                    subject="observer", role=OperatorRole.VIEWER
                )
                denied = await client.post(
                    "/commands/execute",
                    headers={"Authorization": f"Bearer {viewer_token}"},
                    json={"command": "screen 25544"},
                )
                assert denied.status_code == 403

                spoofed = await client.post(
                    "/commands/execute",
                    json={"command": "events list", "role": "admin", "actor": "fake"},
                )
                assert spoofed.status_code == 422

                audit = (await client.get("/audit-actions")).json()
                assert [item["action_type"] for item in audit] == [
                    "assign_case",
                    "open_case",
                ]
                lineage_response = await client.get(
                    f"/lineage/ConjunctionEvent/{event_id}"
                )
                event_lineage = lineage_response.json()
                assert {edge["relationship"] for edge in event_lineage} >= {
                    "involved_in",
                    "produced",
                    "has_assessment",
                    "opens",
                }

    asyncio.run(scenario())
