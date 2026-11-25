"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import SiteFooter from "@/components/SiteFooter";
import ThemeToggle from "@/components/ThemeToggle";
import { ApiError, api } from "@/lib/api";
import { initializeAuth } from "@/lib/auth";

type LatencySummary = {
  requests: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  error_rate: number;
  client_error_rate: number;
};

export type AdminStatsPayload = {
  as_of: string;
  accounts: {
    active: { "1d": number; "7d": number; "30d": number };
    total: number;
    new_per_week: { week_start: string; count: number }[];
  };
  screening_jobs: {
    total: number;
    this_month: number;
    last_30_days: { total: number; by_status: Record<string, number> };
    per_day: { date: string; total: number; by_status: Record<string, number> }[];
    duration_last_30_days: {
      samples: number;
      median_seconds: number | null;
      p95_seconds: number | null;
    };
  };
  commands: { total: number; per_day: { date: string; count: number }[] };
  conjunction_events: { stored: number; upcoming: number };
  waitlist: { total: number; by_interest: Record<string, number> };
  monitored_objects: { total: number; active: number; by_accounts: number; platform: number };
  latency: LatencySummary & {
    scope: string;
    window_minutes: number;
    requests_per_minute: number;
    routes: (LatencySummary & { route: string })[];
  };
};

type View =
  | { state: "loading" }
  | { state: "signed-out" }
  | { state: "forbidden" }
  | { state: "unreachable" }
  | { state: "ready"; stats: AdminStatsPayload };

type Bar = { label: string; value: number; detail?: string };

const CHART_WIDTH = 640;
const CHART_HEIGHT = 150;
const AXIS_SPACE = 22;

/**
 * A plain bar chart in the site's own inks: no library, no colours of its
 * own. Every bar carries a native tooltip, the most recent bar is drawn in
 * signal red as the one to read first, and the numbers are also available
 * as a table for anyone who cannot use the picture.
 */
export function BarChart({ title, bars, unit }: { title: string; bars: Bar[]; unit: string }) {
  const max = Math.max(1, ...bars.map((bar) => bar.value));
  const total = bars.reduce((sum, bar) => sum + bar.value, 0);
  const slot = CHART_WIDTH / Math.max(1, bars.length);
  const gap = Math.min(4, slot * 0.25);
  const plot = CHART_HEIGHT - AXIS_SPACE;
  const last = bars.at(-1);
  const summary =
    `${title}: ${total} ${unit} over ${bars.length} periods` +
    (last ? `; ${last.value} in the latest (${last.label}).` : ".");

  return (
    <figure className="admin-chart">
      <figcaption>
        <span>{title}</span>
        <span>
          max {max} · total {total}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        role="img"
        aria-label={summary}
        preserveAspectRatio="none"
      >
        <line className="admin-chart-base" x1={0} x2={CHART_WIDTH} y1={plot} y2={plot} />
        {bars.map((bar, index) => {
          const height = bar.value === 0 ? 0 : Math.max(2, (bar.value / max) * (plot - 6));
          return (
            <g key={bar.label} className={index === bars.length - 1 ? "latest" : undefined}>
              {/* A full-height hit target, so a zero day still has a tooltip. */}
              <rect className="admin-chart-hit" x={index * slot} y={0} width={slot} height={plot} />
              <rect
                className="admin-chart-bar"
                x={index * slot + gap / 2}
                y={plot - height}
                width={slot - gap}
                height={height}
              />
              <title>{`${bar.label}: ${bar.value} ${unit}${bar.detail ? ` (${bar.detail})` : ""}`}</title>
            </g>
          );
        })}
      </svg>
      <div className="admin-chart-axis" aria-hidden="true">
        <span>{bars[0]?.label}</span>
        <span>{last?.label}</span>
      </div>
      <details className="admin-chart-table">
        <summary>Show as a table</summary>
        <table>
          <thead>
            <tr>
              <th scope="col">Period</th>
              <th scope="col">{unit}</th>
            </tr>
          </thead>
          <tbody>
            {bars.map((bar) => (
              <tr key={bar.label}>
                <td>{bar.label}</td>
                <td>
                  {bar.value}
                  {bar.detail ? ` (${bar.detail})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

function Kpi({ label, value, note }: { label: string; value: number | string; note?: string }) {
  return (
    <div className="admin-kpi">
      <dt>{label}</dt>
      <dd>
        {value}
        {note && <small>{note}</small>}
      </dd>
    </div>
  );
}

const ms = (value: number | null) => (value === null ? "—" : `${Math.round(value)}`);
const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
const shortDate = (iso: string) => iso.slice(5);
const describeStatuses = (counts: Record<string, number>) =>
  Object.entries(counts)
    .map(([status, count]) => `${count} ${status}`)
    .join(", ");

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="account-shell admin-shell">
      <header className="account-top">
        <Link className="account-back" href="/">
          ← CONSOLE
        </Link>
        <span className="account-title">ADMIN · USAGE</span>
        <ThemeToggle />
      </header>
      {children}
      <SiteFooter />
    </main>
  );
}

function AdminsOnly({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="account-identity">
      <p className="eyebrow">ADMINS ONLY</p>
      <h1>This page is for administrators.</h1>
      <p className="account-note">
        {signedIn
          ? "Your account does not have the admin role, so there is nothing to show here."
          : "Sign in with an administrator account to see usage figures."}
      </p>
      {!signedIn && (
        <div className="account-actions">
          <Link className="admin-signin" href="/signin">
            SIGN IN →
          </Link>
        </div>
      )}
    </section>
  );
}

export default function AdminStats() {
  const [view, setView] = useState<View>({ state: "loading" });

  useEffect(() => {
    let active = true;
    (async () => {
      const auth = await initializeAuth().catch(() => null);
      if (!active) return;
      if (!auth || (!auth.session && !auth.development)) {
        setView({ state: "signed-out" });
        return;
      }
      // The role in the token is only a hint for skipping a request bound to
      // be refused; the API's 403 is what actually keeps the figures private.
      if (auth.role !== "admin") {
        setView({ state: "forbidden" });
        return;
      }
      try {
        const stats = await api<AdminStatsPayload>("/admin/stats");
        if (active) setView({ state: "ready", stats });
      } catch (caught) {
        if (!active) return;
        if (caught instanceof ApiError && caught.status === 401) setView({ state: "signed-out" });
        else if (caught instanceof ApiError && caught.status === 403) setView({ state: "forbidden" });
        else setView({ state: "unreachable" });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (view.state === "loading") return <main className="auth-loading">LOADING STATS</main>;
  if (view.state === "signed-out") {
    return (
      <Shell>
        <AdminsOnly signedIn={false} />
      </Shell>
    );
  }
  if (view.state === "forbidden") {
    return (
      <Shell>
        <AdminsOnly signedIn />
      </Shell>
    );
  }
  if (view.state === "unreachable") {
    return (
      <Shell>
        <p className="account-warning">
          Could not reach the API. It sleeps after a quiet spell on the free tier; reload in a
          minute.
        </p>
      </Shell>
    );
  }

  const { stats } = view;
  const jobs = stats.screening_jobs;
  const latency = stats.latency;
  const asOf = new Date(stats.as_of).toISOString().slice(0, 16).replace("T", " ") + " UTC";

  return (
    <Shell>
      <section className="account-identity">
        <p className="eyebrow">USAGE · AS OF {asOf}</p>
        <h1>Who is using Astra</h1>
        <p className="account-note">
          Aggregate counts from the service&apos;s own records: an active account is one that ran
          a command, started a screening or watched an object in the period. No individual is
          tracked or named here.
        </p>
      </section>

      <section className="account-usage">
        <div className="section-head">
          <span>AT A GLANCE</span>
        </div>
        <dl className="admin-kpis">
          <Kpi label="Active today" value={stats.accounts.active["1d"]} note="last 24 h" />
          <Kpi label="Active 7 days" value={stats.accounts.active["7d"]} />
          <Kpi label="Active 30 days" value={stats.accounts.active["30d"]} />
          <Kpi label="Accounts" value={stats.accounts.total} note="all time" />
          <Kpi label="Screenings" value={jobs.this_month} note="this month" />
          <Kpi label="Waitlist" value={stats.waitlist.total} />
        </dl>
      </section>

      <section className="account-usage">
        <div className="section-head">
          <span>GROWTH</span>
          <span>12 WEEKS</span>
        </div>
        <BarChart
          title="New accounts per week"
          unit="accounts"
          bars={stats.accounts.new_per_week.map((week) => ({
            label: `w/c ${shortDate(week.week_start)}`,
            value: week.count
          }))}
        />
      </section>

      <section className="account-usage">
        <div className="section-head">
          <span>SCREENINGS</span>
          <span>30 DAYS</span>
        </div>
        <BarChart
          title="Screenings per day"
          unit="screenings"
          bars={jobs.per_day.map((day) => ({
            label: shortDate(day.date),
            value: day.total,
            detail: describeStatuses(day.by_status) || undefined
          }))}
        />
        <dl className="identity-facts">
          <div>
            <dt>Last 30 days</dt>
            <dd>{describeStatuses(jobs.last_30_days.by_status) || "none"}</dd>
          </div>
          <div>
            <dt>Run time, median / p95</dt>
            <dd>
              {jobs.duration_last_30_days.median_seconds ?? "—"} s /{" "}
              {jobs.duration_last_30_days.p95_seconds ?? "—"} s
            </dd>
          </div>
          <div>
            <dt>All time</dt>
            <dd>{jobs.total}</dd>
          </div>
        </dl>
        <dl className="identity-facts">
          <div>
            <dt>Commands, 30 days</dt>
            <dd>{stats.commands.per_day.reduce((sum, day) => sum + day.count, 0)}</dd>
          </div>
          <div>
            <dt>Conjunctions stored / upcoming</dt>
            <dd>
              {stats.conjunction_events.stored} / {stats.conjunction_events.upcoming}
            </dd>
          </div>
          <div>
            <dt>Watched objects</dt>
            <dd>
              {stats.monitored_objects.total}{" "}
              <small>({stats.monitored_objects.by_accounts} by accounts)</small>
            </dd>
          </div>
          <div>
            <dt>Waitlist by interest</dt>
            <dd>{describeStatuses(stats.waitlist.by_interest) || "none"}</dd>
          </div>
        </dl>
      </section>

      <section className="account-usage">
        <div className="section-head">
          <span>LATENCY</span>
          <span>LAST {latency.window_minutes} MIN</span>
        </div>
        <dl className="identity-facts">
          <div>
            <dt>Requests / min</dt>
            <dd>{latency.requests_per_minute}</dd>
          </div>
          <div>
            <dt>p50 / p95 / p99</dt>
            <dd>
              {ms(latency.p50_ms)} / {ms(latency.p95_ms)} / {ms(latency.p99_ms)} ms
            </dd>
          </div>
          <div>
            <dt>5xx rate</dt>
            <dd>{pct(latency.error_rate)}</dd>
          </div>
        </dl>
        {latency.routes.length ? (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th scope="col">Route</th>
                  <th scope="col">Requests</th>
                  <th scope="col">p50</th>
                  <th scope="col">p95</th>
                  <th scope="col">p99</th>
                  <th scope="col">5xx</th>
                </tr>
              </thead>
              <tbody>
                {latency.routes.map((route) => (
                  <tr key={route.route}>
                    <th scope="row">
                      <code>{route.route}</code>
                    </th>
                    <td>{route.requests}</td>
                    <td>{ms(route.p50_ms)}</td>
                    <td>{ms(route.p95_ms)}</td>
                    <td>{ms(route.p99_ms)}</td>
                    <td>{pct(route.error_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">No requests recorded since this API process started.</p>
        )}
        <p className="account-note">
          Measured inside one API process and kept in memory only: the figures reset whenever
          the instance restarts or wakes from sleep, and times are in milliseconds.
        </p>
      </section>
    </Shell>
  );
}
