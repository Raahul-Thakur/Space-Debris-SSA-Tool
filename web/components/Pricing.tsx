"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import ThemeToggle from "@/components/ThemeToggle";
import { api } from "@/lib/api";
import { initializeAuth } from "@/lib/auth";
import { rememberReturnTo } from "@/lib/returnTo";
import SiteFooter from "@/components/SiteFooter";
import Waitlist from "@/components/Waitlist";

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

type Plans = {
  current_plan: string;
  /** False during the beta: nothing is for sale, and the waitlist is shown. */
  sales_open?: boolean;
  offers: Offer[];
  plans: PlanRow[];
};

function figure(value: number | null, unit: string) {
  return value === null ? "Unlimited" : `${value}${unit}`;
}

/**
 * The page a quota refusal points at, so it has to answer "what would I get"
 * before "what does it cost". The price is shown to anyone; an account is
 * asked for only at the moment of buying.
 *
 * During the beta nothing is on sale: the page says everything is free, shows
 * what Pro will add, and offers a waitlist. It shows that view unless the API
 * says sales are open, so a sleeping API never brings back a buy button.
 */
export default function Pricing() {
  const router = useRouter();
  const [plans, setPlans] = useState<Plans | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [unreachable, setUnreachable] = useState(false);
  const [email, setEmail] = useState("");

  useEffect(() => {
    let active = true;
    initializeAuth()
      .catch(() => null)
      .then(async (state) => {
        if (!active) return;
        setSignedIn(Boolean(state && (state.development || state.session)));
        setEmail(state?.session?.user?.email ?? "");
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
  const salesOpen = plans?.sales_open === true;

  if (!salesOpen) {
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
          <p className="eyebrow">PRICING · PUBLIC BETA</p>
          <h1>Free while Astra is in beta</h1>
          <p className="docs-lede">
            Every account gets the full screening pipeline at no cost during the beta. No card,
            no trial clock, nothing to cancel. Paid plans are coming later, for people who need
            more room to run it.
          </p>

          {free && pro && (
            <table className="docs-table pricing-compare">
              <thead>
                <tr>
                  <th />
                  <th>Beta · free now</th>
                  <th>Pro · coming soon</th>
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

          <section className="pricing-soon" aria-labelledby="pro-soon">
            <p className="eyebrow">PRO · COMING SOON</p>
            <h2 id="pro-soon">What Pro will add</h2>
            <ul className="docs-list">
              <li>
                <strong>Far more screening:</strong>{" "}
                {pro ? figure(pro.screening_runs_per_month, " runs a month") : "many more runs a month"}
                {free ? `, against ${figure(free.screening_runs_per_month, "")} in the beta` : ""}.
              </li>
              <li>
                <strong>A week of look-ahead:</strong> screening windows up to{" "}
                {pro?.max_window_hours ? `${pro.max_window_hours / 24} days` : "a week"}, so a close
                approach shows up days earlier.
              </li>
              <li>
                <strong>A bigger watch list:</strong> track up to{" "}
                {pro ? figure(pro.monitored_objects, " objects") : "hundreds of objects"} at once.
              </li>
              <li>
                <strong>A founding offer:</strong> a limited number of early supporters will be
                offered Pro for life for a one-time payment. The waitlist hears about it first.
              </li>
            </ul>
            <p>
              The science is the same on every plan: Pro lifts the limits, it does not change
              the numbers. Prices will be announced before anything goes on sale.
            </p>
          </section>

          <Waitlist initialEmail={email} />

          <SiteFooter />
        </main>
      </div>
    );
  }

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
        </footer>
        <SiteFooter />
      </main>
    </div>
  );
}
