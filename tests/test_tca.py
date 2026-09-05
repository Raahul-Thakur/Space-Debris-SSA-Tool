import numpy as np

from sdebris.screening.tca import refine_tca


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
