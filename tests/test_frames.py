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


def test_teme_to_geodetic_stays_within_physical_bounds() -> None:
    """A 7000 km geocentric radius must land on Earth at a sane altitude."""
    import pandas as pd

    from sdebris.screening.frames import teme_to_geodetic

    positions = np.array([[7000.0, 0.0, 0.0], [0.0, 7000.0, 0.0], [0.0, 0.0, 7000.0]])
    times = pd.to_datetime(
        ["2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z", "2026-01-01T01:00:00Z"]
    )

    frame = teme_to_geodetic(positions, times)

    assert list(frame.columns) == ["lat_deg", "lon_deg", "alt_km"]
    assert len(frame) == 3
    assert frame["lat_deg"].between(-90, 90).all()
    assert frame["lon_deg"].between(-180, 180).all()
    # A 7000 km geocentric radius sits a few hundred kilometres up.
    assert frame["alt_km"].between(500, 700).all()
