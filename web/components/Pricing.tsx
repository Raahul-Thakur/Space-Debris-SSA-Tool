"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import ThemeToggle from "@/components/ThemeToggle";
import { api } from "@/lib/api";
import { initializeAuth } from "@/lib/auth";
import { rememberReturnTo } from "@/lib/returnTo";

type Offer = {
  code: string;
  label: string;
  price_usd: number;
  interval: "month" | "lifetime";
  blurb: string;
  available: boolean;
  seats_remaining?: number;
};

type PlanRow = {
  plan: string;
  label: string;
  screening_runs_per_month: number | null;
  monitored_objects: number | null;
  max_window_hours: number | null;
  commands_per_minute: number;
};

type Plans = { current_plan: string; offers: Offer[]; plans: PlanRow[] };

function figure(value: number | null, unit: string) {
  return value === null ? "Unlimited" : `${value}${unit}`;
}

/**
 * The page a quota refusal points at, so it has to answer "what would I get"
 * before "what does it cost". The price is shown to anyone; an account is
 * asked for only at the moment of buying.
 */
export default function Pricing() {
  const router = useRouter();
  const [plans, setPlans] = useState<Plans | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let active = true;
    initializeAuth()
      .catch(() => null)
      .then(async (state) => {
        if (!active) return;
        setSignedIn(Boolean(state && (state.development || state.session)));
        try {
          const loaded = await api<Plans>("/billing/plans");
          if (active) setPlans(loaded);
        } catch {
          if (active) setUnreachable(true);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function buy(offer: Offer) {
    setError("");
    if (!signedIn) {
      rememberReturnTo("/pricing");
      router.push("/signin");
      return;
    }
    if (!accepted) {
      setError("Tick the box above to confirm you have read the terms.");
      return;
    }
    setBusy(offer.code);
    try {
      const { checkout_url } = await api<{ checkout_url: string }>("/billing/checkout", {
        method: "POST",
        body: JSON.stringify({ offer: offer.code, accepted_terms: true })
      });
      window.location.assign(checkout_url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Checkout could not be started.");
      setBusy(null);
    }
  }

  const free = plans?.plans.find((row) => row.plan === "free");
  const pro = plans?.plans.find((row) => row.plan === "pro");
  const isPro = plans?.current_plan === "pro";

  return (
    <div className="docs-shell pricing-shell">
      <header className="docs-topbar">
        <Link href="/" className="brand">
          <span className="brand-mark">A</span>
          <span>ASTRA / SSA</span>
        </Link>
        <nav>
          <ThemeToggle />
          <Link href="/" className="docs-back">
            OPEN CONSOLE <span aria-hidden="true">-&gt;</span>
          </Link>
        </nav>
      </header>

      <main className="docs-body pricing-body">
        <p className="eyebrow">PRICING</p>
        <h1>The same science, with more room to run it</h1>
        <p className="docs-lede">
          Free and Pro run the identical pipeline. Pro lifts the limits: more screening
          runs, longer look-ahead windows and a bigger watch list.
        </p>

        {unreachable && (
          <p className="account-warning">
            Could not reach the API. It sleeps after a quiet spell on the free tier; reload
            in a minute.
          </p>
        )}

        {free && pro && (
          <table className="docs-table pricing-compare">
            <thead>
              <tr>
                <th />
                <th>{free.label}</th>
                <th>{pro.label}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Screening runs</td>
                <td>{figure(free.screening_runs_per_month, " / month")}</td>
                <td>{figure(pro.screening_runs_per_month, " / month")}</td>
              </tr>
              <tr>
                <td>Longest window</td>
                <td>{figure(free.max_window_hours, " h")}</td>
                <td>{figure(pro.max_window_hours, " h")}</td>
              </tr>
              <tr>
                <td>Watch list</td>
                <td>{figure(free.monitored_objects, " objects")}</td>
                <td>{figure(pro.monitored_objects, " objects")}</td>
              </tr>
              <tr>
                <td>Command rate</td>
                <td>{free.commands_per_minute} / min</td>
                <td>{pro.commands_per_minute} / min</td>
              </tr>
            </tbody>
          </table>
        )}

        {isPro ? (
          <p className="pricing-current">
            This account already has Pro. <Link href="/account">Manage it from your account</Link>.
          </p>
        ) : (
          plans && (
            <>
              <label className="pricing-consent">
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(event) => setAccepted(event.target.checked)}
                />
                <span>
                  I have read the <Link href="/terms">terms</Link> and the{" "}
                  <Link href="/refunds">refund policy</Link>, and I understand that every
                  output is illustrative and must not be used for a real manoeuvre or any
                  other operational decision.
                </span>
              </label>

              <div className="pricing-offers">
                {plans.offers.map((offer) => (
                  <section key={offer.code} className="pricing-offer">
                    <p className="eyebrow">{offer.label.toUpperCase()}</p>
                    <p className="pricing-price">
                      ${offer.price_usd}
                      <small>{offer.interval === "month" ? " / month" : " once"}</small>
                    </p>
                    <p>{offer.blurb}</p>
                    {offer.seats_remaining !== undefined && (
                      <p className="pricing-seats">{offer.seats_remaining} seats left</p>
                    )}
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => void buy(offer)}
                    >
                      {busy === offer.code
                        ? "OPENING CHECKOUT…"
                        : signedIn
                          ? "CONTINUE TO PAYMENT →"
                          : "SIGN IN TO BUY →"}
                    </button>
                  </section>
                ))}
              </div>
              {error && <p className="command-error pricing-error">{error}</p>}
              <p className="account-note">
                Payment is handled by Dodo Payments, the merchant of record, which also
                calculates and collects any sales tax or VAT. Prices are in US dollars. A
                subscription can be cancelled at any time from your account page and runs
                to the end of the month already paid for.
              </p>
            </>
          )
        )}

        <footer className="docs-footer">
          <Link href="/terms">
            Terms <span aria-hidden="true">-&gt;</span>
          </Link>
          <p>
            Educational screening platform. Outputs are illustrative and must not be used
            for operational maneuver decisions.
          </p>
        </footer>
      </main>
    </div>
  );
}
