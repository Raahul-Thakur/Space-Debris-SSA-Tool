from datetime import datetime, timezone

from sdebris.models import SpaceObject, parse_tle_epoch, parse_tle_text

ISS_L1 = "1 25544U 98067A   24001.50000000  .00016717  00000+0  10270-3 0  9003"
ISS_L2 = "2 25544  51.6421  10.3493 0006703  88.3949  31.2568 15.50015354  9008"


def test_parse_tle_epoch() -> None:
    epoch = parse_tle_epoch(ISS_L1)
    assert epoch.year == 2024
    # Day 1.5 of the year -> Jan 1 12:00 UTC.
    assert epoch == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_age_and_staleness() -> None:
    obj = SpaceObject("25544", "ISS", ISS_L1, ISS_L2)
    ref = datetime(2024, 1, 11, 12, 0, tzinfo=timezone.utc)  # 10 days later
    assert abs(obj.age_days(ref) - 10.0) < 1e-6
    assert obj.is_stale(5.0, ref)
    assert not obj.is_stale(15.0, ref)


def test_parse_tle_text_3line_and_2line() -> None:
    text = f"ISS (ZARYA)\n{ISS_L1}\n{ISS_L2}\n{ISS_L1}\n{ISS_L2}\n"
    objects = parse_tle_text(text)
    assert len(objects) == 2
    assert objects[0].name == "ISS (ZARYA)"
    assert objects[0].norad_id == "25544"
    assert objects[1].name == "OBJECT-25544"  # no name line on the 2nd record
