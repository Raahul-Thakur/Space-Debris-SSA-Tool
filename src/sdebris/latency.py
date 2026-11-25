"""A small in-process record of recent request latency, for the admin page.

This exists so the founder can see how the service is behaving right now
without adding a metrics product: no third party, no extra infrastructure, and
nothing about who made a request. Each sample is a route *template* (for
example ``GET /objects/{norad_id}/trajectory``), a status class and a duration.
Raw paths are never kept, because they carry object ids, job ids and, on a few
routes, query strings a person typed.

Limits, stated plainly because they shape how the numbers should be read:

* It is **per process**. With more than one API instance each one reports
  only its own traffic.
* It **resets on restart**, and the free instance sleeps when idle, so a quiet
  spell followed by a wake-up shows an almost empty window.
* Memory is bounded twice over: at most ``max_samples`` samples, and nothing
  older than ``window_seconds``. Under heavy traffic the window is therefore
  shorter than an hour; ``window_minutes`` in the snapshot says how long it is.
"""

from __future__ import annotations

import math
import threading
import time
from collections import Counter, deque
from collections.abc import Callable, Sequence

#: Label for requests that never reached a route: throttled (429) before
#: routing, or a path that matches nothing. Their raw path is not recorded.
UNROUTED = "(unrouted)"


def status_class(status: int) -> str:
    return f"{status // 100}xx" if 100 <= status < 600 else "other"


def percentile(sorted_values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile of an already sorted sequence.

    Nearest-rank rather than interpolated, so a reported p99 is always a
    latency some request actually had.
    """
    if not sorted_values:
        return None
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _summary(durations: list[float], statuses: Counter[str]) -> dict[str, object]:
    durations.sort()
    count = len(durations)
    return {
        "requests": count,
        "p50_ms": _rounded(percentile(durations, 0.50)),
        "p95_ms": _rounded(percentile(durations, 0.95)),
        "p99_ms": _rounded(percentile(durations, 0.99)),
        # 5xx only: a 4xx is usually the caller's mistake (a bad id, an
        # expired token, a rate limit) and is reported separately.
        "error_rate": round(statuses["5xx"] / count, 4) if count else 0.0,
        "client_error_rate": round(statuses["4xx"] / count, 4) if count else 0.0,
    }


class LatencyRecorder:
    """Rolling latency samples for one process. Safe to call from any thread."""

    def __init__(
        self,
        max_samples: int = 5_000,
        window_seconds: int = 3_600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_samples = max_samples
        self.window_seconds = window_seconds
        self._clock = clock
        self._started = clock()
        # (timestamp, route template, status class, duration in ms)
        self._samples: deque[tuple[float, str, str, float]] = deque(maxlen=max_samples)
        # Recording happens on the event loop and reading in a worker thread.
        self._lock = threading.Lock()

    def record(self, route: str, status: int, duration_ms: float) -> None:
        with self._lock:
            self._samples.append((self._clock(), route, status_class(status), duration_ms))

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def snapshot(self, top_routes: int = 10) -> dict[str, object]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            samples = list(self._samples)
            saturated = len(self._samples) == self.max_samples

        # How much time the samples actually cover: the full window, or less
        # if the process is younger than that, or if the sample cap was hit
        # and the oldest kept sample is more recent than the window start.
        covered_from = max(now - self.window_seconds, self._started)
        if saturated and samples:
            covered_from = max(covered_from, samples[0][0])
        covered_minutes = max((now - covered_from) / 60, 1 / 60)

        durations = [sample[3] for sample in samples]
        statuses = Counter(sample[2] for sample in samples)

        per_minute = [0] * (self.window_seconds // 60)
        for at, *_rest in samples:
            age = int((now - at) // 60)
            if 0 <= age < len(per_minute):
                per_minute[len(per_minute) - 1 - age] += 1

        by_route: dict[str, tuple[list[float], Counter[str]]] = {}
        for _at, route, klass, duration in samples:
            bucket = by_route.setdefault(route, ([], Counter()))
            bucket[0].append(duration)
            bucket[1][klass] += 1
        busiest = sorted(by_route.items(), key=lambda item: -len(item[1][0]))[:top_routes]

        return {
            "scope": "this API process only; resets when it restarts",
            "window_minutes": round(covered_minutes, 1),
            "max_samples": self.max_samples,
            # Over at least a minute: just after a restart a handful of
            # requests in a few seconds would otherwise read as hundreds a
            # minute.
            "requests_per_minute": round(len(samples) / max(covered_minutes, 1), 2),
            # Oldest first, one entry per minute of the window, newest last.
            "per_minute": per_minute,
            "status_classes": dict(sorted(statuses.items())),
            **_summary(durations, statuses),
            "routes": [
                {"route": route, **_summary(list(values), counts)}
                for route, (values, counts) in busiest
            ],
        }
