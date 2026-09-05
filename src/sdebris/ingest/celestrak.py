"""CelesTrak GP API client and catalog refresh helper.

CelesTrak serves General Perturbations (GP) element sets at
``https://celestrak.org/NORAD/elements/gp.php`` with query parameters such as
``GROUP=iridium-33-debris`` or ``CATNR=25544`` and ``FORMAT=tle``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from sdebris.config import Config
from sdebris.ingest.cache import TLECache
from sdebris.models import SpaceObject, parse_tle_text

USER_AGENT = "sdebris/0.1 (space-debris-ssa-tool)"


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
) -> TLECache:
    """Refresh the local cache from CelesTrak.

    Fetches the configured group plus any extra NORAD ids (e.g. the screening
    target). On network failure, falls back to the existing cache (and the
    bundled sample TLE if the cache is empty) when ``offline_ok`` is set.
    """
    group = group or config.ingestion.default_group
    cache = TLECache(config.resolve_path(config.ingestion.cache_path))
    client = CelesTrakClient(base_url=config.ingestion.base_url)

    errors: list[Exception] = []
    try:
        objects = client.fetch_group(group)
        cache.upsert(objects, source=group)
    except (requests.RequestException, ValueError) as exc:
        errors.append(exc)

    # Explicitly monitored objects are refreshed on every poll, even when they
    # already exist in the cache or are not members of the selected group.
    for norad_id in dict.fromkeys(extra_norad_ids or []):
        try:
            cache.upsert(client.fetch_catnr(norad_id), source=f"catnr:{norad_id}")
        except (requests.RequestException, ValueError) as exc:
            errors.append(exc)

    if errors and not offline_ok:
        cache.close()
        raise errors[0]
    missing_explicit = [
        norad_id for norad_id in (extra_norad_ids or []) if cache.get(norad_id) is None
    ]
    if cache.count() == 0 or (errors and missing_explicit):
        _seed_from_sample(cache)
    if errors:
        print(
            f"[sdebris] {len(errors)} CelesTrak request(s) failed; "
            "using cached/sample data where needed."
        )

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
