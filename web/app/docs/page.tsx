import type { Metadata } from "next";
import Link from "next/link";
import DocsSamples from "@/components/DocsSamples";
import RestartTourButton from "@/components/RestartTourButton";

export const metadata: Metadata = {
  title: "Documentation · Astra / SSA",
  description:
    "Command reference, concepts, and methodology for the Astra space situational awareness console."
};

const SECTIONS = [
  { id: "getting-started", label: "Getting started" },
  { id: "samples", label: "Sample queries" },
  { id: "commands", label: "Command reference" },
  { id: "concepts", label: "Concepts" },
  { id: "live-feed", label: "Real-time feed" },
  { id: "roles", label: "Roles & governance" },
  { id: "methodology", label: "Methodology & limits" },
  { id: "faq", label: "FAQ" }
];

const COMMANDS = [
  {
    signature: "screen <norad> [--window 72h] [--threshold 25km] [--step 60s] [--group <name>] [--cached]",
    role: "analyst",
    async: true,
    summary:
      "Propagate one object against a debris group and record every approach inside the threshold.",
    options: [
      ["--window", "Look-ahead span. Accepts hours (72h) or days (3d). Default 72h, max 168h."],
      ["--threshold", "Miss-distance cut-off in km or m. Default 25km."],
      ["--step", "Propagation time step in seconds or minutes. Default 60s, min 10s."],
      ["--group", "Catalogue group to screen against. Default iridium-33-debris."],
      ["--cached", "Skip the CelesTrak refresh and reuse the catalogue already on disk."]
    ]
  },
  {
    signature: "monitor add <norad>",
    role: "analyst",
    summary: "Add an object to the monitored set so it appears on the globe and in the rail."
  },
  {
    signature: "monitor seed-known",
    role: "analyst",
    summary: "Populate the monitored set with a small, well-known starter catalogue."
  },
  {
    signature: "events list [--tier critical|watch|nominal]",
    role: "viewer",
    summary: "List assessed conjunctions, optionally filtered to a single risk tier."
  },
  {
    signature: "event explain <event-id>",
    role: "viewer",
    summary:
      "Return the full assessment for one event: geometry, probability of collision, model version, and the reason the tier was assigned."
  },
  {
    signature: "orbit refresh <norad>",
    role: "analyst",
    summary:
      "Fetch the current public TLE for one object and version it into the ontology. Prior element sets are retained."
  },
  {
    signature: "case assign <case-id> <assignee>",
    role: "operator",
    summary: "Route an open monitoring case to a named analyst. Written to the audit log."
  },
  {
    signature: 'case close <case-id> --reason "<text>"',
    role: "operator",
    summary:
      "Close a case. A reason is mandatory and the console asks for confirmation before the command is sent."
  }
];

const CONCEPTS = [
  {
    term: "TLE / element set",
    body: "A two-line element set: the compact orbital state published for most catalogued objects. Accuracy degrades with age and after any manoeuvre, which is why element sets are versioned rather than overwritten."
  },
  {
    term: "SGP4",
    body: "The analytic propagator TLEs are designed for. It produces positions in the TEME frame. Every track on the globe and every screening run uses it."
  },
  {
    term: "Conjunction / TCA",
    body: "A close approach between two objects. TCA is the time of closest approach — the moment the miss distance is at its minimum within the screening window."
  },
  {
    term: "Miss distance",
    body: "The separation between two objects at TCA, in kilometres. It is the primary screening filter but on its own it says nothing about uncertainty."
  },
  {
    term: "Probability of collision (Pc)",
    body: "An estimate that folds miss distance together with position uncertainty. Here it is illustrative: the covariance is synthetic and age-weighted, not ingested from an authoritative conjunction data message."
  },
  {
    term: "Risk tier",
    body: "Nominal, watch, or critical. A tier is assigned when either the miss distance or the Pc crosses the configured threshold, and the triggering condition is recorded in the explanation."
  },
  {
    term: "Monitoring case",
    body: "The unit of operator work. A case is opened against an event, assigned, acted on, and closed with a recorded justification."
  },
  {
    term: "Lineage",
    body: "Every derived record points back at the inputs and model versions that produced it, so any number on screen can be traced to the element sets and configuration behind it."
  }
];

const FAQ = [
  {
    q: "Why does my screening job take a minute?",
    a: "It refreshes the catalogue from CelesTrak, propagates every object in the group across the window at the requested step, then refines each candidate around TCA. Pass --cached to skip the network fetch, or shorten --window."
  },
  {
    q: "The globe is empty.",
    a: "Nothing is monitored yet. Run monitor seed-known to load a starter set, or monitor add <norad> for a specific object. Tracks need at least one element set, so a brand-new object may also need orbit refresh."
  },
  {
    q: "My command was rejected.",
    a: "Commands are matched against an allowlist grammar — anything outside it is refused before execution, and the rejection itself is audited. Check the signature in the command reference above. If the grammar matched but you were still refused, your role is below the level the action requires."
  },
  {
    q: "Do I have to refresh to see new events?",
    a: "No. The dashboard holds an open stream to the server and renders conjunctions, alerts, job transitions, and governance actions as they are recorded, including ones raised by other operators."
  },
  {
    q: "Can I use these results operationally?",
    a: "No. The covariance model is synthetic and the catalogue is public TLE data. Treat every number as illustrative of how a screening pipeline behaves, not as a basis for a manoeuvre decision."
  }
];

export default function DocsPage() {
  return (
    <div className="docs-shell">
      <header className="docs-topbar">
        <Link href="/" className="brand">
          <span className="brand-mark">A</span>
          <span>ASTRA / SSA</span>
        </Link>
        <nav>
          <RestartTourButton />
          <Link href="/" className="docs-back">
            OPEN CONSOLE <span aria-hidden="true">-&gt;</span>
          </Link>
        </nav>
      </header>

      <aside className="docs-nav" aria-label="Documentation sections">
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
        <section id="getting-started">
          <p className="eyebrow">DOCUMENTATION</p>
          <h1>
            Operating the
            <br />
            console.
          </h1>
          <p className="docs-lede">
            Astra is a governed space situational awareness console: you screen objects for
            close approaches, keep a watch list, and work the resulting cases through an
            audited command surface. This page is the reference for all of it.
          </p>

          <div className="docs-callout">
            <strong>Educational model.</strong> Outputs are derived from public two-line
            element sets and a synthetic covariance model. They must not be used for
            operational collision-avoidance decisions.
          </div>

          <h2>Three commands to a useful screen</h2>
          <ol className="docs-steps">
            <li>
              <code>monitor seed-known</code>
              <span>
                Loads a starter watch list so the globe, the rail, and the telemetry panel
                have data.
              </span>
            </li>
            <li>
              <code>screen 25544 --window 72h --threshold 25km</code>
              <span>
                Queues a background screening job. Its stages stream into the inspector on
                the right as it runs.
              </span>
            </li>
            <li>
              <code>events list --tier critical</code>
              <span>
                Reads back what the run found, filtered to the tier that would drive an
                alert.
              </span>
            </li>
          </ol>

          <h2>Getting around</h2>
          <ul className="docs-list">
            <li>
              <kbd>Ctrl</kbd>+<kbd>K</kbd> focuses the command bar from anywhere.
            </li>
            <li>
              <kbd>↑</kbd> <kbd>↓</kbd> move through the suggestion list, <kbd>Enter</kbd>{" "}
              accepts, <kbd>Esc</kbd> dismisses it.
            </li>
            <li>Selecting a track on the globe selects that object everywhere else.</li>
            <li>
              The guided tour walks the whole layout in about a minute — <RestartTourButton inline />
            </li>
          </ul>
        </section>

        <section id="samples">
          <h2>Sample queries</h2>
          <p>
            Each of these is accepted by the parser exactly as written. Click one to open
            the console with it loaded, or copy it into the command bar yourself.
          </p>
          <DocsSamples />
        </section>

        <section id="commands">
          <h2>Command reference</h2>
          <p>
            Input is tokenised and matched against a fixed grammar. There is no shell, no
            interpolation, and no fallback path for unmatched input — an unrecognised
            command is rejected and the rejection is audited.
          </p>
          {COMMANDS.map((command) => (
            <article className="docs-command" key={command.signature}>
              <header>
                <code>{command.signature}</code>
                <span className={`docs-role ${command.role}`}>{command.role}</span>
                {command.async && <span className="docs-async">async job</span>}
              </header>
              <p>{command.summary}</p>
              {command.options && (
                <dl className="docs-options">
                  {command.options.map(([flag, text]) => (
                    <div key={flag}>
                      <dt>{flag}</dt>
                      <dd>{text}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </article>
          ))}
        </section>

        <section id="concepts">
          <h2>Concepts</h2>
          <dl className="docs-glossary">
            {CONCEPTS.map((concept) => (
              <div key={concept.term}>
                <dt>{concept.term}</dt>
                <dd>{concept.body}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section id="live-feed">
          <h2>Real-time feed</h2>
          <p>
            The dashboard subscribes to <code>GET /stream/activity</code>, a server-sent
            event stream that merges six sources into one chronological feed:
          </p>
          <ul className="docs-list">
            <li>
              <strong>CDM</strong> — conjunctions as they are written by a screening run,
              carrying their assessed tier.
            </li>
            <li>
              <strong>ALRT</strong> — alerts dispatched by the notification rules, and
              whether they have been acknowledged.
            </li>
            <li>
              <strong>JOB</strong> — every stage transition of a screening job, including
              failures and cancellations.
            </li>
            <li>
              <strong>CMD</strong> — command executions with the acting principal, rejected
              ones included.
            </li>
            <li>
              <strong>WTCH</strong> — additions to and removals from the monitored set.
            </li>
            <li>
              <strong>GOV</strong> — audited governance actions such as case assignment,
              closure, and approvals.
            </li>
          </ul>
          <p>
            The feed is cursor-based. Each item carries an <code>occurred_at</code>{" "}
            timestamp, and the client resumes from the last one it saw, so a dropped
            connection or a sleeping laptop replays what was missed without duplicating
            what was already rendered. The indicator in the feed header reads{" "}
            <em>LIVE</em> while the stream is open, <em>RECONNECTING</em> during backoff,
            and <em>OFFLINE</em> after repeated failures — it keeps retrying either way.
          </p>
          <p>
            For a one-shot read instead of a subscription, <code>GET /activity</code>{" "}
            returns the same items with a cursor. Both endpoints require a bearer token.
          </p>
        </section>

        <section id="roles">
          <h2>Roles &amp; governance</h2>
          <p>
            Every command declares the minimum role it needs. A principal below that level
            is refused before anything executes.
          </p>
          <table className="docs-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Can do</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>viewer</td>
                <td>Read events, explanations, the ontology, and the live feed.</td>
              </tr>
              <tr>
                <td>analyst</td>
                <td>Everything a viewer can, plus screening, monitoring, and orbit refresh.</td>
              </tr>
              <tr>
                <td>operator</td>
                <td>Everything an analyst can, plus casework, decisions, and alerts.</td>
              </tr>
              <tr>
                <td>admin</td>
                <td>Everything an operator can, plus the audit log.</td>
              </tr>
            </tbody>
          </table>
          <p>
            State-changing actions write an audit record holding the actor, the previous
            and new state, the justification, and the data and model versions in play.
            Closing a case additionally requires an explicit reason and a confirmation.
          </p>
        </section>

        <section id="methodology">
          <h2>Methodology &amp; limits</h2>
          <dl className="docs-glossary">
            <div>
              <dt>Orbit source</dt>
              <dd>Public two-line element sets from CelesTrak, versioned on ingest.</dd>
            </div>
            <div>
              <dt>Propagator</dt>
              <dd>SGP4, TEME frame, on a fixed time grid refined around each candidate TCA.</dd>
            </div>
            <div>
              <dt>Covariance</dt>
              <dd>Synthetic, age-weighted, in the RIC frame. Not from a conjunction data message.</dd>
            </div>
            <div>
              <dt>Probability model</dt>
              <dd>An illustrative Foster/Chan-style estimate over that synthetic covariance.</dd>
            </div>
          </dl>
          <div className="docs-callout warn">
            <strong>Known limitations.</strong> No authoritative covariance is ingested. TLE
            accuracy degrades with age and after manoeuvres. Object sizes are assumed rather
            than known. Results are illustrative of pipeline behaviour and must not drive
            operational collision-avoidance decisions.
          </div>
        </section>

        <section id="faq">
          <h2>FAQ</h2>
          <div className="docs-faq">
            {FAQ.map((entry) => (
              <details key={entry.q}>
                <summary>{entry.q}</summary>
                <p>{entry.a}</p>
              </details>
            ))}
          </div>
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
