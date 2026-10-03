"""Reference-frame utilities: RIC / RAC decomposition and TEME to geodetic.

The RIC frame (Radial, In-track, Cross-track — also called RTN or RSW) is built
from a primary object's position and velocity:

    R-hat = r / |r|                         (radial, away from Earth)
    C-hat = (r x v) / |r x v|               (cross-track, along orbit normal)
    I-hat = C-hat x R-hat                   (in-track / along-track)

Decomposing the relative position of a secondary object into this frame gives the
"RAC" (radial / along-track / cross-track) components used throughout SSA work.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ric_basis(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Return a 3x3 matrix whose rows are the R, I, C unit vectors.

    Multiplying this matrix by an ECI vector projects it into the RIC frame.
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    r_hat = r / np.linalg.norm(r)
    h = np.cross(r, v)
    c_hat = h / np.linalg.norm(h)
    i_hat = np.cross(c_hat, r_hat)
    return np.vstack([r_hat, i_hat, c_hat])


def ric_components(
    r_primary: np.ndarray,
    v_primary: np.ndarray,
    r_secondary: np.ndarray,
) -> tuple[float, float, float]:
    """Project (secondary - primary) into the primary's RIC frame.

    Returns ``(radial_km, along_track_km, cross_track_km)``.
    """
    basis = ric_basis(r_primary, v_primary)
    dr = np.asarray(r_secondary, dtype=float) - np.asarray(r_primary, dtype=float)
    radial, along, cross = basis @ dr
    return float(radial), float(along), float(cross)


def teme_to_geodetic(positions: np.ndarray, times: pd.DatetimeIndex) -> pd.DataFrame:
    """Convert TEME ECI positions (km) to geodetic lat/lon/alt via astropy.

    Returns a DataFrame with columns ``lat_deg``, ``lon_deg``, ``alt_km``.
    """
    import astropy.units as u
    from astropy.coordinates import ITRS, TEME, CartesianRepresentation
    from astropy.time import Time

    t = Time(times.to_pydatetime())
    cart = CartesianRepresentation(
        positions[:, 0] * u.km, positions[:, 1] * u.km, positions[:, 2] * u.km
    )
    teme = TEME(cart, obstime=t)
    itrs = teme.transform_to(ITRS(obstime=t))
    loc = itrs.earth_location.geodetic
    return pd.DataFrame(
        {
            "lat_deg": np.asarray(loc.lat.deg, dtype=float),
            "lon_deg": np.asarray(loc.lon.deg, dtype=float),
            "alt_km": np.asarray(loc.height.to(u.km).value, dtype=float),
        }
    )
