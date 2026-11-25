import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { addInlineScriptHashes, inlineScripts } from "../scripts/csp-hashes.mjs";

/**
 * Cloudflare Web Analytics is opt-in by build configuration, and the privacy
 * page has to tell the truth in both states. Every check here runs with the
 * token set and unset, because the failure that matters is the page claiming
 * one thing while the build does the other.
 */

const HEADERS = readFileSync(resolve(__dirname, "../public/_headers"), "utf8");

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function withToken(token: string | undefined) {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_CF_ANALYTICS_TOKEN", token ?? "");
  return import("@/lib/analytics");
}

async function renderPrivacy(token: string | undefined) {
  await withToken(token);
  const { default: PrivacyPage } = await import("@/app/privacy/page");
  render(<PrivacyPage />);
}

it("is off unless a token is set", async () => {
  expect((await withToken(undefined)).analyticsEnabled).toBe(false);
  expect((await withToken("   ")).analyticsEnabled).toBe(false);
  const on = await withToken("test-token");
  expect(on.analyticsEnabled).toBe(true);
  expect(on.beaconConfig()).toBe('{"token":"test-token"}');
  expect(on.CF_BEACON_SRC).toBe("https://static.cloudflareinsights.com/beacon.min.js");
});

it("lets the beacon load and report under the CSP, and does not hash it", () => {
  const policy = HEADERS.match(/Content-Security-Policy-Report-Only: (.+)/)![1];
  expect(policy).toMatch(/script-src [^;]*https:\/\/static\.cloudflareinsights\.com/);
  expect(policy).toMatch(/connect-src [^;]*https:\/\/cloudflareinsights\.com/);

  const beacon =
    '<script defer="" src="https://static.cloudflareinsights.com/beacon.min.js" ' +
    'data-cf-beacon="{&quot;token&quot;:&quot;t&quot;}"></script>';
  expect(inlineScripts(`<html><body><script>a()</script>${beacon}</body></html>`)).toEqual(["a()"]);
  const out = addInlineScriptHashes(HEADERS, new Map([["/", `<script>a()</script>${beacon}`]]));
  const home = out.slice(out.indexOf("\n/\n")).split("\n")[3];
  // Hashes are appended after the origin, inside the same directive.
  expect(home).toMatch(/script-src [^;]*cloudflareinsights\.com [^;]*'sha256-/);
});

it("says there is no visitor analytics when the token is unset", async () => {
  await renderPrivacy(undefined);
  expect(screen.getByText(/does not run any visitor analytics/i)).toBeInTheDocument();
  expect(screen.getByText(/there are no third-party scripts on any page/i)).toBeInTheDocument();
  expect(screen.getByText("No analytics or measurement product of any kind.")).toBeInTheDocument();
  expect(screen.getByText(/this build does not load it/i)).toBeInTheDocument();
  expect(screen.getByText("Cloudflare Web Analytics (if enabled)")).toBeInTheDocument();
});

it("describes Cloudflare Web Analytics, attributed to Cloudflare, when it is on", async () => {
  await renderPrivacy("test-token");
  expect(screen.getByRole("heading", { name: /counting visits and usage/i })).toBeInTheDocument();
  expect(screen.getByText(/cloudflare states that web analytics uses no cookies/i)).toBeInTheDocument();
  expect(screen.getByText(/the one third-party script on the site/i)).toBeInTheDocument();
  expect(screen.queryByText(/no third-party scripts on any page/i)).toBeNull();
  expect(screen.queryByText("No analytics or measurement product of any kind.")).toBeNull();
  expect(screen.getByRole("cell", { name: "Cloudflare Web Analytics" })).toBeInTheDocument();
  // The operator's own figures are described either way.
  expect(screen.getByText(/counts\s+only: no email addresses/i)).toBeInTheDocument();
  expect(screen.getByText(/Last\s+updated 25 November 2026/)).toBeInTheDocument();
});
