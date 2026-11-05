import Link from "next/link";
import { CONTACT_EMAIL } from "@/lib/contact";

/**
 * The footer every page ends with: who to contact, where everything else
 * lives, and the standing reminder that the numbers are illustrative.
 *
 * The address is printed as text as well as linked, because a `mailto:` link
 * does nothing for a reader without a mail app set up, and they still need
 * something they can copy.
 */
export default function SiteFooter({ className }: { className?: string }) {
  return (
    <footer className={`site-footer${className ? ` ${className}` : ""}`}>
      <div className="site-footer-contact">
        <p className="eyebrow">CONTACT</p>
        <p>Questions, feedback or a bug to report? Write to</p>
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
      </div>
      <nav className="site-footer-links" aria-label="Site">
        <Link href="/">Console</Link>
        <Link href="/docs">Docs</Link>
        <Link href="/pricing">Pricing</Link>
        <Link href="/terms">Terms</Link>
        <Link href="/privacy">Privacy</Link>
        <Link href="/refunds">Refunds</Link>
      </nav>
      <p className="site-footer-note">
        Astra / SSA is an educational screening platform. Outputs are illustrative and
        must not be used for operational maneuver decisions.
      </p>
    </footer>
  );
}
