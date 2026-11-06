from datetime import datetime, timedelta, timezone

from sdebris.config import load_config
from sdebris.models import SpaceObject
from sdebris.screening.screen import screen_target

ISS_L1 = "1 25544U 98067A   24001.00000000  .00016717  00000+0  10270-3 0  9003"
ISS_L2 = "2 25544  51.6421  10.3493 0006703  88.3949  31.2568 15.50015354  9008"
# A far-away, different orbit (Hubble) that should NOT conjunct with the ISS.
HST_L1 = "1 20580U 90037B   24001.00000000  .00000806  00000+0  35060-4 0  9004"
HST_L2 = "2 20580  28.4691  90.3225 0002946  74.7832 285.3088 15.09271153  9005"

START = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)  # near the TLE epoch


def _config():
    cfg = load_config()
    cfg.propagation.window_hours = 2
    cfg.propagation.step_sec = 30
    return cfg


def test_screen_flags_co_orbital_clone_as_critical() -> None:
    target = SpaceObject("25544", "ISS", ISS_L1, ISS_L2)
    # Same orbit, different NORAD id -> separation ~0 -> critical event.
    clone = SpaceObject("99999", "ISS-CLONE", ISS_L1.replace("25544", "99999"),
                        ISS_L2.replace("25544", "99999"))
    result = screen_target(target, [clone, SpaceObject("20580", "HST", HST_L1, HST_L2)],
                           _config(), start=START)
    by_norad = {e.secondary_norad: e for e in result.events}
    assert "99999" in by_norad
    assert by_norad["99999"].miss_distance_km < 1.0
    assert by_norad["99999"].risk_tier == "critical"
    assert result.n_screened == 2


def test_screen_excludes_self() -> None:
    target = SpaceObject("25544", "ISS", ISS_L1, ISS_L2)
    result = screen_target(target, [target], _config(), start=START)
    assert result.n_screened == 0
    assert result.events == []


def test_tca_falls_inside_the_screening_window() -> None:
    """The time of closest approach is a real date inside the window.

    pandas 3 builds a microsecond-resolution grid where pandas 2 built a
    nanosecond one, and a conversion that assumed nanoseconds put every TCA
    in January 1970 while leaving miss distances correct. Nothing here
    checked the date, so it shipped.
    """
    target = SpaceObject("25544", "ISS", ISS_L1, ISS_L2)
    clone = SpaceObject("99999", "ISS-CLONE", ISS_L1.replace("25544", "99999"),
                        ISS_L2.replace("25544", "99999"))
    cfg = _config()
    result = screen_target(target, [clone], cfg, start=START)
    assert result.events
    end = START + timedelta(hours=cfg.propagation.window_hours)
    for event in result.events:
        tca = event.tca
        assert START <= tca <= end, f"TCA {tca} is outside {START} .. {end}"
