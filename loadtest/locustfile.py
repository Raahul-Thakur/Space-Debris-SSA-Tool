"""Load profile for Astra / SSA, shaped like real traffic.

Two kinds of user:

* ``Visitor`` (most traffic): opens the console, which makes the same three
  public reads the browser does (platform watch list, assessed events, one
  batched trajectory request for the watched objects), then reads an event
  explanation, looks at pricing or reloads, pausing like a person.
* ``Analyst`` (signed in): their jobs, watch list, account and activity feed,
  a console command now and then, and, only when explicitly enabled, a real
  screening job.

Configuration (environment variables):

  LOADTEST_TARGET        "local" (default) or "production".
  LOADTEST_PUBLIC_BASE   Where public reads go. Default: the API host
                         (direct). To go through the Cloudflare edge cache,
                         set it to the site, e.g. https://astra-ssa.pages.dev,
                         and reads are sent to <site>/api/public/<path>.
  LOADTEST_TOKENS        Path to a file of bearer tokens, one per line, for
                         Analysts in production. Locally, development tokens
                         are minted instead (needs SDEBRIS_ENV=development).
  LOADTEST_SCREENINGS    "1" to let Analysts start screening jobs. Off by
                         default; in production it also needs
                         LOADTEST_I_UNDERSTAND=1, because each job costs real
                         CPU and counts against the account's quota.
  LOADTEST_SPOOF_IPS     "1" (default locally, refused in production) sends a
                         distinct X-Forwarded-For per simulated visitor, so
                         the per-address limits behave as they would for many
                         real people rather than one test machine.

See loadtest/README.md for runs.
"""

from __future__ import annotations

import itertools
import os
import random
from pathlib import Path

from locust import HttpUser, between, events, task

TARGET = os.getenv("LOADTEST_TARGET", "local")
PRODUCTION = TARGET == "production"
PUBLIC_BASE = os.getenv("LOADTEST_PUBLIC_BASE", "").rstrip("/")
SCREENINGS = os.getenv("LOADTEST_SCREENINGS") == "1"
SPOOF_IPS = os.getenv("LOADTEST_SPOOF_IPS", "0" if PRODUCTION else "1") == "1"

if PRODUCTION and SPOOF_IPS:
    raise SystemExit("LOADTEST_SPOOF_IPS is not allowed against production")
if PRODUCTION and SCREENINGS and os.getenv("LOADTEST_I_UNDERSTAND") != "1":
    raise SystemExit("screenings against production need LOADTEST_I_UNDERSTAND=1")

_ip_counter = itertools.count(1)
_tokens: list[str] = []
if os.getenv("LOADTEST_TOKENS"):
    _tokens = [
        line.strip() for line in Path(os.environ["LOADTEST_TOKENS"]).read_text().splitlines()
        if line.strip()
    ]
_token_cycle = itertools.cycle(_tokens) if _tokens else None


def _fake_ip() -> str:
    n = next(_ip_counter)
    return f"198.18.{(n // 250) % 250}.{n % 250 + 1}"  # 198.18.0.0/15: benchmarking range


class _Base(HttpUser):
    abstract = True

    def on_start(self) -> None:
        self.headers: dict[str, str] = {}
        if SPOOF_IPS:
            self.headers["X-Forwarded-For"] = _fake_ip()
        self.watched: list[str] = []
        self.event_ids: list[str] = []

    def public(self, path: str, name: str):
        """A public read: direct to the API, or through the edge cache."""
        if PUBLIC_BASE:
            url = f"{PUBLIC_BASE}/api/public/{path.lstrip('/')}"
        else:
            url = path
        return self.client.get(url, headers=self.headers, name=name)

    def open_console(self) -> None:
        """The three public reads a browser makes when the console loads."""
        response = self.public("/monitoring/platform", "public: watch list")
        if response.ok:
            self.watched = [row["norad_id"] for row in response.json()][:40]
        response = self.public("/events/assessed", "public: assessed events")
        if response.ok:
            body = response.json()
            rows = body.get("events", body) if isinstance(body, dict) else body
            self.event_ids = [row["id"] for row in rows if isinstance(row, dict) and "id" in row]
        if self.watched:
            ids = ",".join(self.watched)
            self.public(
                f"/trajectories?norad_ids={ids}&window_hours=3&step_sec=180",
                "public: trajectories (batch)",
            )


class Visitor(_Base):
    weight = 8
    wait_time = between(4, 15)

    def on_start(self) -> None:
        super().on_start()
        self.open_console()

    @task(4)
    def read_an_explanation(self) -> None:
        if self.event_ids:
            event_id = random.choice(self.event_ids)
            self.public(f"/events/{event_id}/explanation", "public: event explanation")

    @task(2)
    def reload(self) -> None:
        self.open_console()

    @task(1)
    def pricing(self) -> None:
        # Visitors read the plans through the edge cache, as the pricing page does.
        self.public("/billing/plans", "pricing: plans")


class Analyst(_Base):
    weight = 2
    wait_time = between(5, 20)

    def on_start(self) -> None:
        super().on_start()
        if _token_cycle is not None:
            token = next(_token_cycle)
        elif PRODUCTION:
            raise SystemExit("set LOADTEST_TOKENS to run Analysts against production")
        else:
            subject = f"loadtest-{next(_ip_counter)}"
            response = self.client.post(
                "/auth/development-token",
                params={"subject": subject, "role": "analyst"},
                name="setup: dev token",
            )
            token = response.json()["access_token"]
        self.headers["Authorization"] = f"Bearer {token}"
        self.open_console()

    def signed_in(self, method: str, path: str, name: str, **kwargs):
        return self.client.request(method, path, headers=self.headers, name=name, **kwargs)

    @task(4)
    def dashboard(self) -> None:
        self.signed_in("GET", "/screening-jobs", "signed-in: jobs")
        self.signed_in("GET", "/monitoring", "signed-in: watch list")
        self.signed_in("GET", "/activity?limit=50", "signed-in: activity")

    @task(1)
    def account(self) -> None:
        self.signed_in("GET", "/billing/me", "signed-in: account")

    @task(2)
    def command(self) -> None:
        self.signed_in(
            "POST", "/commands/execute", "signed-in: command (events list)",
            json={"command": "events list --tier watch"},
        )

    @task(1)
    def screening(self) -> None:
        if not SCREENINGS:
            return
        with self.client.post(
            "/screening-jobs",
            headers=self.headers,
            json={"norad_id": "80000", "window_hours": 6, "threshold_km": 25,
                  "refresh_catalog": False},
            name="signed-in: start screening",
            catch_response=True,
        ) as response:
            # Refusals by the limits (one job at a time, quota) are the
            # platform working, not failing.
            if response.status_code in (202, 402, 429):
                response.success()


@events.init_command_line_parser.add_listener
def _describe(parser) -> None:
    parser.description = __doc__.split("\n\n")[0]
