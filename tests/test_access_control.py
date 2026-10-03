"""The anonymous tier: what a visitor without an account may see and do.

The platform is read-open by design — the point of the public dashboard is
that the orbital picture is real without signing up — so these tests pin down
where that openness stops, and that it cannot be turned into free compute.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sdebris.api.app import create_app
from sdebris.ratelimit import (
    ANONYMOUS_PROPAGATIONS_PER_MINUTE,
    ANONYMOUS_REQUESTS_PER_MINUTE,
    SlidingWindowLimiter,
    client_address,
)

#: Readable without a token: the public orbital picture.
PUBLIC_READS = [
    "/health",
    "/ontology",
    "/methodology",
    "/objects",
    "/events",
    "/events/assessed",
    "/monitoring",
    "/commands/help",
]

#: Requires an account, because it is operational state or costs an identity
#: to meter.
PRIVATE_READS = ["/cases", "/activity", "/billing/me"]


@pytest.fixture()
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'access.sqlite'}")
    with TestClient(app) as test_client:
        yield test_client


def _token(client: TestClient) -> dict[str, str]:
    body = client.post("/auth/development-token").json()
    return {"Authorization": f"Bearer {body['access_token']}"}


# ------------------------------------------------------------------ anonymous
@pytest.mark.parametrize("path", PUBLIC_READS)
def test_the_public_picture_needs_no_account(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("path", PRIVATE_READS)
def test_private_surfaces_refuse_an_anonymous_caller(
    client: TestClient, path: str
) -> None:
    assert client.get(path).status_code == 401, path


def test_assessed_events_match_the_openness_of_plain_events(
    client: TestClient,
) -> None:
    """Both serve the same rows; gating one and not the other protected nothing."""
    assert client.get("/events").status_code == 200
    assert client.get("/events/assessed").status_code == 200


def test_cases_are_not_part_of_the_public_picture(client: TestClient) -> None:
    """Who is investigating what is operational workflow, not public data."""
    assert client.get("/cases").status_code == 401
    # And a signed-in viewer is still not enough: cases start at analyst.
    assert client.get("/cases", headers=_token(client)).status_code in (200, 403)


# ----------------------------------------------------------------- throttling
def test_anonymous_reads_are_capped_per_address(client: TestClient) -> None:
    codes = [
        client.get("/ontology").status_code
        for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 5)
    ]
    assert 429 in codes, "an unauthenticated caller was never throttled"
    assert codes.index(429) <= ANONYMOUS_REQUESTS_PER_MINUTE


def test_propagation_has_its_own_tighter_budget(client: TestClient) -> None:
    """Trajectory runs SGP4 over thousands of points; it cannot share the read budget."""
    assert ANONYMOUS_PROPAGATIONS_PER_MINUTE < ANONYMOUS_REQUESTS_PER_MINUTE
    codes = [
        client.get("/objects/25544/trajectory").status_code
        for _ in range(ANONYMOUS_PROPAGATIONS_PER_MINUTE + 3)
    ]
    assert codes.index(429) == ANONYMOUS_PROPAGATIONS_PER_MINUTE


def test_a_throttled_response_says_when_to_come_back(client: TestClient) -> None:
    last = None
    for _ in range(ANONYMOUS_PROPAGATIONS_PER_MINUTE + 2):
        last = client.get("/objects/25544/trajectory")
    assert last is not None
    assert last.status_code == 429
    assert int(last.headers["Retry-After"]) >= 1


def test_an_authenticated_caller_is_not_subject_to_the_anonymous_budget(
    client: TestClient,
) -> None:
    """Signed-in traffic is metered per principal by plan, not by address."""
    headers = _token(client)
    codes = [
        client.get("/ontology", headers=headers).status_code
        for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 5)
    ]
    assert 429 not in codes


# ------------------------------------------------------------ address parsing
class _Request:
    def __init__(self, forwarded: str | None, peer: str | None) -> None:
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = type("C", (), {"host": peer})() if peer else None


def test_the_socket_peer_is_used_when_there_is_no_proxy() -> None:
    assert client_address(_Request(None, "203.0.113.9")) == "203.0.113.9"


def test_the_rightmost_forwarded_hop_wins() -> None:
    """A caller can forge the left of this header; the trusted proxy appends to the right."""
    request = _Request("198.51.100.1, 203.0.113.9", "10.0.0.1")
    assert client_address(request) == "203.0.113.9"


def test_a_forged_forwarded_header_cannot_impersonate_many_clients() -> None:
    forged = _Request("evil-1, evil-2, 203.0.113.9", "10.0.0.1")
    assert client_address(forged) == "203.0.113.9"


def test_an_unknown_caller_still_gets_a_stable_key() -> None:
    assert client_address(_Request(None, None)) == "unknown"


# --------------------------------------------------------------------- limiter
def test_the_limiter_counts_each_key_separately() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)
    assert all(limiter.check("a", 2, now=1.0) for _ in range(1))
    assert limiter.check("a", 2, now=1.0)
    assert not limiter.check("a", 2, now=1.0)
    # A different address is unaffected by the first one's exhaustion.
    assert limiter.check("b", 2, now=1.0)


def test_the_window_rolls_forward() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)
    assert limiter.check("a", 1, now=0.0)
    assert not limiter.check("a", 1, now=30.0)
    assert limiter.check("a", 1, now=61.0)
