"""Rate limits, stream slots and the response cache shared through Redis.

Run against a real Redis: SDEBRIS_TEST_REDIS_URL (CI provides one), or a
redis-server started here when one is installed. Skipped otherwise.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

import pytest

from sdebris import shared_state
from sdebris.api.app import StreamSlots
from sdebris.api.public_cache import PublicCache
from sdebris.ratelimit import SlidingWindowLimiter


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url():
    url = os.getenv("SDEBRIS_TEST_REDIS_URL")
    process = None
    if not url:
        if not shutil.which("redis-server"):
            pytest.skip("no Redis available (set SDEBRIS_TEST_REDIS_URL)")
        port = _free_port()
        process = subprocess.Popen(
            ["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL,
        )
        url = f"redis://127.0.0.1:{port}/0"
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.05)
    yield url
    if process:
        process.terminate()
        process.wait()


@pytest.fixture
def client(redis_url, monkeypatch):
    monkeypatch.setenv("SDEBRIS_REDIS_URL", redis_url)
    redis = shared_state.redis_client()
    redis.flushdb()
    return redis


def test_two_processes_share_one_limit(client) -> None:
    # Two limiters stand for two API processes. In process memory each would
    # allow the full limit; through Redis they share it.
    first = shared_state.make_limiter("t", SlidingWindowLimiter())
    second = shared_state.make_limiter("t", SlidingWindowLimiter())
    assert isinstance(first, shared_state.RedisSlidingWindowLimiter)
    allowed = [limiter.check("addr", 10) for limiter in (first, second) * 10]
    assert allowed.count(True) == 10
    assert first.retry_after("addr") >= 1


def test_costs_are_charged_in_units_and_refusals_are_free(client) -> None:
    limiter = shared_state.make_limiter("cost", SlidingWindowLimiter())
    assert limiter.check("addr", 150, cost=100)
    assert not limiter.check("addr", 150, cost=60)  # refused, and not charged
    assert limiter.check("addr", 150, cost=50)
    assert not limiter.check("addr", 150, cost=1)


def test_stream_slots_are_counted_across_processes(client) -> None:
    def make():
        return shared_state.make_stream_slots(StreamSlots(2, 3), 2, 3, lease_seconds=60)

    first, second = make(), make()
    assert first.acquire("alice") and second.acquire("alice")
    assert not first.acquire("alice")  # two per account, across both
    assert second.acquire("bob")
    assert not first.acquire("carol")  # three in total
    first.release("alice")
    assert second.acquire("carol")


def test_a_dead_process_cannot_hold_slots_past_its_lease(client) -> None:
    dead = shared_state.make_stream_slots(StreamSlots(1, 1), 1, 1, lease_seconds=0.2)
    assert dead.acquire("alice")  # never released
    other = shared_state.make_stream_slots(StreamSlots(1, 1), 1, 1, lease_seconds=0.2)
    assert not other.acquire("alice")
    time.sleep(0.3)
    assert other.acquire("alice")


def test_one_process_computes_and_the_other_serves(client) -> None:
    calls = []

    def compute():
        calls.append(1)
        return {"answer": 42}

    first = PublicCache(shared=shared_state.make_shared_bodies())
    second = PublicCache(shared=shared_state.make_shared_bodies())
    assert first.get_or_compute("k", 30, compute) == b'{"answer":42}'
    assert second.get_or_compute("k", 30, compute) == b'{"answer":42}'
    assert len(calls) == 1
    assert second.stats.shared_hits == 1


def test_redis_going_away_degrades_to_in_process_limits(monkeypatch) -> None:
    # Nothing listens on this port: every call fails fast and falls back.
    monkeypatch.setenv("SDEBRIS_REDIS_URL", f"redis://127.0.0.1:{_free_port()}/0")
    limiter = shared_state.make_limiter("down", SlidingWindowLimiter())
    assert [limiter.check("addr", 2) for _ in range(3)] == [True, True, False]
    slots = shared_state.make_stream_slots(StreamSlots(1, 5), 1, 5, lease_seconds=60)
    assert slots.acquire("alice") and not slots.acquire("alice")
    slots.release("alice")
    assert slots.acquire("alice")
    cache = PublicCache(shared=shared_state.make_shared_bodies())
    assert cache.get_or_compute("k", 30, lambda: [1]) == b"[1]"
    assert shared_state.describe() == {"backend": "redis", "reachable": False}


def test_without_redis_nothing_changes(monkeypatch) -> None:
    monkeypatch.delenv("SDEBRIS_REDIS_URL", raising=False)
    local = SlidingWindowLimiter()
    assert shared_state.make_limiter("x", local) is local
    assert shared_state.make_shared_bodies() is None
    assert shared_state.describe() == {"backend": "process"}
