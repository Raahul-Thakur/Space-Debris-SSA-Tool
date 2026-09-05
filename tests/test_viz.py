
from sdebris.models import SpaceObject
from sdebris.propagation import make_time_grid, propagate_objects
from sdebris.viz import build_groundtrack, build_orbit_3d, teme_to_geodetic

ISS_L1 = "1 25544U 98067A   24001.00000000  .00016717  00000+0  10270-3 0  9003"
ISS_L2 = "2 25544  51.6421  10.3493 0006703  88.3949  31.2568 15.50015354  9008"


def _eph():
    obj = SpaceObject("25544", "ISS", ISS_L1, ISS_L2)
    times = make_time_grid(start="2024-01-01T00:00:00Z", window_hours=1.5, step_sec=60)
    return propagate_objects([obj], times)


def test_build_orbit_3d_has_earth_and_orbit() -> None:
    eph = _eph()
    fig = build_orbit_3d(eph, "25544")
    # Earth surface + one orbit trace.
    assert len(fig.data) == 2


def test_teme_to_geodetic_bounds() -> None:
    eph = _eph()
    geo = teme_to_geodetic(eph.positions[0], eph.times)
    assert geo["lat_deg"].between(-90, 90).all()
    assert geo["lon_deg"].between(-180, 180).all()
    # ISS altitude is roughly 400-430 km.
    assert geo["alt_km"].between(350, 500).all()
    fig = build_groundtrack({"25544 ISS": geo}, "25544")
    assert len(fig.data) == 1
