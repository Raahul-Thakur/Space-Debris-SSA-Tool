# Operational ontology

The ontology service turns screening output into connected, versioned operational
objects. It is intentionally separate from the Streamlit analyst interface.

## Object model

| Object | Purpose |
|---|---|
| `SpaceObject` | Canonical identity for a NORAD catalog object |
| `ElementSet` | Append-only orbital element version |
| `Ephemeris` | Propagated state associated with a run and element version |
| `ConjunctionEvent` | Close approach between two objects |
| `RiskAssessment` | Versioned risk interpretation for an event |
| `MonitoringCase` | Owned operational workflow opened from an event |
| `SensorObservation` | Source-attributed measured state |
| `ManeuverScenario` | Simulation of a possible mitigation |
| `Alert` | Delivery and acknowledgement state |
| `OperatorDecision` | Human decision, justification, and approval |

`AuditAction` records before/after state, actor, justification, approvals, and
data/model versions for governed actions. `LineageEdge` connects source and
derived objects without replacing the typed domain schema with an EAV model.

## Local startup

Install the API dependencies and initialize the local SQLite database:

```bash
pip install -e ".[api,dev]"
sdebris ontology-init
```
Run the API:

```bash
sdebris-api
```

Open `http://127.0.0.1:8000/docs` for the generated OpenAPI interface.

To persist a screening run and automatically open cases for critical events:

```bash
sdebris screen --norad 25544 --persist-ontology
```

## Database configuration

The zero-configuration backend is `sqlite:///data/ontology.sqlite`. Deployments
should set:

```bash
SDEBRIS_DATABASE_URL=postgresql+psycopg://user:password@host/database
```

Run managed schema upgrades with:

```bash
alembic upgrade head
```

The initial migration defines all ontology, lineage, and audit tables. PostgreSQL
requires a compatible driver such as `psycopg`.

## Governed actions

The API currently supports:

- open, assign, escalate, and close a monitoring case;
- request an orbit refresh or screening rerun;
- acknowledge an alert;
- record an operator decision;
- create a maneuver scenario;
- capture notification requests.

Action requests are immutable audit events. Worker-only requests such as orbit
refresh and notification are recorded now and are intended for consumption by a
durable workflow engine in the next platform milestone.

## API outline

```text
GET    /ontology
POST   /objects
POST   /objects/{norad}/element-sets
POST   /objects/{norad}/observations
POST   /screening-runs
POST   /events
POST   /events/{id}/assessments
POST   /events/{id}/cases
POST   /events/{id}/maneuvers
POST   /cases/{id}/actions/{action}
POST   /cases/{id}/decisions
POST   /alerts/{id}/acknowledge
GET    /audit-actions
GET    /lineage/{entity_type}/{entity_id}
```
