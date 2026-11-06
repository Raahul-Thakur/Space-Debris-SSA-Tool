"use client";

import "./globals.css";

/**
 * The last resort, shown when the root layout itself throws. It replaces the
 * layout, so it brings its own <html> and <body> and does without the fonts
 * the layout sets up; the stylesheet's tokens and fallback faces still apply.
 * Deliberately minimal, because whatever broke the layout may be imported by
 * anything richer.
 */
export default function GlobalError({ retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="en">
      <body>
        <title>Something went wrong · Astra / SSA</title>
        <main className="docs-body pricing-body" role="alert">
          <p className="eyebrow">ERROR</p>
          <h1>Something went wrong.</h1>
          <p className="docs-lede">The site could not start. Trying again usually works.</p>
          <footer className="docs-footer status-actions">
            <button type="button" onClick={retry}>
              Try again <span aria-hidden="true">-&gt;</span>
            </button>
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- the app shell is what failed, so reload it */}
            <a href="/">
              Reload the console <span aria-hidden="true">-&gt;</span>
            </a>
          </footer>
        </main>
      </body>
    </html>
  );
}
