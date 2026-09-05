# Architecture

## Data flow

```
                CelesTrak GP API
                       │  (TLE text)
                       ▼
   ingest/celestrak.py ── parse ──▶ ingest/cache.py  (SQLite, epoch tracking)
                                          │  SpaceObject[]
                                          ▼
                       propagation/sgp4_prop.py  ── vectorised SGP4 ──▶ Ephemeris
                                          │  (positions/velocities, ECI/TEME)
                                          ▼
   screening/screen.py  ──┬─ coarse distance filter
                          ├─ screening/tca.py     (range-rate bisection → TCA)
                          ├─ screening/frames.py  (RAC decomposition)
                          ├─ risk/pc.py           (Foster + Chan Pc)
                          └─ risk/classify.py     (tiered risk)
                                          │  ScreeningResult (events + metadata)
                          ┌───────────────┼────────────────┐
                          ▼               ▼                ▼
                 reports/writer.py   viz/orbits.py    alerts/notify.py
                 (CSV + JSON)        (Plotly figs)    (email / webhook)
                          │               │                │
                          ▼               ▼                ▼
                      CLI (cli.py)   Streamlit app    Scheduled CI
```

## Modules

| Package            | Responsibility                                              |
|--------------------|-------------------------------------------------------------|
| `config`           | Typed (pydantic) config model + YAML loader with deep merge |
| `models`           | `SpaceObject`, TLE parsing, epoch/age/staleness             |
| `ingest`           | CelesTrak client + SQLite cache                             |
| `propagation`      | Vectorised SGP4 → `Ephemeris` (state arrays)                |
| `screening`        | Target-centric screening, TCA refinement, RAC frames        |
| `risk`             | Collision probability + tiered classification               |
| `reports`          | Canonical CSV + JSON metadata with validation               |
| `viz`              | Plotly 3D orbit, ground-track, and analytics figures        |
| `alerts`           | Email/webhook dispatch with per-pair cooldown               |
| `cli`              | `sdebris` command (Click + Rich)                            |

## Design choices

- **Single config object** drives the CLI, the app, and the scheduled job, so
  every entry point behaves identically.
- **Array-first propagation** (`Satrec.sgp4_array`) keeps screening fast: each
  object is propagated across the whole time grid in one C call.
- **Coarse-then-refine screening**: a cheap per-step distance filter prunes the
  catalog before the more expensive TCA refinement and Pc computation run only
  on genuine candidates.
- **Offline resilience**: if CelesTrak is unreachable, the pipeline falls back to
  the cached catalog (or bundled sample TLEs) so demos never hard-fail.

## Operational layer

The screening engine can persist a completed run into a typed operational
ontology. Element sets are append-only and every event is connected to its
screening run, input versions, risk assessment, monitoring case, operator
decisions, audit actions, and lineage edges.

```text
TLE versions -> ScreeningRun -> ConjunctionEvent -> RiskAssessment
                                      |
                                      v
                                MonitoringCase -> OperatorDecision
                                      |
                                      +-> governed actions + immutable audit
```

SQLite provides a zero-setup local backend. The SQLAlchemy mappings and Alembic
migrations are designed to move to PostgreSQL for deployment. FastAPI exposes
the same ontology and action layer to future React/Cesium and agent clients.
