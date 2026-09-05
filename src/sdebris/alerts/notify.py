"""Email + webhook alert dispatch with per-pair cooldown.

SMTP credentials are read from the environment so secrets never live in config:
    SDEBRIS_SMTP_HOST, SDEBRIS_SMTP_PORT, SDEBRIS_SMTP_USER, SDEBRIS_SMTP_PASSWORD
A webhook URL may be set in config or via SDEBRIS_WEBHOOK_URL.
"""

from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests

from sdebris.config import Config
from sdebris.screening.screen import ConjunctionEvent, ScreeningResult


def format_digest(result: ScreeningResult, tiers: tuple[str, ...] = ("critical",)) -> str:
    """Human-readable digest of events at the given tiers."""
    selected = [e for e in result.events if e.risk_tier in tiers]
    header = (
        f"Conjunction alert for {result.target_name} (NORAD {result.target_norad})\n"
        f"Window start: {result.window_start.isoformat()}  |  "
        f"{len(selected)} event(s) at tier(s): {', '.join(tiers)}\n"
        + "-" * 64
    )
    if not selected:
        return header + "\nNo qualifying events."
    lines = [header]
    for e in selected:
        lines.append(
            f"[{e.risk_tier.upper()}] {e.secondary_name} (NORAD {e.secondary_norad})\n"
            f"    TCA: {e.tca.isoformat()}\n"
            f"    Miss: {e.miss_distance_km:.3f} km  |  Rel speed: {e.relative_speed_km_s:.3f} km/s\n"
            f"    RAC: R={e.radial_km:.3f} A={e.along_track_km:.3f} C={e.cross_track_km:.3f} km\n"
            f"    Pc: {e.probability_of_collision:.2e}  |  {e.risk_reason}"
        )
    return "\n".join(lines)


class AlertDispatcher:
    """Sends alerts for new critical events, honouring a per-pair cooldown."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.state_path = config.resolve_path("data/cache/alert_state.json")
        self._state = self._load_state()

    def _load_state(self) -> dict[str, str]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _in_cooldown(self, event: ConjunctionEvent, now: datetime) -> bool:
        key = f"{event.target_norad}:{event.secondary_norad}"
        last = self._state.get(key)
        if last is None:
            return False
        elapsed_h = (now - datetime.fromisoformat(last)).total_seconds() / 3600.0
        return elapsed_h < self.config.alerts.cooldown_hours

    def dispatch(self, result: ScreeningResult, tiers: tuple[str, ...] = ("critical",)) -> list[ConjunctionEvent]:
        """Send alerts for qualifying events not currently in cooldown.

        Returns the list of events that were actually alerted on.
        """
        now = datetime.now(timezone.utc)
        fresh = [
            e for e in result.events
            if e.risk_tier in tiers and not self._in_cooldown(e, now)
        ]
        if not fresh:
            return []

        # Build a result-shaped digest from just the fresh events.
        digest_result = ScreeningResult(
            target_norad=result.target_norad, target_name=result.target_name,
            generated_at=result.generated_at, window_start=result.window_start,
            window_hours=result.window_hours, step_sec=result.step_sec,
            report_threshold_km=result.report_threshold_km,
            n_screened=result.n_screened, n_stale=result.n_stale, events=fresh,
        )
        body = format_digest(digest_result, tiers=tiers)

        if self.config.alerts.email.enabled:
            self._send_email(body)
        webhook_url = os.getenv("SDEBRIS_WEBHOOK_URL") or self.config.alerts.webhook.url
        if self.config.alerts.webhook.enabled and webhook_url:
            self._send_webhook(webhook_url, body)

        for e in fresh:
            self._state[f"{e.target_norad}:{e.secondary_norad}"] = now.isoformat()
        self._save_state()
        return fresh

    def _send_email(self, body: str) -> None:
        host = os.getenv("SDEBRIS_SMTP_HOST")
        if not host:
            print("[sdebris] SMTP host not set (SDEBRIS_SMTP_HOST); skipping email.")
            return
        port = int(os.getenv("SDEBRIS_SMTP_PORT", "587"))
        user = os.getenv("SDEBRIS_SMTP_USER")
        password = os.getenv("SDEBRIS_SMTP_PASSWORD")
        msg = MIMEText(body)
        msg["Subject"] = "[sdebris] Critical conjunction alert"
        msg["From"] = self.config.alerts.email.sender
        msg["To"] = ", ".join(self.config.alerts.email.recipients)
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)

    def _send_webhook(self, url: str, body: str) -> None:
        try:
            requests.post(url, json={"text": body}, timeout=15)
        except requests.RequestException as exc:
            print(f"[sdebris] Webhook delivery failed: {exc}")
