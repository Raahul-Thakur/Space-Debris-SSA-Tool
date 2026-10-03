# Usage

## Installation

```bash
git clone <repo-url>
cd "Space debris SSA tool"
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[app,dev,docs]"
```

## CLI

The package installs a `sdebris` command.

```bash
# Refresh the local TLE cache from CelesTrak
sdebris fetch --group iridium-33-debris

# Inspect the cache
sdebris catalog

# Screen the catalog against a target (ISS = 25544)
sdebris screen --norad 25544 --window-hours 72 --threshold-km 25

# Offline (cache only) + dispatch alerts for critical events
sdebris screen --norad 25544 --no-fetch --alert
```

### Key `screen` options

| Option            | Meaning                                          |
|-------------------|--------------------------------------------------|
| `--norad`         | Target NORAD catalog id (required)               |
| `--group`         | CelesTrak group to screen against                |
| `--window-hours`  | Look-ahead propagation window                    |
| `--step-sec`      | Coarse propagation step                          |
| `--threshold-km`  | Report only approaches closer than this          |
| `--start`         | ISO-8601 UTC start time (default: now)           |
| `--no-fetch`      | Use the cache only; skip CelesTrak               |
| `--alert`         | Send email / webhook alerts for critical events  |
| `--config`        | Path to a YAML config overriding the defaults    |

## Operator console

The web interface is the Next.js app in `web/`, backed by the FastAPI service.
Run both:

```bash
sdebris-api                       # FastAPI on 127.0.0.1:8000
cd web && npm install && npm run dev   # console on localhost:3000
```

Everything is driven from one typed command surface, parsed against an
allowlist. The console shows the orbital picture in 3D, a live activity stream,
telemetry for the selected object, and streaming progress for screening jobs.
Open `/docs` in the app for the full command reference, or press the TOUR
button for a guided walkthrough.

## Configuration

All behaviour is driven by `configs/default.yaml`. Copy it, edit, and pass with
`--config my.yaml`, or override individual fields via CLI flags. See the file's
inline comments for every option (thresholds, uncertainty model, alerts, etc.).

## Alerts

Set delivery channels in config (`alerts.email`, `alerts.webhook`) and provide
secrets via environment variables:

```bash
export SDEBRIS_WEBHOOK_URL="https://hooks.slack.com/services/..."
export SDEBRIS_SMTP_HOST=smtp.example.com
export SDEBRIS_SMTP_USER=...  SDEBRIS_SMTP_PASSWORD=...
```

A per-pair cooldown (`alerts.cooldown_hours`) suppresses repeat alerts.
