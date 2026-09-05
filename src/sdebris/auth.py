"""JWT authentication and server-owned role authorization.

Production tokens are verified against an OIDC/Supabase JWKS endpoint. A local
development token issuer exists only when ``SDEBRIS_ENV=development``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sdebris.ontology.enums import OperatorRole


ROLE_RANK = {
    OperatorRole.VIEWER: 0,
    OperatorRole.ANALYST: 1,
    OperatorRole.OPERATOR: 2,
    OperatorRole.ADMIN: 3,
}


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str | None
    role: OperatorRole

    @property
    def actor(self) -> str:
        return self.email or self.subject


class Authenticator:
    def __init__(self) -> None:
        self.environment = os.getenv("SDEBRIS_ENV", "development").lower()
        self.jwks_url = os.getenv("SDEBRIS_AUTH_JWKS_URL")
        self.issuer = os.getenv("SDEBRIS_AUTH_ISSUER")
        self.audience = os.getenv("SDEBRIS_AUTH_AUDIENCE", "authenticated")
        self.dev_secret = os.getenv(
            "SDEBRIS_DEV_JWT_SECRET", "local-development-only-change-me"
        )
        if self.environment == "production" and not self.jwks_url:
            raise RuntimeError("SDEBRIS_AUTH_JWKS_URL is required in production")
        self._jwk_client = jwt.PyJWKClient(self.jwks_url) if self.jwks_url else None

    def verify(self, token: str) -> Principal:
        try:
            if self._jwk_client:
                key = self._jwk_client.get_signing_key_from_jwt(token).key
                claims = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256", "ES256"],
                    audience=self.audience,
                    issuer=self.issuer,
                    options={"verify_iss": bool(self.issuer)},
                )
            elif self.environment == "development":
                claims = jwt.decode(
                    token,
                    self.dev_secret,
                    algorithms=["HS256"],
                    audience=self.audience,
                    issuer="sdebris-local",
                )
            else:  # defensive: constructor already rejects this configuration
                raise RuntimeError("authentication is not configured")
        except (jwt.PyJWTError, RuntimeError) as exc:
            raise HTTPException(status_code=401, detail="invalid or expired access token") from exc

        metadata: dict[str, Any] = claims.get("app_metadata") or {}
        raw_role = metadata.get("role", claims.get("role", OperatorRole.VIEWER.value))
        # Supabase's default JWT role is "authenticated"; application roles live
        # in app_metadata and safely fall back to viewer.
        if raw_role == "authenticated":
            raw_role = OperatorRole.VIEWER.value
        try:
            role = OperatorRole(raw_role)
        except ValueError:
            role = OperatorRole.VIEWER
        subject = str(claims.get("sub") or "")
        if not subject:
            raise HTTPException(status_code=401, detail="token has no subject")
        return Principal(subject=subject, email=claims.get("email"), role=role)

    def issue_development_token(
        self, subject: str = "local-operator", role: OperatorRole = OperatorRole.ADMIN
    ) -> str:
        if self.environment != "development":
            raise HTTPException(status_code=404, detail="not found")
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": subject,
                "email": f"{subject}@localhost",
                "app_metadata": {"role": role.value},
                "aud": self.audience,
                "iss": "sdebris-local",
                "iat": now,
                "exp": now + timedelta(hours=12),
            },
            self.dev_secret,
            algorithm="HS256",
        )


bearer = HTTPBearer(auto_error=False)


def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer token required")
    return request.app.state.authenticator.verify(credentials.credentials)


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require_role(principal: Principal, minimum: OperatorRole) -> None:
    if ROLE_RANK[principal.role] < ROLE_RANK[minimum]:
        raise HTTPException(
            status_code=403,
            detail=f"{minimum.value} role required; current role is {principal.role.value}",
        )
