"""Alerting: email / webhook notifications with a cooldown to suppress repeats."""

from __future__ import annotations

from sdebris.alerts.notify import AlertDispatcher, format_digest

__all__ = ["AlertDispatcher", "format_digest"]
