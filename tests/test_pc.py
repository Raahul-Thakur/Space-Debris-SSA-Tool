import numpy as np

from sdebris.risk.pc import probability_of_collision


def _cov(sig_m: float) -> np.ndarray:
    return np.diag([sig_m**2, sig_m**2, sig_m**2])


def test_pc_in_unit_interval() -> None:
    r_rel = np.array([100.0, 0.0, 0.0])  # 100 m miss
    v_rel = np.array([0.0, 7500.0, 0.0])
    pc = probability_of_collision(r_rel, v_rel, _cov(50.0), hard_body_radius_m=20.0)
    assert 0.0 <= pc <= 1.0


def test_pc_decreases_with_miss_distance() -> None:
    v_rel = np.array([0.0, 7500.0, 0.0])
    cov = _cov(50.0)
    near = probability_of_collision(np.array([30.0, 0.0, 0.0]), v_rel, cov, 20.0)
    far = probability_of_collision(np.array([2000.0, 0.0, 0.0]), v_rel, cov, 20.0)
    assert near > far
    assert far < 1e-6


def test_pc_grows_with_hard_body_radius() -> None:
    r_rel = np.array([100.0, 0.0, 0.0])
    v_rel = np.array([0.0, 7500.0, 0.0])
    cov = _cov(50.0)
    small = probability_of_collision(r_rel, v_rel, cov, 5.0)
    large = probability_of_collision(r_rel, v_rel, cov, 50.0)
    assert large > small
