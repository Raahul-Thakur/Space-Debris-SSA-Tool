import math

import numpy as np
import pytest
from scipy import integrate

from sdebris.risk.pc import _chan_series, clamp_probability, probability_of_collision


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


# --- Robustness and reference checks -------------------------------------


def _brute_force_pc(miss_2d: np.ndarray, cov_2d: np.ndarray, radius: float) -> float:
    """Integrate the 2D Gaussian (mean ``miss_2d``) over the hard-body disk.

    Plain double integration in polar coordinates over the disk centred on the
    origin, independent of Chan's series and of the principal-axis rotation.
    """
    inv = np.linalg.inv(cov_2d)
    norm = 1.0 / (2.0 * math.pi * math.sqrt(np.linalg.det(cov_2d)))

    def density(rho: float, theta: float) -> float:
        d = np.array([rho * math.cos(theta), rho * math.sin(theta)]) - miss_2d
        return rho * norm * math.exp(-0.5 * d @ inv @ d)

    value, _ = integrate.dblquad(
        density, 0.0, 2.0 * math.pi, 0.0, radius, epsabs=1e-14, epsrel=1e-10
    )
    return value


def test_pc_matches_brute_force_for_isotropic_covariance() -> None:
    # Relative velocity along +y, so the encounter plane is x-z.
    v_rel = np.array([0.0, 7500.0, 0.0])
    r_rel = np.array([60.0, 0.0, 25.0])
    cov = _cov(40.0)
    ref = _brute_force_pc(np.array([60.0, 25.0]), np.diag([1600.0, 1600.0]), 20.0)
    # Both the disk integral and Chan's series (exact for a circular
    # covariance) agree with the reference to 1e-6 relative.
    assert probability_of_collision(r_rel, v_rel, cov, 20.0) == pytest.approx(ref, rel=1e-6)
    chan = probability_of_collision(r_rel, v_rel, cov, 20.0, method="chan")
    assert chan == pytest.approx(ref, rel=1e-6)


def test_pc_matches_brute_force_for_anisotropic_covariance() -> None:
    v_rel = np.array([0.0, 7500.0, 0.0])
    # sigma 60 m along x and 25 m along z in the encounter plane (aspect 2.4),
    # and a long, thin one (1000 m x 70 m) probed out to 4 sigma.
    cases = [
        (60.0, 25.0, 80.0, -30.0),
        (1000.0, 70.0, 0.0, 280.0),
        (1000.0, 70.0, 3000.0, 0.0),
    ]
    for sx, sz, mx, mz in cases:
        cov = np.diag([sx**2, 500.0**2, sz**2])
        pc = probability_of_collision(np.array([mx, 0.0, mz]), v_rel, cov, 20.0)
        ref = _brute_force_pc(np.array([mx, mz]), np.diag([sx**2, sz**2]), 20.0)
        # Exact integration: agrees with the 2D reference to 1e-6 relative.
        assert pc == pytest.approx(ref, rel=1e-6)


def test_chan_series_anisotropic_error_is_as_documented() -> None:
    # Chan's equal-area series with the hard body large next to the minor
    # sigma (20 m vs 10 m): the methodology states errors of tens of per cent
    # there (this case is ~60% high). Within 3 sigma of a 1000 m x 70 m
    # covariance it is within 10%.
    v_rel = np.array([0.0, 7500.0, 0.0])
    cov = np.diag([40.0**2, 500.0**2, 10.0**2])
    chan = probability_of_collision(np.array([80.0, 0.0, 0.0]), v_rel, cov, 20.0, method="chan")
    ref = _brute_force_pc(np.array([80.0, 0.0]), np.diag([40.0**2, 10.0**2]), 20.0)
    assert 0.3 < (chan - ref) / ref < 1.0
    cov = np.diag([1000.0**2, 500.0**2, 70.0**2])
    for mx, mz in ((0.0, 0.0), (0.0, 210.0), (3000.0, 0.0), (1000.0, 70.0)):
        chan = probability_of_collision(np.array([mx, 0.0, mz]), v_rel, cov, 20.0, method="chan")
        ref = _brute_force_pc(np.array([mx, mz]), np.diag([1000.0**2, 70.0**2]), 20.0)
        assert chan == pytest.approx(ref, rel=0.10)


def test_chan_series_survives_extreme_arguments() -> None:
    # v/2 huge: the old fixed 40-term loop overflowed v**m and returned NaN.
    assert _chan_series(800.0, 6.25e8) == 0.0
    # u/2 and v/2 both large (hard body >> sigma, miss inside it): 40 terms
    # truncated a near-certain hit to ~0.06.
    assert _chan_series(400.0, 100.0) == pytest.approx(1.0, abs=1e-9)
    # Small arguments agree with the closed form for a centred hit (v = 0):
    # Pc = 1 - exp(-u/2).
    assert _chan_series(0.04, 0.0) == pytest.approx(1.0 - math.exp(-0.02), rel=1e-12)


def test_pc_large_miss_tiny_sigma_is_zero_not_nan() -> None:
    # 25 km miss with 1 m sigma: the series overflowed and returned NaN, which
    # the screening clamp then turned into Pc = 1 (critical).
    r_rel = np.array([25_000.0, 0.0, 0.0])
    v_rel = np.array([0.0, 7500.0, 0.0])
    for method in ("foster", "chan"):
        assert probability_of_collision(r_rel, v_rel, _cov(1.0), 20.0, method=method) == 0.0


def test_pc_small_sigma_inside_hard_body_is_one() -> None:
    # 10 m miss, 1 m sigma, 20 m hard body: virtually certain collision. A
    # fixed 40-term series truncated this to ~0.
    r_rel = np.array([10.0, 0.0, 0.0])
    v_rel = np.array([0.0, 7500.0, 0.0])
    pc = probability_of_collision(r_rel, v_rel, _cov(1.0), 20.0)
    assert pc == pytest.approx(1.0, abs=1e-9)


def test_pc_zero_covariance_is_a_point_mass() -> None:
    v_rel = np.array([0.0, 7500.0, 0.0])
    zero = np.zeros((3, 3))
    assert probability_of_collision(np.array([25_000.0, 0.0, 0.0]), v_rel, zero, 20.0) == 0.0
    assert probability_of_collision(np.array([5.0, 0.0, 3.0]), v_rel, zero, 20.0) == 1.0


def test_pc_line_covariance_is_exact() -> None:
    # No extent across one in-plane axis: Pc reduces to the 1D Gaussian mass
    # over the disk's chord, Phi(-0.1) - Phi(-0.5) for a 30 m miss, sigma 100
    # m, 20 m hard body. Chan's series (floored sigma) gave ~1.0 here.
    v_rel = np.array([0.0, 7500.0, 0.0])
    cov = np.diag([100.0**2, 0.0, 0.0])
    pc = probability_of_collision(np.array([30.0, 0.0, 0.0]), v_rel, cov, 20.0)
    expected = 0.5 * (math.erfc(0.1 / math.sqrt(2)) - math.erfc(0.5 / math.sqrt(2)))
    assert pc == pytest.approx(expected, rel=1e-4)


def test_clamp_probability_is_nan_safe() -> None:
    assert clamp_probability(float("nan")) == 0.0
    assert clamp_probability(float("inf")) == 1.0
    assert clamp_probability(-0.0) == 0.0
    assert clamp_probability(1.5) == 1.0
    assert clamp_probability(0.25) == 0.25
