"""Manoeuvre what-ifs, and the honesty of comparing three models.

The physics assertions here are deliberately about *relationships* -- an
along-track burn drifts and a radial one does not, more lead time moves more,
the models converge as the horizon shortens -- rather than about absolute
numbers. Pinning absolute values would turn a change in the force model into
a test failure without saying whether the change was an improvement.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from sdebris.maneuver import Burn, evaluate
from sdebris.maneuver.dynamics import (
    DEFAULT_BALLISTIC_COEFFICIENT,
    TWO_BODY,
    acceleration,
    atmospheric_density,
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

# Two real element sets from the Iridium-33 event, the collision this tool
# exists to teach about.
PRIMARY = SpaceObject(
    "25544",
    "ISS (ZARYA)",
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  30100-3 0  9995",
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49814556  5000",
)
SECONDARY = SpaceObject(
    "33773",
    "IRIDIUM 33 DEB",
    "1 33773U 97051M   24001.50000000  .00000500  00000-0  15000-3 0  9990",
    "2 33773  86.3970 120.5000 0010000  90.0000 270.0000 14.35000000  5000",
)
TCA = datetime(2024, 1, 3, tzinfo=timezone.utc)


# ---------------------------------------------------------------- linear model
def test_an_along_track_burn_keeps_moving_the_object() -> None:
    """It changes the period, so the offset accumulates every orbit."""
    n = mean_motion_rad_s(6778.0)
    dv = np.array([0.0, 1e-5, 0.0])  # 10 mm/s along-track
    offsets = [
        float(np.linalg.norm(displacement_from_burn(dv, hours * 3600, n)))
        for hours in (1, 6, 24)
    ]
    assert offsets[0] < offsets[1] < offsets[2]
    # Growth is secular rather than oscillatory, so a day beats an hour by
    # far more than the ratio of their lengths would suggest if it were not.
    assert offsets[2] > 10 * offsets[0]


def test_a_radial_burn_only_oscillates() -> None:
    """It tilts the orbit; the effect is bounded, which is why nobody uses it.

    The along-track response to a radial impulse peaks at 4*dv/n and returns,
    where an along-track impulse grows without limit. That contrast is the
    reason collision avoidance burns are along-track.
    """
    n = mean_motion_rad_s(6778.0)
    magnitude = 1e-5
    dv = np.array([magnitude, 0.0, 0.0])
    period_s = 2 * np.pi / n

    def peak_within(orbits: float) -> float:
        samples = np.linspace(60, orbits * period_s, 400)
        return max(
            float(np.linalg.norm(displacement_from_burn(dv, t, n))) for t in samples
        )

    near, far = peak_within(3), peak_within(30)
    # Ten times as long does not move it any further: bounded, not secular.
    assert far == pytest.approx(near, rel=0.05)
    # And the bound is the analytic one.
    assert far < 4.2 * magnitude / n


def test_a_cross_track_burn_stays_in_its_own_axis() -> None:
    n = mean_motion_rad_s(6778.0)
    offset = displacement_from_burn(np.array([0.0, 0.0, 1e-5]), 3600, n)
    assert abs(offset[0]) < 1e-12
    assert abs(offset[1]) < 1e-12
    assert abs(offset[2]) > 0.0


def test_no_burn_moves_nothing() -> None:
    n = mean_motion_rad_s(6778.0)
    assert np.allclose(displacement_from_burn(np.zeros(3), 3600, n), 0.0)


def test_the_linearisation_declares_its_own_horizon() -> None:
    n = mean_motion_rad_s(6778.0)
    one_orbit = 2 * np.pi / n
    assert is_trusted(one_orbit, n)
    assert not is_trusted(10 * one_orbit, n)
    assert orbits_elapsed(one_orbit, n) == pytest.approx(1.0, rel=1e-6)


# -------------------------------------------------------------- force models
def test_oblateness_changes_the_acceleration() -> None:
    state = np.array([6778.0, 0.0, 100.0, 0.0, 7.67, 0.5])
    plain = acceleration(state, TWO_BODY)
    perturbed = acceleration(state, with_perturbations(0.02))
    assert not np.allclose(plain, perturbed)


def test_density_falls_with_altitude() -> None:
    assert atmospheric_density(300) > atmospheric_density(400)
    assert atmospheric_density(400) > atmospheric_density(800)


def test_an_implausible_drag_term_falls_back_to_a_default() -> None:
    """B* fitted to a manoeuvring object is routinely negative or absurd."""
    assert ballistic_coefficient_from_bstar(-1e-4) == DEFAULT_BALLISTIC_COEFFICIENT
    assert ballistic_coefficient_from_bstar(1e9) == DEFAULT_BALLISTIC_COEFFICIENT
    assert ballistic_coefficient_from_bstar(float("nan")) == DEFAULT_BALLISTIC_COEFFICIENT


# ------------------------------------------------------------------ scenarios
def test_a_burn_is_rejected_when_it_is_not_a_collision_avoidance_burn() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        Burn(along_track_m_s=5_000.0).validate()
    with pytest.raises(ValueError, match="non-zero"):
        Burn().validate()
    with pytest.raises(ValueError, match="lead time"):
        Burn(along_track_m_s=0.05, lead_time_hours=500).validate()


def test_every_model_reports_an_answer() -> None:
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    assert {outcome.model for outcome in result.outcomes} == {
        "linear",
        "two_body",
        "perturbed",
    }


def test_the_models_agree_about_the_burn_over_a_short_horizon() -> None:
    """The point of differencing: they disagree about orbits, not about burns."""
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    assert result.models_agree, result.summary()
    assert result.spread_km < 0.05


def test_the_effect_is_measured_against_each_models_own_baseline() -> None:
    """Otherwise a model's drift is reported as if the burn had caused it.

    Two-body omits J2 and wanders tens of kilometres from SGP4 within hours,
    while the burn moves the object by a fraction of that. Comparing absolute
    miss distances would make the cheapest model look the most effective.
    """
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=6)
    )
    two_body = next(o for o in result.outcomes if o.model == "two_body")
    perturbed = next(o for o in result.outcomes if o.model == "perturbed")

    assert two_body.drift_from_sgp4_km > perturbed.drift_from_sgp4_km
    # The drift dwarfs the burn, which is exactly why it must be differenced.
    assert two_body.drift_from_sgp4_km > abs(two_body.effect_km)
    # And having been differenced, the two agree about the burn itself.
    assert two_body.effect_km == pytest.approx(perturbed.effect_km, rel=0.2)


def test_the_perturbed_model_tracks_sgp4_far_better_than_two_body() -> None:
    """Evidence the J2 term is right, not just present."""
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    two_body = next(o for o in result.outcomes if o.model == "two_body")
    perturbed = next(o for o in result.outcomes if o.model == "perturbed")
    assert perturbed.drift_from_sgp4_km < two_body.drift_from_sgp4_km / 10


def test_a_model_that_has_wandered_further_than_the_burn_says_so() -> None:
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=6)
    )
    two_body = next(o for o in result.outcomes if o.model == "two_body")
    assert not two_body.within_assumptions
    assert two_body.caveat and "different dynamics" in two_body.caveat


def test_more_lead_time_moves_the_object_further() -> None:
    early = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=12)
    )
    late = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=1)
    )
    assert abs(early.best_effect_km) > abs(late.best_effect_km)


def test_the_models_diverge_as_the_horizon_lengthens() -> None:
    """The spread is the finding, so it has to actually respond to the cause."""
    near = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    far = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=48)
    )
    assert far.spread_km > near.spread_km


def test_the_summary_states_the_disagreement_rather_than_hiding_it() -> None:
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    summary = result.summary()
    assert "m/s burn" in summary
    assert "agree" in summary or "disagree" in summary


def test_every_outcome_states_what_it_assumed() -> None:
    """A number without its assumptions is not a result."""
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    for outcome in result.outcomes:
        assert outcome.assumptions
        assert all(isinstance(line, str) and line for line in outcome.assumptions)


def test_the_headline_builds_on_sgp4_rather_than_on_a_drifted_arc() -> None:
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=6)
    )
    assert result.best_estimate_km == pytest.approx(
        result.baseline_miss_distance_km + result.best_effect_km
    )


# ----------------------------------------------- which models get a vote
def test_a_model_outside_its_assumptions_does_not_vote() -> None:
    """Otherwise the warning fires on every scenario and stops being read.

    Two-body declares itself unsuitable within hours, so including it in the
    agreement test would report every result as contested even when the two
    models that still apply agree to within metres.
    """
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=2)
    )
    assert any(not o.within_assumptions for o in result.outcomes)
    assert all(o.within_assumptions for o in result.applicable)
    assert result.models_agree
    # The excluded model is named rather than quietly dropped.
    assert result.disregarded
    assert "left out" in result.summary()


def test_a_single_surviving_model_is_not_called_agreement() -> None:
    """One model agreeing with itself is not corroboration."""
    result = evaluate(
        PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=48)
    )
    if len(result.applicable) == 1:
        assert not result.models_agree
        assert "nothing to corroborate" in result.summary()


def test_the_summary_always_refuses_operational_standing() -> None:
    for lead in (1.0, 12.0, 48.0):
        result = evaluate(
            PRIMARY, SECONDARY, TCA, Burn(along_track_m_s=0.05, lead_time_hours=lead)
        )
        assert "None of this is a manoeuvre plan" in result.summary()
