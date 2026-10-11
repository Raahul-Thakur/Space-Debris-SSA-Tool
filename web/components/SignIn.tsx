"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import { requestEmailCode, verifyEmailCode } from "@/lib/auth";

/**
 * Supabase refuses a second code for the same address inside a minute.
 * Showing the wait is kinder than letting someone press the button and be
 * told off for it.
 */
const RESEND_COOLDOWN_S = 60;

type Stage = "email" | "code";

export default function SignIn() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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
    // Supabase's own wording for this is "email rate limit exceeded", which
    // reads as though the address is at fault. The limit is on the project.
    if (/rate limit/i.test(message)) {
      return (
        "The project has sent as many emails as it is allowed this hour. " +
        "This is a limit on the platform, not on your address, and trying " +
        "another one will not help. Please try again later."
      );
    }
    if (/expired|invalid/i.test(message)) {
      return "That code is wrong or has expired. Codes last one hour.";
    }
    return message;
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
              We will email you a six-digit code. An account lets you screen objects
              of your own and keep a watch list; the orbital picture itself is
              public.
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
              <button type="submit" disabled={busy}>
                {busy ? "SENDING…" : "SEND CODE"} <span aria-hidden="true">&rarr;</span>
              </button>
            </form>
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
