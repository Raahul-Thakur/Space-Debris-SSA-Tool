"""Manoeuvre what-ifs: what a delta-v would do to a predicted encounter.

Three models, deliberately. They disagree, and the disagreement is reported
rather than resolved, because resolving it would mean claiming a precision
the inputs do not support. See :mod:`sdebris.maneuver.scenarios`.
"""

from sdebris.maneuver.dynamics import (
    TWO_BODY,
    ForceModel,
    ballistic_coefficient_from_bstar,
    with_perturbations,
)
from sdebris.maneuver.linear import displacement_from_burn, mean_motion_rad_s
from sdebris.maneuver.scenarios import (
    Burn,
    ModelOutcome,
    ScenarioResult,
    evaluate,
)

__all__ = [
    "TWO_BODY",
    "Burn",
    "ForceModel",
    "ModelOutcome",
    "ScenarioResult",
    "ballistic_coefficient_from_bstar",
    "displacement_from_burn",
    "evaluate",
    "mean_motion_rad_s",
    "with_perturbations",
]
