import type { Metadata } from "next";
import Link from "next/link";
import SiteFooter from "@/components/SiteFooter";
import { CONTACT_EMAIL } from "@/lib/contact";

export const metadata: Metadata = {
  title: "Terms · Astra / SSA",
  description:
    "The terms for using the Astra space situational awareness console and buying its Pro plan."
};

/**
 * Written to be read, like the privacy page. The clause that matters most is
 * the one on outputs: the platform sells screening capacity over public data
 * with a synthetic covariance model, and nobody should be able to read a
 * purchase as buying an operational collision-avoidance service.
 */
const UPDATED = "1 November 2026";

const SECTIONS = [
  { id: "summary", label: "The short version" },
  { id: "service", label: "What the service is" },
  { id: "outputs", label: "Outputs are illustrative" },
  { id: "accounts", label: "Accounts and acceptable use" },
  { id: "paid", label: "Pro plan and payment" },
  { id: "data", label: "Data sources" },
  { id: "warranty", label: "No warranty" },
  { id: "liability", label: "Limitation of liability" },
  { id: "ending", label: "Ending your use" },
  { id: "law", label: "Governing law" },
  { id: "changes", label: "Changes" }
];

export default function TermsPage() {
  return (
    <div className="docs-shell">
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

      <aside className="docs-nav" aria-label="Terms sections">
        <p className="eyebrow">CONTENTS</p>
        <ol>
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>{section.label}</a>
            </li>
          ))}
        </ol>
      </aside>

      <main className="docs-body">
        <p className="eyebrow">TERMS</p>
        <h1>Terms of use</h1>
        <p>
          These terms cover the Astra console, its API and the Pro plan. They are between
          you and Rahul Thakur, who runs the service as an individual. Last updated{" "}
          {UPDATED}.
        </p>

        <section id="summary">
          <h2>The short version</h2>
          <ul className="docs-list">
            <li>Astra is an educational screening tool. It is not an operational service.</li>
            <li>
              Nothing it produces may be used to decide a real manoeuvre, or to make any
              other decision about a real spacecraft.
            </li>
            <li>
              Pro buys more capacity: more runs, longer windows and a bigger watch list. The
              science is the same on every plan.
            </li>
            <li>
              Payments are processed by Dodo Payments, which is the seller of record.
            </li>
          </ul>
        </section>

        <section id="service">
          <h2>What the service is</h2>
          <p>
            Astra screens public orbital data for close approaches between objects. It
            propagates two-line element sets with SGP4, finds each time of closest approach,
            and estimates a collision probability from a covariance model that is
            synthetic and weighted by data age. The method and its limits are set out in
            the <Link href="/docs">documentation</Link>.
          </p>
          <p>
            The service runs on shared, low-cost infrastructure. It can be slow to wake,
            briefly unavailable, or changed without notice. There is no uptime commitment
            on any plan.
          </p>
        </section>

        <section id="outputs">
          <h2>Outputs are illustrative</h2>
          <p>
            Two-line element sets are not precise enough, and the covariance used here is
            not real enough, to support operational conclusions. Every miss distance,
            probability and risk tier Astra reports is an illustration of how a screening
            pipeline behaves. None is a statement about what will actually happen in orbit.
          </p>
          <p>
            You agree not to rely on Astra, or present its outputs as reliable, for collision
            avoidance, mission operations, insurance, regulatory filings, safety-of-flight
            assessment, or any other decision with physical, financial or legal
            consequences. For operational conjunction assessment, use an authoritative
            provider such as the conjunction data messages issued to registered operators.
          </p>
        </section>

        <section id="accounts">
          <h2>Accounts and acceptable use</h2>
          <p>
            You need an account to run commands. Keep your sign-in to yourself; you are
            responsible for what is done with it. Do not:
          </p>
          <ul className="docs-list">
            <li>try to get around plan limits, rate limits or role checks;</li>
            <li>probe, overload or disrupt the service or its infrastructure;</li>
            <li>access another account&apos;s data;</li>
            <li>resell access to the service, or scrape it in bulk.</li>
          </ul>
          <p>
            An account that does any of these may be suspended. If it is a paid account, the
            refund policy still applies to the unused part of the period.
          </p>
        </section>

        <section id="paid">
          <h2>Pro plan and payment</h2>
          <p>
            Pro is sold as a monthly subscription and, while seats remain, as a one-time
            founding purchase. The limits each plan allows are shown on the{" "}
            <Link href="/pricing">pricing page</Link>, which is the definitive statement of
            what you are buying.
          </p>
          <p>
            Checkout, billing, tax and receipts are handled by Dodo Payments as merchant of
            record. Its own terms apply to the payment. Prices are in US dollars, and any
            sales tax or VAT is added at checkout.
          </p>
          <ul className="docs-list">
            <li>
              <strong>Subscription.</strong> Renews monthly until cancelled. Cancel at any
              time from your account page; Pro stays active until the end of the month
              already paid for, and you are not charged again.
            </li>
            <li>
              <strong>Founding purchase.</strong> Pro for as long as the service runs, with
              no further charge. It is not a promise to keep the service running forever. If
              the service closes, founding buyers will get at least 60 days&apos; notice.
            </li>
          </ul>
          <p>
            Refunds are described in the <Link href="/refunds">refund policy</Link>. Limits
            may be raised at any time. They will not be lowered for a period you have
            already paid for.
          </p>
        </section>

        <section id="data">
          <h2>Data sources</h2>
          <p>
            Orbital elements come from CelesTrak, which publishes them from public sources.
            Astra does not own that data and makes no claim about its accuracy or
            completeness. What Pro sells is computing capacity over that data, not the data
            itself.
          </p>
        </section>

        <section id="warranty">
          <h2>No warranty</h2>
          <p>
            The service is provided as is and as available. To the extent the law allows,
            there are no warranties of any kind, express or implied. That includes
            warranties of accuracy, fitness for a particular purpose, merchantability and
            uninterrupted availability.
          </p>
        </section>

        <section id="liability">
          <h2>Limitation of liability</h2>
          <p>
            To the extent the law allows, Rahul Thakur is not liable for any indirect,
            incidental, consequential or special loss. That includes loss of a spacecraft,
            mission, data, revenue or profit, arising from your use of the service or your
            reliance on its outputs.
          </p>
          <p>
            Total liability for any claim is limited to the amount you paid for the service
            in the twelve months before the claim arose. Nothing here limits liability that
            cannot be limited by law.
          </p>
        </section>

        <section id="ending">
          <h2>Ending your use</h2>
          <p>
            You can stop using the service at any time. To delete your account, follow the
            steps in the <Link href="/privacy#deletion">privacy policy</Link>. Cancel any
            subscription first, from your account page.
          </p>
        </section>

        <section id="law">
          <h2>Governing law</h2>
          <p>
            These terms are governed by the laws of India. If you buy as a consumer, you
            keep any protections the law of your own country gives you.
          </p>
          <p>
            Questions or complaints go to <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
          </p>
        </section>

        <section id="changes">
          <h2>Changes</h2>
          <p>
            If these terms change, the date at the top changes with them, and every revision
            stays public in the repository. A change that reduces what a paying customer
            gets will be emailed to them at least 30 days before it takes effect.
          </p>
        </section>

        <footer className="docs-footer">
          <Link href="/refunds">
            Refund policy <span aria-hidden="true">-&gt;</span>
          </Link>
        </footer>
        <SiteFooter />
      </main>
    </div>
  );
}
