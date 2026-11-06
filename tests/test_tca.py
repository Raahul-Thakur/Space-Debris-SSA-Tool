import numpy as np

from sdebris.screening.tca import (
    find_close_approach_candidates,
    interval_min_distance_bound,
    refine_tca,
)


def test_refine_tca_finds_crossing_between_grid_points() -> None:
    # Two objects on perpendicular straight-line paths, closest near t=90s but the
    # 60s grid only samples t=0,60,120,180.
    t = np.array([0.0, 60.0, 120.0, 180.0])
    # Primary moves +x through origin region; secondary moves +y.
    rp = np.array([[-90.0, 0.0, 0.0], [-30.0, 0.0, 0.0], [30.0, 0.0, 0.0], [90.0, 0.0, 0.0]])
    vp = np.tile([1.0, 0.0, 0.0], (4, 1))
    rs = np.array([[0.0, -90.0, 0.0], [0.0, -30.0, 0.0], [0.0, 30.0, 0.0], [0.0, 90.0, 0.0]])
    vs = np.tile([0.0, 1.0, 0.0], (4, 1))

    res = refine_tca(t, rp, vp, rs, vs)
    # Closest approach is where both are nearest the origin: t = 90s.
    assert abs(res.tca_seconds - 90.0) < 1.0
    # At t=90s primary=(0,0,0), secondary=(0,0,0) under linear interp -> ~0 miss.
    assert res.miss_distance_km < 1.0
    assert res.relative_speed_km_s > 1.0


def _head_on(miss_km: float, speed_km_s: float = 15.0, step: float = 60.0):
    """Straight-line relative motion, closest at t = 90 s (midway between samples)."""
    t = np.arange(0.0, 240.0, step)
    dv = np.tile([speed_km_s, 0.0, 0.0], (len(t), 1))
    dr = np.column_stack([speed_km_s * (t - 90.0), np.full(len(t), miss_km), np.zeros(len(t))])
    return t, dr[None], dv[None], np.ones((1, len(t)), dtype=bool)


def test_candidates_keep_a_pass_whose_samples_are_far_apart() -> None:
    # Samples either side are ~450 km away; the pass itself is 0.5 km.
    t, dr, dv, valid = _head_on(0.5)
    assert np.linalg.norm(dr[0], axis=1).min() > 400
    cands = find_close_approach_candidates(t, dr, dv, valid, threshold_km=50.0)
    assert list(cands.obj) == [0]
    assert list(cands.k) == [1]          # the bracket [60 s, 120 s]
    assert list(cands.bracket) == [True]


def test_candidates_drop_a_pass_outside_the_threshold() -> None:
    t, dr, dv, valid = _head_on(80.0)
    cands = find_close_approach_candidates(t, dr, dv, valid, threshold_km=50.0)
    assert len(cands) == 0


def test_interval_bound_is_exact_for_straight_lines() -> None:
    _, dr, dv, _ = _head_on(0.5)
    bound = interval_min_distance_bound(dr[0, 1], dv[0, 1], dr[0, 2], dv[0, 2], 60.0)
    assert abs(float(bound) - 0.5) < 1e-9
