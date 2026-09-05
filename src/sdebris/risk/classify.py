"""Tiered risk classification for screened conjunctions."""

from __future__ import annotations

from enum import Enum

from sdebris.config import RiskConfig


class RiskTier(str, Enum):
    CRITICAL = "critical"
    WATCH = "watch"
    NOMINAL = "nominal"

    @property
    def rank(self) -> int:
        return {"critical": 3, "watch": 2, "nominal": 1}[self.value]


def classify_event(
    miss_distance_km: float,
    probability_of_collision: float,
    risk: RiskConfig,
) -> tuple[RiskTier, str]:
    """Assign the highest tier whose miss-distance OR Pc condition is met.

    Returns the tier and a short human-readable reason.
    """
    crit = risk.tiers.critical
    watch = risk.tiers.watch

    if miss_distance_km <= crit.miss_distance_km or probability_of_collision >= crit.probability_of_collision:
        reason = _reason("CRITICAL", miss_distance_km, probability_of_collision, crit.miss_distance_km, crit.probability_of_collision)
        return RiskTier.CRITICAL, reason
    if miss_distance_km <= watch.miss_distance_km or probability_of_collision >= watch.probability_of_collision:
        reason = _reason("WATCH", miss_distance_km, probability_of_collision, watch.miss_distance_km, watch.probability_of_collision)
        return RiskTier.WATCH, reason
    return RiskTier.NOMINAL, "Outside watch thresholds."


def _reason(tier: str, miss: float, pc: float, miss_thr: float, pc_thr: float) -> str:
    triggers = []
    if miss <= miss_thr:
        triggers.append(f"miss {miss:.2f} km <= {miss_thr:g} km")
    if pc >= pc_thr:
        triggers.append(f"Pc {pc:.2e} >= {pc_thr:g}")
    return f"{tier}: " + "; ".join(triggers)
