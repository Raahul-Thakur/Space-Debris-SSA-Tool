"""Target-centric conjunction screening.

Screens a catalog group against one target object (any NORAD id), finds every
close approach in the window (a pair can have several), refines each to its
TCA on exact SGP4 states, decomposes the geometry into RAC components,
estimates collision probability, and assigns a risk tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from sdebris.config import Config
from sdebris.models import SpaceObject
from sdebris.propagation import make_time_grid, propagate_objects
from sdebris.risk.classify import RiskTier, classify_event
from sdebris.risk.pc import (
    build_ric_covariance,
    clamp_probability,
    probability_of_collision,
    ric_to_eci_covariance,
)
from sdebris.screening.frames import ric_components
from sdebris.screening.tca import TCAResult, find_close_approach_candidates, refine_tca_sgp4

KM_TO_M = 1000.0
#: Secondaries screened per vectorised block; bounds the temporary relative
#: state arrays to ~(block x grid x 3) floats whatever the catalog size.
_SCREEN_BLOCK = 256


@dataclass(frozen=True)
class ConjunctionEvent:
    target_norad: str
    target_name: str
    secondary_norad: str
    secondary_name: str
    tca: datetime
    miss_distance_km: float
    relative_speed_km_s: float
    radial_km: float
    along_track_km: float
    cross_track_km: float
    probability_of_collision: float
    risk_tier: str
    risk_reason: str
    target_tle_age_days: float
    secondary_tle_age_days: float
    secondary_stale: bool

    def to_row(self) -> dict[str, object]:
        return {
            "operational_use": False,
            "methodology_notice": (
                "Educational TLE-based screening with synthetic age-weighted covariance; "
                "not for operational maneuver decisions."
            ),
            "target_norad": self.target_norad,
            "target_name": self.target_name,
            "secondary_norad": self.secondary_norad,
            "secondary_name": self.secondary_name,
            "tca_utc": self.tca.isoformat(),
            "miss_distance_km": round(self.miss_distance_km, 4),
            "relative_speed_km_s": round(self.relative_speed_km_s, 4),
            "radial_km": round(self.radial_km, 4),
            "along_track_km": round(self.along_track_km, 4),
            "cross_track_km": round(self.cross_track_km, 4),
            "probability_of_collision": self.probability_of_collision,
            "risk_tier": self.risk_tier,
            "risk_reason": self.risk_reason,
            "target_tle_age_days": round(self.target_tle_age_days, 2),
            "secondary_tle_age_days": round(self.secondary_tle_age_days, 2),
            "secondary_stale": self.secondary_stale,
        }


@dataclass
class ScreeningResult:
    target_norad: str
    target_name: str
    generated_at: datetime
    window_start: datetime
    window_hours: float
    step_sec: int
    report_threshold_km: float
    n_screened: int
    n_stale: int
    events: list[ConjunctionEvent] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        rows = [e.to_row() for e in self.events]
        frame = pd.DataFrame(rows)
        if not frame.empty:
            tier_rank = {"critical": 0, "watch": 1, "nominal": 2}
            frame = frame.sort_values(
                by=["risk_tier", "miss_distance_km"],
                key=lambda col: col.map(tier_rank) if col.name == "risk_tier" else col,
            ).reset_index(drop=True)
        return frame

    def metadata(self) -> dict[str, object]:
        tier_counts = {t.value: 0 for t in RiskTier}
        for e in self.events:
            tier_counts[e.risk_tier] += 1
        return {
            "target_norad": self.target_norad,
            "target_name": self.target_name,
            "generated_at_utc": self.generated_at.isoformat(),
            "window_start_utc": self.window_start.isoformat(),
            "window_hours": self.window_hours,
            "step_sec": self.step_sec,
            "report_threshold_km": self.report_threshold_km,
            "objects_screened": self.n_screened,
            "objects_stale": self.n_stale,
            "events_total": len(self.events),
            "events_by_tier": tier_counts,
        }


def screen_target(
    target: SpaceObject,
    catalog: list[SpaceObject],
    config: Config,
    start: datetime | None = None,
) -> ScreeningResult:
    """Screen ``catalog`` against ``target`` over the configured window."""
    start = start or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    prop = config.propagation
    screen_cfg = config.screening

    # Build the object set: target first, then catalog minus the target.
    others = [o for o in catalog if o.norad_id != target.norad_id]
    objects = [target, *others]

    times = make_time_grid(start=start, window_hours=prop.window_hours, step_sec=prop.step_sec)
    eph = propagate_objects(objects, times, fail_on_error=False)
    epoch_seconds = eph.epoch_seconds

    target_pos = eph.positions[0]  # target is index 0 by construction
    target_vel = eph.velocities[0]
    target_valid = eph.valid[0]
    satrecs = eph.satrecs or []

    n_stale = sum(
        1 for sec in others if sec.is_stale(config.ingestion.stale_after_days, start)
    )
    events: list[ConjunctionEvent] = []

    for first in range(1, len(objects), _SCREEN_BLOCK):
        block = slice(first, min(first + _SCREEN_BLOCK, len(objects)))
        valid = eph.valid[block] & target_valid
        if not valid.any():
            continue
        candidates = find_close_approach_candidates(
            epoch_seconds,
            eph.positions[block] - target_pos,
            eph.velocities[block] - target_vel,
            valid,
            screen_cfg.coarse_threshold_km,
        )
        last_tca: dict[int, float] = {}
        for obj, k, bracket in zip(candidates.obj, candidates.k, candidates.bracket):
            j = first + int(obj)
            t_lo = float(epoch_seconds[k])
            t_hi = float(epoch_seconds[k + 1]) if bracket else t_lo
            tca = refine_tca_sgp4(
                satrecs[0], satrecs[j], t_lo, t_hi, tol_sec=prop.tca_tolerance_sec
            )
            if tca is None or tca.miss_distance_km > screen_cfg.report_threshold_km:
                continue
            # Candidates of one pair arrive in time order; two brackets can only
            # converge on the same instant if the minimum sits on a grid sample.
            if j in last_tca and abs(tca.tca_seconds - last_tca[j]) <= prop.tca_tolerance_sec:
                continue
            last_tca[j] = tca.tca_seconds
            events.append(_build_event(target, objects[j], tca, config, start))

    return ScreeningResult(
        target_norad=target.norad_id,
        target_name=target.name,
        generated_at=datetime.now(timezone.utc),
        window_start=start,
        window_hours=prop.window_hours,
        step_sec=prop.step_sec,
        report_threshold_km=screen_cfg.report_threshold_km,
        n_screened=len(others),
        n_stale=n_stale,
        events=events,
    )


def _build_event(
    target: SpaceObject,
    sec: SpaceObject,
    tca: TCAResult,
    config: Config,
    start: datetime,
) -> ConjunctionEvent:
    """Turn one refined close approach into a classified event."""
    risk_cfg = config.risk
    radial, along, cross = ric_components(tca.r_primary, tca.v_primary, tca.r_secondary)
    tca_dt = pd.Timestamp(tca.tca_seconds, unit="s", tz="UTC").to_pydatetime(warn=False)

    # The synthetic covariance grows with TLE age, so take the age at the
    # moment of closest approach, not at the start of the window.
    target_age = target.age_days(tca_dt)
    sec_age = sec.age_days(tca_dt)
    cov_eci = (
        ric_to_eci_covariance(build_ric_covariance(risk_cfg, target_age), tca.r_primary, tca.v_primary)
        + ric_to_eci_covariance(build_ric_covariance(risk_cfg, sec_age), tca.r_secondary, tca.v_secondary)
    )
    pc = clamp_probability(
        probability_of_collision(
            (tca.r_secondary - tca.r_primary) * KM_TO_M,
            (tca.v_secondary - tca.v_primary) * KM_TO_M,
            cov_eci,
            risk_cfg.hard_body_radius_m,
        )
    )
    tier, reason = classify_event(tca.miss_distance_km, pc, risk_cfg)

    return ConjunctionEvent(
        target_norad=target.norad_id,
        target_name=target.name,
        secondary_norad=sec.norad_id,
        secondary_name=sec.name,
        tca=tca_dt,
        miss_distance_km=tca.miss_distance_km,
        relative_speed_km_s=tca.relative_speed_km_s,
        radial_km=radial,
        along_track_km=along,
        cross_track_km=cross,
        probability_of_collision=pc,
        risk_tier=tier.value,
        risk_reason=reason,
        target_tle_age_days=target_age,
        secondary_tle_age_days=sec_age,
        secondary_stale=sec.is_stale(config.ingestion.stale_after_days, start),
    )
