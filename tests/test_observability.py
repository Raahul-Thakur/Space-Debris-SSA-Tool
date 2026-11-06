"""Errors are visible to the operator, and secrets are not visible to anyone."""

from __future__ import annotations

import json
import logging

import requests

from sdebris.runtime import JsonFormatter, configure_error_tracking


def test_a_logged_exception_keeps_its_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.getLogger("t").makeRecord(
            "t", logging.ERROR, __file__, 1, "failed", (), exc_info=__import__("sys").exc_info()
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "Traceback" in payload["exception"]
    assert "ValueError: boom" in payload["exception"]


def test_error_tracking_is_off_without_a_dsn(monkeypatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert configure_error_tracking() is False


def test_error_tracking_sends_no_personal_data(monkeypatch) -> None:
    import sentry_sdk

    seen: dict = {}
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: seen.update(kwargs))
    assert configure_error_tracking() is True
    assert seen["send_default_pii"] is False
    assert seen["max_request_body_size"] == "never"
    assert seen["environment"] == "development"


def test_a_failed_alert_webhook_never_prints_its_url(monkeypatch, capsys) -> None:
    from sdebris.alerts.notify import AlertDispatcher
    from sdebris.config import load_config

    secret_url = "https://hooks.slack.com/services/T000/B000/SECRETTOKEN"

    def fail(url, json=None, timeout=None):
        raise requests.ConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {url}")

    monkeypatch.setattr("sdebris.alerts.notify.requests.post", fail)
    AlertDispatcher(load_config())._send_webhook(secret_url, "alert")
    output = capsys.readouterr().out
    assert "failed" in output
    assert "SECRETTOKEN" not in output and "hooks.slack.com" not in output
