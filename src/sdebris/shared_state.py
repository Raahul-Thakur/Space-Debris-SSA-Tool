"""State that has to agree across API processes, kept in Redis when there is one.

On the free stack there is one API process, and the rate limits, the count
of open live streams and the response cache live in its memory. That stops
being correct the moment there are two: each process would enforce its own
copy of every limit, so two workers would allow twice the traffic, and the
cache would be computed once per process.

With ``SDEBRIS_REDIS_URL`` set, these move to Redis. Each operation is a
single Lua script, so a check and the record that follows it are atomic
across every process. Without it, nothing changes: the in-process versions
are used, as before.

Redis is treated as an accelerator, not a dependency the site stands on. If
it stops answering, each call falls back to the in-process version and logs
once; limits then become per-process (looser, never absent) until it is
back, and the site keeps serving.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Every key this module writes starts with this, so the service can share a
#: Redis instance with the job broker without the two colliding.
PREFIX = "astra:"


class Limiter(Protocol):
    def check(self, key: str, limit: int, now: float | None = None, cost: int = 1) -> bool: ...

    def retry_after(self, key: str, now: float | None = None) -> int: ...


class Slots(Protocol):
    def acquire(self, key: str) -> bool: ...

    def release(self, key: str) -> None: ...


def redis_url() -> str | None:
    return os.getenv("SDEBRIS_REDIS_URL", "").strip() or None


@lru_cache(maxsize=4)
def _client_for(url: str) -> Any:
    import redis

    # Short timeouts: a slow Redis must cost a request milliseconds, not
    # seconds, before the in-process fallback takes over.
    return redis.Redis.from_url(
        url, socket_timeout=0.25, socket_connect_timeout=0.5, health_check_interval=30
    )


def redis_client() -> Any | None:
    url = redis_url()
    return _client_for(url) if url else None


class _Fallback:
    """Runs against Redis, and against a local stand-in when Redis fails."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._warned = False
        # After a failure Redis is left alone for a few seconds, so an outage
        # costs one timeout per few seconds rather than one per request.
        self._down_until = 0.0

    def _try(self, remote: Callable[[], T], local: Callable[[], T]) -> T:
        if time.monotonic() < self._down_until:
            return local()
        try:
            value = remote()
        except Exception as exc:  # noqa: BLE001 - any Redis failure degrades the same way
            self._down_until = time.monotonic() + 5.0
            if not self._warned:
                logger.warning(
                    "Redis unavailable for %s; using the in-process fallback (%s)",
                    self._name,
                    exc,
                )
                self._warned = True
            return local()
        if self._warned:
            logger.info("Redis is back for %s", self._name)
            self._warned = False
        return value


# Sliding window as a sorted set of hits scored by time. A hit with a cost of
# n is n members, so a budget measured in units of work behaves exactly as
# the in-process limiter does. An over-budget call records nothing.
_CHECK = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
if redis.call('ZCARD', key) + cost > limit then
  return 0
end
local args = {}
for i = 1, cost do
  args[#args + 1] = now
  args[#args + 1] = ARGV[5] .. ':' .. i
end
redis.call('ZADD', key, unpack(args))
redis.call('PEXPIRE', key, math.ceil(window * 1000))
return 1
"""


class RedisSlidingWindowLimiter(_Fallback):
    """The in-process ``SlidingWindowLimiter``, shared by every process."""

    def __init__(self, name: str, client: Any, local: Limiter, window_seconds: float) -> None:
        super().__init__(f"rate limit {name}")
        self._key = f"{PREFIX}rl:{name}:"
        self._client = client
        self._local = local
        self._window = window_seconds
        self._script = client.register_script(_CHECK)

    def check(self, key: str, limit: int, now: float | None = None, cost: int = 1) -> bool:
        if limit <= 0 or cost <= 0:
            return False
        if now is not None:  # tests drive the local clock
            return self._local.check(key, limit, now=now, cost=cost)
        return self._try(
            lambda: bool(
                self._script(
                    keys=[self._key + key],
                    args=[time.time(), self._window, limit, cost, uuid.uuid4().hex],
                )
            ),
            lambda: self._local.check(key, limit, cost=cost),
        )

    def retry_after(self, key: str, now: float | None = None) -> int:
        def remote() -> int:
            oldest = self._client.zrange(self._key + key, 0, 0, withscores=True)
            if not oldest:
                return 0
            return max(1, int(self._window - (time.time() - oldest[0][1])) + 1)

        return self._try(remote, lambda: self._local.retry_after(key, now))


# Live-stream slots as leases: a member per open stream, scored by when the
# lease ends. A process that dies without releasing its streams cannot hold
# their slots for longer than the lease.
_ACQUIRE = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[4]) then return 0 end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then return 0 end
local expires = now + tonumber(ARGV[2])
redis.call('ZADD', KEYS[1], expires, ARGV[5])
redis.call('ZADD', KEYS[2], expires, ARGV[5])
local ttl = math.ceil(tonumber(ARGV[2]) * 1000)
redis.call('PEXPIRE', KEYS[1], ttl)
redis.call('PEXPIRE', KEYS[2], ttl)
return 1
"""


class RedisStreamSlots(_Fallback):
    """``StreamSlots`` counted across every process.

    The lease is the longest a stream may stay open, plus a margin: streams
    end themselves at that age, so a live one never outlives its lease.
    """

    def __init__(
        self, client: Any, local: Slots, per_account: int, total: int, lease_seconds: float
    ) -> None:
        super().__init__("stream slots")
        self.per_account = per_account
        self.total = total
        self._client = client
        self._local = local
        self._lease = lease_seconds
        self._script = client.register_script(_ACQUIRE)
        # Which leases this process holds, so release() knows which to drop.
        # "local" marks a slot taken from the fallback during an outage.
        self._held: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def _keys(self, key: str) -> list[str]:
        return [f"{PREFIX}streams:all", f"{PREFIX}streams:acct:{key}"]

    def acquire(self, key: str) -> bool:
        token = uuid.uuid4().hex

        def remote() -> str | None:
            granted = self._script(
                keys=self._keys(key),
                args=[time.time(), self._lease, self.per_account, self.total, token],
            )
            return token if granted else None

        held = self._try(remote, lambda: "local" if self._local.acquire(key) else None)
        if held is None:
            return False
        with self._lock:
            self._held.setdefault(key, []).append(held)
        return True

    def release(self, key: str) -> None:
        with self._lock:
            tokens = self._held.get(key)
            if not tokens:
                return
            token = tokens.pop()
            if not tokens:
                del self._held[key]
        if token == "local":
            self._local.release(key)
            return
        all_key, account_key = self._keys(key)
        # Best effort: if this fails the lease simply runs out.
        self._try(
            lambda: self._client.pipeline().zrem(all_key, token).zrem(account_key, token).execute(),
            lambda: None,
        )


class SharedBodies(_Fallback):
    """Cached response bodies in Redis, so processes compute each one once."""

    def __init__(self, client: Any) -> None:
        super().__init__("response cache")
        self._client = client

    @staticmethod
    def _key(key: str) -> str:
        # Keys contain caller-supplied query values; hashing bounds their size.
        return f"{PREFIX}cache:{hashlib.sha256(key.encode()).hexdigest()}"

    def get(self, key: str) -> bytes | None:
        return self._try(lambda: self._client.get(self._key(key)), lambda: None)

    def put(self, key: str, body: bytes, ttl_seconds: float) -> None:
        self._try(
            lambda: self._client.set(self._key(key), body, px=max(1, int(ttl_seconds * 1000))),
            lambda: None,
        )


def make_limiter(name: str, local: Limiter, window_seconds: float = 60.0) -> Limiter:
    """A limiter shared through Redis when configured, else ``local``."""
    client = redis_client()
    if client is None:
        return local
    return RedisSlidingWindowLimiter(name, client, local, window_seconds)


def make_stream_slots(local: Slots, per_account: int, total: int, lease_seconds: float) -> Slots:
    client = redis_client()
    if client is None:
        return local
    return RedisStreamSlots(client, local, per_account, total, lease_seconds)


def make_shared_bodies() -> SharedBodies | None:
    client = redis_client()
    return SharedBodies(client) if client is not None else None


def describe() -> dict[str, object]:
    """For ``/health``: whether shared state is in use and reachable."""
    client = redis_client()
    if client is None:
        return {"backend": "process"}
    try:
        client.ping()
    except Exception:  # noqa: BLE001
        return {"backend": "redis", "reachable": False}
    return {"backend": "redis", "reachable": True}
