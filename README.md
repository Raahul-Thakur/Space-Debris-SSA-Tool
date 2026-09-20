# 🛰️ Space Debris SSA Tool

[![CI](https://github.com/Raahul-Thakur/Space-Debris-SSA-Tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Raahul-Thakur/Space-Debris-SSA-Tool/actions/workflows/ci.yml)
[![Scheduled screening](https://github.com/Raahul-Thakur/Space-Debris-SSA-Tool/actions/workflows/screening.yml/badge.svg)](https://github.com/Raahul-Thakur/Space-Debris-SSA-Tool/actions/workflows/screening.yml)
[![Docs](https://github.com/Raahul-Thakur/Space-Debris-SSA-Tool/actions/workflows/docs.yml/badge.svg)](https://raahul-thakur.github.io/Space-Debris-SSA-Tool/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A conjunction-screening engine for **space situational awareness**. It ingests
live TLEs from CelesTrak, propagates orbits with SGP4, screens an entire catalog
against a target object, refines each close approach to its time of closest
approach (TCA), decomposes the geometry into radial/along-track/cross-track
components, estimates collision probability, and produces structured reports —
all exposed through a CLI, a Streamlit web app, and a scheduled CI pipeline.

> ⚠️ **Educational / portfolio tool.** TLE-derived collision probability is
> *illustrative, not operational* — see [methodology](docs/methodology.md).

---

## Features

| Phase | Capability |
|-------|------------|
| **1 — Foundation** | Live CelesTrak ingestion · SQLite cache with epoch & staleness tracking · vectorised SGP4 propagation · installable `src/` package · pytest suite |
| **2 — Screening** | Target-centric miss distance · TCA via range-rate bisection · RAC decomposition · Foster/Chan **Pc** · TLE-age-weighted uncertainty · tiered risk · canonical CSV + JSON reports · `sdebris` CLI |
| **3 — Interface** | Streamlit app · 3D ECI orbit view · ground tracks · analytics charts · sortable/filterable event table |
| **4 — Automation** | GitHub Actions cron screening · email/webhook alerts with cooldown · MkDocs site · CI/CD |

## Quick start

```bash
pip install -e ".[app,dev]"

sdebris fetch  --group iridium-33-debris        # cache live TLEs
sdebris screen --norad 25544 --threshold-km 25  # screen ISS
streamlit run app/streamlit_app.py              # interactive UI

sdebris ontology-init                           # initialize operational store
sdebris screen --norad 25544 --persist-ontology # persist a governed run
sdebris-api                                     # ontology API on port 8000
```

### Governed command center

The operator frontend is a Next.js + Cesium application. Run the API and frontend
in separate PowerShell terminals:

```powershell
# Terminal 1
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
sdebris-api

# Terminal 2
cd web
npm install
npm run dev
```

Open `http://localhost:3000`. The dashboard supports approved commands such as:

```text
screen 25544 --window 72h --threshold 25km
monitor add 20580
events list --tier critical
case assign <case-id> analyst-1
case close <case-id> --reason "Risk resolved"
event explain <event-id>
orbit refresh 25544
```

Command text is parsed into typed actions and checked against operator roles. It is
never forwarded to a shell. Screening runs asynchronously, streams progress over
Server-Sent Events, supports cancellation, and persists its job and command audit
history in the ontology database.

New to the console? It ships with three things to get you moving:

- **A guided tour** that walks the layout in about a minute. It opens on a first
  visit and can be replayed from the `TOUR` button or the documentation page.
- **A documentation page** at `/docs` with the command reference, the concepts
  behind the numbers, the methodology and its limits, and sample queries you can
  send straight to the console.
- **Sample queries** in the command palette, each with a note on what it does and
  roughly how long it takes. `Ctrl`+`K` focuses the console from anywhere.

The dashboard also holds an open stream to `GET /stream/activity` and renders
conjunctions, alerts, job transitions, commands, and governance actions as they
are recorded — including actions taken by other operators — so nothing needs a
page refresh.

Example output:

```
ISS (ZARYA) (NORAD 25544) — screened 107 objects over 72 h
Events: 0 critical, 2 watch, 5 nominal  (16 stale TLEs)
Report: data/reports/screening_25544_<ts>.csv
```

## How it works

```
CelesTrak → SQLite cache → SGP4 propagation → coarse screen
  → TCA refinement → RAC geometry → Pc (Foster/Chan) → risk tiers
  → CSV/JSON report · 3D viz · email/webhook alerts
```

See [docs/architecture.md](docs/architecture.md) and
[docs/methodology.md](docs/methodology.md) for the full data flow and the science.
For the zero-cost public stack — Vercel Hobby for the frontend, a Render free
web service for the API, and one Supabase free project for both Postgres and
authentication — follow
[docs/deployment-free-tier.md](docs/deployment-free-tier.md). On that stack
screening runs in the API process (`SDEBRIS_JOB_BACKEND=thread`), so no Redis
broker or separate worker is required.

## Project layout

```
src/sdebris/
  config.py          # typed config + YAML loader
  models.py          # SpaceObject, TLE parsing, epoch/age
  ingest/            # CelesTrak client + SQLite cache
  propagation/       # vectorised SGP4 -> Ephemeris
  screening/         # screen.py, tca.py, frames.py
  risk/              # pc.py (Foster/Chan), classify.py
  reports/           # CSV + JSON writer
  viz/               # Plotly orbit / ground-track figures
  alerts/            # email + webhook dispatch
  ontology/          # typed objects, versioned data, actions, audit + lineage
  api/               # FastAPI operational interface
  commands/          # allowlisted command grammar + role gates
  jobs/              # persisted asynchronous screening worker
  cli.py             # `sdebris` command
app/streamlit_app.py # Phase 3 web interface
web/                 # Next.js + Cesium operator command center
migrations/          # Alembic ontology schema history
configs/default.yaml # all tunable parameters
tests/               # pytest suite
docs/                # MkDocs site
.github/workflows/   # CI, scheduled screening, docs deploy
```

## Development

```bash
pip install -e ".[app,dev,docs]"
pytest                       # run the test suite
ruff check src tests         # lint
mkdocs serve                 # preview docs
```

Contributions and methodology feedback are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and report exploitable
issues through the private process in [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- TLE data: [CelesTrak](https://celestrak.org)
- Propagation: the [`sgp4`](https://pypi.org/project/sgp4/) library
- Pc method: Foster (1992) & Chan, *Spacecraft Collision Probability*
