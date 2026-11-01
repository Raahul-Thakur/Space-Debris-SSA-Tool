"""Entitlements, quota enforcement and billing webhooks."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from sdebris.api.app import create_app
from sdebris.billing import Plan, WebhookError, verify_signature
from sdebris.billing.plans import FOUNDING_SEATS, PLAN_LIMITS
from sdebris.ontology.enums import OperatorRole

SECRET = "whsec_" + base64.b64encode(b"a-test-signing-secret").decode()
#: The development token derives the email claim as ``{subject}@localhost``,
#: so the grant has to be made against that address for the match to work.
BUYER_SUBJECT = "buyer"
BUYER = f"{BUYER_SUBJECT}@localhost"


# ----------------------------------------------------------------- signatures
def _sign(body: bytes, event_id: str, timestamp: int, secret: str = SECRET) -> dict[str, str]:
    signed = b"%s.%s.%s" % (event_id.encode(), str(timestamp).encode(), body)
    digest = hmac.new(
        base64.b64decode(secret.removeprefix("whsec_")), signed, hashlib.sha256
    ).digest()
    return {
        "webhook-id": event_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": "v1," + base64.b64encode(digest).decode(),
    }


def test_a_valid_signature_is_accepted() -> None:
    body = b'{"type":"payment.succeeded"}'
    now = datetime.now(timezone.utc)
    headers = _sign(body, "evt_1", int(now.timestamp()))
    assert verify_signature(secret=SECRET, headers=headers, body=body, now=now) == "evt_1"


def test_a_tampered_body_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    headers = _sign(b'{"amount":1}', "evt_2", int(now.timestamp()))
    with pytest.raises(WebhookError, match="no signature"):
        verify_signature(secret=SECRET, headers=headers, body=b'{"amount":9999}', now=now)


def test_an_old_delivery_is_rejected_as_a_replay() -> None:
    body = b"{}"
    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    headers = _sign(body, "evt_3", int(stale.timestamp()))
    with pytest.raises(WebhookError, match="replay window"):
        verify_signature(secret=SECRET, headers=headers, body=body)


def test_missing_headers_are_rejected() -> None:
    with pytest.raises(WebhookError, match="signature headers"):
        verify_signature(secret=SECRET, headers={}, body=b"{}")


# ------------------------------------------------------------------- fixtures
def _token(app, *, subject: str = BUYER_SUBJECT, role: OperatorRole = OperatorRole.ANALYST) -> str:
    return app.state.authenticator.issue_development_token(subject=subject, role=role)


def _run(app, scenario) -> None:
    async def wrapped() -> None:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            await scenario(client)

    asyncio.run(wrapped())


#: Product ids the tests configure as the ones on sale.
MONTHLY = "prod_monthly"
FOUNDING = "prod_founding"


def _sell(monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SDEBRIS_BILLING_PRO_PRODUCT_ID", MONTHLY)
    monkeypatch.setenv("SDEBRIS_BILLING_LIFETIME_PRODUCT_ID", FOUNDING)


def _payment(ref: str, *, email: str = BUYER, product: str = FOUNDING, **data) -> dict:
    """A ``payment.succeeded`` shaped like Dodo's: the product is in the cart."""
    return {
        "type": "payment.succeeded",
        "data": {
            "payload_type": "Payment",
            "payment_id": ref,
            "customer": {"customer_id": "cus_1", "email": email, "name": "Buyer"},
            "product_cart": [{"product_id": product, "quantity": 1}],
            **data,
        },
    }


def _subscription(event_type: str, ref: str, *, email: str = BUYER, **data) -> dict:
    return {
        "type": event_type,
        "data": {
            "payload_type": "Subscription",
            "subscription_id": ref,
            "product_id": MONTHLY,
            "customer": {"customer_id": "cus_1", "email": email, "name": "Buyer"},
            **data,
        },
    }


async def _deliver(client: httpx.AsyncClient, payload: dict, event_id: str) -> httpx.Response:
    body = json.dumps(payload).encode()
    headers = _sign(body, event_id, int(datetime.now(timezone.utc).timestamp()))
    return await client.post("/billing/webhook", content=body, headers=headers)


async def _plan(client: httpx.AsyncClient, app, subject: str = BUYER_SUBJECT) -> dict:
    client.headers["Authorization"] = f"Bearer {_token(app, subject=subject)}"
    return (await client.get("/billing/me")).json()


# ---------------------------------------------------------------- entitlements
def test_a_new_account_is_on_the_free_plan(tmp_path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'b1.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        body = (await client.get("/billing/me")).json()
        assert body["plan"] == "free"
        assert body["limits"]["screening_runs_per_month"] == (
            PLAN_LIMITS[Plan.FREE].screening_runs_per_month
        )
        assert body["usage"]["screening_runs_this_month"] == 0

    _run(app, scenario)


def test_the_founding_purchase_grants_access_that_never_expires(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b2.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        delivered = await _deliver(client, _payment("pay_life"), "evt_life")
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()["outcome"] == "granted-lifetime"
        me = await _plan(client, app)
        assert me["plan"] == "pro"
        assert me["expires_at"] is None

    _run(app, scenario)


def test_a_payment_for_a_product_not_on_sale_grants_nothing(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b2b.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        delivered = await _deliver(client, _payment("pay_x", product="prod_tshirt"), "evt_x")
        assert delivered.json()["outcome"] == "ignored-unknown-product"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_nothing_is_granted_when_no_products_are_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("SDEBRIS_BILLING_PRO_PRODUCT_ID", raising=False)
    monkeypatch.delenv("SDEBRIS_BILLING_LIFETIME_PRODUCT_ID", raising=False)
    app = create_app(f"sqlite:///{(tmp_path / 'b2c.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        delivered = await _deliver(client, _payment("pay_y"), "evt_y")
        assert delivered.json()["outcome"] == "ignored-unknown-product"

    _run(app, scenario)


def test_a_redelivered_webhook_does_not_grant_twice(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b3.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        first = await _deliver(client, _payment("pay_2"), "evt_dup")
        second = await _deliver(client, _payment("pay_2"), "evt_dup")
        assert first.json()["outcome"] == "granted-lifetime"
        assert second.json()["status"] == "duplicate"

    _run(app, scenario)


def test_a_refund_revokes_a_founding_seat(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b4.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        await _deliver(client, _payment("pay_3"), "evt_p")
        refund = {
            "type": "refund.succeeded",
            "data": {"payload_type": "Refund", "refund_id": "ref_1", "payment_id": "pay_3"},
        }
        assert (await _deliver(client, refund, "evt_r")).json()["outcome"] == "revoked"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_a_refunded_renewal_revokes_the_subscription(tmp_path, monkeypatch) -> None:
    """A refund names only the payment; the ledger links it to the subscription."""
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b4b.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        paid = _payment("pay_sub_1", product_cart=None, subscription_id="sub_r")
        assert (await _deliver(client, paid, "evt_sp")).json()["outcome"] == "recorded"
        active = _subscription(
            "subscription.active", "sub_r", next_billing_date=renewal.isoformat()
        )
        assert (await _deliver(client, active, "evt_sa")).json()["outcome"] == "granted"
        assert (await _plan(client, app))["plan"] == "pro"

        refund = {
            "type": "refund.succeeded",
            "data": {"payload_type": "Refund", "refund_id": "ref_2", "payment_id": "pay_sub_1"},
        }
        assert (await _deliver(client, refund, "evt_sr")).json()["outcome"] == "revoked"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_a_won_dispute_restores_access(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b4c.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        await _deliver(client, _payment("pay_d"), "evt_dp")
        dispute = {"payload_type": "Dispute", "dispute_id": "dsp_1", "payment_id": "pay_d"}
        await _deliver(client, {"type": "dispute.opened", "data": dispute}, "evt_do")
        assert (await _plan(client, app))["plan"] == "free"
        won = await _deliver(client, {"type": "dispute.won", "data": dispute}, "evt_dw")
        assert won.json()["outcome"] == "restored"
        assert (await _plan(client, app))["plan"] == "pro"

    _run(app, scenario)


def test_a_grant_reaches_the_account_that_started_checkout(tmp_path, monkeypatch) -> None:
    """Paying with a different email must not strand the purchase."""
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b4d.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        paid = _payment(
            "pay_m", email="work-card@example.com", metadata={"subject": BUYER_SUBJECT}
        )
        await _deliver(client, paid, "evt_m")
        assert (await _plan(client, app))["plan"] == "pro"

    _run(app, scenario)


def test_an_unsigned_webhook_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'b5.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = json.dumps(_payment("x", email="attacker@example.com")).encode()
        assert (await client.post("/billing/webhook", content=body)).status_code == 400

    _run(app, scenario)


def test_the_webhook_refuses_to_run_unconfigured(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SDEBRIS_BILLING_WEBHOOK_SECRET", raising=False)
    app = create_app(f"sqlite:///{(tmp_path / 'b6.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        response = await client.post("/billing/webhook", content=b"{}")
        assert response.status_code == 503

    _run(app, scenario)


# ---------------------------------------------------------------------- quotas
def test_free_plan_refuses_a_window_longer_than_its_limit(tmp_path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'b7.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/commands/execute",
            json={"command": "screen 25544 --window 72h --threshold 25km --cached"},
        )
        assert response.status_code == 402, response.text
        assert "24h" in response.json()["detail"]
        assert "Upgrade to Pro" in response.json()["detail"]

    _run(app, scenario)


def test_the_paid_plan_allows_the_long_window(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'b8.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        await _deliver(client, _payment("pay_8"), "evt_8")
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/commands/execute",
            json={"command": "screen 25544 --window 72h --threshold 25km --cached"},
        )
        assert response.status_code == 200, response.text

    _run(app, scenario)


def test_the_monthly_run_allowance_is_enforced(tmp_path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'b9.db').as_posix()}")
    allowance = PLAN_LIMITS[Plan.FREE].screening_runs_per_month
    assert allowance is not None

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        command = {"command": "screen 25544 --window 1h --threshold 5km --cached"}
        for attempt in range(allowance):
            ok = await client.post("/commands/execute", json=command)
            assert ok.status_code == 200, f"run {attempt} rejected: {ok.text}"

        blocked = await client.post("/commands/execute", json=command)
        assert blocked.status_code == 402
        assert str(allowance) in blocked.json()["detail"]

        # The refusal is audited rather than silently dropped.
        usage = (await client.get("/billing/me")).json()["usage"]
        assert usage["screening_runs_this_month"] == allowance

    _run(app, scenario)


def test_a_quota_refusal_is_recorded_in_the_activity_feed(tmp_path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'b10.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        await client.post(
            "/commands/execute",
            json={"command": "screen 25544 --window 72h --threshold 25km --cached"},
        )
        feed = (await client.get("/activity")).json()
        refusals = [
            item
            for item in feed["items"]
            if item["kind"] == "command" and "24h" in item["detail"]
        ]
        assert refusals, "the quota refusal should be visible in the audit feed"
        assert refusals[0]["severity"] == "critical"

    _run(app, scenario)


def test_seed_known_is_not_blocked_for_a_new_free_account(tmp_path) -> None:
    """The tour tells first-time visitors to run this; it must not paywall."""
    app = create_app(f"sqlite:///{(tmp_path / 'b11.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/commands/execute", json={"command": "monitor seed-known"}
        )
        assert response.status_code == 200, response.text

    _run(app, scenario)


def test_the_direct_job_endpoint_is_metered_too(tmp_path) -> None:
    """Quotas must not be bypassable by skipping the command surface."""
    app = create_app(f"sqlite:///{(tmp_path / 'b12.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/screening-jobs",
            json={"norad_id": "25544", "window_hours": 72, "refresh_catalog": False},
        )
        assert response.status_code == 402, response.text

    _run(app, scenario)


# ------------------------------------------------------------- pricing model
def test_a_subscription_expires_at_the_renewal_date(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'p2.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        active = _subscription(
            "subscription.active", "sub_1", next_billing_date=renewal.isoformat()
        )
        await _deliver(client, active, "evt_sub")
        me = await _plan(client, app)
        assert me["plan"] == "pro"
        expires = datetime.fromisoformat(me["expires_at"])
        # Renewal plus the grace period that stops a late webhook cutting access.
        assert renewal < expires <= renewal + timedelta(days=4)

    _run(app, scenario)


def test_cancelling_keeps_access_until_the_paid_period_ends(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'p2b.db').as_posix()}")
    period_end = datetime.now(timezone.utc) + timedelta(days=12)

    async def scenario(client: httpx.AsyncClient) -> None:
        start = _subscription(
            "subscription.active", "sub_c", next_billing_date=period_end.isoformat()
        )
        await _deliver(client, start, "evt_c1")
        cancel = _subscription(
            "subscription.cancelled", "sub_c", next_billing_date=period_end.isoformat()
        )
        cancelled = await _deliver(client, cancel, "evt_c2")
        assert cancelled.json()["outcome"] == "ends-at-period-end"

        me = await _plan(client, app)
        assert me["plan"] == "pro"
        # No renewal is coming, so the grace period is dropped.
        expires = datetime.fromisoformat(me["expires_at"])
        assert abs(expires - period_end) < timedelta(seconds=1)

    _run(app, scenario)


def test_an_expired_subscription_loses_access(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'p2c.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        start = _subscription(
            "subscription.active", "sub_e", next_billing_date=renewal.isoformat()
        )
        await _deliver(client, start, "evt_e1")
        expired = await _deliver(client, _subscription("subscription.expired", "sub_e"), "evt_e2")
        assert expired.json()["outcome"] == "revoked"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_a_lapsed_subscription_falls_back_to_free(tmp_path) -> None:
    from sdebris.billing import Plan as _Plan
    from sdebris.billing.entitlements import grant
    from sdebris.ontology.database import Database

    url = f"sqlite:///{(tmp_path / 'p3.db').as_posix()}"
    database = Database(url)
    database.initialize()
    with database.session_factory() as session:
        grant(
            session,
            email=BUYER,
            plan=_Plan.PRO,
            source="dodo",
            external_ref="sub_old",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.commit()

    app = create_app(url)

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        assert (await client.get("/billing/me")).json()["plan"] == "free"

    _run(app, scenario)


def test_the_plans_endpoint_offers_the_founding_seat_while_stock_remains(tmp_path) -> None:
    app = create_app(f"sqlite:///{(tmp_path / 'p4.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        body = (await client.get("/billing/plans")).json()
        codes = {offer["code"]: offer for offer in body["offers"]}
        assert codes["pro-monthly"]["price_usd"] == 6.0
        assert codes["pro-monthly"]["interval"] == "month"
        assert codes["pro-founding"]["price_usd"] == 29.0
        assert codes["pro-founding"]["seats_remaining"] == FOUNDING_SEATS
        assert body["current_plan"] == "free"

    _run(app, scenario)


def test_the_founding_offer_disappears_once_the_seats_are_gone(tmp_path, monkeypatch) -> None:
    """The cap is a selling decision, so it withdraws the offer, not the grant."""
    from sdebris.billing import Plan as _Plan
    from sdebris.billing.entitlements import grant
    from sdebris.ontology.database import Database

    monkeypatch.setattr("sdebris.api.app.FOUNDING_SEATS", 2)
    url = f"sqlite:///{(tmp_path / 'p5.db').as_posix()}"
    database = Database(url)
    database.initialize()
    with database.session_factory() as session:
        for index in range(2):
            grant(
                session,
                email=f"founder{index}@localhost",
                plan=_Plan.PRO,
                source="dodo",
                external_ref=f"pay_founder_{index}",
                expires_at=None,
            )
        session.commit()

    app = create_app(url)

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        body = (await client.get("/billing/plans")).json()
        codes = {offer["code"] for offer in body["offers"]}
        assert "pro-monthly" in codes
        assert "pro-founding" not in codes

    _run(app, scenario)


def test_the_plans_endpoint_is_readable_without_an_account(tmp_path) -> None:
    """A visitor sees the price before being asked to sign in."""
    app = create_app(f"sqlite:///{(tmp_path / 'p6.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = (await client.get("/billing/plans")).json()
        assert body["current_plan"] == "free"
        limits = {plan["plan"]: plan for plan in body["plans"]}
        assert limits["pro"]["max_window_hours"] == PLAN_LIMITS[Plan.PRO].max_window_hours

    _run(app, scenario)


# -------------------------------------------------------------------- checkout
class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


def _fake_provider(monkeypatch) -> list[dict]:
    """Stand in for Dodo's API, recording what was sent."""
    calls: list[dict] = []

    def post(url, *, json=None, params=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "params": params, "headers": headers})
        if url.endswith("/checkouts"):
            return _FakeResponse({"session_id": "cks_1", "checkout_url": "https://pay.test/c"})
        return _FakeResponse({"link": "https://pay.test/portal"})

    monkeypatch.setenv("SDEBRIS_DODO_API_KEY", "test-key")
    monkeypatch.setattr("sdebris.billing.dodo.requests.post", post)
    return calls


def test_checkout_sends_the_account_in_metadata(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'c1.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/billing/checkout", json={"offer": "pro-monthly", "accepted_terms": True}
        )
        assert response.status_code == 200, response.text
        assert response.json()["checkout_url"] == "https://pay.test/c"

    _run(app, scenario)
    sent = calls[0]
    assert sent["url"] == "https://test.dodopayments.com/checkouts"
    assert sent["json"]["product_cart"] == [{"product_id": MONTHLY, "quantity": 1}]
    assert sent["json"]["metadata"]["subject"] == BUYER_SUBJECT
    assert sent["json"]["customer"] == {"email": BUYER}
    assert sent["json"]["return_url"].endswith("/account?checkout=complete")


def test_checkout_requires_the_terms_to_be_accepted(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'c2.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post("/billing/checkout", json={"offer": "pro-monthly"})
        assert response.status_code == 400

    _run(app, scenario)


def test_checkout_needs_an_account(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'c3.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/billing/checkout", json={"offer": "pro-monthly", "accepted_terms": True}
        )
        assert response.status_code == 401

    _run(app, scenario)


def test_checkout_refuses_a_founding_seat_once_they_are_gone(tmp_path, monkeypatch) -> None:
    """The cap is enforced here, because a paid grant is always honoured."""
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    monkeypatch.setattr("sdebris.api.app.FOUNDING_SEATS", 1)
    app = create_app(f"sqlite:///{(tmp_path / 'c4.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        await _deliver(client, _payment("pay_first", email="first@localhost"), "evt_first")
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/billing/checkout", json={"offer": "pro-founding", "accepted_terms": True}
        )
        assert response.status_code == 409

    _run(app, scenario)
    assert calls == [], "no checkout should have been created"


def test_checkout_is_unavailable_until_billing_is_configured(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    monkeypatch.delenv("SDEBRIS_DODO_API_KEY", raising=False)
    app = create_app(f"sqlite:///{(tmp_path / 'c5.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/billing/checkout", json={"offer": "pro-monthly", "accepted_terms": True}
        )
        assert response.status_code == 503

    _run(app, scenario)


def test_a_subscriber_is_not_sold_a_second_subscription(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'c6.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        start = _subscription(
            "subscription.active", "sub_twice", next_billing_date=renewal.isoformat()
        )
        await _deliver(client, start, "evt_t")
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/billing/checkout", json={"offer": "pro-monthly", "accepted_terms": True}
        )
        assert response.status_code == 409

    _run(app, scenario)


def test_the_portal_opens_for_a_paying_customer(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'c7.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        start = _subscription(
            "subscription.active", "sub_portal", next_billing_date=renewal.isoformat()
        )
        await _deliver(client, start, "evt_portal")
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post("/billing/portal")
        assert response.status_code == 200, response.text
        assert response.json()["url"] == "https://pay.test/portal"

    _run(app, scenario)
    assert calls[0]["url"].endswith("/customers/cus_1/customer-portal/session")


def test_the_portal_explains_when_there_is_nothing_to_manage(tmp_path, monkeypatch) -> None:
    _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'c8.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        assert (await client.post("/billing/portal")).status_code == 404

    _run(app, scenario)


def test_the_ledger_does_not_keep_card_or_address_details(tmp_path, monkeypatch) -> None:
    from sdebris.ontology.database import Database
    from sdebris.ontology.orm import BillingEventRecord

    _sell(monkeypatch)
    url = f"sqlite:///{(tmp_path / 'l1.db').as_posix()}"
    app = create_app(url)

    async def scenario(client: httpx.AsyncClient) -> None:
        paid = _payment(
            "pay_card",
            card_last_four="4242",
            card_holder_name="A Buyer",
            billing={"country": "IN", "street": "1 Orbit Road"},
        )
        await _deliver(client, paid, "evt_card")

    _run(app, scenario)
    with Database(url).session_factory() as session:
        stored = session.query(BillingEventRecord).one()
        assert stored.payment_id == "pay_card"
        assert "card_last_four" not in stored.payload["data"]
        assert "billing" not in stored.payload["data"]
        assert stored.payload["data"]["customer"]["email"] == BUYER
