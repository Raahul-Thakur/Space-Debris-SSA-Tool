"""Production startup validation for the deployed stacks.

The free deployment runs a single Render instance with the in-process thread
pool, so Redis must not be part of the contract there; the Redis backend still
has to fail closed without a broker URL.
"""

from __future__ import annotations

import pytest

from sdebris.runtime import validate_environment

BASE = {
    "SDEBRIS_ENV": "production",
    "SDEBRIS_DATABASE_URL": "postgresql+psycopg://user:pw@host:6543/postgres",
    "SDEBRIS_AUTH_JWKS_URL": "https://p.supabase.co/auth/v1/.well-known/jwks.json",
    "SDEBRIS_AUTH_ISSUER": "https://p.supabase.co/auth/v1",
    "SDEBRIS_CORS_ORIGINS": "https://astra-ssa.vercel.app",
}


def _apply(monkeypatch, **overrides: str | None) -> None:
    for key, value in {**BASE, **overrides}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_thread_backend_needs_no_redis(monkeypatch) -> None:
    _apply(monkeypatch, SDEBRIS_JOB_BACKEND="thread", SDEBRIS_REDIS_URL=None)
    validate_environment()


def test_thread_backend_is_the_default(monkeypatch) -> None:
    _apply(monkeypatch, SDEBRIS_JOB_BACKEND=None, SDEBRIS_REDIS_URL=None)
    validate_environment()


def test_thread_backend_warns_that_jobs_are_not_durable(monkeypatch, caplog) -> None:
    _apply(monkeypatch, SDEBRIS_JOB_BACKEND="thread", SDEBRIS_REDIS_URL=None)
    with caplog.at_level("WARNING", logger="sdebris.runtime"):
        validate_environment()
    assert "durable" in caplog.text


def test_redis_backend_still_requires_a_broker(monkeypatch) -> None:
    _apply(monkeypatch, SDEBRIS_JOB_BACKEND="redis", SDEBRIS_REDIS_URL=None)
    with pytest.raises(RuntimeError, match="SDEBRIS_REDIS_URL"):
        validate_environment()


def test_redis_backend_accepts_a_broker(monkeypatch) -> None:
    _apply(
        monkeypatch,
        SDEBRIS_JOB_BACKEND="redis",
        SDEBRIS_REDIS_URL="rediss://default:pw@host:6379",
    )
    validate_environment()


def test_an_unknown_backend_is_refused(monkeypatch) -> None:
    _apply(monkeypatch, SDEBRIS_JOB_BACKEND="celery", SDEBRIS_REDIS_URL=None)
    with pytest.raises(RuntimeError, match="SDEBRIS_JOB_BACKEND"):
        validate_environment()


def test_sqlite_is_still_refused_in_production(monkeypatch) -> None:
    _apply(
        monkeypatch,
        SDEBRIS_JOB_BACKEND="thread",
        SDEBRIS_REDIS_URL=None,
        SDEBRIS_DATABASE_URL="sqlite:///data/ontology.sqlite",
    )
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        validate_environment()


def test_localhost_cors_is_still_refused_in_production(monkeypatch) -> None:
    _apply(
        monkeypatch,
        SDEBRIS_JOB_BACKEND="thread",
        SDEBRIS_REDIS_URL=None,
        SDEBRIS_CORS_ORIGINS="http://localhost:3000",
    )
    with pytest.raises(RuntimeError, match="localhost"):
        validate_environment()


def test_development_skips_every_check(monkeypatch) -> None:
    _apply(
        monkeypatch,
        SDEBRIS_ENV="development",
        SDEBRIS_DATABASE_URL="sqlite:///data/ontology.sqlite",
        SDEBRIS_JOB_BACKEND="thread",
        SDEBRIS_REDIS_URL=None,
        SDEBRIS_CORS_ORIGINS="http://localhost:3000",
    )
    validate_environment()
