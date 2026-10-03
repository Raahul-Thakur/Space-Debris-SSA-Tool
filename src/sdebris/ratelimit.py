"""A small in-process rate limiter.

Deliberately not distributed: the deployment runs a single API instance, so a
shared store would add a dependency without buying anything. If the service is
ever scaled horizontally this has to move to Redis, because each process would
otherwise enforce the limit independently.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

#: Entries idle for longer than this are dropped so the map cannot grow without
#: bound as accounts come and go.
IDLE_EVICTION_SECONDS = 600.0

#: Unauthenticated browsing allowance per client address, per minute. Generous
#: enough that a visitor clicking around the globe never notices it.
ANONYMOUS_REQUESTS_PER_MINUTE = 120

#: Propagation is the expensive anonymous operation: a trajectory request runs
#: SGP4 over a time grid of up to 8640 points. It gets its own, much tighter
#: budget so that one address cannot saturate a small instance.
ANONYMOUS_PROPAGATIONS_PER_MINUTE = 12


def client_address(request: object) -> str:
    """Best-effort client address for rate limiting.

    Behind a proxy the socket peer is the proxy, so ``X-Forwarded-For`` has to
    be consulted. The *rightmost* entry is used rather than the leftmost: a
    client can put anything it likes at the front of that header, but the
    trusted proxy in front of this service appends what it actually observed.
    Reading from the right therefore cannot be spoofed by the caller, while
    reading from the left would let one attacker appear as many.
    """
    headers = getattr(request, "headers", {})
    forwarded = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


class SlidingWindowLimiter:
    """Allows at most ``limit`` hits per key within a rolling window."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, now: float | None = None) -> bool:
        """Record a hit and report whether it is within the limit."""
        if limit <= 0:
            return False
        moment = now if now is not None else time.monotonic()
        with self._lock:
            self._evict(moment)
            hits = self._hits[key]
            while hits and moment - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(moment)
            return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Whole seconds until the oldest hit for ``key`` falls out of the window."""
        moment = now if now is not None else time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            return max(1, int(self._window - (moment - hits[0])) + 1)

    def _evict(self, moment: float) -> None:
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or moment - hits[-1] > IDLE_EVICTION_SECONDS
        ]
        for key in stale:
            del self._hits[key]
