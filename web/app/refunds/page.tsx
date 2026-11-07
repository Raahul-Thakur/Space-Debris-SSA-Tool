import type { Metadata } from "next";
import Link from "next/link";
import SiteFooter from "@/components/SiteFooter";
import { CONTACT_EMAIL } from "@/lib/contact";

export const metadata: Metadata = {
  title: "Refunds",
  description: "When and how a payment for the Astra Pro plan is refunded."
};

/**
 * Kept generous on purpose. A refund costs the price of one month; a
 * chargeback costs a fee and counts against the merchant account. A clear
 * no-argument window is the cheaper policy as well as the fairer one.
 */
const UPDATED = "7 November 2026";
const WINDOW_DAYS = 14;

export default function RefundsPage() {
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
        <p className="eyebrow">REFUNDS</p>
        <h1>Refund policy</h1>
        <p>Last updated {UPDATED}.</p>

        <p className="account-notice">
          Astra is free during its public beta and nothing is on sale, so there is nothing to
          refund yet. This policy will apply once paid plans open.
        </p>

        <section>
          <h2>Within {WINDOW_DAYS} days, no questions</h2>
          <p>
            If Pro is not what you wanted, ask for a refund within {WINDOW_DAYS} days of a
            payment and you will get all of it back. This covers the first subscription
            payment, any renewal, and the founding purchase. You do not need to give a
            reason.
          </p>
        </section>

        <section>
          <h2>After {WINDOW_DAYS} days</h2>
          <p>
            Payments older than {WINDOW_DAYS} days are not normally refunded. Cancelling a
            subscription stops future charges, and Pro stays active until the end of the
            month you have paid for. If the service was unavailable for a large part of a
            paid period, or something else went wrong, write anyway. Requests are
            considered fairly.
          </p>
        </section>

        <section>
          <h2>How to ask</h2>
          <p>
            Reply to your receipt email from Dodo Payments, or write to{" "}
            <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> from the address you paid with.
            Refunds go back to the original payment method through Dodo Payments, usually
            within 5–10 business days depending on your bank.
          </p>
          <p>
            When a payment is refunded in full, Pro ends on the account straight away and
            it returns to the Free plan. A subscription is cancelled at the same time, so it
            does not charge you again. Your runs and watch list are kept.
          </p>
          <p>
            A partial refund, such as a credit for time the service was down, leaves Pro
            and the subscription as they are.
          </p>
        </section>

        <section>
          <h2>Chargebacks</h2>
          <p>
            Please ask for a refund before disputing a charge with your bank. It is quicker
            for you, and a dispute suspends Pro while it is open. If the dispute is withdrawn
            or closed without a refund, Pro comes back. If the bank refunds you, the
            subscription is cancelled as it would be for any other refund.
          </p>
        </section>

        <footer className="docs-footer">
          <Link href="/terms">
            Terms of use <span aria-hidden="true">-&gt;</span>
          </Link>
          <p>
            Payments are processed by Dodo Payments as merchant of record. Its terms also
            apply to the payment itself.
          </p>
        </footer>
        <SiteFooter />
      </main>
    </div>
  );
}
