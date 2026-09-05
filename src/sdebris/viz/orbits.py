"""Plotly figure builders for the web interface.

Kept in the package (not the app) so the plotting logic is importable and unit
testable. All functions return Plotly ``Figure`` objects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from sdebris.propagation.sgp4_prop import Ephemeris

EARTH_RADIUS_KM = 6371.0
TIER_COLORS = {"critical": "#e1483f", "watch": "#d8a200", "nominal": "#4a9c2d"}


def _earth_sphere(resolution: int = 40) -> go.Surface:
    u = np.linspace(0, 2 * np.pi, resolution)
    v = np.linspace(0, np.pi, resolution)
    x = EARTH_RADIUS_KM * np.outer(np.cos(u), np.sin(v))
    y = EARTH_RADIUS_KM * np.outer(np.sin(u), np.sin(v))
    z = EARTH_RADIUS_KM * np.outer(np.ones_like(u), np.cos(v))
    return go.Surface(
        x=x, y=y, z=z, showscale=False, opacity=0.55,
        colorscale=[[0, "#0b3d6b"], [1, "#1769aa"]], hoverinfo="skip", name="Earth",
    )


def build_orbit_3d(
    eph: Ephemeris,
    target_norad: str,
    tier_by_norad: dict[str, str] | None = None,
    tca_points: list[dict] | None = None,
) -> go.Figure:
    """3D ECI orbit view: Earth sphere, orbit tracks, and TCA markers."""
    tier_by_norad = tier_by_norad or {}
    fig = go.Figure()
    fig.add_trace(_earth_sphere())

    for i, norad in enumerate(eph.norad_ids):
        pos = eph.positions[i]
        valid = eph.valid[i]
        if not valid.any():
            continue
        if norad == target_norad:
            color, width, name = "#ffffff", 5, f"TARGET {eph.names[i]}"
        else:
            color = TIER_COLORS.get(tier_by_norad.get(norad, "nominal"), "#7a7a7a")
            width, name = 2, f"{eph.names[i]} ({norad})"
        fig.add_trace(
            go.Scatter3d(
                x=pos[valid, 0], y=pos[valid, 1], z=pos[valid, 2],
                mode="lines", line=dict(color=color, width=width),
                name=name, hovertemplate=f"{name}<extra></extra>",
            )
        )

    for point in tca_points or []:
        fig.add_trace(
            go.Scatter3d(
                x=[point["x"]], y=[point["y"]], z=[point["z"]],
                mode="markers",
                marker=dict(size=6, color=TIER_COLORS.get(point.get("tier", "watch"), "#d8a200"),
                            symbol="diamond", line=dict(color="white", width=1)),
                name=f"TCA {point.get('label', '')}",
                hovertemplate=f"Closest approach<br>{point.get('label', '')}<extra></extra>",
            )
        )

    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X (km)", showbackground=False),
            yaxis=dict(title="Y (km)", showbackground=False),
            zaxis=dict(title="Z (km)", showbackground=False),
            aspectmode="data",
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        showlegend=False,
        title="ECI orbit tracks (TEME)",
        template="plotly_dark",
    )
    return fig


def teme_to_geodetic(positions: np.ndarray, times: pd.DatetimeIndex) -> pd.DataFrame:
    """Convert TEME ECI positions (km) to geodetic lat/lon/alt via astropy.

    Returns a DataFrame with columns ``lat_deg``, ``lon_deg``, ``alt_km``.
    """
    import astropy.units as u
    from astropy.coordinates import ITRS, TEME, CartesianRepresentation
    from astropy.time import Time

    t = Time(times.to_pydatetime())
    cart = CartesianRepresentation(positions[:, 0] * u.km, positions[:, 1] * u.km, positions[:, 2] * u.km)
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


def build_groundtrack(tracks: dict[str, pd.DataFrame], target_norad: str) -> go.Figure:
    """Ground-track map. ``tracks`` maps a label -> geodetic DataFrame."""
    fig = go.Figure()
    for label, df in tracks.items():
        is_target = label.startswith(target_norad)
        fig.add_trace(
            go.Scattergeo(
                lon=df["lon_deg"], lat=df["lat_deg"], mode="lines",
                line=dict(width=3 if is_target else 1,
                          color="#ffffff" if is_target else "#e1483f"),
                name=label, opacity=0.9 if is_target else 0.5,
            )
        )
    fig.update_layout(
        geo=dict(projection_type="natural earth", showland=True,
                 landcolor="#16263b", oceancolor="#0b1726", showocean=True,
                 bgcolor="rgba(0,0,0,0)", coastlinecolor="#33597f"),
        margin=dict(l=0, r=0, t=30, b=0), title="Ground tracks", template="plotly_dark",
    )
    return fig
