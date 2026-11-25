"""The rolling latency recorder behind the admin page's latency table."""

from __future__ import annotations

from sdebris.latency import UNROUTED, LatencyRecorder, percentile, status_class


class Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_percentiles_are_nearest_rank() -> None:
    values = [float(n) for n in range(1, 101)]
    assert percentile(values, 0.50) == 50
    assert percentile(values, 0.95) == 95
    assert percentile(values, 0.99) == 99
    assert percentile([7.0], 0.99) == 7
    assert percentile([], 0.5) is None


def test_status_classes() -> None:
    assert [status_class(code) for code in (200, 304, 404, 503, 42)] == [
        "2xx", "3xx", "4xx", "5xx", "other"
    ]


def test_summary_per_route_and_overall() -> None:
    clock = Clock()
    recorder = LatencyRecorder(clock=clock)
    clock.now += 600  # ten minutes of uptime
    for ms in range(1, 101):
        recorder.record("GET /objects", 200, float(ms))
    recorder.record("GET /objects/{norad_id}", 404, 5.0)
    recorder.record("POST /commands/execute", 500, 900.0)
    snap = recorder.snapshot()

    assert snap["requests"] == 102
    assert snap["window_minutes"] == 10.0
    assert snap["requests_per_minute"] == 10.2
    assert snap["status_classes"] == {"2xx": 100, "4xx": 1, "5xx": 1}
    assert snap["error_rate"] == round(1 / 102, 4)
    routes = {route["route"]: route for route in snap["routes"]}
    assert snap["routes"][0]["route"] == "GET /objects"
    assert routes["GET /objects"]["p50_ms"] == 50
    assert routes["GET /objects"]["p95_ms"] == 95
    assert routes["POST /commands/execute"]["error_rate"] == 1.0
    assert routes["GET /objects/{norad_id}"]["client_error_rate"] == 1.0
    assert sum(snap["per_minute"]) == 102
    assert snap["per_minute"][-1] == 102


def test_old_samples_leave_the_window() -> None:
    clock = Clock()
    recorder = LatencyRecorder(window_seconds=3600, clock=clock)
    recorder.record("GET /a", 200, 1.0)
    clock.now += 30 * 60
    recorder.record("GET /b", 200, 2.0)
    clock.now += 31 * 60
    snap = recorder.snapshot()
    assert snap["requests"] == 1
    assert [route["route"] for route in snap["routes"]] == ["GET /b"]
    assert snap["window_minutes"] == 60.0
    # The surviving request was 31 minutes ago.
    assert snap["per_minute"][-32] == 1


def test_memory_is_bounded_by_the_sample_cap() -> None:
    clock = Clock()
    recorder = LatencyRecorder(max_samples=50, clock=clock)
    clock.now += 3600
    for n in range(500):
        clock.now += 1
        recorder.record("GET /a", 200, float(n))
    snap = recorder.snapshot()
    assert snap["requests"] == 50
    # The window then reports how long the kept samples actually cover.
    assert snap["window_minutes"] == round(49 / 60, 1)


def test_top_routes_are_limited() -> None:
    recorder = LatencyRecorder()
    for n in range(20):
        for _ in range(n + 1):
            recorder.record(f"GET /r{n}", 200, 1.0)
    routes = recorder.snapshot(top_routes=5)["routes"]
    assert [route["route"] for route in routes] == [f"GET /r{n}" for n in (19, 18, 17, 16, 15)]


def test_an_empty_recorder_reports_nothing_rather_than_failing() -> None:
    snap = LatencyRecorder().snapshot()
    assert snap["requests"] == 0
    assert snap["p50_ms"] is None
    assert snap["error_rate"] == 0.0
    assert snap["routes"] == []
    assert UNROUTED.startswith("(")


def test_a_fresh_process_does_not_extrapolate_a_burst() -> None:
    clock = Clock()
    recorder = LatencyRecorder(clock=clock)
    clock.now += 6
    for _ in range(12):
        recorder.record("GET /health", 200, 1.23456)
    snap = recorder.snapshot()
    assert snap["requests_per_minute"] == 12
    assert snap["p50_ms"] == 1.23
