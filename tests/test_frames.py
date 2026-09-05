import numpy as np

from sdebris.screening.frames import ric_basis, ric_components


def test_ric_basis_is_orthonormal() -> None:
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])
    basis = ric_basis(r, v)
    assert np.allclose(basis @ basis.T, np.eye(3), atol=1e-12)


def test_ric_components_known_geometry() -> None:
    # Primary at +x moving +y: R-hat=+x, I-hat=+y, C-hat=+z.
    r_p = np.array([7000.0, 0.0, 0.0])
    v_p = np.array([0.0, 7.5, 0.0])
    # Secondary 1 km further out radially, 2 km ahead in-track, 3 km cross-track.
    r_s = np.array([7001.0, 2.0, 3.0])
    radial, along, cross = ric_components(r_p, v_p, r_s)
    assert np.isclose(radial, 1.0, atol=1e-9)
    assert np.isclose(along, 2.0, atol=1e-9)
    assert np.isclose(cross, 3.0, atol=1e-9)
