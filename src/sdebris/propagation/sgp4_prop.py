"""Vectorised SGP4 propagation producing ECI (TEME) state vectors.

We use the C-accelerated ``Satrec.sgp4_array`` path: each object is propagated
across the *entire* time grid in one call, which is dramatically faster than a
per-timestep Python loop when screening hundreds of objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sgp4.api import SGP4_ERRORS, Satrec, jday

from sdebris.models import SpaceObject


def make_time_grid(
    start: datetime | pd.Timestamp | None = None,
    window_hours: float = 72.0,
    step_sec: int = 60,
) -> pd.DatetimeIndex:
    """Build a UTC time grid from ``start`` spanning ``window_hours``."""
    if step_sec <= 0:
        raise ValueError("step_sec must be positive")
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")

    start_ts = pd.Timestamp(start or datetime.now(timezone.utc))
    start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
    periods = int(np.floor(window_hours * 3600 / step_sec)) + 1
    return pd.date_range(start=start_ts, periods=periods, freq=f"{step_sec}s")


def _jd_fr_arrays(times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Convert a DatetimeIndex to parallel Julian-date (jd, fr) arrays for SGP4."""
    jd = np.empty(len(times), dtype=float)
    fr = np.empty(len(times), dtype=float)
    for i, ts in enumerate(times):
        seconds = ts.second + ts.microsecond * 1e-6
        jd[i], fr[i] = jday(ts.year, ts.month, ts.day, ts.hour, ts.minute, seconds)
    return jd, fr


@dataclass
class Ephemeris:
    """Propagated states on a shared time grid.

    ``positions``/``velocities`` have shape ``(n_objects, n_times, 3)`` in km and
    km/s, ECI (TEME) frame. ``valid`` is ``(n_objects, n_times)`` and False where
    SGP4 reported an error (e.g. decayed orbit).
    """

    times: pd.DatetimeIndex
    norad_ids: list[str]
    names: list[str]
    positions: np.ndarray
    velocities: np.ndarray
    valid: np.ndarray

    @property
    def epoch_seconds(self) -> np.ndarray:
        # asi8 is int64 nanoseconds since the UNIX epoch.
        return self.times.asi8 / 1e9

    def index_of(self, norad_id: str) -> int:
        return self.norad_ids.index(str(norad_id))

    def to_dataframe(self) -> pd.DataFrame:
        """Tidy long-format frame (one row per object per timestep)."""
        n_obj, n_t, _ = self.positions.shape
        records = []
        for i in range(n_obj):
            for t in range(n_t):
                if not self.valid[i, t]:
                    continue
                px, py, pz = self.positions[i, t]
                vx, vy, vz = self.velocities[i, t]
                records.append(
                    {
                        "norad_id": self.norad_ids[i],
                        "name": self.names[i],
                        "timestamp": self.times[t],
                        "x_km": px, "y_km": py, "z_km": pz,
                        "vx_km_s": vx, "vy_km_s": vy, "vz_km_s": vz,
                    }
                )
        return pd.DataFrame.from_records(records)


def propagate_objects(
    objects: list[SpaceObject],
    times: pd.DatetimeIndex,
    *,
    fail_on_error: bool = False,
) -> Ephemeris:
    """Propagate every object across the time grid with SGP4."""
    if not objects:
        raise ValueError("No objects to propagate")

    jd, fr = _jd_fr_arrays(times)
    n_obj, n_t = len(objects), len(times)
    positions = np.full((n_obj, n_t, 3), np.nan)
    velocities = np.full((n_obj, n_t, 3), np.nan)
    valid = np.zeros((n_obj, n_t), dtype=bool)

    for i, obj in enumerate(objects):
        sat = Satrec.twoline2rv(obj.line1, obj.line2)
        err, r, v = sat.sgp4_array(jd, fr)  # err:(n_t,), r/v:(n_t,3)
        ok = err == 0
        if fail_on_error and not ok.all():
            bad = int(err[~ok][0])
            raise RuntimeError(f"SGP4 error {bad} ({SGP4_ERRORS.get(bad, 'unknown')}) for {obj.norad_id}")
        positions[i] = r
        velocities[i] = v
        valid[i] = ok

    return Ephemeris(
        times=times,
        norad_ids=[o.norad_id for o in objects],
        names=[o.name for o in objects],
        positions=positions,
        velocities=velocities,
        valid=valid,
    )
