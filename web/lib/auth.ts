import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { API_BASE, setAccessToken } from "./api";

export type AuthState = { session: Session | null; development: boolean };
let supabase: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  supabase ??= createClient(url, key);
  return supabase;
}

export async function initializeAuth(): Promise<AuthState> {
  if (process.env.NEXT_PUBLIC_AUTH_TEST_MODE === "unauthenticated") {
    setAccessToken(null);
    return { session: null, development: false };
  }
  const client = getSupabase();
  if (client) {
    const { data, error } = await client.auth.getSession();
    if (error) throw error;
    setAccessToken(data.session?.access_token ?? null);
    return { session: data.session, development: false };
  }
  const response = await fetch(`${API_BASE}/auth/development-token`, { method: "POST" });
  if (!response.ok) return { session: null, development: false };
  const body = (await response.json()) as { access_token: string };
  setAccessToken(body.access_token);
  return { session: null, development: true };
}

export async function signInWithEmail(email: string) {
  const client = getSupabase();
  if (!client) throw new Error("Supabase authentication is not configured");
  const { error } = await client.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.origin }
  });
  if (error) throw error;
}
