import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * Token handling, pinned.
 *
 * These exist because a magic-link callback once put a live refresh token in
 * the address bar, where it stayed in history and could be pasted somewhere
 * it did not belong. The defence is two-layered — PKCE so the URL never
 * carries a token in the first place, and scrubbing so nothing lingers even
 * when it does — and both layers are easy to remove by accident.
 */

const { createClient } = vi.hoisted(() => ({ createClient: vi.fn() }));
vi.mock("@supabase/supabase-js", () => ({ createClient }));

const session = { access_token: "header.payload.signature" };
const auth = {
  getSession: vi.fn(async () => ({ data: { session }, error: null })),
  signInWithOtp: vi.fn(async () => ({ error: null })),
  signOut: vi.fn(async () => ({ error: null })),
};

beforeEach(() => {
  vi.resetModules();
  createClient.mockReset().mockReturnValue({ auth });
  auth.getSession.mockClear();
  auth.signOut.mockClear();
  auth.signInWithOtp.mockClear();
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://project.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key";
  delete process.env.NEXT_PUBLIC_AUTH_TEST_MODE;
  window.history.replaceState(null, "", "/");
});

afterEach(() => vi.restoreAllMocks());

it("asks for the PKCE flow, so a magic link carries a code and not a token", async () => {
  const { getSupabase } = await import("@/lib/auth");
  getSupabase();
  const options = createClient.mock.calls[0][2];
  expect(options.auth.flowType).toBe("pkce");
});

it("states its session options rather than inheriting them", async () => {
  const { getSupabase } = await import("@/lib/auth");
  getSupabase();
  const { auth: opts } = createClient.mock.calls[0][2];
  expect(opts.persistSession).toBe(true);
  expect(opts.autoRefreshToken).toBe(true);
  expect(opts.detectSessionInUrl).toBe(true);
});

it("removes a spent code from the address bar after sign-in", async () => {
  window.history.replaceState(null, "", "/?code=abc123&type=magiclink");
  const { initializeAuth } = await import("@/lib/auth");
  await initializeAuth();
  expect(window.location.search).not.toContain("code=");
  expect(window.location.search).not.toContain("type=");
});

it("removes tokens left in the fragment by the older implicit flow", async () => {
  window.history.replaceState(
    null, "", "/#access_token=live.jwt.value&refresh_token=secret&expires_in=3600"
  );
  const { initializeAuth } = await import("@/lib/auth");
  await initializeAuth();
  expect(window.location.hash).not.toContain("access_token");
  expect(window.location.hash).not.toContain("refresh_token");
});

it("keeps query parameters that are not part of the callback", async () => {
  // The docs page deep-links into the console with ?command=…; scrubbing the
  // callback must not discard it.
  window.history.replaceState(null, "", "/?command=screen+25544&code=abc");
  const { initializeAuth } = await import("@/lib/auth");
  await initializeAuth();
  expect(window.location.search).toContain("command=");
  expect(window.location.search).not.toContain("code=");
});

it("leaves an ordinary URL untouched", async () => {
  window.history.replaceState(null, "", "/docs");
  const { initializeAuth } = await import("@/lib/auth");
  await initializeAuth();
  expect(window.location.pathname).toBe("/docs");
});

it("signs out of this device only", async () => {
  // Signing someone out of their phone because they closed a laptop tab is
  // a surprise; `signOutEverywhere` is the deliberate version.
  const { signOut } = await import("@/lib/auth");
  await signOut();
  expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
});

it("offers a way to revoke every session when a credential leaks", async () => {
  const { signOutEverywhere } = await import("@/lib/auth");
  await signOutEverywhere();
  expect(auth.signOut).toHaveBeenCalledWith({ scope: "global" });
});

it("drops the local token even when the server call fails", async () => {
  auth.signOut.mockRejectedValueOnce(new Error("offline"));
  const mod = await import("@/lib/auth");
  const api = await import("@/lib/api");
  api.setAccessToken("stale.token");
  await expect(mod.signOut()).rejects.toThrow();
  // The correct outcome of a failed sign-out is still that this tab stops
  // acting as the user.
  expect(api.getAccessToken()).toBeNull();
});
