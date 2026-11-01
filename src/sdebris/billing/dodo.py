"""The two Dodo Payments API calls the platform makes.

Everything else arrives by webhook. Checkout is created server-side, rather
than by linking to a static payment page, for two reasons: the founding-seat
cap can only be enforced by refusing to start a checkout, and the buyer's auth
subject travels in the checkout's metadata, so the grant reaches the right
account even if they pay with a different email address.

Endpoints are from Dodo's API reference: ``POST /checkouts`` and
``POST /customers/{customer_id}/customer-portal/session``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

BASE_URLS = {
    "test": "https://test.dodopayments.com",
    "live": "https://live.dodopayments.com",
}
TIMEOUT_SECONDS = 15


class BillingUnavailable(Exception):
    """Billing is not configured, or the provider could not be reached."""


@dataclass(frozen=True, slots=True)
class DodoClient:
    api_key: str
    base_url: str

    @classmethod
    def from_env(cls) -> DodoClient:
        api_key = os.getenv("SDEBRIS_DODO_API_KEY", "").strip()
        if not api_key:
            raise BillingUnavailable("billing is not configured on this deployment")
        mode = os.getenv("SDEBRIS_DODO_ENVIRONMENT", "test").strip().lower()
        if mode not in BASE_URLS:
            raise BillingUnavailable(f"unknown SDEBRIS_DODO_ENVIRONMENT {mode!r}")
        return cls(api_key=api_key, base_url=BASE_URLS[mode])

    def _post(self, path: str, *, json: dict | None = None, params: dict | None = None) -> dict:
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BillingUnavailable("the payment provider did not answer") from exc

    def create_checkout(
        self,
        *,
        product_id: str,
        email: str | None,
        subject: str,
        offer: str,
        return_url: str,
    ) -> str:
        body: dict = {
            "product_cart": [{"product_id": product_id, "quantity": 1}],
            "return_url": return_url,
            # Read back from the webhook to bind the grant to this account.
            "metadata": {"subject": subject, "offer": offer},
        }
        if email:
            body["customer"] = {"email": email}
        checkout_url = self._post("/checkouts", json=body).get("checkout_url")
        if not checkout_url:
            raise BillingUnavailable("the payment provider returned no checkout link")
        return str(checkout_url)

    def portal_link(self, *, customer_id: str, return_url: str) -> str:
        link = self._post(
            f"/customers/{customer_id}/customer-portal/session",
            params={"return_url": return_url},
        ).get("link")
        if not link:
            raise BillingUnavailable("the payment provider returned no portal link")
        return str(link)
