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
    """A refund names only the payment; the ledger links it to the subscription.

    It also cancels the subscription with the provider. Withdrawing access
    alone left it renewing, so the customer was charged again next month.
    """
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
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
        outcome = (await _deliver(client, refund, "evt_sr")).json()["outcome"]
        assert outcome == "revoked-and-cancelled"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)
    cancels = [call for call in calls if call["method"] == "patch"]
    assert len(cancels) == 1
    assert cancels[0]["url"] == "https://test.dodopayments.com/subscriptions/sub_r"
    assert cancels[0]["json"]["status"] == "cancelled"


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


def _fake_provider(monkeypatch, *, subscription_status: str = "active") -> list[dict]:
    """Stand in for Dodo's API, recording what was sent."""
    calls: list[dict] = []

    def post(url, *, json=None, params=None, headers=None, timeout=None):
        calls.append({"method": "post", "url": url, "json": json, "params": params, "headers": headers})
        if url.endswith("/checkouts"):
            return _FakeResponse({"session_id": "cks_1", "checkout_url": "https://pay.test/c"})
        if url.endswith("/refunds"):
            return _FakeResponse({"refund_id": "ref_auto", "payment_id": json["payment_id"]})
        return _FakeResponse({"link": "https://pay.test/portal"})

    def get(url, *, json=None, params=None, headers=None, timeout=None):
        calls.append({"method": "get", "url": url})
        return _FakeResponse({"subscription_id": url.rsplit("/", 1)[-1], "status": subscription_status})

    def patch(url, *, json=None, params=None, headers=None, timeout=None):
        calls.append({"method": "patch", "url": url, "json": json})
        return _FakeResponse({"subscription_id": url.rsplit("/", 1)[-1], "status": "cancelled"})

    monkeypatch.setenv("SDEBRIS_DODO_API_KEY", "test-key")
    monkeypatch.setattr("sdebris.billing.dodo.requests.post", post)
    monkeypatch.setattr("sdebris.billing.dodo.requests.get", get)
    monkeypatch.setattr("sdebris.billing.dodo.requests.patch", patch)
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


# ------------------------------------------------- refunds cancel subscriptions
def _at(minutes: int) -> str:
    """An event time, so tests can deliver events out of order."""
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def _subscribed(renewal: datetime, *, when: int = 0) -> list[tuple[dict, str]]:
    """The deliveries that start a subscription paid by ``pay_s``."""
    paid = _payment("pay_s", product_cart=None, subscription_id="sub_x")
    active = _subscription("subscription.active", "sub_x", next_billing_date=renewal.isoformat())
    active["timestamp"] = _at(when)
    return [(paid, "evt_paid"), (active, "evt_active")]


def _refund(payment_id: str, *, partial: bool = False, when: int = 10) -> dict:
    return {
        "type": "refund.succeeded",
        "timestamp": _at(when),
        "data": {
            "payload_type": "Refund",
            "refund_id": f"ref_{payment_id}",
            "payment_id": payment_id,
            "is_partial": partial,
        },
    }


def test_a_refunded_subscription_is_not_handed_back_by_its_next_renewal(
    tmp_path, monkeypatch
) -> None:
    _sell(monkeypatch)
    _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'r1.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        for payload, event_id in _subscribed(renewal):
            await _deliver(client, payload, event_id)
        await _deliver(client, _refund("pay_s"), "evt_refund")
        renewed = _subscription(
            "subscription.renewed", "sub_x",
            next_billing_date=(renewal + timedelta(days=30)).isoformat(),
        )
        renewed["timestamp"] = _at(60)
        response = await _deliver(client, renewed, "evt_renewed")
        assert response.json()["outcome"] == "ignored-refunded"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_a_failed_cancellation_is_retried_rather_than_lost(tmp_path, monkeypatch) -> None:
    """If Dodo cannot be reached, nothing is kept and the webhook asks for a retry."""
    _sell(monkeypatch)
    _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'r2.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    def unreachable(*args, **kwargs):
        import requests

        raise requests.ConnectionError("down")

    async def scenario(client: httpx.AsyncClient) -> None:
        for payload, event_id in _subscribed(renewal):
            await _deliver(client, payload, event_id)

        monkeypatch.setattr("sdebris.billing.dodo.requests.get", unreachable)
        failed = await _deliver(client, _refund("pay_s"), "evt_refund")
        assert failed.status_code == 503
        assert (await _plan(client, app))["plan"] == "pro", "nothing should have been kept"

        _fake_provider(monkeypatch)
        retried = await _deliver(client, _refund("pay_s"), "evt_refund")
        assert retried.json()["outcome"] == "revoked-and-cancelled"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_an_already_finished_subscription_is_not_cancelled_twice(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch, subscription_status="cancelled")
    app = create_app(f"sqlite:///{(tmp_path / 'r3.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        for payload, event_id in _subscribed(renewal):
            await _deliver(client, payload, event_id)
        response = await _deliver(client, _refund("pay_s"), "evt_refund")
        assert response.json()["outcome"] == "revoked-and-cancelled"

    _run(app, scenario)
    assert not [call for call in calls if call["method"] == "patch"]


def test_a_partial_refund_is_a_credit_and_keeps_pro(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'r4.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        for payload, event_id in _subscribed(renewal):
            await _deliver(client, payload, event_id)
        response = await _deliver(client, _refund("pay_s", partial=True), "evt_refund")
        assert response.json()["outcome"] == "partial-refund-kept"
        assert (await _plan(client, app))["plan"] == "pro"

    _run(app, scenario)
    assert not [call for call in calls if call["method"] == "patch"]


def test_a_lost_dispute_cancels_the_subscription(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'r5.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        for payload, event_id in _subscribed(renewal):
            await _deliver(client, payload, event_id)
        lost = {
            "type": "dispute.lost",
            "timestamp": _at(20),
            "data": {"payload_type": "Dispute", "dispute_id": "dsp_9", "payment_id": "pay_s"},
        }
        assert (await _deliver(client, lost, "evt_lost")).json()["outcome"] == "revoked-and-cancelled"

    _run(app, scenario)
    assert [call["url"] for call in calls if call["method"] == "patch"] == [
        "https://test.dodopayments.com/subscriptions/sub_x"
    ]


def test_a_withdrawn_dispute_restores_access(tmp_path, monkeypatch) -> None:
    """Only a won dispute used to restore; a withdrawn one left Pro suspended."""
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'r6.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        await _deliver(client, _payment("pay_w"), "evt_pw")
        dispute = {"payload_type": "Dispute", "dispute_id": "dsp_w", "payment_id": "pay_w"}
        await _deliver(client, {"type": "dispute.opened", "data": dispute}, "evt_wo")
        assert (await _plan(client, app))["plan"] == "free"
        withdrawn = await _deliver(client, {"type": "dispute.cancelled", "data": dispute}, "evt_wc")
        assert withdrawn.json()["outcome"] == "restored"
        assert (await _plan(client, app))["plan"] == "pro"

    _run(app, scenario)


# ------------------------------------------------------- out-of-order events
def test_a_late_retry_cannot_undo_a_cancellation(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'o1.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)
    period_end = datetime.now(timezone.utc) + timedelta(days=5)

    async def scenario(client: httpx.AsyncClient) -> None:
        active = _subscription("subscription.active", "sub_o", next_billing_date=renewal.isoformat())
        active["timestamp"] = _at(0)
        await _deliver(client, active, "evt_a1")
        cancelled = _subscription(
            "subscription.cancelled", "sub_o", next_billing_date=period_end.isoformat()
        )
        cancelled["timestamp"] = _at(20)
        await _deliver(client, cancelled, "evt_c")

        # The same subscription.active, redelivered late under a new delivery id.
        late = await _deliver(client, active, "evt_a1_retry")
        assert late.json()["outcome"] == "ignored-stale"
        plan = await _plan(client, app)
        assert plan["plan"] == "pro"
        assert plan["cancelled"] is True
        assert datetime.fromisoformat(plan["expires_at"]) <= period_end + timedelta(seconds=1)

    _run(app, scenario)


def test_a_late_renewal_cannot_revive_a_subscription_on_hold(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'o2.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        active = _subscription("subscription.active", "sub_h", next_billing_date=renewal.isoformat())
        active["timestamp"] = _at(0)
        await _deliver(client, active, "evt_h1")
        on_hold = _subscription("subscription.on_hold", "sub_h")
        on_hold["timestamp"] = _at(30)
        await _deliver(client, on_hold, "evt_h2")
        renewed = _subscription("subscription.renewed", "sub_h", next_billing_date=renewal.isoformat())
        renewed["timestamp"] = _at(25)  # happened before the hold, arrived after
        assert (await _deliver(client, renewed, "evt_h3")).json()["outcome"] == "ignored-stale"
        assert (await _plan(client, app))["plan"] == "free"

    _run(app, scenario)


def test_a_genuinely_newer_renewal_still_applies(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'o3.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        on_hold = _subscription("subscription.on_hold", "sub_n")
        active = _subscription("subscription.active", "sub_n", next_billing_date=renewal.isoformat())
        active["timestamp"] = _at(0)
        on_hold["timestamp"] = _at(10)
        renewed = _subscription("subscription.renewed", "sub_n", next_billing_date=renewal.isoformat())
        renewed["timestamp"] = _at(40)  # the card was fixed and the payment went through
        await _deliver(client, active, "evt_n1")
        await _deliver(client, on_hold, "evt_n2")
        assert (await _deliver(client, renewed, "evt_n3")).json()["outcome"] == "granted"
        assert (await _plan(client, app))["plan"] == "pro"

    _run(app, scenario)


# ------------------------------------------------------- the founding-seat cap
def _founding_checkout(client: httpx.AsyncClient, app, subject: str):
    client.headers["Authorization"] = f"Bearer {_token(app, subject=subject)}"
    return client.post("/billing/checkout", json={"offer": "pro-founding", "accepted_terms": True})


def _founding_payment(ref: str, subject: str) -> dict:
    return _payment(ref, email=f"{subject}@localhost", metadata={"subject": subject})


def test_the_last_seat_cannot_be_sold_twice(tmp_path, monkeypatch) -> None:
    """At seat 99 every open checkout used to be able to pay and be granted."""
    _sell(monkeypatch)
    _fake_provider(monkeypatch)
    monkeypatch.setattr("sdebris.api.app.FOUNDING_SEATS", 1)
    app = create_app(f"sqlite:///{(tmp_path / 's1.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _founding_checkout(client, app, "first")).status_code == 200
        second = await _founding_checkout(client, app, "second")
        assert second.status_code == 409
        assert "reserved" in second.json()["detail"]
        # The offer is gone for everyone else while the seat is reserved...
        offers = (await client.get("/billing/plans")).json()["offers"]
        assert "pro-founding" not in {offer["code"] for offer in offers}
        # ...and the holder can still restart their own checkout.
        assert (await _founding_checkout(client, app, "first")).status_code == 200

        paid = await _deliver(client, _founding_payment("pay_first", "first"), "evt_first")
        assert paid.json()["outcome"] == "granted-lifetime"

    _run(app, scenario)


def test_a_purchase_that_skipped_checkout_is_refunded_when_seats_are_gone(
    tmp_path, monkeypatch
) -> None:
    """A Dodo payment link bypasses checkout; past the cap it is refunded, not granted."""
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    monkeypatch.setattr("sdebris.api.app.FOUNDING_SEATS", 1)
    app = create_app(f"sqlite:///{(tmp_path / 's2.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        await _deliver(client, _founding_payment("pay_one", "one"), "evt_one")
        extra = await _deliver(client, _founding_payment("pay_two", "two"), "evt_two")
        assert extra.json()["outcome"] == "refunded-over-cap"
        assert (await _plan(client, app, subject="two"))["plan"] == "free"
        assert (await _plan(client, app, subject="one"))["plan"] == "pro"

    _run(app, scenario)
    refunds = [call for call in calls if call["url"].endswith("/refunds")]
    assert [call["json"]["payment_id"] for call in refunds] == ["pay_two"]


def test_a_seat_reserved_and_paid_is_honoured(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    monkeypatch.setattr("sdebris.api.app.FOUNDING_SEATS", 1)
    app = create_app(f"sqlite:///{(tmp_path / 's3.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _founding_checkout(client, app, "holder")).status_code == 200
        paid = await _deliver(client, _founding_payment("pay_h", "holder"), "evt_h")
        assert paid.json()["outcome"] == "granted-lifetime"
        assert (await _plan(client, app, subject="holder"))["plan"] == "pro"
        # The seat is now paid for, not reserved: still none left for others.
        assert (await _founding_checkout(client, app, "late")).status_code == 409

    _run(app, scenario)
    assert not [call for call in calls if call["url"].endswith("/refunds")]


def test_a_failed_checkout_gives_its_seat_back(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    monkeypatch.setattr("sdebris.api.app.FOUNDING_SEATS", 1)
    monkeypatch.setenv("SDEBRIS_DODO_API_KEY", "test-key")

    def down(*args, **kwargs):
        import requests

        raise requests.ConnectionError("down")

    monkeypatch.setattr("sdebris.billing.dodo.requests.post", down)
    app = create_app(f"sqlite:///{(tmp_path / 's4.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _founding_checkout(client, app, "unlucky")).status_code == 503
        _fake_provider(monkeypatch)
        assert (await _founding_checkout(client, app, "next")).status_code == 200

    _run(app, scenario)


# ------------------------------------------------------------ terms of sale
def test_checkout_records_which_terms_were_accepted_and_when(tmp_path, monkeypatch) -> None:
    from sdebris.billing import TERMS_VERSION

    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 't1.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        response = await client.post(
            "/billing/checkout", json={"offer": "pro-monthly", "accepted_terms": True}
        )
        assert response.status_code == 200, response.text

    _run(app, scenario)
    metadata = calls[0]["json"]["metadata"]
    assert metadata["terms_version"] == TERMS_VERSION
    accepted = datetime.fromisoformat(metadata["terms_accepted_at"])
    assert abs(datetime.now(timezone.utc) - accepted) < timedelta(minutes=1)


def test_the_grant_keeps_the_terms_the_buyer_accepted(tmp_path, monkeypatch) -> None:
    from sdebris.ontology.database import Database
    from sdebris.ontology.orm import EntitlementRecord

    _sell(monkeypatch)
    url = f"sqlite:///{(tmp_path / 't2.db').as_posix()}"
    app = create_app(url)

    async def scenario(client: httpx.AsyncClient) -> None:
        paid = _payment(
            "pay_terms",
            metadata={"subject": BUYER_SUBJECT, "terms_version": "2026-11-06",
                      "terms_accepted_at": "2026-11-06T10:00:00+00:00"},
        )
        assert (await _deliver(client, paid, "evt_terms")).status_code == 200

    _run(app, scenario)
    database = Database(url)
    with database.session_factory() as session:
        record = session.query(EntitlementRecord).filter_by(external_ref="pay_terms").one()
        assert record.metadata_json["terms_version"] == "2026-11-06"
        assert record.metadata_json["terms_accepted_at"] == "2026-11-06T10:00:00+00:00"


def test_the_recorded_terms_version_matches_the_terms_page() -> None:
    """TERMS_VERSION is the page's 'Last updated' date; changing one means changing both."""
    import re
    from pathlib import Path

    from sdebris.billing import TERMS_VERSION

    page = Path(__file__).parents[1] / "web" / "app" / "terms" / "page.tsx"
    updated = re.search(r'const UPDATED = "([^"]+)"', page.read_text()).group(1)
    parsed = datetime.strptime(updated, "%d %B %Y").replace(tzinfo=timezone.utc)
    assert parsed.date().isoformat() == TERMS_VERSION


# ------------------------------------------- founding seat for a subscriber
def test_buying_a_founding_seat_cancels_the_monthly_plan(tmp_path, monkeypatch) -> None:
    """A subscriber upgrading to lifetime used to keep paying $6 a month."""
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'f1.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        active = _subscription(
            "subscription.active", "sub_up", next_billing_date=renewal.isoformat(),
            metadata={"subject": BUYER_SUBJECT},
        )
        await _deliver(client, active, "evt_up_a")
        founding = _payment("pay_up", metadata={"subject": BUYER_SUBJECT})
        response = await _deliver(client, founding, "evt_up_f")
        assert response.json()["outcome"] == "granted-lifetime-replaced-subscription"
        plan = await _plan(client, app)
        assert plan["plan"] == "pro"
        assert plan["expires_at"] is None, "the lifetime grant should now be the one in force"

    _run(app, scenario)
    cancels = [call for call in calls if call["method"] == "patch"]
    assert [call["url"] for call in cancels] == [
        "https://test.dodopayments.com/subscriptions/sub_up"
    ]


def test_a_founding_seat_alone_cancels_nothing(tmp_path, monkeypatch) -> None:
    _sell(monkeypatch)
    calls = _fake_provider(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'f2.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        founding = _payment("pay_solo", metadata={"subject": BUYER_SUBJECT})
        assert (await _deliver(client, founding, "evt_solo")).json()["outcome"] == "granted-lifetime"

    _run(app, scenario)
    assert not [call for call in calls if call["method"] == "patch"]


# -------------------------------------------------- one purchase, one account
def test_a_purchase_unlocks_only_the_account_that_made_it(tmp_path, monkeypatch) -> None:
    """The email typed at Dodo's checkout used to unlock that address's account too."""
    _sell(monkeypatch)
    app = create_app(f"sqlite:///{(tmp_path / 'a1.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        paid = _payment(
            "pay_typed", email="someone-else@localhost", metadata={"subject": BUYER_SUBJECT}
        )
        await _deliver(client, paid, "evt_typed")
        assert (await _plan(client, app))["plan"] == "pro"
        assert (await _plan(client, app, subject="someone-else"))["plan"] == "free"

    _run(app, scenario)


def test_a_grant_made_by_hand_still_matches_by_email(tmp_path) -> None:
    from sdebris.billing.entitlements import grant
    from sdebris.ontology.database import Database

    url = f"sqlite:///{(tmp_path / 'a2.db').as_posix()}"
    database = Database(url)
    database.initialize()
    with database.session_factory() as session:
        grant(session, email=BUYER, plan=Plan.PRO, source="manual", external_ref=None)
        session.commit()
    app = create_app(url)

    async def scenario(client: httpx.AsyncClient) -> None:
        assert (await _plan(client, app))["plan"] == "pro"

    _run(app, scenario)


# --------------------------------------------------------- return address
def test_checkout_needs_a_site_address_in_production(monkeypatch) -> None:
    """Falling back to the first CORS origin sent buyers to localhost."""
    from sdebris.api.app import _site_url
    from sdebris.billing import BillingUnavailable

    monkeypatch.setenv("SDEBRIS_ENV", "production")
    monkeypatch.delenv("SDEBRIS_SITE_URL", raising=False)
    monkeypatch.setenv("SDEBRIS_CORS_ORIGINS", "http://localhost:3000,https://astra-ssa.pages.dev")
    with pytest.raises(BillingUnavailable, match="SDEBRIS_SITE_URL"):
        _site_url()
    monkeypatch.setenv("SDEBRIS_SITE_URL", "https://astra-ssa.pages.dev/")
    assert _site_url() == "https://astra-ssa.pages.dev"


# ------------------------------------------------- watch list after a lapse
def test_objects_over_the_free_limit_are_paused_when_pro_ends(tmp_path) -> None:
    from sdebris.ontology.database import Database
    from sdebris.ontology.orm import MonitoredObjectRecord, SpaceObjectRecord

    url = f"sqlite:///{(tmp_path / 'm1.db').as_posix()}"
    database = Database(url)
    database.initialize()
    limit = PLAN_LIMITS[Plan.FREE].monitored_objects
    with database.session_factory() as session:
        for index in range(limit + 5):
            obj = SpaceObjectRecord(norad_id=str(40000 + index), name=f"OBJ {index}")
            session.add(obj)
            session.flush()
            session.add(MonitoredObjectRecord(space_object_id=obj.id, added_by=BUYER))
            session.commit()
    app = create_app(url)

    async def scenario(client: httpx.AsyncClient) -> None:
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        rows = (await client.get("/monitoring")).json()
        own = [row for row in rows if row["added_by"] == BUYER]
        assert len(own) == limit
        # The oldest are the ones kept.
        assert own[0]["norad_id"] == "40000"
        assert "40029" not in {row["norad_id"] for row in own}

    _run(app, scenario)
