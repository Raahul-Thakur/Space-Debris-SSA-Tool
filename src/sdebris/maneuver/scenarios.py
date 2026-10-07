"""Run a proposed burn through every available model and compare them.

A manoeuvre scenario is a question with no single honest answer: the result
depends on dynamics that were approximated to get it, and the approximations
disagree by amounts comparable to the miss distances being screened. Reporting
one number would hide that.

So all three models run, and the spread between them is reported as part of
the result. Where they agree, the answer is robust. Where they diverge, the
divergence *is* the finding: it says the scenario's lead time has run past
what the cheap models can represent.

None of this is a manoeuvre plan. The covariance underneath is synthetic, the
element sets are public two-line sets of unknown freshness, and the post-burn
dynamics are not the dynamics that produced the pre-burn arc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp

from sdebris.maneuver.dynamics import (
    TWO_BODY,
    ForceModel,
    acceleration,
    ballistic_coefficient_from_bstar,
    with_perturbations,
)
from sdebris.maneuver.linear import (
    displacement_from_burn,
    is_trusted,
    mean_motion_rad_s,
    orbits_elapsed,
)
from sdebris.models import SpaceObject
from sdebris.propagation import propagate_objects
from sdebris.screening.frames import ric_basis

#: Integrator tolerances. Tight enough that the difference between models is
#: physics rather than integration error, which is the only way the comparison
#: means anything.
INTEGRATION_RTOL = 1e-10
INTEGRATION_ATOL = 1e-12

#: A burn larger than this is not a collision-avoidance manoeuvre.
MAX_DELTA_V_M_S = 50.0
#: Beyond this lead time the propagated arc is longer than the element set
#: supports, whatever the integrator says.
MAX_LEAD_TIME_HOURS = 72.0


@dataclass(frozen=True, slots=True)
class Burn:
    """An impulsive delta-v in the primary's RIC frame, before closest approach."""

    radial_m_s: float = 0.0
    along_track_m_s: float = 0.0
    cross_track_m_s: float = 0.0
    lead_time_hours: float = 6.0

    @property
    def magnitude_m_s(self) -> float:
        return float(
            np.linalg.norm(
                [self.radial_m_s, self.along_track_m_s, self.cross_track_m_s]
            )
        )

    def as_km_s(self) -> np.ndarray:
        return (
            np.array(
                [self.radial_m_s, self.along_track_m_s, self.cross_track_m_s],
                dtype=float,
            )
            / 1000.0
        )

    def validate(self) -> None:
        if self.magnitude_m_s <= 0.0:
            raise ValueError("a burn needs a non-zero delta-v")
        if self.magnitude_m_s > MAX_DELTA_V_M_S:
            raise ValueError(
                f"delta-v of {self.magnitude_m_s:.1f} m/s exceeds the "
                f"{MAX_DELTA_V_M_S:g} m/s this tool models"
            )
        if not 0.0 < self.lead_time_hours <= MAX_LEAD_TIME_HOURS:
            raise ValueError(
                f"lead time must be between 0 and {MAX_LEAD_TIME_HOURS:g} hours"
            )


@dataclass(frozen=True, slots=True)
class ModelOutcome:
    """What one model says the burn achieves.

    ``miss_distance_km`` is this model's own burned answer, and
    ``effect_km`` is the quantity actually worth comparing: the change this
    model attributes to the burn, measured against its *own* unburned
    prediction rather than against SGP4's.

    The distinction is the difference between a working comparison and a
    misleading one. A model that omits J2 drifts kilometres from SGP4 within
    hours with no burn at all, so its absolute miss distance mostly measures
    that drift. Differencing against its own baseline cancels it out and
    leaves the burn.

    ``drift_from_sgp4_km`` keeps that cancelled-out error visible instead of
    discarding it, because it is the honest measure of how far this model has
    departed from the theory the original screening used.
    """

    model: str
    label: str
    miss_distance_km: float
    effect_km: float
    assumptions: tuple[str, ...]
    #: How far this model's unburned trajectory ends from SGP4's. Zero for
    #: the linearised model, which perturbs SGP4's own answer.
    drift_from_sgp4_km: float = 0.0
    #: False when the scenario is outside what this model claims to cover.
    within_assumptions: bool = True
    caveat: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    baseline_miss_distance_km: float
    burn: Burn
    outcomes: list[ModelOutcome] = field(default_factory=list)

    @property
    def applicable(self) -> list[ModelOutcome]:
        """Outcomes from models still inside their own stated assumptions.

        A model that has already declared itself unsuitable is not casting a
        vote. Counting it would make the result read as contested whenever
        the cheapest model misbehaves, which is most of the time, and a
        warning that fires constantly stops being read.
        """
        trusted = [o for o in self.outcomes if o.within_assumptions]
        return trusted or list(self.outcomes)

    @property
    def disregarded(self) -> list[ModelOutcome]:
        """Models excluded from the comparison, and therefore worth naming."""
        if not any(o.within_assumptions for o in self.outcomes):
            return []
        return [o for o in self.outcomes if not o.within_assumptions]

    @property
    def spread_km(self) -> float:
        """How far apart the applicable models are about the burn's effect.

        Compared on ``effect_km``, not on absolute miss distance: a model's
        own drift is not a disagreement about the manoeuvre.
        """
        effects = [outcome.effect_km for outcome in self.applicable]
        if len(effects) < 2:
            return 0.0
        return float(max(effects) - min(effects))

    @property
    def models_agree(self) -> bool:
        """Whether the spread is small against the change being claimed."""
        if len(self.applicable) < 2:
            return False
        improvement = abs(self.best_effect_km)
        if improvement <= 0.0:
            return self.spread_km < 0.1
        return self.spread_km < 0.25 * improvement

    @property
    def best_effect_km(self) -> float:
        """The most complete model's view of the burn, which is not truth."""
        for outcome in self.outcomes:
            if outcome.model == "perturbed":
                return outcome.effect_km
        return self.outcomes[0].effect_km if self.outcomes else 0.0

    @property
    def best_estimate_km(self) -> float:
        """Resulting miss distance: SGP4's baseline plus the modelled effect.

        Built from the baseline rather than taken from the integration, so a
        model's drift does not leak into the headline number.
        """
        return self.baseline_miss_distance_km + self.best_effect_km

    def summary(self) -> str:
        if not self.outcomes:
            return "No model could evaluate this burn."
        direction = "increases" if self.best_effect_km > 0 else "reduces"
        text = (
            f"A {self.burn.magnitude_m_s:.2f} m/s burn "
            f"{self.burn.lead_time_hours:g} h before closest approach "
            f"{direction} the miss distance from "
            f"{self.baseline_miss_distance_km:.3f} km to "
            f"{self.best_estimate_km:.3f} km."
        )
        counted = len(self.applicable)
        if self.models_agree:
            text += (
                f" The {counted} applicable models agree to within "
                f"{self.spread_km:.3f} km, so the result does not hinge on "
                "which dynamics were assumed."
            )
        elif counted < 2:
            text += (
                " Only one model still applies at this lead time, so there is "
                "nothing to corroborate it against."
            )
        else:
            text += (
                f" The applicable models disagree by {self.spread_km:.3f} km, "
                "which is large against the change being claimed: at this "
                "lead time the answer depends on which dynamics are assumed."
            )

        excluded = self.disregarded
        if excluded:
            names = ", ".join(outcome.label for outcome in excluded)
            text += (
                f" {names} "
                f"{'was' if len(excluded) == 1 else 'were'} left out, having "
                "run past the assumptions it states."
                if len(excluded) == 1
                else f" {names} were left out, having run past the "
                "assumptions they state."
            )
        text += (
            " None of this is a manoeuvre plan: the post-burn dynamics are "
            "not the dynamics that found the encounter."
        )
        return text


def _propagate(
    state: np.ndarray, seconds: float, model: ForceModel
) -> np.ndarray:
    """Integrate a TEME state forward under ``model``."""
    if seconds <= 0.0:
        return state

    def derivative(_t: float, y: np.ndarray) -> np.ndarray:
        return np.concatenate([y[3:], acceleration(y, model)])

    solution = solve_ivp(
        derivative,
        (0.0, seconds),
        state,
        method="DOP853",
        rtol=INTEGRATION_RTOL,
        atol=INTEGRATION_ATOL,
        dense_output=False,
    )
    if not solution.success:
        raise RuntimeError(f"propagation failed: {solution.message}")
    return np.asarray(solution.y[:, -1], dtype=float)


def _states_at(
    objects: list[SpaceObject], moment: datetime
) -> list[tuple[np.ndarray, np.ndarray]]:
    """SGP4 position and velocity for each object at one instant."""
    grid = pd.DatetimeIndex([moment])
    ephemeris = propagate_objects(objects, grid, fail_on_error=True)
    return [
        (ephemeris.positions[i, 0], ephemeris.velocities[i, 0])
        for i in range(len(objects))
    ]


def evaluate(
    primary: SpaceObject,
    secondary: SpaceObject,
    tca: datetime,
    burn: Burn,
    *,
    bstar: float | None = None,
) -> ScenarioResult:
    """Run ``burn`` through every model and report what each one says.

    The secondary is propagated with SGP4 throughout: only the primary
    manoeuvres, so only the primary's arc has to leave the theory its element
    set was fitted to.
    """
    burn.validate()
    burn_time = tca - timedelta(hours=burn.lead_time_hours)

    (r_burn, v_burn), _ = _states_at([primary, secondary], burn_time)
    (r_primary_tca, v_primary_tca), (r_secondary_tca, _) = _states_at(
        [primary, secondary], tca
    )

    baseline_miss = float(np.linalg.norm(r_secondary_tca - r_primary_tca))

    # The burn is given in the primary's RIC frame at the moment it fires.
    basis = ric_basis(r_burn, v_burn)
    delta_v_teme = basis.T @ burn.as_km_s()
    elapsed_s = burn.lead_time_hours * 3600.0

    outcomes: list[ModelOutcome] = []

    # --- linearised relative motion ------------------------------------
    n = mean_motion_rad_s(float(np.linalg.norm(r_burn)))
    offset_ric = displacement_from_burn(burn.as_km_s(), elapsed_s, n)
    basis_tca = ric_basis(r_primary_tca, v_primary_tca)
    miss_ric = basis_tca @ (r_secondary_tca - r_primary_tca)
    trusted = is_trusted(elapsed_s, n)
    linear_miss = float(np.linalg.norm(miss_ric - offset_ric))
    outcomes.append(
        ModelOutcome(
            model="linear",
            label="Clohessy-Wiltshire",
            miss_distance_km=linear_miss,
            # The linearisation perturbs SGP4's own trajectory, so its
            # unburned case is the baseline by construction and it has no
            # drift of its own to subtract.
            effect_km=linear_miss - baseline_miss,
            drift_from_sgp4_km=0.0,
            assumptions=(
                "near-circular reference orbit",
                "relative motion small enough to linearise",
                "no perturbations between the burn and closest approach",
            ),
            within_assumptions=trusted,
            caveat=None
            if trusted
            else (
                f"{orbits_elapsed(elapsed_s, n):.1f} orbits of lead time is "
                "beyond where this linearisation is reliable"
            ),
        )
    )

    # --- integrated, two fidelities ------------------------------------
    coefficient = (
        ballistic_coefficient_from_bstar(bstar) if bstar is not None else None
    )
    models = [TWO_BODY, with_perturbations(coefficient or 0.02)]
    unburned_state = np.concatenate([r_burn, v_burn])
    burned_state = np.concatenate([r_burn, v_burn + delta_v_teme])
    for model in models:
        # Propagated twice under identical dynamics. Differencing the two
        # cancels the model's own error, which would otherwise swamp the
        # burn: dropping J2 moves a low-orbit object by hundreds of
        # kilometres in a day, while the manoeuvre moves it by metres.
        unburned = _propagate(unburned_state, elapsed_s, model)
        burned = _propagate(burned_state, elapsed_s, model)
        model_baseline = float(np.linalg.norm(r_secondary_tca - unburned[:3]))
        model_burned = float(np.linalg.norm(r_secondary_tca - burned[:3]))
        drift = float(np.linalg.norm(unburned[:3] - r_primary_tca))
        outcomes.append(
            ModelOutcome(
                model=model.name,
                label=model.label,
                miss_distance_km=model_burned,
                effect_km=model_burned - model_baseline,
                drift_from_sgp4_km=drift,
                assumptions=model.assumptions,
                # A model whose unburned arc has already wandered further
                # than the burn moves anything is not describing the burn.
                within_assumptions=drift <= abs(model_burned - model_baseline)
                or drift < 1.0,
                caveat=(
                    "the pre-burn arc came from SGP4, so the two halves of "
                    f"this trajectory use different dynamics; this model's "
                    f"own unburned path ends {drift:.3f} km from SGP4's"
                ),
            )
        )

    return ScenarioResult(
        baseline_miss_distance_km=baseline_miss, burn=burn, outcomes=outcomes
    )
