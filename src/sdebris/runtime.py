"""Production configuration validation and structured logging."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import Request


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "method", "path", "status", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("SDEBRIS_LOG_LEVEL", "INFO").upper())


#: Job backends the API will start under in production.
PRODUCTION_JOB_BACKENDS = ("thread", "redis")


def validate_environment() -> None:
    if os.getenv("SDEBRIS_ENV", "development").lower() != "production":
        return
    backend = os.getenv("SDEBRIS_JOB_BACKEND", "thread").lower()
    if backend not in PRODUCTION_JOB_BACKENDS:
        raise RuntimeError(
            "SDEBRIS_JOB_BACKEND must be one of "
            f"{', '.join(PRODUCTION_JOB_BACKENDS)}; got {backend!r}"
        )
    required = [
        "SDEBRIS_DATABASE_URL",
        "SDEBRIS_AUTH_JWKS_URL",
        "SDEBRIS_AUTH_ISSUER",
        "SDEBRIS_CORS_ORIGINS",
    ]
    # Redis is only part of the contract when it is the queue being used. The
    # single-instance free deployment runs the thread backend instead.
    if backend == "redis":
        required.append("SDEBRIS_REDIS_URL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing production environment variables: {', '.join(missing)}")
    if not os.environ["SDEBRIS_DATABASE_URL"].startswith("postgresql"):
        raise RuntimeError("production requires PostgreSQL; SQLite is ephemeral")
    if "localhost" in os.environ["SDEBRIS_CORS_ORIGINS"]:
        raise RuntimeError("production CORS origins must not contain localhost")
    if backend == "thread":
        logging.getLogger("sdebris.runtime").warning(
            "running production screening on the in-process thread pool; "
            "a job in flight is lost if the instance restarts. Set "
            "SDEBRIS_JOB_BACKEND=redis with SDEBRIS_REDIS_URL for a durable queue."
        )


async def request_log_middleware(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logging.getLogger("sdebris.request").info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return response
