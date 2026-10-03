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


def _webhook_body(event_type: str, *, email: str, ref: str) -> bytes:
    return json.dumps(
        {
            "type": event_type,
            "data": {"customer": {"email": email}, "payment_id": ref},
        }
    ).encode()


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


def test_a_paid_webhook_upgrades_the_buyer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'b2.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = _webhook_body("payment.succeeded", email=BUYER, ref="pay_1")
        headers = _sign(body, "evt_paid", int(datetime.now(timezone.utc).timestamp()))
        delivered = await client.post("/billing/webhook", content=body, headers=headers)
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()["outcome"] == "granted"

        client.headers["Authorization"] = f"Bearer {_token(app)}"
        me = (await client.get("/billing/me")).json()
        assert me["plan"] == "pro"
        # Without a configured lifetime product this is treated as a period
        # that has to be renewed, so a misconfiguration under-grants.
        assert me["expires_at"] is not None

    _run(app, scenario)


def test_a_redelivered_webhook_does_not_grant_twice(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'b3.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = _webhook_body("payment.succeeded", email=BUYER, ref="pay_2")
        headers = _sign(body, "evt_dup", int(datetime.now(timezone.utc).timestamp()))
        first = await client.post("/billing/webhook", content=body, headers=headers)
        second = await client.post("/billing/webhook", content=body, headers=headers)
        assert first.json()["outcome"] == "granted"
        assert second.json()["status"] == "duplicate"

    _run(app, scenario)


def test_a_refund_revokes_access(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'b4.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        paid = _webhook_body("payment.succeeded", email=BUYER, ref="pay_3")
        await client.post(
            "/billing/webhook",
            content=paid,
            headers=_sign(paid, "evt_p", int(datetime.now(timezone.utc).timestamp())),
        )
        refund = _webhook_body("payment.refunded", email=BUYER, ref="pay_3")
        revoked = await client.post(
            "/billing/webhook",
            content=refund,
            headers=_sign(refund, "evt_r", int(datetime.now(timezone.utc).timestamp())),
        )
        assert revoked.json()["outcome"] == "revoked"

        client.headers["Authorization"] = f"Bearer {_token(app)}"
        assert (await client.get("/billing/me")).json()["plan"] == "free"

    _run(app, scenario)


def test_an_unsigned_webhook_is_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'b5.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = _webhook_body("payment.succeeded", email="attacker@example.com", ref="x")
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
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'b8.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = _webhook_body("payment.succeeded", email=BUYER, ref="pay_8")
        await client.post(
            "/billing/webhook",
            content=body,
            headers=_sign(body, "evt_8", int(datetime.now(timezone.utc).timestamp())),
        )
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
def test_the_lifetime_product_grants_access_that_never_expires(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SDEBRIS_BILLING_LIFETIME_PRODUCT_ID", "prod_founding")
    app = create_app(f"sqlite:///{(tmp_path / 'p1.db').as_posix()}")

    async def scenario(client: httpx.AsyncClient) -> None:
        body = json.dumps(
            {
                "type": "payment.succeeded",
                "data": {
                    "customer": {"email": BUYER},
                    "payment_id": "pay_life",
                    "product_id": "prod_founding",
                },
            }
        ).encode()
        await client.post(
            "/billing/webhook",
            content=body,
            headers=_sign(body, "evt_life", int(datetime.now(timezone.utc).timestamp())),
        )
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        me = (await client.get("/billing/me")).json()
        assert me["plan"] == "pro"
        assert me["expires_at"] is None

    _run(app, scenario)


def test_a_subscription_expires_at_the_renewal_date(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SDEBRIS_BILLING_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("SDEBRIS_BILLING_LIFETIME_PRODUCT_ID", "prod_founding")
    app = create_app(f"sqlite:///{(tmp_path / 'p2.db').as_posix()}")
    renewal = datetime.now(timezone.utc) + timedelta(days=30)

    async def scenario(client: httpx.AsyncClient) -> None:
        body = json.dumps(
            {
                "type": "subscription.active",
                "data": {
                    "customer": {"email": BUYER},
                    "subscription_id": "sub_1",
                    "product_id": "prod_monthly",
                    "next_billing_date": renewal.isoformat(),
                },
            }
        ).encode()
        await client.post(
            "/billing/webhook",
            content=body,
            headers=_sign(body, "evt_sub", int(datetime.now(timezone.utc).timestamp())),
        )
        client.headers["Authorization"] = f"Bearer {_token(app)}"
        me = (await client.get("/billing/me")).json()
        assert me["plan"] == "pro"
        expires = datetime.fromisoformat(me["expires_at"])
        # Renewal plus the grace period that stops a late webhook cutting access.
        assert renewal < expires <= renewal + timedelta(days=4)

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
