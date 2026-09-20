"""CORS has to admit the deployed frontend and its preview deployments."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from sdebris.api.app import create_app

PRODUCTION = "https://astra-ssa.vercel.app"
PREVIEW = "https://astra-ssa-git-feature-someone.vercel.app"
PREVIEW_REGEX = r"https://astra-ssa-[a-z0-9-]+\.vercel\.app"


def _origin_allowed(app, origin: str) -> str | None:
    async def scenario() -> str | None:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/health", headers={"Origin": origin})
            return response.headers.get("access-control-allow-origin")

    return asyncio.run(scenario())


def test_only_the_configured_origins_are_allowed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_CORS_ORIGINS", PRODUCTION)
    monkeypatch.delenv("SDEBRIS_CORS_ORIGIN_REGEX", raising=False)
    app = create_app(f"sqlite:///{(tmp_path / 'cors.db').as_posix()}")

    assert _origin_allowed(app, PRODUCTION) == PRODUCTION
    # Preview deployments are refused until the pattern is configured.
    assert _origin_allowed(app, PREVIEW) is None
    assert _origin_allowed(app, "https://attacker.example") is None


def test_the_preview_pattern_admits_preview_deployments(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_CORS_ORIGINS", PRODUCTION)
    monkeypatch.setenv("SDEBRIS_CORS_ORIGIN_REGEX", PREVIEW_REGEX)
    app = create_app(f"sqlite:///{(tmp_path / 'cors-preview.db').as_posix()}")

    assert _origin_allowed(app, PRODUCTION) == PRODUCTION
    assert _origin_allowed(app, PREVIEW) == PREVIEW
    # The pattern must not become a wildcard.
    assert _origin_allowed(app, "https://astra-ssa.attacker.example") is None


def test_a_malformed_pattern_fails_fast(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_CORS_ORIGIN_REGEX", "https://[unclosed")
    with pytest.raises(RuntimeError, match="valid regular expression"):
        create_app(f"sqlite:///{(tmp_path / 'cors-bad.db').as_posix()}")
