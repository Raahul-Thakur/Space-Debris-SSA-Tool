import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The admin usage page: figures for an administrator, a plain "admins only"
 * for everyone else, and no request for the figures unless it could succeed.
 */

const auth = vi.hoisted(() => ({
  state: { session: { user: { email: "root@example.com" } }, development: false, role: "admin" } as {
    session: unknown;
    development: boolean;
    role: string;
  }
}));

vi.mock("@/lib/auth", () => ({ initializeAuth: async () => auth.state }));

const days = Array.from({ length: 30 }, (_, n) => ({
  date: new Date(Date.UTC(2026, 9, 27 + n)).toISOString().slice(0, 10),
  total: 0,
  by_status: {} as Record<string, number>
}));
days[29] = { date: "2026-11-25", total: 3, by_status: { succeeded: 2, failed: 1 } };

const STATS = {
  as_of: "2026-11-25T12:00:00+00:00",
  accounts: {
    active: { "1d": 4, "7d": 11, "30d": 23 },
    total: 57,
    new_per_week: Array.from({ length: 12 }, (_, n) => ({
      week_start: `2026-09-${String(7 + n).padStart(2, "0")}`,
      count: n
    }))
  },
  screening_jobs: {
    total: 410,
    this_month: 96,
    last_30_days: { total: 120, by_status: { succeeded: 110, failed: 10 } },
    per_day: days,
    duration_last_30_days: { samples: 110, median_seconds: 8.4, p95_seconds: 31.2 }
  },
  commands: { total: 900, per_day: [{ date: "2026-11-25", count: 12 }] },
  conjunction_events: { stored: 1500, upcoming: 42 },
  waitlist: { total: 19, by_interest: { founding: 12, unspecified: 7 } },
  monitored_objects: { total: 80, active: 78, by_accounts: 50, platform: 30 },
  latency: {
    scope: "this API process only; resets when it restarts",
    window_minutes: 60,
    max_samples: 5000,
    requests_per_minute: 3.5,
    per_minute: [],
    status_classes: { "2xx": 200 },
    requests: 210,
    p50_ms: 12.3,
    p95_ms: 80.9,
    p99_ms: 240.1,
    error_rate: 0.0048,
    client_error_rate: 0.02,
    routes: [
      {
        route: "GET /objects/{norad_id}/trajectory",
        requests: 120,
        p50_ms: 30,
        p95_ms: 90,
        p99_ms: 200,
        error_rate: 0,
        client_error_rate: 0
      }
    ]
  }
};

const fetchMock = vi.fn();

beforeEach(() => {
  auth.state = {
    session: { user: { email: "root@example.com" } },
    development: false,
    role: "admin"
  };
  fetchMock.mockReset().mockImplementation(async (url: string) => {
    if (String(url).endsWith("/admin/stats")) return new Response(JSON.stringify(STATS));
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

async function renderAdmin() {
  const { default: AdminStats } = await import("@/components/AdminStats");
  render(<AdminStats />);
}

function kpi(label: string) {
  const term = screen.getByText(label, { selector: "dt" });
  return term.nextElementSibling?.textContent ?? "";
}

it("shows the headline figures to an administrator", async () => {
  await renderAdmin();
  await screen.findByRole("heading", { name: /who is using astra/i });
  expect(kpi("Active today")).toMatch(/^4/);
  expect(kpi("Active 7 days")).toBe("11");
  expect(kpi("Active 30 days")).toBe("23");
  expect(kpi("Accounts")).toMatch(/^57/);
  expect(kpi("Screenings")).toMatch(/^96/);
  expect(kpi("Waitlist")).toBe("19");
  expect(screen.getByText(/8.4 s \/ 31.2 s/)).toBeInTheDocument();
});

it("draws both charts as labelled SVG with one bar per period", async () => {
  await renderAdmin();
  const weekly = await screen.findByRole("img", { name: /new accounts per week/i });
  const daily = screen.getByRole("img", { name: /screenings per day/i });
  expect(weekly.querySelectorAll(".admin-chart-bar")).toHaveLength(12);
  expect(daily.querySelectorAll(".admin-chart-bar")).toHaveLength(30);
  // 0 + 1 + ... + 11 accounts, and the latest week is the one called out.
  expect(weekly.getAttribute("aria-label")).toContain("66 accounts over 12 periods");
  expect(weekly.getAttribute("aria-label")).toContain("11 in the latest");
  // A day's tooltip says what the screenings ended as.
  expect(daily.textContent).toContain("11-25: 3 screenings (2 succeeded, 1 failed)");
});

it("lists latency by route template", async () => {
  await renderAdmin();
  const route = await screen.findByText("GET /objects/{norad_id}/trajectory");
  const row = route.closest("tr")!;
  expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
    "120", "30", "90", "200", "0.0%"
  ]);
  expect(screen.getByText("12 / 81 / 240 ms")).toBeInTheDocument();
  expect(screen.getByText(/reset whenever the instance restarts/i)).toBeInTheDocument();
});

it("tells a non-admin the page is for admins, without asking for the figures", async () => {
  auth.state = { ...auth.state, role: "analyst" };
  await renderAdmin();
  await screen.findByRole("heading", { name: /for administrators/i });
  expect(screen.getByText(/does not have the admin role/i)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/admin/stats"))).toBe(false);
});

it("asks a signed-out visitor to sign in", async () => {
  auth.state = { session: null, development: false, role: "viewer" };
  await renderAdmin();
  await screen.findByRole("heading", { name: /for administrators/i });
  expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/signin");
});

it("believes the API over the token when it refuses", async () => {
  fetchMock.mockImplementation(
    async () => new Response(JSON.stringify({ detail: "admin role required" }), { status: 403 })
  );
  await renderAdmin();
  await screen.findByRole("heading", { name: /for administrators/i });
  expect(screen.queryByText(/who is using astra/i)).toBeNull();
});

it("says so when the API is asleep", async () => {
  fetchMock.mockImplementation(async () => {
    throw new TypeError("network down");
  });
  await renderAdmin();
  await screen.findByText(/could not reach the api/i);
});
