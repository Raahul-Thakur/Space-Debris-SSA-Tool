"""A short-lived cache for the public read endpoints.

The orbital picture is the same for everybody. Nothing in ``/events/assessed``,
``/objects`` or a trajectory depends on who is asking: the rows are
platform-owned, the propagation starts from the same elements, and the whole
set is rewritten only when the scheduled screening runs, every six hours.

Computing it per visitor was therefore pure waste, and expensive waste. A
trajectory request runs SGP4 across a time grid; the free instance this is
deployed on has a tenth of a CPU, and a single page load asks for twenty of
them. Measured, that ceiling was about thirty page loads a minute for the
entire site.

What is cached here is the finished JSON, not the Python objects it was built
from. Serialising a few thousand ephemeris points is itself a visible cost at
this instance size, and once the bytes exist they can be handed to every
subsequent caller untouched.

The cache is per-process and in memory, which is the right scope for what it
is defending. It needs no infrastructure, costs nothing, cannot fall out of
sync with a second copy of itself, and an eviction is never worse than the
behaviour before it existed. A deploy empties it; so does a Render instance
going to sleep. Neither matters, because a miss is just the old code path.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from fastapi.encoders import jsonable_encoder

__all__ = ["CacheStats", "PublicCache"]


class CacheStats:
    """Hit and miss counts, reported on ``/health`` for tuning."""

    __slots__ = ("evictions", "hits", "misses")

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def as_dict(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "evictions": self.evictions}


class PublicCache:
    """Memoise serialised payloads under a key, for a bounded time.

    Entries are capped in number as well as in age. The key for a trajectory
    includes its query parameters, and those are caller-controlled, so an
    unbounded dictionary would be a way for one visitor to exhaust the
    instance's memory by walking ``step_sec`` through its permitted range.
    Least-recently-used eviction keeps that to a fixed cost.
    """

    def __init__(self, *, max_entries: int = 256) -> None:
        self._entries: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self.stats = CacheStats()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def get_or_compute(
        self, key: str, ttl_seconds: float, compute: Callable[[], Any]
    ) -> bytes:
        """Return the cached body for ``key``, computing it when absent or stale.

        ``compute`` runs outside the lock. Holding it across a database query
        and an SGP4 propagation would serialise every request on the instance
        behind the slowest one, which is the opposite of the point. The cost
        of releasing it is that two simultaneous misses on the same key both
        do the work; they then agree on the answer, so the only loss is one
        duplicated computation at the moment a key expires.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] > now:
                self._entries.move_to_end(key)
                self.stats.hits += 1
                return entry[1]

        self.stats.misses += 1
        body = _encode(compute())

        with self._lock:
            self._entries[key] = (time.monotonic() + ttl_seconds, body)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                self.stats.evictions += 1
        return body


def _encode(payload: Any) -> bytes:
    """Serialise exactly as FastAPI would have, so the bytes are unchanged.

    ``jsonable_encoder`` is what the framework applies to a returned Pydantic
    model or dataclass; going through it rather than ``json.dumps`` alone
    keeps datetimes, enums and nested models rendering the way every existing
    client already expects.
    """
    return json.dumps(jsonable_encoder(payload), separators=(",", ":")).encode()
