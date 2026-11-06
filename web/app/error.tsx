"use client";

import Link from "next/link";
import { useEffect } from "react";
import SiteFooter from "@/components/SiteFooter";

/**
 * A page that threw while rendering. The root layout, its fonts and its
 * stylesheet are still in place here, so this can look like the rest of the
 * site; `global-error.tsx` covers the case where the layout itself failed.
 *
 * `retry` fetches and re-renders the segment, which is enough for a
 * transient failure, such as an API that answered with something unexpected
 * while waking. The reload link is a full navigation on purpose: if the
 * retry fails too, a fresh load is the next thing worth trying.
 */
export default function ErrorPage({
  error,
  retry
}: {
  error: unknown;
  retry: () => void;
}) {
  useEffect(() => {
    // Kept in the browser console so a visitor's bug report can include it.
    console.error(error);
  }, [error]);

  return (
    <div className="docs-shell pricing-shell">
      <header className="docs-topbar">
        <Link href="/" className="brand">
          <span className="brand-mark">A</span>
          <span>ASTRA / SSA</span>
        </Link>
      </header>

      <main className="docs-body pricing-body" role="alert">
        <p className="eyebrow">ERROR</p>
        <h1>Something went wrong.</h1>
        <p className="docs-lede">
          This page hit an error it could not recover from. Trying again usually works. If
          it keeps happening, please write to the address below and say what you were
          doing.
        </p>
        <footer className="docs-footer status-actions">
          <button type="button" onClick={retry}>
            Try again <span aria-hidden="true">-&gt;</span>
          </button>
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- a full reload is the point */}
          <a href="/">
            Reload the console <span aria-hidden="true">-&gt;</span>
          </a>
        </footer>
        <SiteFooter />
      </main>
    </div>
  );
}
