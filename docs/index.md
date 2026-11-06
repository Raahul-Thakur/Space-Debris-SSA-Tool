# Space Debris SSA Tool

A conjunction-screening engine for space situational awareness (SSA). It fetches
public two-line element sets (TLEs) from CelesTrak, propagates orbits with SGP4, finds close
approaches to a chosen target object, estimates collision probability, classifies
risk, and produces structured reports — exposed through a CLI, a Next.js
operator console, and a scheduled GitHub Actions pipeline.

## What it does

- **TLE ingestion** from CelesTrak, refreshed on each run, with a local SQLite
  cache and staleness tracking. If CelesTrak is unreachable, the cache is used.
- **Vectorised SGP4 propagation** producing ECI (TEME) state vectors.
- **Target-centric screening**: miss distance, refined time of closest approach
  (TCA), and radial / along-track / cross-track (RAC) geometry.
- **Collision probability (Pc)** from Chan's analytic series in the encounter
  (conjunction) plane.
- **Tiered risk classification** (critical / watch / nominal).
- **Structured output**: canonical CSV + JSON metadata with validation checks.
- **Interactive UI**: 3D orbit view, ground tracks, and analytics charts.
- **Automation**: scheduled screening with email / webhook alerts.

## Quick start

```bash
pip install -e ".[api,dev]"
sdebris fetch --group iridium-33-debris
sdebris screen --norad 25544 --window-hours 72 --threshold-km 25
```

!!! warning "Scope & limitations"
    This is an educational / portfolio tool. TLE-derived Pc is **illustrative,
    not operational** — see [Methodology](methodology.md). Do not use it for
    real collision-avoidance decisions.
