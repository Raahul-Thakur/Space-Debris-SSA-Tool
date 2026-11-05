"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import ThemeToggle from "@/components/ThemeToggle";
import { api } from "@/lib/api";
import { initializeAuth, signOut, signOutEverywhere } from "@/lib/auth";
import type { Job } from "@/lib/types";
import SiteFooter from "@/components/SiteFooter";

type Billing = {
  plan: string;
  plan_label: string;
  limits: {
    screening_runs_per_month: number | null;
    monitored_objects: number | null;
    max_window_hours: number | null;
    commands_per_minute: number;
  };
  usage: { screening_runs_this_month: number; monitored_objects: number };
  expires_at: string | null;
  manageable: boolean;
  cancelled: boolean;
};

/** How long to wait for the payment webhook after returning from checkout. */
const CHECKOUT_POLL_MS = 3000;
const CHECKOUT_POLL_ATTEMPTS = 20;

type Identity = {
  email: string;
  role: string;
  userId: string;
  lastSignIn: string | null;
  development: boolean;
};

/** A quota as a proportion, or null when the plan does not cap it. */
function share(used: number, limit: number | null): number | null {
  if (limit === null || limit <= 0) return null;
  return Math.min(1, used / limit);
}

function Meter({
  label,
  used,
  limit,
  unit
}: {
  label: string;
  used: number;
  limit: number | null;
  unit: string;
}) {
  const filled = share(used, limit);
  // Warn before the wall, not at it: discovering a quota by being refused is
  // a worse experience than seeing it approach.
  const state = filled === null ? "" : filled >= 1 ? "full" : filled > 0.8 ? "near" : "";
  return (
    <div className={`meter ${state}`}>
      <div className="meter-head">
        <span>{label}</span>
        <strong>
          {used}
          {limit === null ? "" : ` / ${limit}`} <small>{unit}</small>
        </strong>
      </div>
      <div className="meter-track">
        {filled === null ? (
          <i className="unlimited" style={{ width: "100%" }} />
        ) : (
          <i style={{ width: `${Math.max(2, filled * 100)}%` }} />
        )}
      </div>
      {limit === null && <small className="meter-note">No cap on this plan</small>}
    </div>
  );
}

export default function AccountPanel() {
  const router = useRouter();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [billing, setBilling] = useState<Billing | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [ready, setReady] = useState(false);
  const [reachable, setReachable] = useState(true);
  const [checkoutNotice, setCheckoutNotice] = useState("");
  const [billingError, setBillingError] = useState("");
  const [openingPortal, setOpeningPortal] = useState(false);

  const load = useCallback(async () => {
    const [b, j] = await Promise.all([
      api<Billing>("/billing/me").catch(() => null),
      api<Job[]>("/screening-jobs?limit=8").catch(() => null)
    ]);
    setReachable(b !== null);
    if (b) setBilling(b);
    if (j) setJobs(j);
    return b;
  }, []);

  /**
   * Back from checkout, the grant arrives by webhook, usually within seconds
   * but not before the redirect. Poll until it lands rather than showing a
   * paying customer the free plan and leaving them to wonder.
   */
  const awaitCheckout = useCallback(async () => {
    setCheckoutNotice("Payment received. Waiting for the provider to confirm it…");
    window.history.replaceState(null, "", "/account");
    for (let attempt = 0; attempt < CHECKOUT_POLL_ATTEMPTS; attempt += 1) {
      const b = await api<Billing>("/billing/me").catch(() => null);
      if (b?.plan === "pro") {
        setBilling(b);
        setCheckoutNotice("Pro is active on this account. Thank you for supporting the project.");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, CHECKOUT_POLL_MS));
    }
    setCheckoutNotice(
      "The payment has not been confirmed yet. It can take a few minutes; reload this page " +
        "later. If Pro has not appeared within an hour, reply to your receipt email."
    );
  }, []);

  async function openPortal() {
    setBillingError("");
    setOpeningPortal(true);
    try {
      const { url } = await api<{ url: string }>("/billing/portal", { method: "POST" });
      window.location.assign(url);
    } catch (caught) {
      setBillingError(caught instanceof Error ? caught.message : "Could not open billing.");
      setOpeningPortal(false);
    }
  }

  useEffect(() => {
    let active = true;
    initializeAuth()
      .then(async (state) => {
        if (!active) return;
        const user = state.session?.user;
        if (!user && !state.development) {
          // An account page is meaningless without an account.
          router.replace("/signin");
          return;
        }
        setIdentity({
          email: user?.email ?? "local-operator@localhost",
          role: state.role,
          userId: user?.id ?? "local",
          lastSignIn: user?.last_sign_in_at ?? null,
          development: state.development
        });
        setReady(true);
        const loaded = await load();
        const returning =
          new URLSearchParams(window.location.search).get("checkout") === "complete";
        if (returning && active && loaded?.plan !== "pro") await awaitCheckout();
        else if (returning) window.history.replaceState(null, "", "/account");
      })
      .catch(() => {
        if (active) router.replace("/signin");
      });
    return () => {
      active = false;
    };
  }, [router, load, awaitCheckout]);

  if (!ready || !identity) {
    return <main className="auth-loading">LOADING ACCOUNT</main>;
  }

  const runs = billing?.usage.screening_runs_this_month ?? 0;
  const watched = billing?.usage.monitored_objects ?? 0;

  return (
    <main className="account-shell">
      <header className="account-top">
        <Link className="account-back" href="/">
          ← CONSOLE
        </Link>
        <span className="account-title">ACCOUNT</span>
        <ThemeToggle />
      </header>

      <section className="account-identity">
        <p className="eyebrow">SIGNED IN AS</p>
        <h1>{identity.email}</h1>
        <div className="identity-chips">
          <span className={`role-chip ${identity.role}`}>{identity.role}</span>
          {billing && <span className="plan-chip">{billing.plan_label} plan</span>}
          {identity.development && <span className="plan-chip">development token</span>}
        </div>
        <dl className="identity-facts">
          <div>
            <dt>Account id</dt>
            <dd>{identity.userId.slice(0, 8)}</dd>
          </div>
          <div>
            <dt>Last sign-in</dt>
            <dd>
              {identity.lastSignIn
                ? new Date(identity.lastSignIn).toISOString().slice(0, 16).replace("T", " ") + " UTC"
                : "—"}
            </dd>
          </div>
          <div>
            <dt>Plan expires</dt>
            <dd>
              {billing?.plan !== "pro"
                ? "—"
                : billing.expires_at
                  ? new Date(billing.expires_at).toISOString().slice(0, 10)
                  : "Never"}
            </dd>
          </div>
        </dl>
      </section>

      {checkoutNotice && <p className="account-notice">{checkoutNotice}</p>}

      {billing && (
        <section className="account-billing">
          <div className="section-head">
            <span>BILLING</span>
            <span>{billing.plan_label}</span>
          </div>
          {billing.plan === "pro" ? (
            <p className="account-note">
              {billing.cancelled
                ? "Your subscription is cancelled. Pro stays active until the date above, and you will not be charged again."
                : billing.manageable
                  ? "Cancel, change your card or download invoices from the billing portal. Cancelling keeps Pro until the end of the period you have paid for."
                  : "Pro was granted to this account directly, so there is nothing to manage."}
            </p>
          ) : (
            <p className="account-note">
              Pro raises every limit above: more runs, longer windows and a bigger
              watch list.
            </p>
          )}
          <div className="account-actions">
            {billing.plan === "pro" ? (
              billing.manageable && (
                <button type="button" disabled={openingPortal} onClick={() => void openPortal()}>
                  {openingPortal ? "OPENING…" : "MANAGE BILLING"}
                </button>
              )
            ) : (
              <button type="button" className="primary" onClick={() => router.push("/pricing")}>
                SEE PRO →
              </button>
            )}
          </div>
          {billingError && <p className="account-warning">{billingError}</p>}
        </section>
      )}

      {!reachable && (
        <p className="account-warning">
          Could not reach the API. It sleeps after a quiet spell on the free tier;
          your figures will be stale until it answers.
        </p>
      )}

      <section className="account-usage">
        <div className="section-head">
          <span>THIS MONTH</span>
          <span>{billing?.plan_label ?? "—"}</span>
        </div>
        <Meter
          label="Screening runs"
          used={runs}
          limit={billing?.limits.screening_runs_per_month ?? null}
          unit="runs"
        />
        <Meter
          label="Monitored objects"
          used={watched}
          limit={billing?.limits.monitored_objects ?? null}
          unit="objects"
        />
        <dl className="identity-facts">
          <div>
            <dt>Longest window</dt>
            <dd>
              {billing?.limits.max_window_hours
                ? `${billing.limits.max_window_hours}h`
                : "Unlimited"}
            </dd>
          </div>
          <div>
            <dt>Command rate</dt>
            <dd>{billing?.limits.commands_per_minute ?? "—"} / min</dd>
          </div>
        </dl>
        <p className="account-note">
          Usage is counted from the records the platform already writes, not from a
          separate tally, so it cannot drift from what actually happened.
        </p>
      </section>

      <section className="account-activity">
        <div className="section-head">
          <span>YOUR RECENT RUNS</span>
          <span>{jobs.length}</span>
        </div>
        {jobs.length ? (
          <ol className="run-list">
            {jobs.map((job) => (
              <li key={job.id}>
                <span className={`job-status ${job.status}`} />
                <span className="run-body">
                  <code>{job.command}</code>
                  <small>{job.message}</small>
                </span>
                <time>
                  {new Date(job.created_at).toISOString().slice(5, 16).replace("T", " ")}
                </time>
              </li>
            ))}
          </ol>
        ) : (
          <p className="empty">
            {reachable
              ? "No screening runs yet. Everything you run appears here, and only here — another account cannot see it."
              : "Waiting for the API."}
          </p>
        )}
      </section>

      <section className="account-sessions">
        <div className="section-head">
          <span>SESSIONS</span>
        </div>
        <p className="account-note">
          Signing out ends this browser&apos;s session. If you believe a sign-in link
          or token has been seen by someone else, end every session instead — that
          revokes it everywhere, immediately.
        </p>
        <div className="account-actions">
          <button
            type="button"
            onClick={() => void signOut().finally(() => router.replace("/"))}
          >
            SIGN OUT
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => {
              if (
                window.confirm(
                  "End every session on every device? You will need a new sign-in link."
                )
              ) {
                void signOutEverywhere().finally(() => router.replace("/"));
              }
            }}
          >
            END EVERY SESSION
          </button>
        </div>
      </section>

      <SiteFooter />
    </main>
  );
}
