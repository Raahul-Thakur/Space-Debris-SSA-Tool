"use client";

import Link from "next/link";
import { useState } from "react";
import { SAMPLE_CATEGORIES, SAMPLE_QUERIES } from "@/lib/samples";

export default function DocsSamples() {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(command: string) {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(command);
      setTimeout(() => setCopied((current) => (current === command ? null : current)), 1600);
    } catch {
      // Clipboard access can be denied; the command stays selectable on screen.
    }
  }

  return (
    <div className="docs-samples">
      {SAMPLE_CATEGORIES.map((category) => {
        const samples = SAMPLE_QUERIES.filter((sample) => sample.category === category);
        if (!samples.length) return null;
        return (
          <section key={category}>
            <h3>{category}</h3>
            {samples.map((sample) => (
              <article key={sample.command}>
                <header>
                  <code>{sample.command}</code>
                  <span className={`docs-role ${sample.role}`}>{sample.role}</span>
                </header>
                <p>{sample.description}</p>
                <footer>
                  {sample.duration && <span className="docs-duration">{sample.duration}</span>}
                  <button type="button" onClick={() => copy(sample.command)}>
                    {copied === sample.command ? "COPIED" : "COPY"}
                  </button>
                  {sample.placeholder ? (
                    <span className="docs-needs-id">needs an id</span>
                  ) : (
                    <Link href={`/?command=${encodeURIComponent(sample.command)}`}>
                      RUN IN CONSOLE <span aria-hidden="true">-&gt;</span>
                    </Link>
                  )}
                </footer>
              </article>
            ))}
          </section>
        );
      })}
    </div>
  );
}
