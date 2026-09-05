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
