"""Minimal end-to-end example: screen the ISS against Iridium-33 debris.

    python examples/screen_iss.py
"""

from __future__ import annotations

from sdebris.config import load_config
from sdebris.ingest import refresh_catalog
from sdebris.reports import write_report
from sdebris.screening.screen import screen_target


def main() -> None:
    config = load_config()
    config.propagation.window_hours = 72
    config.screening.report_threshold_km = 25

    target_norad = "25544"  # ISS
    cache = refresh_catalog(config, group="iridium-33-debris", extra_norad_ids=[target_norad])
    target = cache.get(target_norad)
    objects = cache.all()
    cache.close()

    if target is None:
        raise SystemExit("Could not obtain the target TLE (offline and not cached).")

    result = screen_target(target, objects, config)
    meta = result.metadata()
    print(f"Target: {meta['target_name']} (NORAD {meta['target_norad']})")
    print(f"Screened {meta['objects_screened']} objects over {meta['window_hours']:g} h")
    print(f"Events by tier: {meta['events_by_tier']}")

    paths = write_report(result, config)
    print(f"Wrote {paths.csv}")
    print(f"Wrote {paths.json}")


if __name__ == "__main__":
    main()
