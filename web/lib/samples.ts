/**
 * Curated sample commands shown in the palette and the docs page.
 *
 * Every entry is a command the allowlist parser in `sdebris.commands.parser`
 * accepts verbatim, so a visitor can run one without editing it first. Entries
 * whose `placeholder` is set need an id substituted and are therefore offered
 * as copyable reference rather than one-click runnable.
 */

export type SampleCategory =
  | "Start here"
  | "Screening"
  | "Monitoring"
  | "Investigation"
  | "Casework";

export type SampleQuery = {
  command: string;
  label: string;
  description: string;
  category: SampleCategory;
  role: "viewer" | "analyst" | "operator";
  /** True when the command contains an id the operator has to fill in. */
  placeholder?: boolean;
  /** Roughly how long the command takes, for expectation setting. */
  duration?: string;
};

export const SAMPLE_QUERIES: SampleQuery[] = [
  {
    command: "monitor seed-known",
    label: "Seed the watch list",
    description:
      "Loads a small set of well-known objects (ISS, Hubble, debris fragments) so the globe and telemetry panels have something to show.",
    category: "Start here",
    role: "analyst",
    duration: "~5s"
  },
  {
    command: "events list",
    label: "List assessed conjunctions",
    description:
      "Returns every conjunction currently held in the ontology with its risk tier and miss distance.",
    category: "Start here",
    role: "viewer",
    duration: "instant"
  },
  {
    command: "screen 25544 --window 72h --threshold 25km",
    label: "Screen the ISS for 72 hours",
    description:
      "Propagates NORAD 25544 against the debris catalogue and records any approach closer than 25 km. Runs as a background job with live progress.",
    category: "Screening",
    role: "analyst",
    duration: "30s–2min"
  },
  {
    command: "screen 20580 --window 24h --threshold 10km --step 30s",
    label: "Tight screen on Hubble",
    description:
      "A shorter window with a finer 30-second time grid and a 10 km miss threshold — fewer events, higher time resolution near TCA.",
    category: "Screening",
    role: "analyst",
    duration: "30s–2min"
  },
  {
    command: "screen 25544 --window 72h --threshold 25km --cached",
    label: "Re-screen without refetching",
    description:
      "Same screening run against the catalogue already on disk. Use it when you want a repeatable result or the network is unavailable.",
    category: "Screening",
    role: "analyst",
    duration: "10–40s"
  },
  {
    command: "monitor add 20580",
    label: "Add Hubble to the watch list",
    description:
      "Adds NORAD 20580 to the monitored set. Monitored objects get a propagated track on the globe and appear in the left rail.",
    category: "Monitoring",
    role: "analyst",
    duration: "~2s"
  },
  {
    command: "orbit refresh 25544",
    label: "Refresh an element set",
    description:
      "Pulls the latest public TLE for one object from CelesTrak and versions it into the ontology. Older element sets are retained for lineage.",
    category: "Monitoring",
    role: "analyst",
    duration: "~3s"
  },
  {
    command: "events list --tier critical",
    label: "Filter to critical events only",
    description:
      "Narrows the event list to the critical tier — the events that would drive an alert in a real operations centre.",
    category: "Investigation",
    role: "viewer",
    duration: "instant"
  },
  {
    command: "events list --tier watch",
    label: "Filter to the watch tier",
    description:
      "Events that crossed the watch thresholds but not the critical ones. Useful for seeing how tier boundaries behave.",
    category: "Investigation",
    role: "viewer",
    duration: "instant"
  },
  {
    command: "event explain <event-id>",
    label: "Explain a single event",
    description:
      "Returns the miss distance, relative speed, probability of collision, the model version that produced it, and the reason the tier was assigned.",
    category: "Investigation",
    role: "viewer",
    placeholder: true,
    duration: "instant"
  },
  {
    command: "case assign <case-id> analyst-1",
    label: "Assign a monitoring case",
    description:
      "Routes an open case to a named analyst. The assignment is written to the audit log with the acting principal.",
    category: "Casework",
    role: "operator",
    placeholder: true,
    duration: "instant"
  },
  {
    command: 'case close <case-id> --reason "Risk resolved"',
    label: "Close a case with a reason",
    description:
      "Closing requires an explicit reason and a confirmation step. Both the reason and the confirmation are recorded.",
    category: "Casework",
    role: "operator",
    placeholder: true,
    duration: "instant"
  }
];

export const SAMPLE_CATEGORIES: SampleCategory[] = [
  "Start here",
  "Screening",
  "Monitoring",
  "Investigation",
  "Casework"
];

/** Commands safe to run with a single click — no id substitution needed. */
export const RUNNABLE_SAMPLES = SAMPLE_QUERIES.filter((sample) => !sample.placeholder);

/** Rank samples by how well they match what the operator has typed so far. */
export function matchSamples(query: string, limit = 6): SampleQuery[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return SAMPLE_QUERIES.slice(0, limit);
  const scored = SAMPLE_QUERIES.map((sample) => {
    const command = sample.command.toLowerCase();
    if (command.startsWith(needle)) return { sample, score: 0 };
    if (command.includes(needle)) return { sample, score: 1 };
    if (sample.label.toLowerCase().includes(needle)) return { sample, score: 2 };
    if (sample.description.toLowerCase().includes(needle)) return { sample, score: 3 };
    return { sample, score: Number.POSITIVE_INFINITY };
  }).filter((entry) => Number.isFinite(entry.score));
  scored.sort((a, b) => a.score - b.score);
  return scored.slice(0, limit).map((entry) => entry.sample);
}
