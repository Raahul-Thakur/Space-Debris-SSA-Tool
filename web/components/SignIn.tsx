"use client";

import { FormEvent, useState } from "react";
import { signInWithEmail } from "@/lib/auth";

export default function SignIn() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setStatus("Sending secure link...");
    try {
      await signInWithEmail(email);
      setStatus("Check your inbox for the sign-in link.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Sign-in failed");
    }
  }

  return (
    <main className="signin-shell">
      <div className="signin-orbit" aria-hidden="true"><i /><i /><i /></div>
      <section className="signin-panel">
        <div className="brand"><span className="brand-mark">A</span><span>ASTRA / SSA</span></div>
        <p className="eyebrow">VERIFIED ACCESS</p>
        <h1>Enter the<br />orbital picture.</h1>
        <p className="signin-copy">A secure link will be sent to your email. New accounts receive read-only access.</p>
        <form onSubmit={submit}>
          <label htmlFor="email">EMAIL ADDRESS</label>
          <input id="email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="operator@example.com" />
          <button type="submit">SEND SIGN-IN LINK <span>-&gt;</span></button>
        </form>
        {status && <p className="signin-status">{status}</p>}
        <p className="science-notice">Educational screening platform. Outputs are illustrative and must not be used for operational maneuver decisions.</p>
      </section>
    </main>
  );
}
