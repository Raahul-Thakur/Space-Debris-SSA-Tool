"""Time of Closest Approach (TCA) detection and refinement.

The coarse propagation grid (e.g. 60 s) brackets the true closest approach but
rarely lands on it. At the true TCA the range-rate vanishes:

    g(t) = dr(t) . dv(t) = 0          (dr = relative position, dv = relative velocity)

We locate the coarse minimum, then bisect ``g`` over the neighbouring interval to
pin down the TCA, interpolating the state vectors of both objects to that instant.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TCAResult:
    tca_seconds: float                 # epoch seconds (UNIX) of closest approach
    miss_distance_km: float
    relative_speed_km_s: float
    r_primary: np.ndarray              # interpolated ECI state at TCA
    v_primary: np.ndarray
    r_secondary: np.ndarray
    v_secondary: np.ndarray


def _interp_vec(t: float, times: np.ndarray, vecs: np.ndarray) -> np.ndarray:
    return np.array([np.interp(t, times, vecs[:, k]) for k in range(vecs.shape[1])])


def refine_tca(
    epoch_seconds: np.ndarray,
    r_primary: np.ndarray,
    v_primary: np.ndarray,
    r_secondary: np.ndarray,
    v_secondary: np.ndarray,
    *,
    max_iter: int = 60,
    tol_sec: float = 1e-3,
) -> TCAResult:
    """Refine the closest approach from coarse, gridded state arrays.

    All arrays are aligned to ``epoch_seconds`` (shape ``(n,)``); the position and
    velocity arrays have shape ``(n, 3)``.
    """
    dr = r_secondary - r_primary
    dist = np.linalg.norm(dr, axis=1)
    k = int(np.argmin(dist))

    # Bracket the minimum with its valid neighbours.
    lo = max(k - 1, 0)
    hi = min(k + 1, len(epoch_seconds) - 1)
    t_lo, t_hi = epoch_seconds[lo], epoch_seconds[hi]

    def g(t: float) -> float:
        rp = _interp_vec(t, epoch_seconds, r_primary)
        vp = _interp_vec(t, epoch_seconds, v_primary)
        rs = _interp_vec(t, epoch_seconds, r_secondary)
        vs = _interp_vec(t, epoch_seconds, v_secondary)
        return float(np.dot(rs - rp, vs - vp))

    g_lo, g_hi = g(t_lo), g(t_hi)
    if t_hi - t_lo < tol_sec:
        t_star = epoch_seconds[k]
    elif g_lo <= 0.0 <= g_hi or g_hi <= 0.0 <= g_lo:
        # Range-rate changes sign across the bracket -> bisection.
        a, b, ga = t_lo, t_hi, g_lo
        for _ in range(max_iter):
            m = 0.5 * (a + b)
            gm = g(m)
            if abs(gm) < 1e-9 or (b - a) < tol_sec:
                break
            if (ga <= 0.0) == (gm <= 0.0):
                a, ga = m, gm
            else:
                b = m
        t_star = 0.5 * (a + b)
    else:
        # No sign change (minimum sits at a grid edge) -> keep the coarse minimum.
        t_star = epoch_seconds[k]

    rp = _interp_vec(t_star, epoch_seconds, r_primary)
    vp = _interp_vec(t_star, epoch_seconds, v_primary)
    rs = _interp_vec(t_star, epoch_seconds, r_secondary)
    vs = _interp_vec(t_star, epoch_seconds, v_secondary)
    miss = float(np.linalg.norm(rs - rp))
    rel_speed = float(np.linalg.norm(vs - vp))

    return TCAResult(
        tca_seconds=float(t_star),
        miss_distance_km=miss,
        relative_speed_km_s=rel_speed,
        r_primary=rp, v_primary=vp,
        r_secondary=rs, v_secondary=vs,
    )
