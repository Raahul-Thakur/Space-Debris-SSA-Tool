import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

/**
 * The phone menu in the console's top bar.
 *
 * Two things a keyboard or touch user notices at once and nobody else does:
 * Escape used to hide the menu with focus still inside it, so focus fell back
 * to the top of the document; and a tap outside left it covering the page.
 *
 * The console is rendered for real, with everything that would reach the
 * network or Cesium stubbed out.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("@/lib/auth", () => ({
  initializeAuth: () => Promise.resolve({ development: false, session: null }),
  getSupabase: () => null,
  signOut: () => Promise.resolve()
}));
vi.mock("@/lib/api", () => ({
  // Never answers: the menu does not depend on the API.
  publicApi: () => new Promise(() => {}),
  api: () => new Promise(() => {}),
  streamSse: () => () => {},
  isQuotaError: () => false
}));
vi.mock("@/lib/useActivityFeed", () => ({
  useActivityFeed: () => ({ items: [], status: "idle" })
}));
vi.mock("@/components/GlobeStage", () => ({ default: () => <div /> }));
vi.mock("@/components/ProductTour", () => ({ default: () => null }));

import CommandCenter from "@/components/CommandCenter";

async function openMenu() {
  render(<CommandCenter />);
  const toggle = await screen.findByRole("button", { name: "MENU" });
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  return toggle;
}

it("returns focus to the menu button when Escape closes it", async () => {
  const toggle = await openMenu();
  // Move into the menu, as a keyboard user would.
  screen.getByRole("link", { name: "PRICING" }).focus();

  await userEvent.keyboard("{Escape}");

  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
});

it("closes on a tap outside the menu", async () => {
  const toggle = await openMenu();
  await userEvent.click(screen.getByRole("heading", { level: 1 }));
  expect(toggle).toHaveAttribute("aria-expanded", "false");
});

it("stays open for a tap inside the menu", async () => {
  const toggle = await openMenu();
  // The clock is inside the menu and is not a control, so nothing else
  // would close the menu on this tap.
  await userEvent.click(screen.getByText(/ UTC$/));
  expect(toggle).toHaveAttribute("aria-expanded", "true");
});
