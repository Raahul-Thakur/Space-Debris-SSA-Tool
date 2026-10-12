import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy · Astra / SSA",
  description:
    "What the Astra space situational awareness console collects, who processes it, and how to have it deleted."
};

/**
 * Required before Google will publish the OAuth consent screen, but written to
 * be true rather than to satisfy a form. Every claim here is checkable against
 * the source: there is no analytics package in the frontend, the request logger
 * records no address, and the only personal field the database holds is the
 * email the identity provider returned.
 */
const UPDATED = "12 October 2026";
const CONTACT = "raahul.thakurr01@gmail.com";

const SECTIONS = [
  { id: "summary", label: "The short version" },
  { id: "reading", label: "Reading without an account" },
  { id: "account", label: "If you sign in" },
  { id: "browser", label: "What is stored in your browser" },
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
            personal data is collected at all. There is no analytics, no advertising and
            no tracking of any kind, on any page.
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
            user agent.
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
            No tracking cookies are set, by this site or by anyone else, and there are no
            third-party scripts on any page.
          </p>
        </section>

        <section id="not">
          <h2>What this site does not do</h2>
          <ul className="docs-list">
            <li>No analytics or measurement product of any kind.</li>
            <li>No advertising, and no data shared with advertisers.</li>
            <li>No selling or renting of personal data, in any circumstances.</li>
            <li>No tracking across other websites.</li>
            <li>No marketing email. Email is only ever sent to deliver a sign-in code.</li>
          </ul>
        </section>

        <section id="processors">
          <h2>Who else handles it</h2>
          <p>
            Running this service free of charge means relying on other companies for
            infrastructure. Each sees only what it needs:
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
                <td>Vercel</td>
                <td>Hosting and the edge cache</td>
                <td>Requests for pages, as any web host does</td>
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
            Email <a href={`mailto:${CONTACT}`}>{CONTACT}</a> from the address you signed up
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
          <p>
            Educational screening platform. Outputs are illustrative and must not be used
            for operational maneuver decisions.
          </p>
        </footer>
      </main>
    </div>
  );
}
