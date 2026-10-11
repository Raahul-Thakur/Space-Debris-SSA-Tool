"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore
} from "react";
import { api, streamSse } from "@/lib/api";
import { getSupabase, initializeAuth, signOut } from "@/lib/auth";
import {
  getSeenEventsServerSnapshot,
  getSeenEventsSnapshot,
  markEventsSeen,
  parseSeenEvents,
  subscribeToSeenEvents
} from "@/lib/seenEvents";
import { matchSamples } from "@/lib/samples";
import type { SampleQuery } from "@/lib/samples";
import type {
  ActivityItem,
  Job,
  JobEvent,
  MonitoredObject,
  RiskEvent,
  Trajectory
} from "@/lib/types";
import { useActivityFeed } from "@/lib/useActivityFeed";
import ActivityFeed from "@/components/ActivityFeed";
import CommandPalette from "@/components/CommandPalette";
import ProductTour from "@/components/ProductTour";

const OrbitGlobe = dynamic(() => import("@/components/OrbitGlobe"), { ssr: false });

/** Feed kinds that change what the panels should be showing. */
const REFRESHING_KINDS = new Set<ActivityItem["kind"]>([
  "conjunction",
  "monitoring",
  "alert"
]);
/** Collapse bursts of stream activity into one reload. */
const REFRESH_DEBOUNCE_MS = 1_200;
const DEFAULT_COMMAND = "screen 25544 --window 72h --threshold 25km";
/** A command typed before signing in, restored afterwards. */
const PENDING_COMMAND_KEY = "astra.pending-command";
/** Verbs the allowlist grammar starts with. */
const COMMAND_VERBS = ["screen", "monitor", "events", "event", "case", "orbit"];
/** Long enough to be a question rather than a half-typed command. */
const MIN_PROSE_LENGTH = 12;
const INTERPRET_DEBOUNCE_MS = 450;

/**
 * Whether the text reads as a question rather than as a command.
 *
 * Only a hint for when to offer a translation, never a gate on anything: the
 * allowlist parser decides what is actually runnable, both here and on the
 * server.
 */
function looksLikeProse(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.length < MIN_PROSE_LENGTH || !trimmed.includes(" ")) return false;
  const verb = trimmed.split(/\s+/)[0].toLowerCase();
  return !COMMAND_VERBS.includes(verb);
}

export default function CommandCenter() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Deep links from the docs page: `?command=<text>` preloads the console and
  // `?tour=1` opens the guided tour. Captured once so they seed state rather
  // than overwriting whatever the operator has typed since.
  const [deepLink] = useState(() => ({
    command: searchParams.get("command"),
    tour: searchParams.get("tour") === "1"
  }));
  const [authReady, setAuthReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [command, setCommand] = useState(deepLink.command ?? DEFAULT_COMMAND);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [jobEvents, setJobEvents] = useState<JobEvent[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [monitored, setMonitored] = useState<MonitoredObject[]>([]);
  const [trajectories, setTrajectories] = useState<Trajectory[]>([]);
  const [selectedNoradId, setSelectedNoradId] = useState<string | null>(null);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(
    deepLink.command ? "Command loaded from the docs. Review it, then press Execute." : ""
  );
  const [busy, setBusy] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(Boolean(deepLink.command));
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  // Incremented to ask ProductTour for a run; never reset.
  const [tourRequest, setTourRequest] = useState(deepLink.tour ? 1 : 0);
  const [now, setNow] = useState(() => Date.now());
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  /** Reinstate a command typed before the visitor was sent to sign in. */
  const restorePendingCommand = useCallback(() => {
    let pending: string | null = null;
    try {
      pending = window.sessionStorage.getItem(PENDING_COMMAND_KEY);
      if (pending) window.sessionStorage.removeItem(PENDING_COMMAND_KEY);
    } catch {
      return;
    }
    if (!pending) return;
    setCommand(pending);
    setNotice("Signed in. Your command is ready — press Execute to run it.");
    setPaletteOpen(true);
  }, []);

  const refresh = useCallback(async () => {
    const [nextJobs, nextMonitored, listed] = await Promise.all([
      api<Job[]>("/screening-jobs").catch(() => []),
      api<MonitoredObject[]>("/monitoring").catch(() => []),
      // A plain read, not `events list` through the command endpoint: polling
      // must not fill the audit log and the activity feed with its own traffic.
      api<{ events: RiskEvent[]; generated_at: string | null }>(
        "/events/assessed"
      ).catch(() => ({ events: [], generated_at: null }))
    ]);
    setJobs(nextJobs);
    setMonitored(nextMonitored);
    setSelectedNoradId((current) =>
      current && nextMonitored.some((object) => object.norad_id === current)
        ? current
        : nextMonitored[0]?.norad_id ?? null
    );
    setRiskEvents(listed.events ?? []);
    setGeneratedAt(listed.generated_at ?? null);
    const ids = nextMonitored.length
      ? nextMonitored.map((object) => object.norad_id)
      : ["25544"];
    const paths = ids.map((id) =>
      api<Trajectory>(`/objects/${id}/trajectory?window_hours=3&step_sec=180`).catch(
        () => null
      )
    );
    setTrajectories((await Promise.all(paths)).filter(Boolean) as Trajectory[]);
  }, []);

  // Stream activity reloads the panels, but only once per burst.
  const onActivity = useCallback(
    (items: ActivityItem[]) => {
      if (!items.some((item) => REFRESHING_KINDS.has(item.kind))) return;
      clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => void refresh(), REFRESH_DEBOUNCE_MS);
    },
    [refresh]
  );

  const feed = useActivityFeed(authenticated, onActivity);

  useEffect(() => () => clearTimeout(refreshTimer.current), []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);

  // Drop the consumed parameters so a reload does not replay the deep link.
  // The native history API is the shallow update Next supports here: a
  // `router.replace` would re-run the route and tear down the running tour.
  useEffect(() => {
    if (deepLink.command || deepLink.tour) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [deepLink]);

  useEffect(() => {
    let active = true;
    initializeAuth()
      .then(async (state) => {
        if (!active) return;
        const signedIn = state.development || Boolean(state.session);
        setAuthenticated(signedIn);
        setAuthReady(true);
        if (signedIn) restorePendingCommand();
        // Loaded either way. The catalogue, the orbital picture and the
        // assessed conjunctions are public; an account is what lets someone
        // act on them, so a visitor without one still gets the real thing.
        await refresh();
      })
      .catch(async (caught) => {
        if (!active) return;
        setAuthReady(true);
        // A failure to establish a session is not a failure to show the
        // public picture, so it is reported without emptying the page.
        setNotice(
          caught instanceof Error
            ? `Viewing as a guest: ${caught.message}`
            : "Viewing as a guest."
        );
        await refresh();
      });
    const client = getSupabase();
    const subscription = client?.auth.onAuthStateChange((_event, session) => {
      import("@/lib/api").then(({ setAccessToken }) =>
        setAccessToken(session?.access_token ?? null)
      );
      setAuthenticated(Boolean(session));
      if (session) {
        restorePendingCommand();
        void refresh();
      }
    }).data.subscription;
    return () => {
      active = false;
      subscription?.unsubscribe();
    };
  }, [refresh, restorePendingCommand]);

  // Read through an external store: the server has no localStorage, so this
  // needs a defined server snapshot rather than state seeded in an effect.
  const seenRaw = useSyncExternalStore(
    subscribeToSeenEvents,
    getSeenEventsSnapshot,
    getSeenEventsServerSnapshot
  );
  const seenEventIds = useMemo(() => parseSeenEvents(seenRaw), [seenRaw]);

  const unseenEvents = useMemo(
    () => riskEvents.filter((item) => !seenEventIds.has(item.id)).length,
    [riskEvents, seenEventIds]
  );

  const dismissUnseen = useCallback(
    () => markEventsSeen(riskEvents.map((item) => item.id)),
    [riskEvents]
  );

  const freshness = useMemo(() => {
    if (!generatedAt) return null;
    const ageMs = now - new Date(generatedAt).getTime();
    if (!Number.isFinite(ageMs) || ageMs < 0) return null;
    const hours = ageMs / 3_600_000;
    if (hours < 1) return `${Math.max(1, Math.round(ageMs / 60_000))}M AGO`;
    if (hours < 48) return `${Math.round(hours)}H AGO`;
    return `${Math.round(hours / 24)}D AGO`;
  }, [generatedAt, now]);

  // The explanation endpoint is open to anonymous readers, which is the point:
  // the reading of an event is the most useful thing the platform gives away.
  const [interpretation, setInterpretation] = useState<{
    command: string | null;
    rationale: string;
  } | null>(null);
  // Keyed by event so "still loading" is derived from a mismatch rather than
  // written by clearing state at the top of an effect.
  const [narrative, setNarrative] = useState<{
    eventId: string;
    lines: string[];
  } | null>(null);
  const [narrativeOpen, setNarrativeOpen] = useState(false);
  const selectedEventId = riskEvents[0]?.id ?? null;

  useEffect(() => {
    if (!narrativeOpen || !selectedEventId) return;
    if (narrative?.eventId === selectedEventId) return;
    const eventId = selectedEventId;
    let active = true;
    api<{ narrative?: string[] }>(`/events/${eventId}/explanation`)
      .then((body) => {
        if (active) setNarrative({ eventId, lines: body.narrative ?? [] });
      })
      .catch(() => {
        if (active) setNarrative({ eventId, lines: [] });
      });
    return () => {
      active = false;
    };
  }, [narrativeOpen, selectedEventId, narrative?.eventId]);

  // Translate plain English into a proposal while the operator types. The
  // server runs every proposal through the real allowlist parser before
  // returning it, so nothing suggested here can name an action the platform
  // does not have.
  useEffect(() => {
    if (!authenticated || !paletteOpen || !looksLikeProse(command)) {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api<{ command: string | null; rationale: string }>("/commands/interpret", {
        method: "POST",
        body: JSON.stringify({ command }),
        signal: controller.signal
      })
        .then((body) => setInterpretation(body))
        .catch(() => {
          // A failed translation is not an error worth showing: the sample
          // list and the raw input both still work.
        });
    }, INTERPRET_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [authenticated, paletteOpen, command]);

  const activeJobId = activeJob?.id;
  useEffect(() => {
    if (!activeJobId) return;
    const controller = new AbortController();
    streamSse<JobEvent>(
      `/screening-jobs/${activeJobId}/events`,
      (update) => {
        setJobEvents((current) =>
          current.some((item) => item.sequence === update.sequence)
            ? current
            : [...current, update]
        );
        setActiveJob((current) =>
          current
            ? {
                ...current,
                stage: update.stage,
                progress: update.progress,
                message: update.message,
                status: ["complete", "failed", "cancelled"].includes(update.stage)
                  ? update.stage === "complete"
                    ? "succeeded"
                    : update.stage
                  : "running"
              }
            : current
        );
        if (["complete", "failed", "cancelled"].includes(update.stage)) {
          controller.abort();
          api<Job>(`/screening-jobs/${activeJobId}`).then(setActiveJob);
          refresh();
        }
      },
      controller.signal
    ).catch((caught) => {
      if (!controller.signal.aborted)
        setError(caught instanceof Error ? caught.message : "Progress stream failed");
    });
    return () => controller.abort();
  }, [activeJobId, refresh]);

  const openPalette = useCallback((next?: string) => {
    if (next !== undefined) setCommand(next);
    setPaletteOpen(true);
    setActiveSuggestion(-1);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  // Ctrl/Cmd+K focuses the console from anywhere in the page.
  useEffect(() => {
    function onKey(event: globalThis.KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openPalette();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openPalette]);

  const matches = useMemo(() => matchSamples(command), [command]);

  function pickSample(sample: SampleQuery) {
    setCommand(sample.command);
    setActiveSuggestion(-1);
    setNotice(sample.placeholder ? "Replace the placeholder id before running this." : "");
    inputRef.current?.focus();
  }

  function onCommandKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setPaletteOpen(false);
      setActiveSuggestion(-1);
      return;
    }
    if (!paletteOpen || !matches.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveSuggestion((index) => (index + 1) % matches.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveSuggestion((index) => (index <= 0 ? matches.length - 1 : index - 1));
    } else if (event.key === "Enter" && activeSuggestion >= 0) {
      event.preventDefault();
      pickSample(matches[activeSuggestion]);
    }
  }

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!command.trim()) return;
    if (!authenticated) {
      // The prompt arrives where the visitor already wants something, with
      // the command they typed preserved, rather than in front of the page.
      setError("");
      setNotice("Running commands needs an account. Your command is kept.");
      try {
        window.sessionStorage.setItem(PENDING_COMMAND_KEY, command);
      } catch {
        // Not worth blocking sign-in over.
      }
      router.push("/signin");
      return;
    }
    const closing = command.trim().startsWith("case close");
    const confirmed = closing
      ? window.confirm("Close this monitoring case? This action is recorded in the audit log.")
      : false;
    if (closing && !confirmed) return;
    setBusy(true);
    setError("");
    setNotice("");
    setJobEvents([]);
    try {
      const response = await api<{
        status: string;
        result: Record<string, unknown>;
        job: Job | null;
      }>("/commands/execute", {
        method: "POST",
        body: JSON.stringify({ command, confirmed })
      });
      if (response.job) setActiveJob(response.job);
      await refresh();
      setPaletteOpen(false);
      setActiveSuggestion(-1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Command failed");
    } finally {
      setBusy(false);
    }
  }

  async function cancelActiveJob() {
    if (!activeJob) return;
    try {
      const cancelled = await api<Job>(`/screening-jobs/${activeJob.id}/cancel`, {
        method: "POST"
      });
      setActiveJob(cancelled);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Cancellation failed");
    }
  }

  function focusActivity(item: ActivityItem) {
    if (item.norad_id && monitored.some((object) => object.norad_id === item.norad_id)) {
      setSelectedNoradId(item.norad_id);
    }
    if (item.kind === "conjunction") openPalette(`event explain ${item.entity_id}`);
    if (item.kind === "job") {
      const job = jobs.find((candidate) => candidate.id === item.entity_id);
      if (job) {
        setActiveJob(job);
        setJobEvents([]);
      }
    }
  }

  const latestProgress = activeJob?.progress ?? 0;
  const selectedEvent = riskEvents[0];
  const selectedObject =
    monitored.find((object) => object.norad_id === selectedNoradId) ?? null;
  const selectedTrajectory =
    trajectories.find((trajectory) => trajectory.norad_id === selectedNoradId) ?? null;
  const selectedTelemetry = useMemo(() => {
    const points = selectedTrajectory?.points.filter((point) => point.valid) ?? [];
    const point = points[0];
    if (!point) return null;
    const radius = Math.hypot(point.x_km, point.y_km, point.z_km);
    const next = points[1];
    let speed: number | null = null;
    if (next) {
      const seconds =
        (new Date(next.timestamp).getTime() - new Date(point.timestamp).getTime()) / 1000;
      if (seconds > 0) {
        speed =
          Math.hypot(
            next.x_km - point.x_km,
            next.y_km - point.y_km,
            next.z_km - point.z_km
          ) / seconds;
      }
    }
    const altitude = radius - 6378.137;
    const orbitClass =
      altitude < 2000 ? "LEO" : altitude < 30000 ? "MEO" : altitude < 45000 ? "GEO" : "HEO";
    return { point, altitude, speed, orbitClass, trackPoints: points.length };
  }, [selectedTrajectory]);
  const statusCounts = useMemo(
    () => ({
      active: monitored.length,
      watch: riskEvents.filter((item) => item.tier === "watch").length,
      critical: riskEvents.filter((item) => item.tier === "critical").length
    }),
    [monitored, riskEvents]
  );
  const utc = useMemo(() => new Date(now).toISOString().slice(11, 19), [now]);

  if (!authReady) return <main className="auth-loading">LOADING ORBITAL PICTURE</main>;

  return (
    <main className="shell">
      <ProductTour
        request={tourRequest}
        onPrepare={() => setPaletteOpen(true)}
        onFinish={() => setPaletteOpen(false)}
      />

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">A</span>
          <span>ASTRA / SSA</span>
        </div>
        <div className="system-state">
          <i /> CATALOG LINKED <span>·</span> TEME / SGP4 <span>·</span>
          <em className={`stream-state ${feed.status}`}>
            {feed.status === "idle"
              ? "PUBLIC VIEW"
              : `STREAM ${feed.status.toUpperCase()}`}
          </em>
        </div>
        <div className="topbar-actions">
          {freshness && (
            <span className="freshness" title={`Last screening completed ${generatedAt}`}>
              SCREENED {freshness}
            </span>
          )}
          <span className="utc-clock">{utc} UTC</span>
          <button
            type="button"
            className="topbar-link"
            onClick={() => setTourRequest((count) => count + 1)}
          >
            TOUR
          </button>
          <Link className="topbar-link" href="/docs" data-tour="docs-link">
            DOCS
          </Link>
          {authenticated ? (
            <button
              type="button"
              className="topbar-link"
              onClick={() => {
                // Ending a session must not depend on the network call
                // succeeding: the local token is dropped either way.
                void signOut().finally(() => {
                  setAuthenticated(false);
                  setNotice("Signed out. The public picture stays available.");
                  void refresh();
                });
              }}
            >
              SIGN OUT
            </button>
          ) : (
            <Link className="topbar-link accent" href="/signin">
              SIGN IN →
            </Link>
          )}
        </div>
      </header>

      <aside className="rail">
        <section className="rail-intro">
          <p className="eyebrow">OPERATIONAL PICTURE</p>
          <h1>
            Orbital
            <br />
            command.
          </h1>
          <p>Governed screening, monitoring, and case actions from one typed console.</p>
        </section>

        <section className="metrics" data-tour="metrics">
          <div>
            <span>MONITORED</span>
            <strong>{String(statusCounts.active).padStart(2, "0")}</strong>
          </div>
          <div>
            <span>WATCH</span>
            <strong>{String(statusCounts.watch).padStart(2, "0")}</strong>
          </div>
          <div className={statusCounts.critical ? "danger" : ""}>
            <span>CRITICAL</span>
            <strong>{String(statusCounts.critical).padStart(2, "0")}</strong>
          </div>
        </section>

        <section className="object-list" data-tour="object-list">
          <div className="section-head">
            <span>MONITORED ELEMENTS</span>
            <span className="object-count">
              {monitored.length} / {monitored.length}
            </span>
            <button
              onClick={() => openPalette("monitor add ")}
              aria-label="Add a monitored object"
            >
              +
            </button>
          </div>
          <div className="object-scroll">
            {monitored.length ? (
              monitored.map((object, index) => (
                <button
                  className={`object-row ${object.norad_id === selectedNoradId ? "selected" : ""}`}
                  key={object.id}
                  onClick={() => setSelectedNoradId(object.norad_id)}
                  aria-pressed={object.norad_id === selectedNoradId}
                >
                  <span className="index">{String(index + 1).padStart(2, "0")}</span>
                  <span>
                    <strong>{object.name}</strong>
                    <small>NORAD {object.norad_id}</small>
                  </span>
                  <i className="live-dot" />
                </button>
              ))
            ) : (
              <p className="empty">
                {authenticated ? (
                  <>
                    No monitored elements. Run <code>monitor seed-known</code> to load a
                    starter set, or <code>monitor add 25544</code> for one object.
                  </>
                ) : (
                  <>
                    The public catalogue is empty right now.{" "}
                    <Link href="/signin">Sign in</Link> to build a watch list of your
                    own.
                  </>
                )}
              </p>
            )}
          </div>
        </section>

        <section className="history">
          <div className="section-head">
            <span>RECENT RUNS</span>
            <span>{jobs.length}</span>
          </div>
          {jobs.slice(0, 3).map((job) => (
            <button
              key={job.id}
              onClick={() => {
                setActiveJob(job);
                setJobEvents([]);
              }}
            >
              <span className={`job-status ${job.status}`} />
              <span>
                <strong>{job.command}</strong>
                <small>{job.message}</small>
              </span>
            </button>
          ))}
        </section>
      </aside>

      <section className="orbital-stage" data-tour="globe">
        <OrbitGlobe
          trajectories={trajectories}
          selectedNoradId={selectedNoradId}
          onSelect={setSelectedNoradId}
        />
        <div className="stage-title">
          <p>ORBITAL PICTURE / +3H</p>
          <span>{trajectories.length} TRACKS / TEME FRAME</span>
        </div>
        {unseenEvents > 0 && (
          <button type="button" className="unseen-banner" onClick={dismissUnseen}>
            <strong>{unseenEvents}</strong>
            <span>
              new {unseenEvents === 1 ? "conjunction" : "conjunctions"} since your
              last visit
            </span>
            <em>MARK SEEN</em>
          </button>
        )}
        <div className="reticle" aria-hidden="true" />
        <div className="legend">
          <span>
            <i className="primary" /> PRIMARY
          </span>
          <span>
            <i /> MONITORED
          </span>
        </div>
        <ActivityFeed
          items={feed.items}
          status={feed.status}
          now={now}
          onSelect={focusActivity}
        />
      </section>

      <aside className="inspector" data-tour="inspector">
        <div className="section-head">
          <span>SELECTED ELEMENT</span>
          <span>LIVE</span>
        </div>
        {selectedObject ? (
          <section className="object-card" key={selectedObject.norad_id}>
            <div className="object-card-head">
              <div>
                <p>TRACK {selectedObject.norad_id}</p>
                <h2>{selectedObject.name}</h2>
              </div>
              <span className="tracking-state">
                <i /> TRACKING
              </span>
            </div>
            {selectedTelemetry ? (
              <>
                <div className="telemetry-primary">
                  <div>
                    <span>ALTITUDE</span>
                    <strong>
                      {selectedTelemetry.altitude.toFixed(0)}
                      <small> km</small>
                    </strong>
                  </div>
                  <div>
                    <span>VELOCITY / EST.</span>
                    <strong>
                      {selectedTelemetry.speed?.toFixed(2) ?? "--"}
                      <small> km/s</small>
                    </strong>
                  </div>
                </div>
                <div className="telemetry-grid">
                  <div>
                    <span>ORBIT</span>
                    <strong>{selectedTelemetry.orbitClass}</strong>
                  </div>
                  <div>
                    <span>FRAME</span>
                    <strong>{selectedTrajectory?.frame}</strong>
                  </div>
                  <div>
                    <span>X / KM</span>
                    <strong>{selectedTelemetry.point.x_km.toFixed(1)}</strong>
                  </div>
                  <div>
                    <span>Y / KM</span>
                    <strong>{selectedTelemetry.point.y_km.toFixed(1)}</strong>
                  </div>
                  <div>
                    <span>Z / KM</span>
                    <strong>{selectedTelemetry.point.z_km.toFixed(1)}</strong>
                  </div>
                  <div>
                    <span>SAMPLES</span>
                    <strong>{selectedTelemetry.trackPoints}</strong>
                  </div>
                </div>
                <p className="telemetry-time">
                  PROPAGATED {new Date(selectedTelemetry.point.timestamp).toISOString()}
                </p>
                <button
                  className="screen-object"
                  onClick={() =>
                    openPalette(
                      `screen ${selectedObject.norad_id} --window 72h --threshold 25km`
                    )
                  }
                >
                  SCREEN THIS OBJECT <span>-&gt;</span>
                </button>
              </>
            ) : (
              <p className="empty">Loading propagated telemetry...</p>
            )}
          </section>
        ) : (
          <p className="empty">Select a monitored element.</p>
        )}

        <div className="section-head event-heading">
          <span>EVENT INSPECTOR</span>
          <span>LIVE</span>
        </div>
        {selectedEvent ? (
          <div className="event-detail">
            <p className={`tier ${selectedEvent.tier}`}>{selectedEvent.tier}</p>
            <h2>
              {selectedEvent.miss_distance_km.toFixed(3)} <small>km miss</small>
            </h2>
            <dl>
              <div>
                <dt>TCA</dt>
                <dd>{new Date(selectedEvent.tca).toISOString().slice(11, 19)} UTC</dd>
              </div>
              <div>
                <dt>Pc</dt>
                <dd>{selectedEvent.probability_of_collision?.toExponential(2) ?? "—"}</dd>
              </div>
              <div>
                <dt>Event</dt>
                <dd>{selectedEvent.id.slice(0, 8)}</dd>
              </div>
            </dl>
            <button
              className="explain-toggle"
              aria-expanded={narrativeOpen}
              onClick={() => setNarrativeOpen((open) => !open)}
            >
              {narrativeOpen ? "HIDE READING" : "WHAT DOES THIS MEAN?"}
            </button>
            {narrativeOpen && (
              <div className="narrative">
                {narrative?.eventId !== selectedEvent.id ? (
                  <p className="narrative-loading">Reading the geometry…</p>
                ) : narrative.lines.length ? (
                  <>
                    {narrative.lines.map((line) => (
                      <p key={line}>{line}</p>
                    ))}
                    <p className="narrative-source">
                      Derived from the numbers above, not written about them.
                    </p>
                  </>
                ) : (
                  <p className="narrative-loading">
                    No reading available for this event.
                  </p>
                )}
              </div>
            )}
          </div>
        ) : (
          <p className="empty">
            {authenticated ? (
              <>
                No assessed conjunctions yet. Run <code>screen 25544</code> to produce
                some.
              </>
            ) : (
              <>
                No assessed conjunctions in the public picture yet.{" "}
                <Link href="/signin">Sign in</Link> to screen an object yourself.
              </>
            )}
          </p>
        )}

        <div className="job-panel">
          <div className="section-head">
            <span>ACTIVE PROCESS</span>
            <span>{activeJob?.status ?? "IDLE"}</span>
          </div>
          {activeJob ? (
            <>
              <div className="progress">
                <i style={{ width: `${latestProgress * 100}%` }} />
              </div>
              <p className="active-command">&gt; {activeJob.command}</p>
              {["queued", "running"].includes(activeJob.status) && (
                <button className="cancel-job" type="button" onClick={cancelActiveJob}>
                  REQUEST CANCELLATION
                </button>
              )}
              <ol>
                {jobEvents.map((item) => (
                  <li key={item.sequence} className={item.stage === "failed" ? "failed" : ""}>
                    <i /> <span>{item.message}</span>
                    <small>{Math.round(item.progress * 100)}%</small>
                  </li>
                ))}
              </ol>
            </>
          ) : (
            <p className="empty">Command worker ready.</p>
          )}
        </div>
      </aside>

      <form
        className={`command-bar ${paletteOpen ? "expanded" : ""}`}
        onSubmit={execute}
        data-tour="command-bar"
      >
        {paletteOpen && (
          <CommandPalette
            matches={matches}
            activeIndex={activeSuggestion}
            onPick={pickSample}
            onHover={setActiveSuggestion}
            interpretation={
              looksLikeProse(command) ? interpretation : null
            }
            onAcceptInterpretation={(proposed) => {
              setCommand(proposed);
              setInterpretation(null);
              setActiveSuggestion(-1);
              inputRef.current?.focus();
            }}
            canInterpret={authenticated}
          />
        )}
        <div className="command-input">
          <span className="prompt">&gt;</span>
          <input
            ref={inputRef}
            value={command}
            onChange={(event) => {
              setCommand(event.target.value);
              setActiveSuggestion(-1);
            }}
            onFocus={() => setPaletteOpen(true)}
            onKeyDown={onCommandKeyDown}
            aria-label="Operator command"
            spellCheck={false}
          />
          <span className="safe">ALLOWLISTED</span>
          <button disabled={busy} type="submit">
            {busy ? "QUEUING…" : "EXECUTE ↵"}
          </button>
        </div>
        {error && <p className="command-error">{error}</p>}
        {!error && notice && <p className="command-notice">{notice}</p>}
      </form>
    </main>
  );
}
