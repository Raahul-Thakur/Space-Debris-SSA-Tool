"""Vectorised SGP4 propagation producing ECI (TEME) state vectors.

We use the C-accelerated ``Satrec.sgp4_array`` path: each object is propagated
across the *entire* time grid in one call, which is dramatically faster than a
per-timestep Python loop when screening hundreds of objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sgp4.api import SGP4_ERRORS, Satrec

from sdebris.models import SpaceObject

_UNIX_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
_UNIX_EPOCH_JD = 2440587.5
_SECONDS_PER_DAY = 86400.0


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


def unix_seconds_to_jd(seconds: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    """Split UNIX seconds into the (whole-day jd, day-fraction fr) pair SGP4 takes.

    Keeping the day fraction separate preserves sub-millisecond resolution
    (a single float Julian date only resolves ~40 us at present-day values).
    """
    t = np.atleast_1d(np.asarray(seconds, dtype=float))
    days = np.floor(t / _SECONDS_PER_DAY)
    return _UNIX_EPOCH_JD + days, (t - days * _SECONDS_PER_DAY) / _SECONDS_PER_DAY


def _epoch_seconds(times: pd.DatetimeIndex) -> np.ndarray:
    # Measured as a duration from the UNIX epoch rather than read off the
    # raw integers: pandas 2 stores a grid in nanoseconds and pandas 3 in
    # microseconds, and dividing the integers by a fixed 1e9 under pandas 3
    # put every time of closest approach in January 1970.
    return ((times - _UNIX_EPOCH) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


def _jd_fr_arrays(times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Convert a DatetimeIndex to parallel Julian-date (jd, fr) arrays for SGP4."""
    return unix_seconds_to_jd(_epoch_seconds(times))


def satrec_for(obj: SpaceObject) -> Satrec:
    """Build the SGP4 satellite record for ``obj``."""
    return Satrec.twoline2rv(obj.line1, obj.line2)


def propagate_at(
    sat: Satrec, epoch_seconds: np.ndarray | float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Propagate one object to arbitrary UNIX times (not tied to a grid).

    Returns ``(positions (n, 3) km, velocities (n, 3) km/s, ok (n,) bool)`` in
    TEME. Used to refine each close approach on exact SGP4 states rather than
    on states interpolated between grid samples.
    """
    jd, fr = unix_seconds_to_jd(epoch_seconds)
    err, r, v = sat.sgp4_array(jd, fr)
    return np.asarray(r), np.asarray(v), np.asarray(err) == 0


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
    #: The SGP4 records the states came from, one per object, so callers can
    #: propagate the same objects to times off the grid (TCA refinement).
    satrecs: list[Satrec] | None = field(default=None, repr=False)

    @property
    def epoch_seconds(self) -> np.ndarray:
        return _epoch_seconds(self.times)

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
    satrecs: list[Satrec] = []

    for i, obj in enumerate(objects):
        sat = satrec_for(obj)
        satrecs.append(sat)
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
        satrecs=satrecs,
    )
