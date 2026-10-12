"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import {
  requestEmailCode,
  signInWithProvider,
  verifyEmailCode,
  type OAuthProvider
} from "@/lib/auth";

/**
 * Supabase refuses a second code for the same address inside a minute.
 * Showing the wait is kinder than letting someone press the button and be
 * told off for it.
 */
const RESEND_COOLDOWN_S = 60;

type Stage = "email" | "code";

/**
 * Identity providers, in the order they are offered.
 *
 * GitHub first on the evidence of who this is for: the orbital picture is
 * open source, and the people most likely to want an account are the ones
 * already reading the repository.
 */
const PROVIDERS: { id: OAuthProvider; label: string; icon: ReactNode }[] = [
  {
    id: "github",
    label: "GitHub",
    icon: (
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
      </svg>
    )
  },
  {
    id: "google",
    label: "Google",
    icon: (
      <svg viewBox="0 0 18 18" width="16" height="16" aria-hidden="true">
        <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
        <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
        <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z" />
        <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
      </svg>
    )
  }
];

export default function SignIn() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [redirecting, setRedirecting] = useState<OAuthProvider | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [cooldown]);

  useEffect(() => {
    if (stage === "code") codeRef.current?.focus();
  }, [stage]);

  function describe(caught: unknown): string {
    const message = caught instanceof Error ? caught.message : String(caught);
    // Supabase words this "email rate limit exceeded", which reads as though
    // the address is at fault. The limit is on the project, so the useful
    // advice is to take a route that is not metered at all.
    if (/rate limit/i.test(message)) {
      return (
        "The project has sent as many emails as it is allowed this hour. " +
        "This is a limit on the platform, not on your address, and trying " +
        "another one will not help. Sign in with GitHub or Google instead, " +
        "which is not metered, or try again later."
      );
    }
    if (/expired|invalid/i.test(message)) {
      return "That code is wrong or has expired. Codes last one hour.";
    }
    // Returned when a provider has not been enabled in the Supabase project.
    // Untranslated, the visitor sees "Unsupported provider" and reasonably
    // concludes the fault is theirs.
    if (/provider is not enabled|unsupported provider/i.test(message)) {
      return "That sign-in method is not available yet. Please use another.";
    }
    return message;
  }

  async function startProviderSignIn(provider: OAuthProvider) {
    if (busy || redirecting) return;
    setError("");
    setStatus("");
    setRedirecting(provider);
    try {
      // Navigates away when it succeeds, so there is no success branch.
      await signInWithProvider(provider);
    } catch (caught) {
      setRedirecting(null);
      setError(describe(caught));
    }
  }

  async function sendCode(event?: FormEvent) {
    event?.preventDefault();
    if (!email.trim() || busy || cooldown > 0) return;
    setBusy(true);
    setError("");
    setStatus("Sending a code…");
    try {
      await requestEmailCode(email.trim());
      setStage("code");
      setStatus(`Six-digit code sent to ${email.trim()}.`);
      setCooldown(RESEND_COOLDOWN_S);
    } catch (caught) {
      setStatus("");
      setError(describe(caught));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    if (code.trim().length < 6 || busy) return;
    setBusy(true);
    setError("");
    setStatus("Checking…");
    try {
      await verifyEmailCode(email.trim(), code);
      setStatus("Signed in.");
      router.replace("/");
    } catch (caught) {
      setStatus("");
      setError(describe(caught));
      setBusy(false);
    }
  }

  return (
    <main className="signin-shell">
      <section className="signin-panel">
        <div className="brand">
          <span className="brand-mark">A</span>
          <span>ASTRA / SSA</span>
        </div>
        <p className="eyebrow">VERIFIED ACCESS</p>
        <h1>
          Enter the
          <br />
          orbital picture.
        </h1>

        {stage === "email" ? (
          <>
            <p className="signin-copy">
              An account lets you screen objects of your own and keep a watch
              list; the orbital picture itself is public.
            </p>

            <div className="provider-row">
              {PROVIDERS.map((provider) => (
                <button
                  key={provider.id}
                  type="button"
                  className="provider-button"
                  disabled={busy || redirecting !== null}
                  onClick={() => void startProviderSignIn(provider.id)}
                >
                  {provider.icon}
                  {redirecting === provider.id
                    ? "REDIRECTING…"
                    : `CONTINUE WITH ${provider.label.toUpperCase()}`}
                </button>
              ))}
            </div>

            <p className="signin-divider">
              <span>OR BY EMAIL</span>
            </p>

            <form onSubmit={sendCode}>
              <label htmlFor="email">EMAIL ADDRESS</label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="operator@example.com"
              />
              <button type="submit" disabled={busy || redirecting !== null}>
                {busy ? "SENDING…" : "SEND CODE"} <span aria-hidden="true">&rarr;</span>
              </button>
            </form>
            <p className="signin-note">
              Emailed codes are rationed, and a busy hour can exhaust them for
              everybody at once. GitHub and Google are not.
            </p>
          </>
        ) : (
          <>
            <p className="signin-copy">
              Enter the code from your inbox. It is valid for one hour, and you can
              type it on any device — it does not have to be this one.
            </p>
            <form onSubmit={submitCode}>
              <label htmlFor="code">SIX-DIGIT CODE</label>
              <input
                id="code"
                ref={codeRef}
                // Numeric keypad on a phone, and one-tap autofill from the
                // email on iOS and Android.
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={6}
                required
                className="code-input"
                value={code}
                onChange={(event) =>
                  setCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                }
                placeholder="000000"
              />
              <button type="submit" disabled={busy || code.length < 6}>
                {busy ? "CHECKING…" : "SIGN IN"} <span aria-hidden="true">&rarr;</span>
              </button>
            </form>
            <p className="signin-secondary">
              <button type="button" onClick={() => void sendCode()} disabled={cooldown > 0}>
                {cooldown > 0 ? `RESEND IN ${cooldown}S` : "RESEND CODE"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setStage("email");
                  setCode("");
                  setError("");
                  setStatus("");
                }}
              >
                USE A DIFFERENT ADDRESS
              </button>
            </p>
          </>
        )}

        {error && <p className="signin-error">{error}</p>}
        {!error && status && <p className="signin-status">{status}</p>}

        <p className="signin-back">
          <Link href="/">← Back to the public picture</Link>
          {" · "}
          <Link href="/privacy">Privacy</Link>
        </p>
        <p className="science-notice">
          Educational screening platform. Outputs are illustrative and must not be used
          for operational maneuver decisions.
        </p>
      </section>
      {/* A ruled ink block: the page's dominant mass, carrying no illustration. */}
      <div className="signin-orbit" aria-hidden="true" />
    </main>
  );
}
