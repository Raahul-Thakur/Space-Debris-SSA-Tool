"""Time of Closest Approach (TCA) detection and refinement.

The coarse propagation grid (e.g. 60 s) brackets each close approach but rarely
lands on it. At a closest approach the range-rate changes sign from negative to
positive:

    g(t) = dr(t) . dv(t) = 0          (dr = relative position, dv = relative velocity)

Detection (:func:`find_close_approach_candidates`) works on the gridded states
of many object pairs at once. Every grid interval where ``g`` goes from
negative to non-negative holds a local minimum of the separation. Whether that
minimum can be inside the coarse threshold is decided from a bound on the
distance *within* the interval, not from the two sampled distances: at
~15 km/s relative speed two 60 s samples can be ~900 km apart while the real
miss between them is a few hundred metres.

Refinement (:func:`refine_tca_sgp4`) then solves ``g(t) = 0`` inside each
bracket with Brent's method, re-propagating both objects with SGP4 at every
trial time, so the TCA and miss distance carry no interpolation error.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq
from sgp4.api import Satrec

from sdebris.propagation.sgp4_prop import propagate_at


@dataclass(frozen=True)
class TCAResult:
    tca_seconds: float                 # epoch seconds (UNIX) of closest approach
    miss_distance_km: float
    relative_speed_km_s: float
    r_primary: np.ndarray              # ECI (TEME) state at TCA
    v_primary: np.ndarray
    r_secondary: np.ndarray
    v_secondary: np.ndarray


@dataclass(frozen=True)
class Candidates:
    """Close-approach candidates found on a coarse grid.

    ``obj`` indexes the secondary (first axis of the arrays passed in), ``k``
    is a grid index. Where ``bracket`` is True the minimum lies in the
    interval ``[k, k+1]`` (range-rate sign change); where it is False the
    candidate is the sample ``k`` itself: a window or validity-gap edge the
    pair is receding from (or approaching) at that moment, or a degenerate
    pair with no range-rate sign change at all (e.g. identical orbits).
    """

    obj: np.ndarray
    k: np.ndarray
    bracket: np.ndarray

    def __len__(self) -> int:
        return len(self.obj)


def interval_min_distance_bound(
    dr0: np.ndarray, dv0: np.ndarray, dr1: np.ndarray, dv1: np.ndarray, h: np.ndarray
) -> np.ndarray:
    """Lower bound on the separation inside grid intervals of length ``h``.

    The relative motion is extrapolated linearly forward from the left sample
    and backward from the right sample, and the exact closest approach of each
    straight line over the interval is taken. The true path departs from those
    lines by at most about ``|dv1 - dv0| * h / 2`` (the change of relative
    velocity across the interval, i.e. the relative acceleration, acting for
    half the step), which is subtracted as a pad. All inputs are ``(..., 3)``
    except ``h`` which broadcasts against ``(...)``.
    """

    def straight_line_min(dr: np.ndarray, dv: np.ndarray, sign: float) -> np.ndarray:
        vv = np.einsum("...k,...k->...", dv, dv)
        gg = np.einsum("...k,...k->...", dr, dv)
        with np.errstate(divide="ignore", invalid="ignore"):
            tau = np.where(vv > 0.0, -sign * gg / vv, 0.0)
        tau = np.clip(tau, 0.0, h)
        return np.linalg.norm(dr + sign * dv * tau[..., None], axis=-1)

    d_fwd = straight_line_min(dr0, dv0, +1.0)
    d_bwd = straight_line_min(dr1, dv1, -1.0)
    pad = np.linalg.norm(dv1 - dv0, axis=-1) * h / 2.0
    return np.maximum(np.minimum(d_fwd, d_bwd) - pad, 0.0)


def find_close_approach_candidates(
    epoch_seconds: np.ndarray,
    dr: np.ndarray,
    dv: np.ndarray,
    valid: np.ndarray,
    threshold_km: float,
) -> Candidates:
    """Find every local minimum of separation that may be within ``threshold_km``.

    ``dr``/``dv`` are relative positions/velocities of shape ``(m, n, 3)`` for
    ``m`` secondaries on a grid of ``n`` times; ``valid`` is ``(m, n)``.
    """
    m, n = valid.shape
    if n == 0 or m == 0:
        empty = np.zeros(0, dtype=int)
        return Candidates(empty, empty, np.zeros(0, dtype=bool))

    g = np.einsum("mnk,mnk->mn", dr, dv)
    dist = np.linalg.norm(dr, axis=-1)
    g = np.where(valid, g, np.nan)
    dist = np.where(valid, dist, np.inf)

    objs: list[np.ndarray] = []
    ks: list[np.ndarray] = []
    brackets: list[np.ndarray] = []

    # 1. Interior minima: range-rate goes from negative to non-negative.
    if n > 1:
        both = valid[:, :-1] & valid[:, 1:]
        with np.errstate(invalid="ignore"):
            sign_change = both & (g[:, :-1] < 0.0) & (g[:, 1:] >= 0.0)
        bo, bk = np.nonzero(sign_change)
        if len(bo):
            h = epoch_seconds[bk + 1] - epoch_seconds[bk]
            bound = interval_min_distance_bound(
                dr[bo, bk], dv[bo, bk], dr[bo, bk + 1], dv[bo, bk + 1], h
            )
            keep = bound <= threshold_km
            objs.append(bo[keep])
            ks.append(bk[keep])
            brackets.append(np.ones(int(keep.sum()), dtype=bool))

    # 2. Edges of each valid span: closest at the edge because the pair is
    #    receding from the start (or still approaching at the end).
    prev_valid = np.zeros_like(valid)
    prev_valid[:, 1:] = valid[:, :-1]
    next_valid = np.zeros_like(valid)
    next_valid[:, :-1] = valid[:, 1:]
    near = dist <= threshold_km
    with np.errstate(invalid="ignore"):
        starts = valid & ~prev_valid & near & (g > 0.0)
        ends = valid & ~next_valid & near & (g < 0.0)
    eo, ek = np.nonzero(starts | ends)
    objs.append(eo)
    ks.append(ek)
    brackets.append(np.zeros(len(eo), dtype=bool))

    obj = np.concatenate(objs)
    k = np.concatenate(ks)
    bracket = np.concatenate(brackets)

    # 3. Degenerate pairs (no sign change anywhere, e.g. range-rate identically
    #    zero for a co-located clone): fall back to the closest sample.
    found = np.zeros(m, dtype=bool)
    found[obj] = True
    min_idx = np.argmin(dist, axis=1)
    min_dist = dist[np.arange(m), min_idx]
    fallback = np.nonzero(~found & (min_dist <= threshold_km))[0]
    if len(fallback):
        obj = np.concatenate([obj, fallback])
        k = np.concatenate([k, min_idx[fallback]])
        bracket = np.concatenate([bracket, np.zeros(len(fallback), dtype=bool)])

    order = np.lexsort((k, obj))
    return Candidates(obj[order], k[order], bracket[order])


class _PropagationFailed(RuntimeError):
    pass


def _range_rate(res: TCAResult) -> float:
    return float(np.dot(res.r_secondary - res.r_primary, res.v_secondary - res.v_primary))


def refine_tca_sgp4(
    sat_primary: Satrec,
    sat_secondary: Satrec,
    t_lo: float,
    t_hi: float,
    *,
    tol_sec: float = 1e-3,
) -> TCAResult | None:
    """Refine one closest approach on exact SGP4 states.

    ``[t_lo, t_hi]`` (UNIX seconds) is a bracket with a range-rate sign change,
    or ``t_lo == t_hi`` for a single-sample candidate. The root of the
    range-rate is found with Brent's method to ``tol_sec``; both objects are
    re-propagated with SGP4 at every trial time. Returns None if SGP4 fails
    at the bracket ends.
    """

    def states(t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        rp, vp, okp = propagate_at(sat_primary, t)
        rs, vs, oks = propagate_at(sat_secondary, t)
        if not (okp[0] and oks[0]):
            raise _PropagationFailed(t)
        return rp[0], vp[0], rs[0], vs[0]

    def range_rate(t: float) -> float:
        rp, vp, rs, vs = states(t)
        return float(np.dot(rs - rp, vs - vp))

    def result(t: float) -> TCAResult:
        rp, vp, rs, vs = states(t)
        return TCAResult(
            tca_seconds=float(t),
            miss_distance_km=float(np.linalg.norm(rs - rp)),
            relative_speed_km_s=float(np.linalg.norm(vs - vp)),
            r_primary=rp, v_primary=vp,
            r_secondary=rs, v_secondary=vs,
        )

    try:
        if t_hi - t_lo <= tol_sec:
            return result(t_lo)
        lo, hi = result(t_lo), result(t_hi)
        if _range_rate(lo) < 0.0 <= _range_rate(hi):
            try:
                t_star = brentq(range_rate, t_lo, t_hi, xtol=tol_sec, maxiter=200)
                return result(t_star)
            except _PropagationFailed:
                pass
        # No sign change on the exact states (the grid sign change was within
        # rounding) or SGP4 failed inside: keep the closer bracket end.
        return lo if lo.miss_distance_km <= hi.miss_distance_km else hi
    except _PropagationFailed:
        return None


def _hermite(
    t: float, times: np.ndarray, r: np.ndarray, v: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Cubic Hermite interpolation of position (and its derivative) on a grid."""
    i = int(np.clip(np.searchsorted(times, t) - 1, 0, len(times) - 2))
    h = times[i + 1] - times[i]
    s = (t - times[i]) / h
    h00, h10 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s
    h01, h11 = -2 * s**3 + 3 * s**2, s**3 - s**2
    pos = h00 * r[i] + h10 * h * v[i] + h01 * r[i + 1] + h11 * h * v[i + 1]
    d00, d10 = (6 * s**2 - 6 * s) / h, 3 * s**2 - 4 * s + 1
    d01, d11 = (-6 * s**2 + 6 * s) / h, 3 * s**2 - 2 * s
    vel = d00 * r[i] + d10 * v[i] + d01 * r[i + 1] + d11 * v[i + 1]
    return pos, vel


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
    """Refine the single closest sampled approach from gridded states alone.

    For callers that only have tabulated states and no propagator. States are
    cubic-Hermite interpolated from positions and velocities. Screening does
    not use this: it finds every minimum with
    :func:`find_close_approach_candidates` and refines each on exact SGP4
    states with :func:`refine_tca_sgp4`.

    All arrays are aligned to ``epoch_seconds`` (shape ``(n,)``); the position and
    velocity arrays have shape ``(n, 3)``.
    """
    n = len(epoch_seconds)

    def interp(t: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        if n == 1:
            return r_primary[0], v_primary[0], r_secondary[0], v_secondary[0]
        rp, vp = _hermite(t, epoch_seconds, r_primary, v_primary)
        rs, vs = _hermite(t, epoch_seconds, r_secondary, v_secondary)
        return rp, vp, rs, vs

    def g(t: float) -> float:
        rp, vp, rs, vs = interp(t)
        return float(np.dot(rs - rp, vs - vp))

    dist = np.linalg.norm(r_secondary - r_primary, axis=1)
    k = int(np.argmin(dist))
    t_star = float(epoch_seconds[k])
    # The minimum lies on whichever side of the closest sample the range-rate
    # changes sign.
    for lo, hi in ((k - 1, k), (k, k + 1)):
        if lo < 0 or hi >= n:
            continue
        a, b = float(epoch_seconds[lo]), float(epoch_seconds[hi])
        ga, gb = g(a), g(b)
        if ga < 0.0 <= gb:
            t_star = brentq(g, a, b, xtol=tol_sec, maxiter=max_iter)
            break

    rp, vp, rs, vs = interp(t_star)
    return TCAResult(
        tca_seconds=float(t_star),
        miss_distance_km=float(np.linalg.norm(rs - rp)),
        relative_speed_km_s=float(np.linalg.norm(vs - vp)),
        r_primary=rp, v_primary=vp,
        r_secondary=rs, v_secondary=vs,
    )
