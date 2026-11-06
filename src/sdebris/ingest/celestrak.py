"""CelesTrak GP API client and catalog refresh helper.

CelesTrak serves General Perturbations (GP) element sets at
``https://celestrak.org/NORAD/elements/gp.php`` with query parameters such as
``GROUP=iridium-33-debris`` or ``CATNR=25544`` and ``FORMAT=tle``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from sdebris import __version__
from sdebris.config import Config
from sdebris.ingest.cache import TLECache
from sdebris.models import SpaceObject, parse_tle_text

logger = logging.getLogger("sdebris.ingest")

#: CelesTrak asks automated clients to identify themselves with a way to
#: reach the operator, and blocks addresses that fetch too often without one.
USER_AGENT = (
    f"Astra-SSA/{__version__} "
    "(+https://github.com/Raahul-Thakur/Space-Debris-SSA-Tool; raahul.thakurr01@gmail.com)"
)


@dataclass
class RefreshReport:
    """What a catalogue refresh actually did, so results can say how fresh they are."""

    fetched: list[str] = field(default_factory=list)
    #: Skipped because the cached copy is newer than the poll interval.
    fresh: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    #: The bundled sample file was used because nothing better was available.
    used_sample: bool = False

    @property
    def live(self) -> bool:
        """True when nothing failed and no sample data stood in."""
        return not self.failed and not self.used_sample

    def as_dict(self) -> dict[str, object]:
        return {
            "fetched": self.fetched,
            "fresh": self.fresh,
            "failed": self.failed,
            "used_sample": self.used_sample,
            "live": self.live,
        }


@dataclass
class CelesTrakClient:
    base_url: str = "https://celestrak.org/NORAD/elements/gp.php"
    timeout_sec: float = 30.0

    def _get(self, params: dict[str, str]) -> str:
        params = {**params, "FORMAT": "tle"}
        resp = requests.get(
            self.base_url, params=params, timeout=self.timeout_sec,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or "No GP data found" in text or "<" in text[:1]:
            raise ValueError(f"CelesTrak returned no usable TLE data for params={params}")
        return text

    def fetch_group(self, group: str) -> list[SpaceObject]:
        """Fetch every object in a CelesTrak group (e.g. ``iridium-33-debris``)."""
        return parse_tle_text(self._get({"GROUP": group}))

    def fetch_catnr(self, norad_id: str | int) -> list[SpaceObject]:
        """Fetch a single object by NORAD catalog number."""
        return parse_tle_text(self._get({"CATNR": str(norad_id)}))


def refresh_catalog(
    config: Config,
    group: str | None = None,
    extra_norad_ids: list[str] | None = None,
    *,
    offline_ok: bool = True,
    now: datetime | None = None,
) -> TLECache:
    """Refresh the local cache from CelesTrak, no more often than it asks.

    Fetches the group plus any extra NORAD ids (e.g. the screening target),
    skipping any that were fetched within ``ingestion.poll_interval_hours``.
    CelesTrak updates element sets about every two hours and blocks clients
    that download unchanged data repeatedly; every screening used to
    re-download its whole group, and the scheduled workflow fetched the same
    group three times a run, from shared cloud addresses.

    On network failure, falls back to the existing cache (and the bundled
    sample TLE if the cache is empty) when ``offline_ok`` is set. What
    happened is recorded on ``cache.refresh_report``.
    """
    group = group or config.ingestion.default_group
    cache = TLECache(config.resolve_path(config.ingestion.cache_path))
    client = CelesTrakClient(base_url=config.ingestion.base_url)
    report = RefreshReport()
    moment = now or datetime.now(timezone.utc)
    interval = timedelta(hours=config.ingestion.poll_interval_hours)

    def is_fresh(fetched: datetime | None) -> bool:
        return fetched is not None and moment - fetched < interval

    errors: list[Exception] = []
    if is_fresh(cache.fetched_at(source=group)):
        report.fresh.append(group)
    else:
        try:
            objects = client.fetch_group(group)
            cache.upsert(objects, source=group)
            report.fetched.append(group)
        except (requests.RequestException, ValueError) as exc:
            errors.append(exc)
            report.failed.append(group)

    # Explicitly requested objects are refreshed too, even when they are not
    # members of the selected group, subject to the same interval.
    for norad_id in dict.fromkeys(extra_norad_ids or []):
        if is_fresh(cache.fetched_at(norad_id=norad_id)):
            report.fresh.append(f"catnr:{norad_id}")
            continue
        try:
            cache.upsert(client.fetch_catnr(norad_id), source=f"catnr:{norad_id}")
            report.fetched.append(f"catnr:{norad_id}")
        except (requests.RequestException, ValueError) as exc:
            errors.append(exc)
            report.failed.append(f"catnr:{norad_id}")

    if errors and not offline_ok:
        cache.close()
        raise errors[0]
    missing_explicit = [
        norad_id for norad_id in (extra_norad_ids or []) if cache.get(norad_id) is None
    ]
    if cache.count() == 0 or (errors and missing_explicit):
        _seed_from_sample(cache)
        report.used_sample = True
    if errors:
        logger.warning(
            "%d CelesTrak request(s) failed (%s); using cached%s data",
            len(errors),
            ", ".join(report.failed),
            " and sample" if report.used_sample else "",
        )
        print(
            f"[sdebris] {len(errors)} CelesTrak request(s) failed; "
            "using cached/sample data where needed."
        )

    cache.refresh_report = report
    return cache


def _seed_from_sample(cache: TLECache) -> None:
    """Populate an empty cache from the bundled sample TLE file (offline mode)."""
    from sdebris.config import REPO_ROOT

    sample = REPO_ROOT / "data" / "tle" / "sample.tle"
    if sample.exists():
        objects = parse_tle_text(sample.read_text(encoding="utf-8"))
        cache.upsert(objects, source="sample")


def load_tle_file(path: str | Path) -> list[SpaceObject]:
    """Convenience loader for a local TLE file."""
    return parse_tle_text(Path(path).read_text(encoding="utf-8"))
