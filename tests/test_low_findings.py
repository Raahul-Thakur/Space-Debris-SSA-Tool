"""The audit's low-severity findings, each pinned by a test."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from sdebris.api.app import create_app
from sdebris.jobs.manager import ScreeningRequestError, _user_facing_error
from sdebris.ontology.database import Database


def _production(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_ENV", "production")
    monkeypatch.setenv("SDEBRIS_JOB_BACKEND", "thread")
    monkeypatch.setenv(
        "SDEBRIS_AUTH_JWKS_URL", "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    )
    monkeypatch.setenv("SDEBRIS_AUTH_ISSUER", "https://project.supabase.co/auth/v1")
    monkeypatch.setenv("SDEBRIS_CORS_ORIGINS", "https://astra-ssa.pages.dev")
    monkeypatch.setenv("SDEBRIS_DATABASE_URL", "postgresql+psycopg://user:pw@host:6543/postgres")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def test_production_publishes_no_api_map(monkeypatch, tmp_path) -> None:
    """/docs and /openapi.json listed every route, admin ones included."""
    _production(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'p.db').as_posix()}")
    with TestClient(app) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, path


def test_development_keeps_the_api_docs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SDEBRIS_ENV", "development")
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'd.db').as_posix()}")) as client:
        assert client.get("/openapi.json").status_code == 200


def test_lineage_needs_a_signed_in_caller(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SDEBRIS_ENV", "development")
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'l.db').as_posix()}")) as client:
        assert client.get("/lineage/ConjunctionEvent/x").status_code == 401
        token = client.post(
            "/auth/development-token", params={"subject": "v", "role": "viewer"}
        ).json()["access_token"]
        signed_in = client.get(
            "/lineage/ConjunctionEvent/x", headers={"Authorization": f"Bearer {token}"}
        )
        assert signed_in.status_code == 200


def test_cors_never_allows_credentials(monkeypatch, tmp_path) -> None:
    """Tokens are headers, so a cookie-bearing cross-origin call has no use."""
    monkeypatch.setenv("SDEBRIS_ENV", "development")
    monkeypatch.setenv("SDEBRIS_CORS_ORIGINS", "https://astra-ssa.pages.dev")
    with TestClient(create_app(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "https://astra-ssa.pages.dev",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.headers.get("access-control-allow-origin") == "https://astra-ssa.pages.dev"
    assert "access-control-allow-credentials" not in response.headers


def test_a_failed_job_shows_its_owner_no_internal_detail(caplog) -> None:
    internal = RuntimeError("could not open /usr/lib/python3/site-packages/x.db: SQL error")
    with caplog.at_level("ERROR", logger="sdebris.jobs.manager"):
        shown = _user_facing_error(internal, "job-123")
    assert "site-packages" not in shown and "SQL" not in shown
    assert "job-123" in shown
    assert "site-packages" in caplog.text  # the detail is logged instead


def test_a_problem_with_the_request_is_still_explained() -> None:
    error = ScreeningRequestError("NORAD 99999 is not available in the catalog")
    assert _user_facing_error(error, "job-1") == "NORAD 99999 is not available in the catalog"


def test_a_migrated_database_is_left_to_alembic(tmp_path) -> None:
    """create_all on a migrated database made tables no migration knew about."""
    database = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    with database.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    database.initialize()
    assert inspect(database.engine).get_table_names() == ["alembic_version"]


def test_a_fresh_local_database_still_gets_the_schema(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'f.db').as_posix()}")
    database.initialize()
    assert "screening_jobs" in inspect(database.engine).get_table_names()
