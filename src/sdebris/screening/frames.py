"""RIC / RAC reference-frame utilities.

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
