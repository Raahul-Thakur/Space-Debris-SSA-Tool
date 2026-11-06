"""CelesTrak is asked no more often than it publishes, and politely."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from sdebris.config import load_config
from sdebris.ingest import refresh_catalog
from sdebris.ingest.celestrak import USER_AGENT

ISS = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   24001.00000000  .00016717  00000+0  10270-3 0  9003\n"
    "2 25544  51.6421  10.3493 0006703  88.3949  31.2568 15.50015354  9008\n"
)


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _config(tmp_path):
    config = load_config()
    config.ingestion.cache_path = str(tmp_path / "tle.sqlite")
    return config


def _counting(monkeypatch, *, fail: bool = False) -> list[dict]:
    calls: list[dict] = []

    def get(url, params=None, timeout=None, headers=None):
        calls.append({"params": params, "headers": headers})
        if fail:
            raise requests.ConnectionError("unreachable")
        return _Response(ISS)

    monkeypatch.setattr("sdebris.ingest.celestrak.requests.get", get)
    return calls


def test_a_second_refresh_within_two_hours_downloads_nothing(tmp_path, monkeypatch) -> None:
    """Every screening used to re-download its whole group."""
    calls = _counting(monkeypatch)
    config = _config(tmp_path)
    refresh_catalog(config, group="stations", extra_norad_ids=["25544"]).close()
    # The target arrived inside the group download moments ago, so it is not
    # fetched a second time on its own either.
    assert len(calls) == 1
    cache = refresh_catalog(config, group="stations", extra_norad_ids=["25544"])
    assert len(calls) == 1, "the second refresh should have used the cache"
    assert cache.refresh_report.fresh == ["stations", "catnr:25544"]
    cache.close()


def test_a_refresh_after_the_interval_fetches_again(tmp_path, monkeypatch) -> None:
    calls = _counting(monkeypatch)
    config = _config(tmp_path)
    refresh_catalog(config, group="stations").close()
    later = datetime.now(timezone.utc) + timedelta(hours=config.ingestion.poll_interval_hours, minutes=1)
    refresh_catalog(config, group="stations", now=later).close()
    assert len(calls) == 2


def test_requests_identify_the_operator(tmp_path, monkeypatch) -> None:
    calls = _counting(monkeypatch)
    refresh_catalog(_config(tmp_path), group="stations").close()
    agent = calls[0]["headers"]["User-Agent"]
    assert agent == USER_AGENT
    assert "@" in agent and "github.com" in agent


def test_a_run_on_sample_data_is_marked_as_not_live(tmp_path, monkeypatch) -> None:
    """Results quietly built on the bundled 2024 sample used to look live."""
    _counting(monkeypatch, fail=True)
    cache = refresh_catalog(_config(tmp_path), group="stations", extra_norad_ids=["25544"])
    report = cache.refresh_report
    assert report.used_sample is True
    assert report.live is False
    assert report.failed == ["stations", "catnr:25544"]
    cache.close()
