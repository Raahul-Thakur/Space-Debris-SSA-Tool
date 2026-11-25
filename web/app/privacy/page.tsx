import type { Metadata } from "next";
import Link from "next/link";
import SiteFooter from "@/components/SiteFooter";
import { analyticsEnabled } from "@/lib/analytics";
import { CONTACT_EMAIL } from "@/lib/contact";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What the Astra space situational awareness console collects, who processes it, and how to have it deleted."
};

/**
 * Required before Google will publish the OAuth consent screen, but written to
 * be true rather than to satisfy a form. Every claim here is checkable against
 * the source: the only analytics is Cloudflare Web Analytics, loaded only when
 * NEXT_PUBLIC_CF_ANALYTICS_TOKEN is set (lib/analytics.ts), and the sentences
 * about it follow that same setting, so a build without it never claims it;
 * the admin figures are aggregates computed by src/sdebris/usage.py and
 * latency.py; the request logger records no address; and the personal fields
 * the database holds are the email the identity provider returned and, for
 * buyers, what the billing webhook keeps after `ledger_payload` strips card
 * and address details.
 *
 * What is said about Cloudflare Web Analytics is Cloudflare's own description
 * of the product, attributed to it, not something this site can verify.
 */
const UPDATED = "25 November 2026";

const SECTIONS = [
  { id: "summary", label: "The short version" },
  { id: "reading", label: "Reading without an account" },
  { id: "account", label: "If you sign in" },
  { id: "waitlist", label: "If you join the waitlist" },
  { id: "paying", label: "If you buy Pro" },
  { id: "browser", label: "What is stored in your browser" },
  { id: "measurement", label: "Counting visits and usage" },
  { id: "not", label: "What this site does not do" },
  { id: "processors", label: "Who else handles it" },
  { id: "retention", label: "How long it is kept" },
  { id: "deletion", label: "Deleting your account" },
  { id: "changes", label: "Changes" }
];

export default function PrivacyPage() {
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

      <aside className="docs-nav" aria-label="Privacy sections">
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
        <p className="eyebrow">PRIVACY</p>
        <h1>What this site knows about you</h1>
        <p>
          Astra is an open-source, educational space situational awareness tool. Last
          updated {UPDATED}.
        </p>

        <section id="summary">
          <h2>The short version</h2>
          <p>
            You can read everything on this site without an account, and if you do, no
            personal data is collected by this site. There is no advertising, and nothing
            follows you between visits or across other websites.
          </p>
          <p>
            {analyticsEnabled
              ? "Page visits are counted with Cloudflare Web Analytics, which Cloudflare describes as cookie-free and not based on fingerprinting. "
              : "This site does not run any visitor analytics. "}
            The operator also sees aggregate counts, such as how many accounts were active
            this week or how many screenings ran, computed from the records described
            below. <a href="#measurement">Counting visits and usage</a> has the detail.
          </p>
          <p>
            If you choose to sign in, the only personal information held is the email
            address your identity provider returns, plus a name and avatar if you signed
            in with GitHub or Google. That email is recorded against the work you do, so
            the platform can show you your own results and not somebody else&apos;s.
          </p>
          <p>Nothing is sold, shared for advertising, or used to build a profile.</p>
        </section>

        <section id="reading">
          <h2>Reading without an account</h2>
          <p>
            The orbital picture — the object catalogue, conjunction events, risk tiers and
            trajectories — is public and requires no account. Viewing it collects nothing
            about you.
          </p>
          <p>
            Most of those pages are served from a cache at the network edge and never
            reach the application at all. When a request does reach it, the application
            log records the method, the path, the response status and how long it took.
            It does not record your IP address, and it does not record your browser&apos;s
            user agent. For the response-time figures described below, the application
            also keeps, in memory only, the route&apos;s pattern (for example{" "}
            <code>/objects/{"{norad_id}"}</code>, never the object you asked for), the
            status and the time taken, for at most the last hour.
          </p>
        </section>

        <section id="account">
          <h2>If you sign in</h2>
          <p>There are three ways to sign in, and each shares a little less than the last:</p>
          <ul className="docs-list">
            <li>
              <strong>GitHub or Google.</strong> The provider tells us your email address,
              your display name and the URL of your avatar image. It does not tell us your
              password, and it does not give access to your repositories, documents, mail
              or contacts.
            </li>
            <li>
              <strong>A six-digit code by email.</strong> Only your email address.
            </li>
          </ul>
          <p>
            Once you have an account, your email address is stored alongside the things you
            do: screening runs you start, objects you add to your watch list, commands you
            issue, and the audit record of any governed action. That association is the
            mechanism by which your work stays yours — it is what the platform checks before
            showing you a result.
          </p>
          <p>
            Your account is also given a role, which determines what you are allowed to run.
            That is the extent of the decision-making applied to your data; nothing here is
            automated profiling.
          </p>
        </section>

        <section id="waitlist">
          <h2>If you join the waitlist</h2>
          <p>
            The waitlist on the pricing page stores the email address you give, which plan
            you said interests you, the note if you wrote one, the time, and your account if
            you were signed in. It is used for one thing: an email when paid plans open. It
            is not shared, and it is not used for anything else.
          </p>
          <p>
            To be removed, email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> and
            the entry is deleted.
          </p>
        </section>

        <section id="paying">
          <h2>If you buy Pro</h2>
          <p>
            Pro is not on sale during the public beta, so nothing in this section applies
            yet. It describes what will happen once paid plans open.
          </p>
          <p>
            Payment happens on a checkout page run by Dodo Payments, the merchant of record.
            Your card number never reaches this site. Dodo collects what it needs to take
            the payment and work out tax: your name, email, billing country and card. Its
            own privacy policy governs that.
          </p>
          <p>
            When a payment succeeds, Dodo tells this platform so your account can be
            upgraded. What is kept from that message:
          </p>
          <ul className="docs-list">
            <li>your name and email address as you gave them at checkout;</li>
            <li>Dodo&apos;s identifiers for you, the payment and any subscription;</li>
            <li>which product you bought, the amount, the currency and the dates.</li>
          </ul>
          <p>
            Your billing address and card details (brand, last four digits, expiry and
            cardholder name) are deleted from that message before it is stored. Payment
            records are kept for as long as tax and accounting rules require, even after
            an account is deleted.
          </p>
        </section>

        <section id="browser">
          <h2>What is stored in your browser</h2>
          <ul className="docs-list">
            <li>
              <strong>Your sign-in session</strong>, so that you stay signed in between
              visits. Signing out removes it.
            </li>
            <li>
              <strong>Which conjunction events you have already seen</strong>, so the
              console can mark what is new since your last visit. This never leaves your
              browser and is not linked to your account.
            </li>
          </ul>
          <p>
            No tracking cookies are set, by this site or by anyone else.{" "}
            {analyticsEnabled
              ? "The one third-party script on the site is Cloudflare's Web Analytics beacon, described below; Cloudflare says it sets no cookies and stores nothing in your browser. "
              : "There are no third-party scripts on any page. "}
            The typefaces are served from this site too, so loading a page does not
            contact Google Fonts or any other font service.
          </p>
        </section>

        <section id="measurement">
          <h2>Counting visits and usage</h2>
          <p>Two things are measured, both in aggregate.</p>
          <h3>Page visits: Cloudflare Web Analytics</h3>
          {analyticsEnabled ? (
            <>
              <p>
                Every page loads a small script from Cloudflare,{" "}
                <code>static.cloudflareinsights.com</code>, which reports the visit to{" "}
                <code>cloudflareinsights.com</code>. It is run by Cloudflare, which already
                hosts this site. As Cloudflare describes it, the report covers the page
                visited, the referring page, your browser, operating system and device
                type, the country the visit came from, and how quickly the page loaded.
              </p>
              <p>
                Cloudflare states that Web Analytics uses no cookies or local storage, does
                not fingerprint visitors, and does not use your IP address to track you or
                store it for analytics. Your browser does send the report from your IP
                address, as it does every request, and Cloudflare&apos;s handling of that
                is governed by its own privacy policy. What this site&apos;s operator sees
                is a dashboard of totals: visits, popular pages, referrers, countries,
                browsers and load times. It does not show individual visitors.
              </p>
              <p>
                Blocking the script, as many content blockers do, changes nothing about how
                the site works.
              </p>
            </>
          ) : (
            <p>
              The site is set up to use Cloudflare Web Analytics, but this build does not
              load it: no script from Cloudflare runs on these pages. If it is switched
              on, this section describes what it collects.
            </p>
          )}
          <h3>Use of the service: the operator&apos;s own figures</h3>
          <p>
            An administrator&apos;s page shows totals computed from the records the service
            already keeps to work at all: how many accounts ran a command, started a
            screening or watched an object in the last day, week and month; how many
            accounts appeared each week; how many screenings ran each day and how long they
            took; the size of the waitlist; and how quickly the API has been answering,
            by route. Nothing new is recorded for these figures, and the page shows counts
            only: no email addresses, account names or commands.
          </p>
          <p>
            The response times are held in the API&apos;s memory for at most an hour and
            are lost whenever it restarts.
          </p>
        </section>

        <section id="not">
          <h2>What this site does not do</h2>
          <ul className="docs-list">
            <li>
              {analyticsEnabled
                ? "No analytics that identifies you: Cloudflare Web Analytics, above, is the only measurement product, and it sets no cookies."
                : "No analytics or measurement product of any kind."}
            </li>
            <li>No advertising, and no data shared with advertisers.</li>
            <li>No selling or renting of personal data, in any circumstances.</li>
            <li>No tracking across other websites.</li>
            <li>
              No marketing email. This site emails you only to deliver a sign-in code; Dodo
              Payments sends receipts if you buy Pro.
            </li>
          </ul>
        </section>

        <section id="processors">
          <h2>Who else handles it</h2>
          <p>
            Running this service means relying on other companies for infrastructure and
            payments. Each sees only what it needs:
          </p>
          <table className="docs-table">
            <thead>
              <tr>
                <th>Service</th>
                <th>What it does</th>
                <th>What it sees</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Supabase</td>
                <td>Accounts and database</td>
                <td>Your email, name and avatar URL, and your stored work</td>
              </tr>
              <tr>
                <td>Cloudflare</td>
                <td>Hosting and the edge cache</td>
                <td>Requests for pages, as any web host does</td>
              </tr>
              <tr>
                <td>Cloudflare Web Analytics{analyticsEnabled ? "" : " (if enabled)"}</td>
                <td>Counts page visits</td>
                <td>
                  The page visited, referrer, browser, operating system, country and load
                  times. Per Cloudflare, no cookies, no fingerprinting and no stored IP
                  address
                </td>
              </tr>
              <tr>
                <td>Cloudflare R2</td>
                <td>Nightly database backups</td>
                <td>
                  Encrypted copies of the database. They cannot be read without a key that
                  Cloudflare does not hold
                </td>
              </tr>
              <tr>
                <td>Sentry (if enabled)</td>
                <td>Error reports from the API</td>
                <td>
                  Technical details of a failure. No request bodies, IP addresses, cookies or
                  email addresses are sent
                </td>
              </tr>
              <tr>
                <td>Render</td>
                <td>The screening API</td>
                <td>Requests, and your email when you are signed in</td>
              </tr>
              <tr>
                <td>Brevo</td>
                <td>Sends sign-in codes</td>
                <td>Your email address, only if you use the email route</td>
              </tr>
              <tr>
                <td>Dodo Payments</td>
                <td>Checkout, billing, tax and receipts</td>
                <td>What you enter at checkout, only if you buy Pro</td>
              </tr>
              <tr>
                <td>GitHub / Google</td>
                <td>Identity providers</td>
                <td>That you signed in here, if you use them</td>
              </tr>
            </tbody>
          </table>
          <p>
            Database records are held in Supabase&apos;s Mumbai (ap-south-1) region. These
            providers keep their own infrastructure logs for security and operations, and
            those will include IP addresses even though this application does not record
            them. That part is governed by their privacy policies, not this one.
          </p>
        </section>

        <section id="retention">
          <h2>How long it is kept</h2>
          <p>
            Your account and the records attached to it are kept until you ask for them to
            be deleted. Sign-in codes expire after an hour. Sessions can be ended at any
            time from the account page, which also offers ending every session everywhere
            if you believe a credential has been seen by someone else.
          </p>
          <p>
            The catalogue and conjunction data itself is not personal data and is retained
            indefinitely; it comes from public two-line element sets.
          </p>
        </section>

        <section id="deletion">
          <h2>Deleting your account</h2>
          <p>
            Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> from the address you signed up
            with and the account will be deleted along with the screening runs, watch-list
            entries and command history attached to it. You can also ask for a copy of
            what is held, or for a correction to it.
          </p>
          <p>
            This is a personal open-source project rather than a company, so expect a
            reply measured in days.
          </p>
        </section>

        <section id="changes">
          <h2>Changes</h2>
          <p>
            If this policy changes, the date at the top changes with it. The history of
            every revision is public in the repository, so you can see exactly what
            changed and when.
          </p>
        </section>

        <footer className="docs-footer">
          <Link href="/">
            Back to the console <span aria-hidden="true">-&gt;</span>
          </Link>
        </footer>
        <SiteFooter />
      </main>
    </div>
  );
}
