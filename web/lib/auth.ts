import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { API_BASE, setAccessToken } from "./api";

export type AuthState = {
  session: Session | null;
  development: boolean;
  /** The application role the API will enforce for this caller. */
  role: string;
};

/**
 * Read the role claim out of a token, for display only.
 *
 * The server verifies the signature and decides what the caller may do; this
 * is purely so the account page can state the role without a second request.
 * Anything unreadable falls back to the least privileged value, matching how
 * the API treats a missing or unrecognised claim.
 */
function roleFromToken(token: string): string {
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const claims = JSON.parse(json) as { app_metadata?: { role?: string } };
    return claims.app_metadata?.role ?? "viewer";
  } catch {
    return "viewer";
  }
}
let supabase: SupabaseClient | null = null;

/**
 * The Supabase client, configured explicitly rather than by default.
 *
 * Every option below is the library's default except `flowType`, and they are
 * written out anyway: authentication behaviour that matters should be
 * readable here rather than inferred from a version of a dependency.
 *
 * `pkce` is the important one. Under the older implicit flow a magic link
 * returns the access *and refresh* tokens in the URL fragment, so a working
 * credential ends up in the address bar, in browser history, and in any
 * screenshot or pasted link. A refresh token obtained that way keeps minting
 * access tokens until somebody revokes the session.
 *
 * PKCE returns a single-use `code` instead, which the SDK exchanges for a
 * session using a verifier held in this browser. The code is worthless to
 * anyone who intercepts it, because they do not have the verifier.
 *
 * The trade-off is that the link must be opened in the browser that asked
 * for it: requesting on a laptop and opening on a phone will not work. That
 * is the accepted cost, and `signInWithEmail` warns about it.
 */
export function getSupabase(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  supabase ??= createClient(url, key, {
    auth: {
      flowType: "pkce",
      detectSessionInUrl: true,
      persistSession: true,
      autoRefreshToken: true
    }
  });
  return supabase;
}

/**
 * Remove any authentication parameters the sign-in redirect left behind.
 *
 * Belt and braces. PKCE means the only thing in the URL is a spent code, and
 * the SDK already consumes it, but a spent code still should not sit in the
 * address bar to be copied, and a project that has not yet been switched to
 * PKCE will arrive here with real tokens in the fragment. Using
 * `replaceState` rather than a navigation keeps the page mounted.
 */
function scrubAuthParamsFromUrl() {
  if (typeof window === "undefined") return;
  const { hash, search, pathname } = window.location;
  const sensitive = /(access_token|refresh_token|provider_token|code|token_hash)=/;
  if (!sensitive.test(hash) && !sensitive.test(search)) return;

  const params = new URLSearchParams(search);
  for (const key of ["code", "token_hash", "type", "error", "error_description"]) {
    params.delete(key);
  }
  const query = params.toString();
  window.history.replaceState(null, "", pathname + (query ? `?${query}` : ""));
}

export async function initializeAuth(): Promise<AuthState> {
  if (process.env.NEXT_PUBLIC_AUTH_TEST_MODE === "unauthenticated") {
    setAccessToken(null);
    return { session: null, development: false, role: "viewer" };
  }
  const client = getSupabase();
  if (client) {
    // getSession resolves after the SDK has exchanged any code in the URL,
    // so scrubbing afterwards cannot race the exchange.
    const { data, error } = await client.auth.getSession();
    scrubAuthParamsFromUrl();
    if (error) throw error;
    setAccessToken(data.session?.access_token ?? null);
    return {
      session: data.session,
      development: false,
      role: String(data.session?.user?.app_metadata?.role ?? "viewer"),
    };
  }
  const response = await fetch(`${API_BASE}/auth/development-token`, { method: "POST" });
  if (!response.ok) return { session: null, development: false, role: "viewer" };
  const body = (await response.json()) as { access_token: string };
  setAccessToken(body.access_token);
  // The development issuer mints an admin token; reporting "viewer" here
  // would contradict what the API actually permits.
  return { session: null, development: true, role: roleFromToken(body.access_token) };
}

export async function signInWithEmail(email: string) {
  const client = getSupabase();
  if (!client) throw new Error("Supabase authentication is not configured");
  const { error } = await client.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${window.location.origin}/` }
  });
  if (error) throw error;
}

/**
 * End the session on this device.
 *
 * Scoped locally, because that is what a sign-out button is understood to
 * mean; signing someone out of their phone because they closed a laptop tab
 * is a surprise. `signOutEverywhere` exists for the case where a credential
 * is believed to have leaked.
 *
 * The in-memory access token is cleared whatever the server says: if the
 * network call fails, the correct outcome is still that this tab stops
 * acting as the user.
 */
export async function signOut() {
  const client = getSupabase();
  setAccessToken(null);
  if (client) await client.auth.signOut({ scope: "local" });
}

/** Revoke every session for this account, on every device. */
export async function signOutEverywhere() {
  const client = getSupabase();
  setAccessToken(null);
  if (client) await client.auth.signOut({ scope: "global" });
}
