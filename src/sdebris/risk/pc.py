"""Collision probability in the encounter plane (Foster), with Chan's series.

Pipeline:
  1. Model each object's position uncertainty as a diagonal RIC covariance that
     grows with TLE age (TLEs carry no covariance, so this is a documented
     surrogate -- see docs/methodology.md).
  2. Rotate both covariances into ECI and sum them (combined covariance).
  3. Project the combined covariance and the miss vector onto the conjunction
     plane (perpendicular to the relative velocity), as in Foster's method.
  4. Integrate the 2D Gaussian over the circular hard-body cross-section
     (Foster). The integral across each chord is a normal-CDF difference, so a
     single adaptive quadrature remains; it is exact for any aspect ratio.
     Chan's analytic series is available as ``method="chan"``; its equal-area
     treatment of the disk errs by several to tens of per cent for elongated
     covariances, more as the miss grows (see docs/methodology.md).
  A covariance with no extent at all is a point mass.

IMPORTANT: Pc from TLE-derived covariance is illustrative, not operational. Real
conjunction assessment uses covariance from the owner/operator or the 18 SDS.
"""

from __future__ import annotations

import logging
import math

import numpy as np
from scipy.integrate import quad
from scipy.special import gammainc, gammaln, ndtr

from sdebris.config import RiskConfig

logger = logging.getLogger(__name__)

#: Combined covariance with every in-plane 1-sigma below this (1 mm) is
#: treated as exactly known: a point mass at the miss vector.
POINT_MASS_SIGMA_M = 1e-3
#: Width (in standard deviations) of the Poisson window summed in Chan's series.
_POISSON_SPREAD_SIGMAS = 12.0


def clamp_probability(pc: float) -> float:
    """Clamp a probability to [0, 1], NaN-safely.

    ``max(0, min(1, nan))`` is 1.0 in Python, which once turned a numerical
    failure on a harmless 25 km pass into Pc = 1 and a critical tier. NaN now
    maps to 0.0 with a logged warning (the event is still tiered on its miss
    distance), +inf to 1.0, and -0.0 to 0.0.
    """
    value = float(pc)
    if math.isnan(value):
        logger.warning("Pc evaluated to NaN; reporting 0.0")
        return 0.0
    return min(max(value, 0.0), 1.0) + 0.0


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
    # Imported here: sdebris.screening imports this module, so a module-level
    # import made ``import sdebris.risk`` fail unless screening came first.
    from sdebris.screening.frames import ric_basis

    basis = ric_basis(r, v)
    return basis.T @ cov_ric @ basis


def _chan_series(u: float, v: float) -> float:
    """Chan's series for circular-cross-section Pc in principal-axis coords.

    Written as ``sum_m Poisson(m; v/2) * P(Poisson(u/2) > m)``, the m-th term
    of ``e^{-v/2} sum_m v^m/(2^m m!) [1 - e^{-u/2} sum_{k<=m} u^k/(2^k k!)]``,
    with ``P(Poisson(u/2) > m)`` the regularised incomplete gamma function
    ``P(m+1, u/2)``. Weights are evaluated in log space and summed over the
    window that holds all but ~1e-30 of the Poisson(v/2) mass, so neither a
    large ``v`` (many sigma away: powers overflowed and the old fixed 40-term
    loop returned NaN) nor a large ``u`` (hard body much larger than sigma:
    40 terms truncated a near-certain hit to a few per cent) breaks it.
    """
    if not (math.isfinite(u) and math.isfinite(v)):
        return float("nan")
    if u <= 0.0:
        return 0.0
    lu, lv = 0.5 * u, 0.5 * v
    spread = _POISSON_SPREAD_SIGMAS * math.sqrt(lv) + 30.0
    m_lo = max(0, math.floor(lv - spread))
    m_hi = math.ceil(lv + spread)
    # P(m+1, u/2) falls with m, so if it underflows at the start of the window
    # every term does: the miss is so many sigma out that Pc is negligible.
    if gammainc(m_lo + 1, lu) == 0.0:
        return 0.0
    m = np.arange(m_lo, m_hi + 1, dtype=float)
    if lv > 0.0:
        weights = np.exp(m * math.log(lv) - lv - gammaln(m + 1.0))
    else:
        weights = (m == 0.0).astype(float)
    return float(np.sum(weights * gammainc(m + 1.0, lu)))


def _gaussian_band(lo: float, hi: float) -> float:
    """P(lo < Z < hi) for a standard normal, without cancellation in the tails."""
    if lo >= 0.0:
        return float(ndtr(-lo) - ndtr(-hi))
    return float(ndtr(hi) - ndtr(lo))


def _disk_integral(xm: float, ym: float, sigma_x: float, sigma_y: float, radius: float) -> float:
    """Exact Pc: the principal-axis Gaussian integrated over the hard-body disk.

    The inner integral across the chord at each ``x`` is a normal CDF
    difference, leaving one adaptive quadrature along the axis with the
    larger sigma. Valid for any aspect ratio, including a covariance that is
    (floored) flat along one axis.
    """
    if sigma_x < sigma_y:
        xm, ym, sigma_x, sigma_y = ym, xm, sigma_y, sigma_x
    norm = 1.0 / (sigma_x * math.sqrt(2.0 * math.pi))

    def integrand(x: float) -> float:
        half = math.sqrt(max(radius * radius - x * x, 0.0))
        band = _gaussian_band((-half - ym) / sigma_y, (half - ym) / sigma_y)
        return norm * math.exp(-0.5 * ((x - xm) / sigma_x) ** 2) * band

    breaks = [xm]
    if abs(ym) < radius:
        edge = math.sqrt(radius * radius - ym * ym)
        breaks += [-edge, edge]
    points = sorted({p for p in breaks if -radius < p < radius})
    value, _ = quad(
        integrand, -radius, radius, points=points or None,
        limit=200, epsabs=0.0, epsrel=1e-10,
    )
    return value


def probability_of_collision(
    r_rel_m: np.ndarray,
    v_rel_m_s: np.ndarray,
    cov_eci_m2: np.ndarray,
    hard_body_radius_m: float,
    *,
    method: str = "foster",
) -> float:
    """Pc in the encounter plane. Inputs in metres and m/s; covariance is 3x3 ECI in m^2.

    ``method="foster"`` (default) integrates the Gaussian over the hard-body
    disk; ``method="chan"`` uses Chan's series instead. Always a finite number
    in [0, 1]. A combined covariance with no in-plane extent above 1 mm is a
    point mass: 1 if the miss is inside the hard body, else 0.
    """
    if method not in ("foster", "chan"):
        raise ValueError(f"unknown Pc method {method!r}")
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

    if not (np.all(np.isfinite(cov_2d)) and np.all(np.isfinite(miss_2d))):
        return clamp_probability(float("nan"))

    # Rotate to principal axes so the covariance is diagonal.
    eigvals, eigvecs = np.linalg.eigh(cov_2d)
    floor = POINT_MASS_SIGMA_M**2
    if eigvals.max() < floor:
        # No uncertainty to speak of: the relative position is a point mass,
        # which hits exactly when it lies inside the hard body.
        return 1.0 if float(np.linalg.norm(miss_2d)) < hard_body_radius_m else 0.0
    eigvals = np.clip(eigvals, floor, None)   # one axis degenerate: floor at 1 mm
    miss_principal = eigvecs.T @ miss_2d
    sigma_x, sigma_y = np.sqrt(eigvals[0]), np.sqrt(eigvals[1])
    xm, ym = miss_principal

    radius = float(hard_body_radius_m)
    if radius <= 0.0:
        return 0.0
    # Negligible: even the disk's nearest point is > 40 sigma (largest sigma)
    # from the mean, so the mass inside is below ~1e-300.
    if (math.hypot(xm, ym) - radius) / max(sigma_x, sigma_y) > 40.0:
        return 0.0
    if method == "foster":
        return clamp_probability(_disk_integral(xm, ym, sigma_x, sigma_y, radius))

    u = float(radius**2 / (sigma_x * sigma_y))
    v_param = float((xm**2) / eigvals[0] + (ym**2) / eigvals[1])
    return clamp_probability(_chan_series(u, v_param))
