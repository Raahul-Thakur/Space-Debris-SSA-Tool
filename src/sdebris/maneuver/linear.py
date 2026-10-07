"""Linearised relative motion: what a burn does to a miss distance.

The Clohessy-Wiltshire equations describe motion relative to a body on a
circular orbit. They answer the question a manoeuvre scenario is really
asking -- how far does this delta-v move me by the time of closest approach --
without propagating anything, because the displacement from an impulsive burn
has a closed form.

That makes this the cheapest of the three models and, within its assumptions,
the most direct: it computes the quantity of interest rather than computing a
trajectory and then measuring it. The assumptions are the catch. The reference
orbit must be near-circular, the lead time must be short enough that the
linearisation holds -- roughly a few orbits -- and nothing perturbs either
object in between.
"""

from __future__ import annotations

import numpy as np

from sdebris.maneuver.dynamics import MU_KM3_S2

#: Beyond this the linearisation is no longer worth reporting without saying
#: so. Expressed in orbits rather than hours because that is what it depends
#: on; CW error grows with how far the reference has travelled, not with time.
TRUSTED_ORBITS = 3.0


def mean_motion_rad_s(radius_km: float) -> float:
    """Circular-orbit mean motion at this radius."""
    return float(np.sqrt(MU_KM3_S2 / radius_km**3))


def displacement_from_burn(
    delta_v_ric_km_s: np.ndarray, elapsed_s: float, mean_motion: float
) -> np.ndarray:
    """Position offset in RIC at ``elapsed_s`` after an impulsive burn.

    The Clohessy-Wiltshire solution with zero initial offset, so the result is
    purely the burn's effect. Axes are radial, along-track, cross-track.

    The along-track term carries a secular ``-3nt`` piece, and it multiplies
    the *along-track* component of the burn. An along-track delta-v changes
    the semi-major axis, which changes the period, which makes the offset
    accumulate every orbit. A radial burn only tilts the orbit and its effect
    oscillates within a bounded envelope.

    That is why along-track is the efficient direction for collision
    avoidance, and why a tiny burn applied early beats a large one applied
    late. It is also the whole reason lead time is a parameter here rather
    than a constant.
    """
    n = mean_motion
    t = elapsed_s
    if n <= 0.0 or t <= 0.0:
        return np.zeros(3)

    dv_r, dv_i, dv_c = (float(component) for component in delta_v_ric_km_s)
    sin_nt = float(np.sin(n * t))
    cos_nt = float(np.cos(n * t))

    radial = (dv_r / n) * sin_nt + (2.0 * dv_i / n) * (1.0 - cos_nt)
    along = (2.0 * dv_r / n) * (cos_nt - 1.0) + (dv_i / n) * (
        4.0 * sin_nt - 3.0 * n * t
    )
    cross = (dv_c / n) * sin_nt
    return np.array([radial, along, cross])


def orbits_elapsed(elapsed_s: float, mean_motion: float) -> float:
    """How far round the reference orbit has gone, in revolutions."""
    if mean_motion <= 0.0:
        return 0.0
    return float(mean_motion * elapsed_s / (2.0 * np.pi))


def is_trusted(elapsed_s: float, mean_motion: float) -> bool:
    return orbits_elapsed(elapsed_s, mean_motion) <= TRUSTED_ORBITS
