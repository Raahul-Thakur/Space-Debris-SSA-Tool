"""Collision probability via Foster's 2D method with Chan's analytic series.

Pipeline:
  1. Model each object's position uncertainty as a diagonal RIC covariance that
     grows with TLE age (TLEs carry no covariance, so this is a documented
     surrogate -- see docs/methodology.md).
  2. Rotate both covariances into ECI and sum them (combined covariance).
  3. Project the combined covariance and the miss vector onto the conjunction
     plane (perpendicular to the relative velocity) -- Foster's B-plane.
  4. Evaluate Pc with Chan's series, treating the combined hard-body radius as a
     circular cross-section in the plane.

IMPORTANT: Pc from TLE-derived covariance is illustrative, not operational. Real
conjunction assessment uses covariance from the owner/operator or the 18 SDS.
"""

from __future__ import annotations

from math import exp, factorial

import numpy as np

from sdebris.config import RiskConfig
from sdebris.screening.frames import ric_basis


def build_ric_covariance(risk: RiskConfig, age_days: float) -> np.ndarray:
    """Diagonal RIC covariance (m^2), 1-sigma growing linearly with TLE age."""
    age = max(age_days, 0.0)
    sigma_r = risk.sigma_radial_m + risk.age_growth_m_per_day.radial * age
    sigma_i = risk.sigma_intrack_m + risk.age_growth_m_per_day.intrack * age
    sigma_c = risk.sigma_crosstrack_m + risk.age_growth_m_per_day.crosstrack * age
    return np.diag([sigma_r**2, sigma_i**2, sigma_c**2])


def ric_to_eci_covariance(cov_ric: np.ndarray, r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rotate a RIC covariance into the ECI frame.

    The RIC basis ``B`` maps ECI->RIC, so ``cov_eci = B^T cov_ric B``.
    """
    basis = ric_basis(r, v)
    return basis.T @ cov_ric @ basis


def _chan_series(u: float, v: float, terms: int = 40) -> float:
    """Chan's series for circular-cross-section Pc in principal-axis coords."""
    total = 0.0
    for m in range(terms):
        inner = 1.0 - exp(-u / 2.0) * sum(
            (u**k) / (2.0**k * factorial(k)) for k in range(m + 1)
        )
        total += (v**m) / (2.0**m * factorial(m)) * inner
    return exp(-v / 2.0) * total


def probability_of_collision(
    r_rel_m: np.ndarray,
    v_rel_m_s: np.ndarray,
    cov_eci_m2: np.ndarray,
    hard_body_radius_m: float,
) -> float:
    """Foster/Chan Pc. Inputs in metres and m/s; covariance is 3x3 ECI in m^2."""
    r_rel = np.asarray(r_rel_m, dtype=float)
    v_rel = np.asarray(v_rel_m_s, dtype=float)
    speed = np.linalg.norm(v_rel)
    if speed == 0.0:
        return 0.0

    # Conjunction-plane basis: perpendicular to relative velocity.
    n = v_rel / speed
    x_raw = r_rel - np.dot(r_rel, n) * n      # in-plane direction of the miss
    x_norm = np.linalg.norm(x_raw)
    if x_norm < 1e-9:
        # Miss is (nearly) along the velocity; pick an arbitrary in-plane axis.
        helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        x_axis = helper - np.dot(helper, n) * n
        x_axis /= np.linalg.norm(x_axis)
    else:
        x_axis = x_raw / x_norm
    y_axis = np.cross(n, x_axis)

    proj = np.vstack([x_axis, y_axis])        # 2x3
    cov_2d = proj @ cov_eci_m2 @ proj.T       # 2x2 projected covariance
    miss_2d = proj @ r_rel                    # 2-vector projected miss

    # Rotate to principal axes so the covariance is diagonal.
    eigvals, eigvecs = np.linalg.eigh(cov_2d)
    eigvals = np.clip(eigvals, 1e-6, None)    # floor to avoid singular covariance
    miss_principal = eigvecs.T @ miss_2d
    sigma_x, sigma_y = np.sqrt(eigvals[0]), np.sqrt(eigvals[1])
    xm, ym = miss_principal

    u = hard_body_radius_m**2 / (sigma_x * sigma_y)
    v_param = (xm**2) / eigvals[0] + (ym**2) / eigvals[1]
    pc = _chan_series(u, v_param)
    return float(min(max(pc, 0.0), 1.0))
