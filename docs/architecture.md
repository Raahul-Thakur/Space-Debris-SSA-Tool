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
                 reports/writer.py   api/app.py       alerts/notify.py
                 (CSV + JSON)        (FastAPI)        (email / webhook)
                          │               │                │
                          ▼               ▼                ▼
                      CLI (cli.py)   Next.js console  Scheduled CI
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

## Who sees what

The ontology holds three kinds of thing and scopes them differently.

**Reference data** — space objects, element sets, sensor observations, and the
ephemeris derived from them — describes the physical world. There is one ISS.
Everyone reads the same rows, and only the ingestion pipeline or an
administrator writes them: a bad write here is visible to every reader, which
is why those endpoints are admin rather than analyst.

**Derived facts** — conjunction events and their risk assessments — are
computed from that reference data by a deterministic model. Two principals
screening the same object get the same answer, so there is nothing in the
result to keep private, and the public dashboard is built from exactly these
rows.

**Work products** — screening runs, watch lists, cases, decisions, alerts,
manoeuvre scenarios, jobs, commands and the audit trail — record what a
particular principal did, and are scoped to them. Note the asymmetry: the
*run* is private while the conjunction it found is public, because screening
activity reveals operational interest even when its output does not.

A NULL actor means the platform produced the row — a scheduled screening, a
CLI run, the seeded catalogue — and those rows are visible to everyone. That
is what lets an anonymous visitor see a real picture rather than an empty one,
and it is why the platform keeps its own watch list alongside each
principal's.

Administrators read across principals. Everyone else sees their own rows plus
the platform's. A request for someone else's row by id returns 404 rather than
403, because confirming that an id exists is itself a disclosure.

`sdebris.tenancy` is the single place these rules are expressed; call sites
pass a column and a principal rather than re-deriving the predicate.

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
