from datetime import datetime, timezone

from sdebris.alerts import AlertDispatcher, format_digest
from sdebris.config import load_config
from sdebris.risk.classify import RiskTier, classify_event
from sdebris.screening.screen import ConjunctionEvent, ScreeningResult


def _event(tier_miss: float, pc: float, sec="99999") -> ConjunctionEvent:
    return ConjunctionEvent(
        target_norad="25544", target_name="ISS",
        secondary_norad=sec, secondary_name="DEB",
        tca=datetime(2026, 1, 1, tzinfo=timezone.utc),
        miss_distance_km=tier_miss, relative_speed_km_s=10.0,
        radial_km=0.1, along_track_km=0.2, cross_track_km=0.05,
        probability_of_collision=pc, risk_tier="critical", risk_reason="x",
        target_tle_age_days=1.0, secondary_tle_age_days=2.0, secondary_stale=False,
    )


def test_classify_tiers() -> None:
    cfg = load_config().risk
    assert classify_event(0.5, 0.0, cfg)[0] is RiskTier.CRITICAL          # miss trigger
    assert classify_event(100.0, 1e-3, cfg)[0] is RiskTier.CRITICAL       # Pc trigger
    assert classify_event(3.0, 0.0, cfg)[0] is RiskTier.WATCH
    assert classify_event(50.0, 0.0, cfg)[0] is RiskTier.NOMINAL


def _result(events) -> ScreeningResult:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ScreeningResult(
        target_norad="25544", target_name="ISS", generated_at=now, window_start=now,
        window_hours=72, step_sec=60, report_threshold_km=25, n_screened=10, n_stale=0,
        events=events,
    )


def test_format_digest_lists_events() -> None:
    text = format_digest(_result([_event(0.5, 1e-3)]))
    assert "CRITICAL" in text and "DEB" in text


def test_alert_cooldown(tmp_path) -> None:
    cfg = load_config()
    cfg.reports.output_dir = str(tmp_path)  # unused here but keeps paths local
    dispatcher = AlertDispatcher(cfg)
    dispatcher.state_path = tmp_path / "alert_state.json"
    dispatcher._state = {}
    result = _result([_event(0.5, 1e-3)])

    first = dispatcher.dispatch(result)        # alerts disabled, but records state
    assert len(first) == 1
    second = dispatcher.dispatch(result)       # within cooldown -> suppressed
    assert second == []
