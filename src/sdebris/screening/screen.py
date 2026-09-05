"""Target-centric conjunction screening.

Screens an entire catalog against one target object (any NORAD id), finds close
approaches, refines each to its TCA, decomposes the geometry into RAC components,
estimates collision probability, and assigns a risk tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from sdebris.config import Config
from sdebris.models import SpaceObject
from sdebris.propagation import make_time_grid, propagate_objects
from sdebris.risk.classify import RiskTier, classify_event
from sdebris.risk.pc import build_ric_covariance, probability_of_collision, ric_to_eci_covariance
from sdebris.screening.frames import ric_components
from sdebris.screening.tca import refine_tca

KM_TO_M = 1000.0


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
    risk_cfg = config.risk

    # Build the object set: target first, then catalog minus the target.
    others = [o for o in catalog if o.norad_id != target.norad_id]
    objects = [target, *others]

    times = make_time_grid(start=start, window_hours=prop.window_hours, step_sec=prop.step_sec)
    eph = propagate_objects(objects, times, fail_on_error=False)
    epoch_seconds = eph.epoch_seconds

    t_idx = 0  # target is index 0 by construction
    target_pos = eph.positions[t_idx]
    target_vel = eph.velocities[t_idx]
    target_valid = eph.valid[t_idx]
    target_cov_ric = build_ric_covariance(risk_cfg, target.age_days(start))

    events: list[ConjunctionEvent] = []
    n_stale = 0

    for j in range(1, len(objects)):
        sec = objects[j]
        if sec.is_stale(config.ingestion.stale_after_days, start):
            n_stale += 1

        both_valid = target_valid & eph.valid[j]
        if not both_valid.any():
            continue

        sep = np.full(len(times), np.inf)
        sep[both_valid] = np.linalg.norm(
            eph.positions[j][both_valid] - target_pos[both_valid], axis=1
        )
        if np.nanmin(sep) > screen_cfg.coarse_threshold_km:
            continue

        # Restrict TCA refinement to the valid, finite span.
        mask = np.isfinite(sep)
        tca = refine_tca(
            epoch_seconds[mask],
            target_pos[mask], target_vel[mask],
            eph.positions[j][mask], eph.velocities[j][mask],
        )
        if tca.miss_distance_km > screen_cfg.report_threshold_km:
            continue

        radial, along, cross = ric_components(tca.r_primary, tca.v_primary, tca.r_secondary)

        sec_cov_ric = build_ric_covariance(risk_cfg, sec.age_days(start))
        cov_eci = (
            ric_to_eci_covariance(target_cov_ric * 1.0, tca.r_primary, tca.v_primary)
            + ric_to_eci_covariance(sec_cov_ric, tca.r_secondary, tca.v_secondary)
        )
        pc = probability_of_collision(
            (tca.r_secondary - tca.r_primary) * KM_TO_M,
            (tca.v_secondary - tca.v_primary) * KM_TO_M,
            cov_eci,
            risk_cfg.hard_body_radius_m,
        )
        # Normalize floating-point negative zero and guard the probability range.
        pc = max(0.0, min(1.0, float(pc)))

        tier, reason = classify_event(tca.miss_distance_km, pc, risk_cfg)
        tca_dt = pd.Timestamp(tca.tca_seconds, unit="s", tz="UTC").to_pydatetime(warn=False)

        events.append(
            ConjunctionEvent(
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
                target_tle_age_days=target.age_days(start),
                secondary_tle_age_days=sec.age_days(start),
                secondary_stale=sec.is_stale(config.ingestion.stale_after_days, start),
            )
        )

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
