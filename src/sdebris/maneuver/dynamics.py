"""Force models for propagating a state vector after a burn.

SGP4 cannot be used past the burn. It propagates TLE *mean elements* through
a theory that already contains its own secular and periodic terms; there is no
state vector inside it to add a delta-v to, and feeding a perturbed state back
in would mean fitting a new element set, which is a different and lossy
operation.

So the post-burn arc has to be integrated, and the honest consequence is that
the two halves of a manoeuvre scenario come from different dynamics. This
module provides the post-burn half, in two fidelities that differ *only* in
which accelerations are summed. Running both and showing the gap is the point:
it measures what the neglected physics is worth over the scenario's own
horizon, rather than asserting a single number and hoping.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Earth gravitational parameter, km^3/s^2 (WGS-84, as used by SGP4).
MU_KM3_S2 = 398600.8
#: Earth equatorial radius, km (WGS-84).
EARTH_RADIUS_KM = 6378.135
#: Second zonal harmonic. The dominant non-spherical term by two orders of
#: magnitude, and in low orbit the dominant perturbation of any kind.
J2 = 1.082616e-3

#: Exponential atmosphere, calibrated at 400 km. Crude on purpose: real
#: density varies by an order of magnitude with solar activity, and pretending
#: otherwise would put false precision on the least certain term in the model.
REFERENCE_ALTITUDE_KM = 400.0
REFERENCE_DENSITY_KG_M3 = 3.9e-12
SCALE_HEIGHT_KM = 60.0

#: Cd*A/m for a typical uncontrolled LEO satellite, m^2/kg. Used when the
#: element set carries no usable drag term.
DEFAULT_BALLISTIC_COEFFICIENT = 0.02

#: SGP4's reference density, kg/(m^2 * earth radii), for converting B* into a
#: ballistic coefficient.
SGP4_REFERENCE_DENSITY = 2.461e-5
#: Physically plausible bounds for Cd*A/m, m^2/kg. A B* fitted to a manoeuvring
#: or poorly tracked object can be negative or absurd, and an absurd ballistic
#: coefficient produces a confidently wrong trajectory.
MIN_BALLISTIC_COEFFICIENT = 1e-4
MAX_BALLISTIC_COEFFICIENT = 1.0


def ballistic_coefficient_from_bstar(bstar: float) -> float:
    """Convert an element set's B* drag term into Cd*A/m in m^2/kg.

    B* is SGP4's own drag parameter, so deriving from it keeps the post-burn
    drag roughly consistent with the pre-burn arc rather than inventing a
    second, unrelated assumption. The conversion is approximate, and a B*
    fitted to a manoeuvring object is frequently negative or wildly large, so
    anything implausible falls back to the default.
    """
    if not np.isfinite(bstar) or bstar <= 0.0:
        return DEFAULT_BALLISTIC_COEFFICIENT
    coefficient = 2.0 * bstar / SGP4_REFERENCE_DENSITY
    if not MIN_BALLISTIC_COEFFICIENT <= coefficient <= MAX_BALLISTIC_COEFFICIENT:
        return DEFAULT_BALLISTIC_COEFFICIENT
    return float(coefficient)


def atmospheric_density(altitude_km: float) -> float:
    """Density in kg/m^3 from a single exponential scale height."""
    if altitude_km <= 0.0:
        return REFERENCE_DENSITY_KG_M3
    exponent = -(altitude_km - REFERENCE_ALTITUDE_KM) / SCALE_HEIGHT_KM
    # Clamped because the exponential runs away at very low altitudes, and a
    # re-entering object is outside what any of this is modelling anyway.
    return REFERENCE_DENSITY_KG_M3 * float(np.exp(np.clip(exponent, -50.0, 50.0)))


@dataclass(frozen=True, slots=True)
class ForceModel:
    """Which accelerations act on the propagated state."""

    name: str
    label: str
    oblateness: bool
    drag: bool
    #: Cd*A/m in m^2/kg; ignored unless ``drag``.
    ballistic_coefficient: float = DEFAULT_BALLISTIC_COEFFICIENT

    @property
    def assumptions(self) -> tuple[str, ...]:
        stated = ["Earth as a point mass"]
        if self.oblateness:
            stated.append("J2 oblateness")
        else:
            stated.append("no oblateness, which dominates drift in low orbit")
        if self.drag:
            stated.append(
                "exponential atmosphere, which ignores solar activity "
                f"(Cd*A/m = {self.ballistic_coefficient:.3g} m^2/kg)"
            )
        else:
            stated.append("no atmospheric drag")
        stated.append("no third-body or radiation pressure terms")
        return tuple(stated)


def acceleration(state: np.ndarray, model: ForceModel) -> np.ndarray:
    """Acceleration in km/s^2 for a TEME state ``[x, y, z, vx, vy, vz]``."""
    position = state[:3]
    velocity = state[3:]
    r = float(np.linalg.norm(position))
    if r <= 0.0:
        return np.zeros(3)

    acc = -MU_KM3_S2 * position / r**3

    if model.oblateness:
        z_ratio_sq = (position[2] / r) ** 2
        factor = 1.5 * J2 * MU_KM3_S2 * EARTH_RADIUS_KM**2 / r**5
        acc = acc - factor * np.array(
            [
                position[0] * (1.0 - 5.0 * z_ratio_sq),
                position[1] * (1.0 - 5.0 * z_ratio_sq),
                position[2] * (3.0 - 5.0 * z_ratio_sq),
            ]
        )

    if model.drag:
        # The atmosphere co-rotates, so drag acts on velocity relative to it
        # rather than on inertial velocity. Omitting this misstates the
        # along-track effect, which is the one that matters for a conjunction.
        earth_rotation = np.array([0.0, 0.0, 7.2921159e-5])  # rad/s
        relative_velocity = velocity - np.cross(earth_rotation, position)
        speed = float(np.linalg.norm(relative_velocity))
        if speed > 0.0:
            density = atmospheric_density(r - EARTH_RADIUS_KM)
            # density kg/m^3 * (m^2/kg) * (km/s)^2 -> needs km: the 1000
            # converts the m^2/kg area term into km^2/kg.
            drag_km_s2 = (
                -0.5
                * density
                * model.ballistic_coefficient
                * 1000.0
                * speed
                * relative_velocity
            )
            acc = acc + drag_km_s2

    return acc


#: Point-mass gravity only. Fast, exactly integrable in principle, and wrong
#: in a way that grows: in low orbit J2 moves an object by kilometres within a
#: single day, which is the same scale as the miss distances being screened.
TWO_BODY = ForceModel(
    name="two_body",
    label="Two-body",
    oblateness=False,
    drag=False,
)


def with_perturbations(ballistic_coefficient: float) -> ForceModel:
    """Point-mass gravity plus J2 and drag."""
    return ForceModel(
        name="perturbed",
        label="J2 + drag",
        oblateness=True,
        drag=True,
        ballistic_coefficient=ballistic_coefficient,
    )
