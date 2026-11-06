"""Screening accuracy against a brute-force fine-step SGP4 search.

The crossing pair below was built with ``sgp4init`` and exported to TLEs: two
circular ~400 km orbits inclined 10 deg and 170 deg with a common node line, so
they meet almost head-on (~15 km/s) about every half orbit with a ~0.4 km miss.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from scipy.optimize import minimize_scalar
from sgp4.api import Satrec

from sdebris.config import load_config
from sdebris.models import SpaceObject
from sdebris.screening.screen import screen_target

EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)

CROSS_A = SpaceObject(
    "90001", "CROSS-A",
    "1 90001U          24001.00000000  .00000000  00000-0  50000-4 0    09",
    "2 90001  10.0000   0.0000 0001000   0.0000 246.0000 15.20000000    04",
)
CROSS_B = SpaceObject(
    "90002", "CROSS-B",
    "1 90002U          24001.00000000  .00000000  00000-0  50000-4 0    00",
    "2 90002 170.0000   0.0000 0001000   0.0000 246.0200 15.20000000    04",
)

# Real sample elements (data/tle/sample.tle) whose closest pass in the first
# 72 h of 2024 is ~12 km, about 4.7 h after epoch.
IRIDIUM_DEB = SpaceObject(
    "33772", "IRIDIUM 33 DEB",
    "1 33772U 97051C   24001.00000000  .00001234  00000+0  30000-3 0  9001",
    "2 33772  86.3950 120.4500 0010000  90.0000 270.0000 14.34000000  9000",
)
SENTINEL_2A = SpaceObject(
    "40697", "SENTINEL-2A",
    "1 40697U 15028A   24001.00000000  .00000161  00000+0  74850-4 0  9005",
    "2 40697  98.5682  76.0035 0001134  86.8744 273.2583 14.30815284  9001",
)


def _separation(a: Satrec, b: Satrec, t: np.ndarray) -> np.ndarray:
    """Exact SGP4 separation (km) at ``t`` seconds after EPOCH."""
    t = np.atleast_1d(np.asarray(t, dtype=float))
    jd = np.full(t.shape, 2460310.5)  # 2024-01-01T00:00Z
    _, ra, _ = a.sgp4_array(jd, t / 86400.0)
    _, rb, _ = b.sgp4_array(jd, t / 86400.0)
    return np.linalg.norm(ra - rb, axis=1)


def _brute_force_minima(
    a: SpaceObject, b: SpaceObject, t0: float, t1: float, max_km: float
) -> list[tuple[float, float]]:
    """Every local minimum of the separation in [t0, t1] (s after EPOCH).

    A 0.5 s scan brackets each minimum; a bounded scalar search then pins it
    to ~1e-5 s. Returns (seconds after EPOCH, miss km) pairs.
    """
    sa = Satrec.twoline2rv(a.line1, a.line2)
    sb = Satrec.twoline2rv(b.line1, b.line2)
    t = np.arange(t0, t1 + 0.5, 0.5)
    d = _separation(sa, sb, t)
    out = []
    for k in range(1, len(t) - 1):
        if d[k] <= d[k - 1] and d[k] < d[k + 1] and d[k] < max_km:
            res = minimize_scalar(
                lambda x: float(_separation(sa, sb, x)[0]),
                bounds=(t[k - 1], t[k + 1]), method="bounded",
                options={"xatol": 1e-6},
            )
            out.append((float(res.x), float(res.fun)))
    return out


def _seconds_after_epoch(dt: datetime) -> float:
    return (dt - EPOCH).total_seconds()


def _config(window_hours: float, step_sec: int):
    cfg = load_config()
    cfg.propagation.window_hours = window_hours
    cfg.propagation.step_sec = step_sec
    return cfg


def test_fast_crossing_midway_between_samples_is_reported() -> None:
    """A 0.4 km head-on pass falling midway between 60 s samples is found.

    At ~15 km/s the two samples either side are ~450 km apart, far beyond the
    50 km coarse threshold, so a screen that only looks at sampled distances
    throws the pass away.
    """
    (tca_true, miss_true), = _brute_force_minima(CROSS_A, CROSS_B, 1500, 2100, 50)
    assert miss_true < 1.0
    start = EPOCH + timedelta(seconds=tca_true - 30.0 - 600.0)  # TCA midway
    result = screen_target(CROSS_A, [CROSS_B], _config(0.5, 60), start=start)

    assert len(result.events) == 1
    event = result.events[0]
    assert event.miss_distance_km < 1.0
    assert event.miss_distance_km == pytest.approx(miss_true, abs=0.01)
    assert _seconds_after_epoch(event.tca) == pytest.approx(tca_true, abs=0.1)
    assert event.relative_speed_km_s > 14.0
    assert event.risk_tier == "critical"


def test_two_encounters_of_one_pair_are_both_reported() -> None:
    """Each local minimum in the window is its own event, with its own TCA."""
    start = EPOCH + timedelta(minutes=20)
    window_h = 1.5
    expected = _brute_force_minima(
        CROSS_A, CROSS_B, 1200, 1200 + window_h * 3600, 25.0
    )
    assert len(expected) == 2
    # A 5 s step keeps every sampled minimum under the coarse threshold, so
    # this isolates the one-event-per-pair behaviour from the coarse screen.
    result = screen_target(CROSS_A, [CROSS_B], _config(window_h, 5), start=start)

    events = sorted(result.events, key=lambda e: e.tca)
    assert len(events) == 2
    assert all(e.secondary_norad == "90002" for e in events)
    assert events[0].tca != events[1].tca
    for event, (tca_true, miss_true) in zip(events, expected):
        assert _seconds_after_epoch(event.tca) == pytest.approx(tca_true, abs=0.1)
        assert event.miss_distance_km == pytest.approx(miss_true, abs=0.01)


def test_refined_tca_matches_brute_force_on_real_tles() -> None:
    """TCA within 0.1 s and miss within 10 m of a fine-step SGP4 search."""
    start = EPOCH + timedelta(hours=3)
    window_h = 3.0
    expected = _brute_force_minima(
        IRIDIUM_DEB, SENTINEL_2A, 3 * 3600, 6 * 3600, 25.0
    )
    assert expected
    result = screen_target(IRIDIUM_DEB, [SENTINEL_2A], _config(window_h, 60), start=start)

    events = sorted(result.events, key=lambda e: e.tca)
    assert len(events) == len(expected)
    for event, (tca_true, miss_true) in zip(events, expected):
        assert abs(_seconds_after_epoch(event.tca) - tca_true) < 0.1
        assert abs(event.miss_distance_km - miss_true) < 0.010


def test_tle_age_is_taken_at_the_time_of_closest_approach() -> None:
    """Covariance growth uses the TLE age at TCA, not at the window start."""
    start = EPOCH + timedelta(hours=3)
    result = screen_target(IRIDIUM_DEB, [SENTINEL_2A], _config(3.0, 60), start=start)
    assert result.events
    for event in result.events:
        age_at_tca = (event.tca - EPOCH).total_seconds() / 86400.0
        assert event.target_tle_age_days == pytest.approx(age_at_tca, abs=1e-6)
        assert event.secondary_tle_age_days == pytest.approx(age_at_tca, abs=1e-6)


def test_several_events_per_pair_persist_as_distinct_records(tmp_path) -> None:
    """The ontology keys events on (run, pair, TCA), so repeats of a pair persist."""
    from sdebris.ontology import Database, OntologyService, persist_screening_result

    start = EPOCH + timedelta(minutes=20)
    result = screen_target(CROSS_A, [CROSS_B], _config(1.5, 60), start=start)
    assert len(result.events) == 2

    database = Database(f"sqlite:///{(tmp_path / 'ontology.db').as_posix()}")
    database.initialize()
    session = database.session_factory()
    try:
        summary = persist_screening_result(session, result, [CROSS_A, CROSS_B], load_config())
        assert summary.events_created == 2
        stored = OntologyService(session).list_events()
        assert len({record.tca for record in stored}) == 2
    finally:
        session.close()
        database.engine.dispose()


def test_retired_refine_step_sec_key_still_loads(tmp_path) -> None:
    override = tmp_path / "old.yaml"
    override.write_text("propagation:\n  refine_step_sec: 1\n", encoding="utf-8")
    cfg = load_config(override)
    assert cfg.propagation.tca_tolerance_sec == pytest.approx(1e-3)


def test_a_report_with_two_passes_of_one_pair_still_validates() -> None:
    """The validator flagged any repeated secondary, which is now normal."""
    from datetime import datetime, timezone

    import pandas as pd

    from sdebris.reports import writer

    class _Result:
        n_stale = 0

        def to_dataframe(self):
            return pd.DataFrame(
                {
                    "secondary_norad": ["99999", "99999"],
                    "tca_utc": [
                        datetime(2026, 11, 7, 1, tzinfo=timezone.utc).isoformat(),
                        datetime(2026, 11, 7, 3, tzinfo=timezone.utc).isoformat(),
                    ],
                    "miss_distance_km": [2.0, 3.0],
                    "probability_of_collision": [1e-6, 1e-7],
                }
            )

    checks = writer._validation_checks(_Result())
    assert checks["passed"], checks["issues"]
