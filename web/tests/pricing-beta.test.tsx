import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The pricing page during the beta: free, Pro coming soon, a waitlist, and
 * no way to buy anything, even if the API is asleep and says nothing.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/auth", () => ({
  initializeAuth: async () => ({ session: { user: { email: "fan@example.com" } }, development: false, role: "viewer" })
}));

const PLANS = {
  current_plan: "free",
  sales_open: false,
  offers: [],
  plans: [
    { plan: "free", label: "Free", screening_runs_per_month: 5, monitored_objects: 25, max_window_hours: 24, commands_per_minute: 10 },
    { plan: "pro", label: "Pro", screening_runs_per_month: 500, monitored_objects: 250, max_window_hours: 168, commands_per_minute: 60 }
  ]
};

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset().mockImplementation(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith("/billing/plans")) return new Response(JSON.stringify(PLANS));
    if (String(url).endsWith("/waitlist") && init?.method === "POST") {
      return new Response(JSON.stringify({ status: "joined" }), { status: 202 });
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

async function renderPricing() {
  const { default: Pricing } = await import("@/components/Pricing");
  render(<Pricing />);
}

it("says the beta is free and offers nothing to buy", async () => {
  await renderPricing();
  expect(screen.getByRole("heading", { name: /free while astra is in beta/i })).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Pro · coming soon")).toBeInTheDocument());
  expect(screen.getByText(/500 runs a month/)).toBeInTheDocument();
  expect(screen.getByText(/7 days/)).toBeInTheDocument();
  expect(screen.queryByText(/continue to payment/i)).toBeNull();
  expect(screen.queryByText(/sign in to buy/i)).toBeNull();
});

it("never shows a buy button while the API is unreachable", async () => {
  fetchMock.mockImplementation(async () => {
    throw new TypeError("network down");
  });
  await renderPricing();
  expect(screen.getByRole("heading", { name: /free while astra is in beta/i })).toBeInTheDocument();
  expect(screen.queryByText(/continue to payment/i)).toBeNull();
});

it("joins the waitlist with the signed-in email filled in", async () => {
  const user = userEvent.setup();
  await renderPricing();
  const email = await screen.findByLabelText("Email");
  await waitFor(() => expect(email).toHaveValue("fan@example.com"));
  await user.click(screen.getByLabelText("Founding lifetime"));
  await user.click(screen.getByRole("button", { name: /join the waitlist/i }));

  await screen.findByRole("heading", { name: /you are on the list/i });
  const [, init] = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/waitlist"))!;
  expect(JSON.parse(String(init.body))).toMatchObject({ email: "fan@example.com", interest: "founding" });
});
