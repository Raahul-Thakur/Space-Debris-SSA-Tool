"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { api } from "@/lib/api";

type Interest = "pro-monthly" | "founding" | "either";

const INTERESTS: { value: Interest; label: string }[] = [
  { value: "pro-monthly", label: "Pro, monthly" },
  { value: "founding", label: "Founding lifetime" },
  { value: "either", label: "Not sure yet" }
];

/**
 * Sign up to hear when paid plans open. No account needed.
 *
 * The hidden "website" field is a trap for form-filling bots: people never
 * see it, and the API quietly discards any sign-up that fills it in.
 */
export default function Waitlist({ initialEmail = "" }: { initialEmail?: string }) {
  // What the person typed, or null to show the signed-in address, which
  // arrives after the first render. Derived rather than copied into state,
  // so a late address still appears and never overwrites typing.
  const [typed, setTyped] = useState<string | null>(null);
  const email = typed ?? initialEmail;
  const [interest, setInterest] = useState<Interest>("either");
  const [note, setNote] = useState("");
  const [website, setWebsite] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "joined">("idle");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setState("sending");
    try {
      await api("/waitlist", {
        method: "POST",
        body: JSON.stringify({ email, interest, note: note || undefined, website: website || undefined })
      });
      setState("joined");
    } catch (caught) {
      setState("idle");
      const message = caught instanceof Error ? caught.message : "";
      setError(
        message && !message.startsWith("Request failed")
          ? message
          : "That did not go through. The service may be waking up; try again in a minute."
      );
    }
  }

  if (state === "joined") {
    return (
      <section className="waitlist" aria-live="polite">
        <p className="eyebrow">WAITLIST</p>
        <h2>You are on the list</h2>
        <p>
          We will email <strong>{email.trim().toLowerCase()}</strong> once, when paid plans open.
          Until then, everything stays free.
        </p>
      </section>
    );
  }

  return (
    <section className="waitlist" aria-labelledby="waitlist-title">
      <p className="eyebrow">WAITLIST</p>
      <h2 id="waitlist-title">Hear first when Pro opens</h2>
      <p>
        Leave your email and we will write once, when paid plans go on sale, before anyone
        else hears. Nothing else is sent, and you can ask to be removed at any time.
      </p>
      <form className="waitlist-form" onSubmit={(event) => void submit(event)}>
        <label className="waitlist-field" htmlFor="waitlist-email">
          <span>Email</span>
          <input
            id="waitlist-email"
            type="email"
            required
            autoComplete="email"
            inputMode="email"
            maxLength={254}
            value={email}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="you@example.com"
          />
        </label>

        <fieldset className="waitlist-interest">
          <legend>Which plan interests you?</legend>
          {INTERESTS.map((option) => (
            <label key={option.value}>
              <input
                type="radio"
                name="waitlist-interest"
                value={option.value}
                checked={interest === option.value}
                onChange={() => setInterest(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </fieldset>

        <label className="waitlist-field" htmlFor="waitlist-note">
          <span>What would you use it for? (optional)</span>
          <textarea
            id="waitlist-note"
            rows={3}
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="A university CubeSat, research, curiosity…"
          />
        </label>

        <div className="waitlist-trap" aria-hidden="true">
          <label htmlFor="waitlist-website">Website</label>
          <input
            id="waitlist-website"
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(event) => setWebsite(event.target.value)}
          />
        </div>

        <button type="submit" disabled={state === "sending"}>
          {state === "sending" ? "JOINING…" : "JOIN THE WAITLIST →"}
        </button>
        {error && <p className="command-error pricing-error">{error}</p>}
        <p className="account-note">
          Your address is used for this one email and nothing else. See the{" "}
          <Link href="/privacy">privacy page</Link>.
        </p>
      </form>
    </section>
  );
}
