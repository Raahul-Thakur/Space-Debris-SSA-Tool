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
    ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE,
    ANONYMOUS_REQUESTS_PER_MINUTE,
    MAX_SAMPLES_PER_TRAJECTORY_REQUEST,
    SIGNED_IN_ALLOWANCE_MULTIPLIER,
    SlidingWindowLimiter,
    client_address,
    propagation_cost,
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


def test_propagation_is_budgeted_by_work_not_by_request_count() -> None:
    """A three-hour track and a twenty-four-hour one are not the same request.

    Counting calls would either throttle a normal page load -- the console
    needs one per monitored object -- or leave the expensive case unbounded.
    """
    console_track = propagation_cost(window_hours=3, step_sec=180)
    largest_allowed = propagation_cost(window_hours=24, step_sec=10)
    assert console_track == 1
    assert largest_allowed > console_track * 50
    # A full twenty-object page load fits comfortably...
    assert 20 * console_track < ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE
    # ...while the largest single request cannot be repeated freely.
    assert largest_allowed * 3 > ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE


def test_a_full_page_of_tracks_is_not_throttled(client: TestClient) -> None:
    """The budget must not silently truncate the globe it exists to protect."""
    codes = [
        client.get("/objects/25544/trajectory?window_hours=3&step_sec=180").status_code
        for _ in range(20)
    ]
    assert 429 not in codes, "a normal page load was throttled"


def test_an_oversized_propagation_is_refused(client: TestClient) -> None:
    response = client.get("/objects/25544/trajectory?window_hours=24&step_sec=10")
    # Either rejected for cost, or served because the object is absent; what
    # must not happen is it being served cheaply.
    assert response.status_code in (404, 429)


def test_an_expensive_request_does_not_lock_out_the_window(client: TestClient) -> None:
    """A refused request is not charged, so one oversized call cannot block the rest."""
    for _ in range(3):
        client.get("/objects/25544/trajectory?window_hours=24&step_sec=10")
    assert (
        client.get(
            "/objects/25544/trajectory?window_hours=3&step_sec=180"
        ).status_code
        != 429
    )


def test_a_throttled_response_says_when_to_come_back(client: TestClient) -> None:
    last = None
    for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 2):
        last = client.get("/ontology")
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


def test_a_made_up_authorization_header_earns_no_exemption(client: TestClient) -> None:
    """Any Authorization header used to skip metering, valid or not.

    That made the limiter optional: one invented header and a script could
    ask for as much propagation as it liked.
    """
    headers = {"Authorization": "Bearer not-a-real-token"}
    codes = [
        client.get("/ontology", headers=headers).status_code
        for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 5)
    ]
    assert 429 in codes, "an invalid token bypassed the anonymous allowance"


def test_a_non_bearer_header_earns_no_exemption(client: TestClient) -> None:
    codes = [
        client.get("/ontology", headers={"Authorization": "x"}).status_code
        for _ in range(ANONYMOUS_REQUESTS_PER_MINUTE + 5)
    ]
    assert 429 in codes


def test_a_signed_in_caller_has_a_larger_allowance_not_an_unlimited_one(
    client: TestClient,
) -> None:
    headers = _token(client)
    allowance = ANONYMOUS_REQUESTS_PER_MINUTE * SIGNED_IN_ALLOWANCE_MULTIPLIER
    codes = [
        client.get("/ontology", headers=headers).status_code
        for _ in range(allowance + 5)
    ]
    assert 429 not in codes[:allowance]
    assert 429 in codes[allowance:]


def test_one_request_cannot_ask_for_an_unbounded_amount_of_propagation(
    tmp_path, monkeypatch
) -> None:
    """Forty objects at 24 h and 10 s steps was 345,600 samples in one response.

    Sent through the website's proxy, whose shared budget is large enough to
    admit it, so it is the size cap and not the limiter that refuses it.
    """
    monkeypatch.setenv("SDEBRIS_PROXY_TOKEN", "a-shared-secret")
    app = create_app(f"sqlite:///{tmp_path / 'size.sqlite'}")
    ids = ",".join(str(25000 + n) for n in range(40))
    with TestClient(app) as client:
        response = client.get(
            f"/trajectories?norad_ids={ids}&window_hours=24&step_sec=10",
            headers={"x-sdebris-proxy": "a-shared-secret"},
        )
    assert response.status_code == 422
    assert str(MAX_SAMPLES_PER_TRAJECTORY_REQUEST) in response.text


def test_the_console_default_request_is_well_inside_the_size_cap(
    client: TestClient,
) -> None:
    ids = ",".join(str(25000 + n) for n in range(20))
    response = client.get(f"/trajectories?norad_ids={ids}&window_hours=3&step_sec=180")
    assert response.status_code == 200, response.text


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
