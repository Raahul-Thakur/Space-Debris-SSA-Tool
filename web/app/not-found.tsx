import type { Metadata } from "next";
import Link from "next/link";
import SiteFooter from "@/components/SiteFooter";

export const metadata: Metadata = {
  title: "Page not found",
  // A missing page should never be indexed under the address that missed.
  robots: { index: false }
};

/**
 * What a mistyped or retired address shows. In the static export this page
 * is written to 404.html, which Cloudflare Pages serves, with a 404 status,
 * for any path that matches no file. It offers the two places almost every
 * visitor was trying to reach rather than a bare apology.
 */
export default function NotFound() {
  return (
    <div className="docs-shell pricing-shell">
      <header className="docs-topbar">
        <Link href="/" className="brand">
          <span className="brand-mark">A</span>
          <span>ASTRA / SSA</span>
        </Link>
        <nav>
          <Link href="/" className="docs-back">
            OPEN CONSOLE <span aria-hidden="true">-&gt;</span>
          </Link>
        </nav>
      </header>

      <main className="docs-body pricing-body">
        <p className="eyebrow">404 / NOT FOUND</p>
        <h1>No such page.</h1>
        <p className="docs-lede">
          This address does not match anything on the site. It may have been mistyped, or
          the page may have moved.
        </p>
        <footer className="docs-footer status-actions">
          <Link href="/">
            Open the console <span aria-hidden="true">-&gt;</span>
          </Link>
          <Link href="/docs">
            Read the docs <span aria-hidden="true">-&gt;</span>
          </Link>
        </footer>
        <SiteFooter />
      </main>
    </div>
  );
}
