from sdebris.monitoring import WELL_KNOWN_NORAD_IDS


def test_well_known_catalog_has_twenty_unique_objects() -> None:
    assert len(WELL_KNOWN_NORAD_IDS) == 20
    assert len(set(WELL_KNOWN_NORAD_IDS)) == 20
    assert all(norad_id.isdigit() for norad_id in WELL_KNOWN_NORAD_IDS)
