"""The plain-English layer proposes; the allowlist still decides."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sdebris.commands.parser import parse_command
from sdebris.nl import narrate_event, resolve_object, suggest_from_rules

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


# ------------------------------------------------------------------ resolution
@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("close approaches for the ISS this week", "25544"),
        ("is hubble in danger tomorrow", "20580"),
        ("watch landsat 8", "39084"),
        ("track norad 43013", "43013"),
        ("is sentinel 2a safe", "40697"),
        ("refresh the orbit for envisat", "27386"),
    ],
)
def test_objects_resolve_from_names_and_ids(phrase: str, expected: str) -> None:
    resolved = resolve_object(phrase)
    assert resolved is not None
    assert resolved[0] == expected


def test_a_name_containing_digits_is_not_read_as_an_id() -> None:
    """"landsat 8" must not resolve to catalogue number 8."""
    assert resolve_object("watch landsat 8")[0] == "39084"


def test_a_distance_is_not_read_as_an_id() -> None:
    assert resolve_object("anything within 10 km of 25544")[0] == "25544"


def test_a_duration_is_not_read_as_an_id() -> None:
    assert resolve_object("screen 25544 over the next 3 days")[0] == "25544"


def test_a_year_is_not_read_as_an_id() -> None:
    assert resolve_object("conjunctions during 2026") is None


def test_an_unknown_phrase_resolves_to_nothing() -> None:
    assert resolve_object("make me a sandwich") is None


# ----------------------------------------------------------------- translation
@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("close approaches for the ISS this week", "screen 25544 --window 168h"),
        ("is hubble in danger tomorrow", "screen 20580 --window 48h"),
        ("watch landsat 8", "monitor add 39084"),
        ("show me critical events", "events list --tier critical"),
        (
            "anything within 10 km of 25544 in the next 3 days",
            "screen 25544 --window 72h --threshold 10km",
        ),
        ("refresh the orbit for envisat", "orbit refresh 27386"),
        ("get me started", "monitor seed-known"),
        ("how close does noaa 19 get today", "screen 33591 --window 24h"),
    ],
)
def test_phrases_translate_to_the_expected_command(phrase: str, expected: str) -> None:
    assert suggest_from_rules(phrase).command == expected


def test_every_suggestion_survives_the_real_parser() -> None:
    """Nothing may be proposed that the allowlist would refuse."""
    phrases = [
        "close approaches for the ISS this week",
        "is hubble in danger tomorrow",
        "watch landsat 8",
        "show me critical events",
        "anything within 10 km of 25544 in the next 3 days",
        "refresh the orbit for envisat",
        "screen 25544 for 2 weeks",
        "conjunctions for satellite id 27386 within 5km",
    ]
    for phrase in phrases:
        suggestion = suggest_from_rules(phrase)
        assert suggestion.command is not None, phrase
        # Raises if the grammar would not accept it.
        parse_command(suggestion.command)


def test_a_window_beyond_the_parser_maximum_is_clamped() -> None:
    suggestion = suggest_from_rules("screen the ISS for the next 90 days")
    assert suggestion.command == "screen 25544 --window 168h"
    parse_command(suggestion.command)


def test_nonsense_is_declined_rather_than_guessed_at() -> None:
    suggestion = suggest_from_rules("make me a sandwich")
    assert suggestion.command is None
    assert not suggestion.understood
    assert "could not tell" in suggestion.rationale.lower()


def test_an_empty_request_is_declined() -> None:
    assert suggest_from_rules("   ").command is None


def test_explanations_are_redirected_rather_than_translated() -> None:
    """`event explain` needs an id the operator has to pick, not invent."""
    suggestion = suggest_from_rules("explain this event to me")
    assert suggestion.command is None
    assert "inspector" in suggestion.rationale.lower()


def test_the_rationale_names_how_the_object_was_matched() -> None:
    suggestion = suggest_from_rules("close approaches for the ISS this week")
    assert "25544" in suggestion.rationale
    assert "168h" in suggestion.rationale


# ------------------------------------------------------------------- narration
def _explanation(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "primary": {"name": "ISS (ZARYA)", "norad_id": "25544"},
        "secondary": {"name": "IRIDIUM 33 DEB", "norad_id": "99999"},
        "tca": (NOW + timedelta(hours=14)).isoformat(),
        "miss_distance_km": 0.412,
        "relative_speed_km_s": 13.7,
        "tier": "critical",
        "probability_of_collision": 2.4e-4,
        "explanation": "CRITICAL: miss 0.41 km <= 1 km",
        "model_version": "foster-chan-v1",
    }
    base.update(overrides)
    return base


def test_the_narration_states_the_geometry_and_the_timing() -> None:
    lines = narrate_event(_explanation(), now=NOW)
    joined = " ".join(lines)
    assert "0.412 km" in joined
    assert "14.0 hours" in joined
    assert "13.70 km/s" in joined


def test_the_narration_always_carries_the_covariance_caveat() -> None:
    """The model's biggest limitation must never be omitted."""
    lines = narrate_event(_explanation(), now=NOW)
    assert any("synthetic" in line for line in lines)
    assert any("not as grounds for a manoeuvre" in line for line in lines)


def test_a_stale_element_set_is_called_out() -> None:
    lines = narrate_event(
        _explanation(), tle_epoch=NOW - timedelta(days=9), now=NOW
    )
    assert any("9.0 days" in line and "drifted" in line for line in lines)


def test_a_fresh_element_set_is_described_as_usable() -> None:
    lines = narrate_event(
        _explanation(), tle_epoch=NOW - timedelta(hours=8), now=NOW
    )
    assert any("recent enough" in line for line in lines)


def test_a_zero_probability_is_explained_rather_than_dismissed() -> None:
    lines = narrate_event(_explanation(probability_of_collision=0.0), now=NOW)
    assert any("not that a collision is impossible" in line for line in lines)


def test_missing_numbers_are_omitted_not_invented() -> None:
    sparse = {"primary": {"name": "ISS"}, "secondary": {"name": "DEB"}, "tier": "unassessed"}
    lines = narrate_event(sparse, now=NOW)
    joined = " ".join(lines)
    assert "km/s" not in joined
    assert "probability of collision is" not in joined
    # The caveat survives even when everything else is missing.
    assert any("synthetic" in line for line in lines)


def test_the_tier_reason_is_quoted_verbatim() -> None:
    lines = narrate_event(_explanation(), now=NOW)
    assert any("CRITICAL: miss 0.41 km <= 1 km" in line for line in lines)


def test_a_past_encounter_is_described_in_the_past() -> None:
    lines = narrate_event(
        _explanation(tca=(NOW - timedelta(hours=5)).isoformat()), now=NOW
    )
    assert any("already happened" in line for line in lines)
