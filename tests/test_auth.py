import pytest
from fastapi import HTTPException

from sdebris.auth import Authenticator
from sdebris.ontology.enums import OperatorRole


def test_development_token_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_ENV", "development")
    authenticator = Authenticator()
    token = authenticator.issue_development_token("analyst-1", OperatorRole.ANALYST)

    principal = authenticator.verify(token)

    assert principal.subject == "analyst-1"
    assert principal.role is OperatorRole.ANALYST


def test_invalid_token_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_ENV", "development")
    with pytest.raises(HTTPException) as caught:
        Authenticator().verify("not-a-jwt")
    assert caught.value.status_code == 401


def test_production_fails_closed_without_jwks(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_ENV", "production")
    monkeypatch.delenv("SDEBRIS_AUTH_JWKS_URL", raising=False)
    with pytest.raises(RuntimeError, match="JWKS"):
        Authenticator()


def test_production_refuses_to_mint_development_tokens(monkeypatch, tmp_path) -> None:
    """The deployed API has no way in except a real JWKS issuer."""
    import asyncio

    import httpx

    from sdebris.api.app import create_app

    monkeypatch.setenv("SDEBRIS_ENV", "production")
    monkeypatch.setenv("SDEBRIS_JOB_BACKEND", "thread")
    monkeypatch.setenv(
        "SDEBRIS_AUTH_JWKS_URL",
        "https://project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setenv("SDEBRIS_AUTH_ISSUER", "https://project.supabase.co/auth/v1")
    monkeypatch.setenv("SDEBRIS_CORS_ORIGINS", "https://astra-ssa.vercel.app")
    # The startup check reads the environment; the app under test still runs on
    # a throwaway SQLite file passed in directly.
    monkeypatch.setenv(
        "SDEBRIS_DATABASE_URL", "postgresql+psycopg://user:pw@host:6543/postgres"
    )
    app = create_app(f"sqlite:///{(tmp_path / 'prod.db').as_posix()}")

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            assert (await client.post("/auth/development-token")).status_code == 404
            anonymous = await client.post(
                "/commands/execute", json={"command": "events list"}
            )
            assert anonymous.status_code == 401
            assert (await client.get("/health")).status_code == 200

    asyncio.run(scenario())
