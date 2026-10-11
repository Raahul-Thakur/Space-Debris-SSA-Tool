"""The public picture is computed once and served many times.

Every endpoint covered here returns the same bytes to everybody: the rows are
platform-owned and the propagation starts from the same elements, so the only
thing a per-visitor computation bought was load. These tests pin the three
things that make the cache safe to rely on -- that it actually prevents the
recomputation, that it cannot serve one caller's answer to a question somebody
else asked, and that the headers tell a shared cache the truth.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sdebris.api.app import MAX_BATCH_TRAJECTORIES, create_app
from sdebris.api.public_cache import PublicCache
from sdebris.ontology.enums import OperatorRole
from sdebris.ontology.schemas import ElementSetCreate, SpaceObjectCreate
from sdebris.ontology.service import OntologyService
from sdebris.ratelimit import ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE

#: A real element set, so SGP4 produces real positions rather than NaNs.
ISS = (
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9003",
    "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49514751 24183",
)
HST = (
    "1 20580U 90037B   24001.50000000  .00001234  00000-0  70000-4 0  9992",
    "2 20580  28.4696 288.8102 0002823 321.7771  38.2581 15.09299865 24183",
)


def seed(app, entries) -> None:
    with app.state.database.session_factory() as session:
        service = OntologyService(session)
        for norad_id, name, (line1, line2) in entries:
            service.create_space_object(
                SpaceObjectCreate(norad_id=norad_id, name=name, status="active")
            )
            service.add_element_set(
                norad_id,
                ElementSetCreate(
                    line1=line1, line2=line2, source="test", parser_version="test-v1"
                ),
            )


@pytest.fixture()
def client(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'cache.sqlite').as_posix()}")
    with TestClient(app) as test_client:
        seed(app, [("25544", "ISS", ISS), ("20580", "HUBBLE", HST)])
        test_client.app_instance = app  # type: ignore[attr-defined]
        yield test_client


def stats(client) -> dict[str, int]:
    return client.app_instance.state.public_cache.stats.as_dict()


# --------------------------------------------------------------- the cache
def test_a_repeated_read_is_not_recomputed(client) -> None:
    before = stats(client)["misses"]
    first = client.get("/events/assessed")
    second = client.get("/events/assessed")
    assert first.status_code == 200
    assert first.content == second.content
    # One computation, however many times it was asked for.
    assert stats(client)["misses"] == before + 1
    assert stats(client)["hits"] >= 1


def test_different_questions_do_not_share_an_answer(client) -> None:
    """The failure this guards against would be a data leak, not a slow page.

    A cache keyed on the route rather than on the query would serve the
    filtered view to somebody who asked for the unfiltered one.
    """
    everything = client.get("/objects?limit=100").json()
    one = client.get("/objects?limit=1").json()
    assert len(everything) == 2
    assert len(one) == 1


def test_a_cached_read_still_advertises_itself_as_shareable(client) -> None:
    response = client.get("/objects")
    directive = response.headers["cache-control"]
    # s-maxage is the one that matters: it is what keeps the request off the
    # instance entirely. max-age is deliberately shorter, so a visitor who has
    # just run a screening sees it on reload.
    assert "s-maxage=300" in directive
    assert "stale-while-revalidate" in directive
    assert "max-age=60" in directive


def test_a_private_read_is_never_marked_public(client) -> None:
    """Scoped routes must not acquire the header by being near the others.

    Signed in deliberately: an unauthenticated request is refused before it
    reaches the route, so it would pass this assertion however the route
    behaved, and prove nothing about the case that matters.
    """
    token = client.app_instance.state.authenticator.issue_development_token(
        subject="someone", role=OperatorRole.ANALYST
    )
    response = client.get("/billing/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    assert "public" not in response.headers.get("cache-control", "")


def test_the_ontology_is_held_far_longer_than_the_picture(client) -> None:
    assert "s-maxage=3600" in client.get("/ontology").headers["cache-control"]
    assert "s-maxage=3600" in client.get("/methodology").headers["cache-control"]


# ------------------------------------------------------------- determinism
def test_the_same_trajectory_question_gets_the_same_answer(client) -> None:
    """Anchoring the time grid is what makes a trajectory cacheable at all.

    Started at "now", every request would be a unique key and the cache would
    never hit. The first timestamp must therefore be stable between calls.
    """
    first = client.get("/objects/25544/trajectory").json()
    second = client.get("/objects/25544/trajectory").json()
    assert first["points"][0]["timestamp"] == second["points"][0]["timestamp"]
    assert first == second


def test_an_anchored_track_still_propagates_real_positions(client) -> None:
    points = client.get("/objects/25544/trajectory").json()["points"]
    assert len(points) > 1
    assert all(point["valid"] for point in points)
    assert any(abs(point["x_km"]) > 1.0 for point in points)


# ------------------------------------------------------------------ batching
def test_one_request_returns_every_track(client) -> None:
    batch = client.get("/trajectories?norad_ids=25544,20580").json()
    assert [track["norad_id"] for track in batch] == ["25544", "20580"]


def test_a_batched_track_matches_the_single_one(client) -> None:
    single = client.get("/objects/25544/trajectory").json()
    batched = client.get("/trajectories?norad_ids=25544").json()[0]
    assert batched == single


def test_an_unknown_object_costs_its_own_track_and_no_more(client) -> None:
    """A globe missing one object is better than a globe missing all of them."""
    batch = client.get("/trajectories?norad_ids=25544,00000,20580").json()
    assert [track["norad_id"] for track in batch] == ["25544", "20580"]


def test_an_empty_request_is_refused(client) -> None:
    assert client.get("/trajectories?norad_ids=").status_code == 422


def test_a_batch_cannot_be_made_arbitrarily_large(client) -> None:
    ids = ",".join(str(100000 + n) for n in range(MAX_BATCH_TRAJECTORIES + 1))
    assert client.get(f"/trajectories?norad_ids={ids}").status_code == 422


def test_order_does_not_split_the_cache(client) -> None:
    before = stats(client)["misses"]
    client.get("/trajectories?norad_ids=25544,20580")
    client.get("/trajectories?norad_ids=20580,25544")
    # Same set, same work: the second ordering must not pay for propagation.
    assert stats(client)["misses"] == before + 1


def test_batching_is_charged_per_object_not_per_request(tmp_path) -> None:
    """Otherwise one call could do forty objects of work and pay for one."""
    app = create_app(f"sqlite:///{(tmp_path / 'cost.sqlite').as_posix()}")
    with TestClient(app) as client:
        seed(app, [("25544", "ISS", ISS)])
        ids = ",".join([str(100000 + n) for n in range(MAX_BATCH_TRAJECTORIES)])
        calls = (ANONYMOUS_PROPAGATION_UNITS_PER_MINUTE // MAX_BATCH_TRAJECTORIES) + 2
        statuses = [
            client.get(f"/trajectories?norad_ids={ids}&window_hours=3&step_sec=120").status_code
            for _ in range(calls)
        ]
    assert 429 in statuses


# --------------------------------------------------------- the trusted edge
def test_the_proxy_is_exempt_from_the_address_allowance(tmp_path, monkeypatch) -> None:
    """Behind a cache every visitor shares an address, so metering it would
    refuse the second person to open the site."""
    monkeypatch.setenv("SDEBRIS_PROXY_TOKEN", "a-shared-secret")
    app = create_app(f"sqlite:///{(tmp_path / 'proxy.sqlite').as_posix()}")
    with TestClient(app) as client:
        seed(app, [("25544", "ISS", ISS)])
        headers = {"x-sdebris-proxy": "a-shared-secret"}
        statuses = {
            client.get("/objects/25544/trajectory?step_sec=10&window_hours=24", headers=headers).status_code
            for _ in range(6)
        }
    assert statuses == {200}


def test_the_wrong_token_earns_no_exemption(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_PROXY_TOKEN", "a-shared-secret")
    app = create_app(f"sqlite:///{(tmp_path / 'wrong.sqlite').as_posix()}")
    with TestClient(app) as client:
        seed(app, [("25544", "ISS", ISS)])
        headers = {"x-sdebris-proxy": "guessed"}
        statuses = [
            client.get("/objects/25544/trajectory?step_sec=10&window_hours=24", headers=headers).status_code
            for _ in range(6)
        ]
    assert 429 in statuses


def test_no_token_configured_means_no_header_is_trusted(tmp_path, monkeypatch) -> None:
    """An empty secret must not become a skeleton key."""
    monkeypatch.delenv("SDEBRIS_PROXY_TOKEN", raising=False)
    app = create_app(f"sqlite:///{(tmp_path / 'none.sqlite').as_posix()}")
    with TestClient(app) as client:
        seed(app, [("25544", "ISS", ISS)])
        statuses = [
            client.get(
                "/objects/25544/trajectory?step_sec=10&window_hours=24",
                headers={"x-sdebris-proxy": ""},
            ).status_code
            for _ in range(6)
        ]
    assert 429 in statuses


# ------------------------------------------------------------- the structure
def test_the_cache_cannot_grow_without_bound() -> None:
    """The key carries caller-controlled query values, so an unbounded map
    would be a way to exhaust the instance's memory by walking step_sec."""
    cache = PublicCache(max_entries=4)
    for n in range(20):
        cache.get_or_compute(f"key-{n}", 60, lambda n=n: {"n": n})
    assert len(cache._entries) == 4
    assert cache.stats.evictions == 16


def test_an_expired_entry_is_recomputed() -> None:
    cache = PublicCache()
    calls = []
    cache.get_or_compute("k", 0, lambda: calls.append(1) or {"v": 1})
    cache.get_or_compute("k", 0, lambda: calls.append(1) or {"v": 1})
    assert len(calls) == 2
