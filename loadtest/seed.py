"""Fill a database with a realistic orbital picture for load testing.

Builds a synthetic LEO catalogue (valid TLEs with epochs around now, so
element ages and times of closest approach are current), screens a few
targets against it with the real pipeline, persists the results through the
real ontology bridge, and puts a set of objects on the platform watch list
so the public globe has tracks to draw.

    SDEBRIS_ENV=development SDEBRIS_DATABASE_URL=postgresql+psycopg://... \\
        python loadtest/seed.py --objects 300 --targets 3 --watch 20

Never point this at production: it writes synthetic objects.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from sgp4 import exporter
from sgp4.api import WGS72, Satrec

from sdebris.config import load_config
from sdebris.models import SpaceObject
from sdebris.ontology.bridge import persist_screening_result
from sdebris.ontology.database import Database
from sdebris.ontology.orm import MonitoredObjectRecord, SpaceObjectRecord
from sdebris.screening.screen import screen_target

SGP4_EPOCH = datetime(1949, 12, 31, tzinfo=timezone.utc)


def synthetic_catalogue(count: int, *, seed: int = 7) -> list[SpaceObject]:
    """LEO objects with plausible elements; a few share shells so some pass close."""
    rng = np.random.default_rng(seed)
    now = datetime.now(timezone.utc)
    objects = []
    for index in range(count):
        epoch = now - timedelta(days=float(rng.uniform(0.2, 3.0)))
        sat = Satrec()
        sat.sgp4init(
            WGS72, "i", 80000 + index, (epoch - SGP4_EPOCH).total_seconds() / 86400,
            float(rng.uniform(1e-5, 2e-4)), 0.0, 0.0,
            float(rng.uniform(0, 0.005)),
            np.radians(rng.uniform(0, 360)),
            # Two crowded inclination bands, as debris clouds are.
            np.radians(rng.choice([rng.uniform(86, 87), rng.uniform(97, 99)])),
            np.radians(rng.uniform(0, 360)),
            float(rng.uniform(14.2, 14.6)) * 2 * np.pi / 1440.0,
            np.radians(rng.uniform(0, 360)),
        )
        line1, line2 = exporter.export_tle(sat)
        objects.append(SpaceObject(str(80000 + index), f"LOADTEST-{index:03d}", line1, line2))
    return objects


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--objects", type=int, default=300)
    parser.add_argument("--targets", type=int, default=3)
    parser.add_argument("--watch", type=int, default=20)
    args = parser.parse_args()

    url = os.environ.get("SDEBRIS_DATABASE_URL", "")
    if not url or "supabase" in url or "render.com" in url:
        print("refusing: set SDEBRIS_DATABASE_URL to a local test database", file=sys.stderr)
        return 2

    database = Database(url)
    database.initialize()
    catalogue = synthetic_catalogue(args.objects)
    config = load_config()
    config.propagation.window_hours = 72
    config.propagation.step_sec = 60
    config.screening.report_threshold_km = 50

    events = 0
    for target in catalogue[: args.targets]:
        started = time.perf_counter()
        result = screen_target(target, catalogue, config)
        with database.session_factory() as session:
            persist_screening_result(session, result, catalogue, config)
        events += len(result.events)
        print(f"screened {target.name}: {len(result.events)} events in {time.perf_counter() - started:.1f}s")

    with database.session_factory() as session:
        objects = (
            session.query(SpaceObjectRecord)
            .filter(SpaceObjectRecord.norad_id.in_([o.norad_id for o in catalogue[: args.watch]]))
            .all()
        )
        for obj in objects:
            session.add(MonitoredObjectRecord(space_object_id=obj.id, added_by=None))
        session.commit()
    print(f"seeded {args.objects} objects, {events} events, {len(objects)} on the platform watch list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
