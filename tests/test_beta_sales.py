"""During the beta nothing is sold, and people can ask to hear when it is."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sdebris.api.app import create_app
from sdebris.ontology.database import Database
from sdebris.ontology.orm import WaitlistEntryRecord


@pytest.fixture()
def url(tmp_path, monkeypatch):
    monkeypatch.delenv("SDEBRIS_BILLING_OPEN", raising=False)
    return f"sqlite:///{tmp_path / 'beta.sqlite'}"


def _headers(client: TestClient, subject: str, role: str = "analyst") -> dict[str, str]:
    body = client.post(
        "/auth/development-token", params={"subject": subject, "role": role}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _entries(url: str) -> list[WaitlistEntryRecord]:
    with Database(url).session_factory() as session:
        return list(session.query(WaitlistEntryRecord))


# -------------------------------------------------------------- sales closed
def test_sales_are_closed_unless_switched_on(url) -> None:
    from sdebris.billing import sales_open

    assert sales_open() is False


def test_the_pricing_endpoint_offers_nothing_to_buy(url) -> None:
    with TestClient(create_app(url)) as client:
        body = client.get("/billing/plans").json()
    assert body["sales_open"] is False
    assert body["offers"] == []
    # What Pro would offer is still described, for the page to show.
    assert {plan["plan"] for plan in body["plans"]} == {"free", "pro"}


@pytest.mark.parametrize("offer", ["pro-monthly", "pro-founding"])
def test_checkout_is_refused_for_every_offer(url, monkeypatch, offer: str) -> None:
    monkeypatch.setenv("SDEBRIS_DODO_API_KEY", "would-be-used-if-open")
    monkeypatch.setenv("SDEBRIS_BILLING_PRO_PRODUCT_ID", "prod_m")
    monkeypatch.setenv("SDEBRIS_BILLING_LIFETIME_PRODUCT_ID", "prod_f")
    with TestClient(create_app(url)) as client:
        response = client.post(
            "/billing/checkout",
            headers=_headers(client, "buyer"),
            json={"offer": offer, "accepted_terms": True},
        )
    assert response.status_code == 403
    assert "waitlist" in response.json()["detail"]


def test_a_quota_message_points_at_the_waitlist_not_a_purchase(url) -> None:
    from sdebris.billing.plans import Plan
    from sdebris.billing.quota import _exceeded

    detail = _exceeded("The Free plan allows 5 runs.", Plan.FREE).detail
    assert "waitlist" in detail
    assert "Upgrade to Pro" not in detail


# ------------------------------------------------------------------ waitlist
def test_anyone_can_join_without_an_account(url) -> None:
    with TestClient(create_app(url)) as client:
        response = client.post(
            "/waitlist", json={"email": " Someone@Example.com ", "interest": "founding"}
        )
    assert response.status_code == 202
    (entry,) = _entries(url)
    assert entry.email == "someone@example.com"
    assert entry.interest == "founding"
    assert entry.subject is None


def test_a_signed_in_join_is_linked_to_the_account(url) -> None:
    with TestClient(create_app(url)) as client:
        client.post("/waitlist", headers=_headers(client, "alice"),
                    json={"email": "alice@example.com", "note": "for my cubesat"})
    (entry,) = _entries(url)
    assert entry.subject == "alice"
    assert entry.note == "for my cubesat"


def test_joining_twice_keeps_one_entry_and_says_nothing_about_it(url) -> None:
    """The same answer either way, so the list cannot be probed for members."""
    with TestClient(create_app(url)) as client:
        first = client.post("/waitlist", json={"email": "dup@example.com"})
        second = client.post("/waitlist", json={"email": "dup@example.com", "interest": "either"})
    assert first.json() == second.json() == {"status": "joined"}
    (entry,) = _entries(url)
    assert entry.interest == "either"


def test_a_bot_filling_the_hidden_field_is_discarded_quietly(url) -> None:
    with TestClient(create_app(url)) as client:
        response = client.post("/waitlist", json={"email": "bot@spam.test", "website": "x"})
    assert response.status_code == 202
    assert _entries(url) == []


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "a b@c.com", "@example.com"])
def test_an_unusable_address_is_refused(url, email: str) -> None:
    with TestClient(create_app(url)) as client:
        assert client.post("/waitlist", json={"email": email}).status_code == 422


def test_one_address_cannot_fill_the_list(url) -> None:
    from sdebris.api.app import WAITLIST_JOINS_PER_WINDOW

    with TestClient(create_app(url)) as client:
        codes = [
            client.post("/waitlist", json={"email": f"user{n}@example.com"}).status_code
            for n in range(WAITLIST_JOINS_PER_WINDOW + 2)
        ]
    assert codes[:WAITLIST_JOINS_PER_WINDOW] == [202] * WAITLIST_JOINS_PER_WINDOW
    assert codes[-1] == 429


def test_only_an_administrator_can_read_the_list(url) -> None:
    with TestClient(create_app(url)) as client:
        client.post("/waitlist", json={"email": "listed@example.com"})
        assert client.get("/waitlist").status_code == 401
        assert client.get("/waitlist", headers=_headers(client, "nosy", "operator")).status_code == 403
        body = client.get("/waitlist", headers=_headers(client, "root", "admin")).json()
    assert body["count"] == 1
    assert body["entries"][0]["email"] == "listed@example.com"
