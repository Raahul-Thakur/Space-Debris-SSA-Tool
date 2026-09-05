import numpy as np

from sdebris.models import SpaceObject
from sdebris.propagation import make_time_grid, propagate_objects

ISS_L1 = "1 25544U 98067A   24001.00000000  .00016717  00000+0  10270-3 0  9003"
ISS_L2 = "2 25544  51.6421  10.3493 0006703  88.3949  31.2568 15.50015354  9008"


def test_time_grid_spacing() -> None:
    grid = make_time_grid(start="2024-01-01T00:00:00Z", window_hours=1, step_sec=60)
    assert len(grid) == 61
    assert (grid[1] - grid[0]).total_seconds() == 60


def test_propagate_iss_is_in_leo() -> None:
    obj = SpaceObject("25544", "ISS", ISS_L1, ISS_L2)
    times = make_time_grid(start="2024-01-01T00:00:00Z", window_hours=1, step_sec=60)
    eph = propagate_objects([obj], times)
    assert eph.valid.all()
    radius = np.linalg.norm(eph.positions[0], axis=1)
    # ISS orbital radius ~6780 km (Earth radius + ~400 km altitude).
    assert np.all((radius > 6600) & (radius < 6900))
    speed = np.linalg.norm(eph.velocities[0], axis=1)
    assert np.all((speed > 7.0) & (speed < 8.5))  # ~7.66 km/s
