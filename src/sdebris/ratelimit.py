"""A small in-process rate limiter.

Deliberately not distributed: the deployment runs a single API instance, so a
shared store would add a dependency without buying anything. If the service is
ever scaled horizontally this has to move to Redis, because each process would
otherwise enforce the limit independently.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

#: Entries idle for longer than this are dropped so the map cannot grow without
#: bound as accounts come and go.
IDLE_EVICTION_SECONDS = 600.0

#: Unauthenticated browsing allowance per client address, per minute. Generous
#: enough that a visitor clicking around the globe never notices it.
ANONYMOUS_REQUESTS_PER_MINUTE = 120

#: Propagation is the expensive anonymous operation, and requests vary enormously
#: in cost: the console asks for a three-hour track per monitored object, around
#: ninety SGP4 evaluations, while the endpoint permits twenty-four hours at
#: ten-second steps, which is 8640. Budgeting by request count would either
#: throttle a normal page load -- the console needs one call per object before
#: the globe is complete -- or leave the expensive case unbounded. So the budget
#: is denominated in units of work.
#: Sized from the console's actual shape: it asks for one track per monitored
#: object, so a twenty-object catalogue is twenty units per paint. This allows
#: several page loads a minute while still refusing the largest request the
#: endpoint permits more than twice over.
ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE = 150
#: Samples per unit. A default console track costs one; the largest request the
#: endpoint allows costs more than the whole budget, and is refused outright.
SAMPLES_PER_PROPAGATION_UNIT = 120


#: A verified account is metered by identity rather than by address, with this
#: many times the anonymous allowance. Before this existed, sending any
#: ``Authorization`` header at all -- even a made-up one -- skipped metering
#: entirely, because the check looked for the header rather than a valid token.
SIGNED_IN_ALLOWANCE_MULTIPLIER = 5

#: The website's caching proxy is exempt from per-address metering (every
#: visitor shares its address), but not from all metering: its query
#: parameters are the visitor's, so each distinct value is a cache miss that
#: reaches this process. One shared budget, far above what a cached site
#: needs, bounds what that can cost.
PROXY_PROPAGATION_UNITS_PER_MINUTE = ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE * 20

#: The most SGP4 samples one trajectory request may ask for, across all of its
#: objects. The console's default (twenty objects, three hours at 180 s) is
#: about 1,200; the old ceiling of forty objects at twenty-four hours and ten
#: seconds was 345,600, a response tens of megabytes long.
MAX_SAMPLES_PER_TRAJECTORY_REQUEST = 50_000


def trajectory_samples(window_hours: float, step_sec: float, objects: int = 1) -> int:
    """SGP4 samples a trajectory request asks for, across ``objects``."""
    if step_sec <= 0:
        return 0
    per_object = math.floor(window_hours * 3600.0 / step_sec) + 1
    return per_object * max(1, objects)


def propagation_cost(window_hours: float, step_sec: float) -> int:
    """Units of work a trajectory request represents."""
    if step_sec <= 0:
        return 1
    samples = max(1.0, (window_hours * 3600.0) / step_sec)
    return max(1, math.ceil(samples / SAMPLES_PER_PROPAGATION_UNIT))


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

    def check(
        self, key: str, limit: int, now: float | None = None, cost: int = 1
    ) -> bool:
        """Record ``cost`` units against ``key`` and report whether they fit.

        A cost above one lets a budget track work rather than calls, for
        endpoints where one request can be far more expensive than another.
        An over-budget request is rejected without being charged, so a single
        oversized call cannot lock an address out for the whole window.
        """
        if limit <= 0 or cost <= 0:
            return False
        moment = now if now is not None else time.monotonic()
        with self._lock:
            self._evict(moment)
            hits = self._hits[key]
            while hits and moment - hits[0] >= self._window:
                hits.popleft()
            if len(hits) + cost > limit:
                return False
            hits.extend([moment] * cost)
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
