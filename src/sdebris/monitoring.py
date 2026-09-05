"""Curated monitoring catalogs and repeatable ontology seeding."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdebris.config import load_config
from sdebris.ingest.celestrak import CelesTrakClient
from sdebris.models import SpaceObject
from sdebris.ontology.orm import MonitoredObjectRecord
from sdebris.ontology.schemas import ElementSetCreate, SpaceObjectCreate
from sdebris.ontology.service import OntologyService

# Twenty recognizable objects with standard GP elements available from CelesTrak.
# Hubble (20580) is intentionally not included because it is already part of the
# starter monitored set in the current project database.
WELL_KNOWN_NORAD_IDS = (
    "25544",  # ISS (ZARYA)
    "48274",  # CSS (TIANHE)
    "39084",  # LANDSAT 8
    "49260",  # LANDSAT 9
    "25994",  # TERRA
    "27424",  # AQUA
    "39634",  # SENTINEL-1A
    "40697",  # SENTINEL-2A
    "42063",  # SENTINEL-2B
    "41335",  # SENTINEL-3A
    "43437",  # SENTINEL-3B
    "41866",  # GOES 16
    "43226",  # GOES 17
    "51850",  # GOES 18
    "25338",  # NOAA 15
    "28654",  # NOAA 18
    "33591",  # NOAA 19
    "43013",  # NOAA 20 (JPSS-1)
    "27386",  # ENVISAT
    "00005",  # VANGUARD 1
)


def seed_well_known_objects(
    session: Session, actor: str, *, max_workers: int = 5
) -> dict[str, Any]:
    """Fetch and monitor the curated catalog as one governed database update."""
    config = load_config()
    client = CelesTrakClient(base_url=config.ingestion.base_url)

    def fetch(norad_id: str) -> tuple[str, SpaceObject]:
        objects = client.fetch_catnr(norad_id)
        if not objects:
            raise ValueError(f"NORAD {norad_id} returned no GP elements")
        return norad_id, objects[0]

    fetched: dict[str, SpaceObject] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fetch, norad_id): norad_id
            for norad_id in WELL_KNOWN_NORAD_IDS
        }
        for future in as_completed(futures):
            norad_id = futures[future]
            try:
                _, fetched[norad_id] = future.result()
            except Exception as exc:
                errors[norad_id] = str(exc)

    service = OntologyService(session, auto_commit=False)
    added = 0
    updated = 0
    objects: list[dict[str, str]] = []
    for norad_id in WELL_KNOWN_NORAD_IDS:
        domain_object = fetched.get(norad_id)
        if domain_object is None:
            continue
        ontology_object = service.get_space_object_by_norad(norad_id, required=False)
        if ontology_object is None:
            ontology_object = service.create_space_object(
                SpaceObjectCreate(
                    norad_id=norad_id,
                    name=domain_object.name,
                    status="active",
                    metadata_json={
                        "source_model": "TLE",
                        "catalog": "well-known",
                    },
                )
            )
        service.add_element_set(
            norad_id,
            ElementSetCreate(
                line1=domain_object.line1,
                line2=domain_object.line2,
                source=f"catnr:{norad_id}",
                parser_version="sdebris-tle-v1",
            ),
        )
        monitor = session.scalar(
            select(MonitoredObjectRecord).where(
                MonitoredObjectRecord.space_object_id == ontology_object.id
            )
        )
        if monitor is None:
            session.add(
                MonitoredObjectRecord(
                    space_object_id=ontology_object.id,
                    added_by=actor,
                )
            )
            added += 1
        else:
            monitor.active = True
            monitor.added_by = actor
            updated += 1
        objects.append({"norad_id": norad_id, "name": domain_object.name})

    session.commit()
    return {
        "requested": len(WELL_KNOWN_NORAD_IDS),
        "added": added,
        "updated": updated,
        "objects": objects,
        "errors": errors,
    }
