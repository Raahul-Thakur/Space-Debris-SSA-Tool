"use client";

import dynamic from "next/dynamic";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, streamSse } from "@/lib/api";
import { getSupabase, initializeAuth } from "@/lib/auth";
import type { Job, JobEvent, MonitoredObject, RiskEvent, Trajectory } from "@/lib/types";
import SignIn from "@/components/SignIn";

const OrbitGlobe = dynamic(() => import("@/components/OrbitGlobe"), { ssr: false });
const EXAMPLES = [
  "screen 25544 --window 72h --threshold 25km",
  "monitor add 20580",
  "monitor seed-known",
  "events list --tier critical",
  "orbit refresh 25544"
];

export default function CommandCenter() {
  const [authReady, setAuthReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [command, setCommand] = useState(EXAMPLES[0]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [jobEvents, setJobEvents] = useState<JobEvent[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [monitored, setMonitored] = useState<MonitoredObject[]>([]);
  const [trajectories, setTrajectories] = useState<Trajectory[]>([]);
  const [selectedNoradId, setSelectedNoradId] = useState<string | null>(null);
  const [riskEvents, setRiskEvents] = useState<RiskEvent[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const refresh = useCallback(async () => {
    const [nextJobs, nextMonitored, listed] = await Promise.all([
      api<Job[]>("/screening-jobs").catch(() => []),
      api<MonitoredObject[]>("/monitoring").catch(() => []),
      api<{ events: RiskEvent[] }>("/commands/execute", {
        method: "POST",
        body: JSON.stringify({ command: "events list" })
      }).catch(() => ({ events: [] }))
    ]);
    setJobs(nextJobs);
    setMonitored(nextMonitored);
    setSelectedNoradId((current) =>
      current && nextMonitored.some((object) => object.norad_id === current)
        ? current
        : nextMonitored[0]?.norad_id ?? null
    );
    setRiskEvents(listed.events ?? []);
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

  useEffect(() => {
    let active = true;
    initializeAuth().then(async (state) => {
      if (!active) return;
      const signedIn = state.development || Boolean(state.session);
      setAuthenticated(signedIn);
      setAuthReady(true);
      if (signedIn) await refresh();
    }).catch((caught) => {
      if (!active) return;
      setError(caught instanceof Error ? caught.message : "Authentication failed");
      setAuthReady(true);
    });
    const client = getSupabase();
    const subscription = client?.auth.onAuthStateChange((_event, session) => {
      import("@/lib/api").then(({ setAccessToken }) =>
        setAccessToken(session?.access_token ?? null)
      );
      setAuthenticated(Boolean(session));
      if (session) void refresh();
    }).data.subscription;
    return () => {
      active = false;
      subscription?.unsubscribe();
    };
  }, [refresh]);

  const activeJobId = activeJob?.id;
  useEffect(() => {
    if (!activeJobId) return;
    const controller = new AbortController();
    streamSse<JobEvent>(`/screening-jobs/${activeJobId}/events`, (update) => {
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
                ? update.stage === "complete" ? "succeeded" : update.stage
                : "running"
            }
          : current
      );
      if (["complete", "failed", "cancelled"].includes(update.stage)) {
        controller.abort();
        api<Job>(`/screening-jobs/${activeJobId}`).then(setActiveJob);
        refresh();
      }
    }, controller.signal).catch((caught) => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Progress stream failed");
    });
    return () => controller.abort();
  }, [activeJobId, refresh]);

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!command.trim()) return;
    const confirmed = command.trim().startsWith("case close")
      ? window.confirm("Close this monitoring case? This action is recorded in the audit log.")
      : false;
    if (command.trim().startsWith("case close") && !confirmed) return;
    setBusy(true);
    setError("");
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

  if (!authReady) return <main className="auth-loading">VERIFYING ACCESS</main>;
  if (!authenticated) return <SignIn />;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">A</span><span>ASTRA / SSA</span></div>
        <div className="system-state"><i /> CATALOG LINKED <span>·</span> TEME / SGP4</div>
        <div className="clock">EDUCATIONAL MODEL <strong>NON-OPERATIONAL</strong></div>
      </header>

      <aside className="rail">
        <section className="rail-intro">
          <p className="eyebrow">OPERATIONAL PICTURE</p>
          <h1>Orbital<br />command.</h1>
          <p>Governed screening, monitoring, and case actions from one typed console.</p>
        </section>

        <section className="metrics">
          <div><span>MONITORED</span><strong>{String(statusCounts.active).padStart(2, "0")}</strong></div>
          <div><span>WATCH</span><strong>{String(statusCounts.watch).padStart(2, "0")}</strong></div>
          <div className={statusCounts.critical ? "danger" : ""}><span>CRITICAL</span><strong>{String(statusCounts.critical).padStart(2, "0")}</strong></div>
        </section>

        <section className="object-list">
          <div className="section-head">
            <span>MONITORED ELEMENTS</span>
            <span className="object-count">{monitored.length} / {monitored.length}</span>
            <button onClick={() => { setCommand("monitor add "); setPaletteOpen(true); }}>+</button>
          </div>
          <div className="object-scroll">
            {monitored.length ? monitored.map((object, index) => (
              <button
                className={`object-row ${object.norad_id === selectedNoradId ? "selected" : ""}`}
                key={object.id}
                onClick={() => setSelectedNoradId(object.norad_id)}
                aria-pressed={object.norad_id === selectedNoradId}
              >
                <span className="index">{String(index + 1).padStart(2, "0")}</span>
                <span><strong>{object.name}</strong><small>NORAD {object.norad_id}</small></span>
                <i className="live-dot" />
              </button>
            )) : <p className="empty">No monitored elements. Use <code>monitor add 25544</code>.</p>}
          </div>
        </section>

        <section className="history">
          <div className="section-head"><span>RECENT RUNS</span><span>{jobs.length}</span></div>
          {jobs.slice(0, 3).map((job) => (
            <button key={job.id} onClick={() => { setActiveJob(job); setJobEvents([]); }}>
              <span className={`job-status ${job.status}`} />
              <span><strong>{job.command}</strong><small>{job.message}</small></span>
            </button>
          ))}
        </section>
      </aside>

      <section className="orbital-stage">
        <OrbitGlobe
          trajectories={trajectories}
          selectedNoradId={selectedNoradId}
          onSelect={setSelectedNoradId}
        />
        <div className="stage-title">
          <p>ORBITAL PICTURE / +3H</p>
          <span>{trajectories.length} TRACKS / TEME FRAME</span>
        </div>
        <div className="reticle" aria-hidden="true" />
        <div className="legend"><span><i className="primary" /> PRIMARY</span><span><i /> MONITORED</span></div>
      </section>

      <aside className="inspector">
        <div className="section-head"><span>SELECTED ELEMENT</span><span>LIVE</span></div>
        {selectedObject ? (
          <section className="object-card" key={selectedObject.norad_id}>
            <div className="object-card-head">
              <div>
                <p>TRACK {selectedObject.norad_id}</p>
                <h2>{selectedObject.name}</h2>
              </div>
              <span className="tracking-state"><i /> TRACKING</span>
            </div>
            {selectedTelemetry ? (
              <>
                <div className="telemetry-primary">
                  <div>
                    <span>ALTITUDE</span>
                    <strong>{selectedTelemetry.altitude.toFixed(0)}<small> km</small></strong>
                  </div>
                  <div>
                    <span>VELOCITY / EST.</span>
                    <strong>{selectedTelemetry.speed?.toFixed(2) ?? "--"}<small> km/s</small></strong>
                  </div>
                </div>
                <div className="telemetry-grid">
                  <div><span>ORBIT</span><strong>{selectedTelemetry.orbitClass}</strong></div>
                  <div><span>FRAME</span><strong>{selectedTrajectory?.frame}</strong></div>
                  <div><span>X / KM</span><strong>{selectedTelemetry.point.x_km.toFixed(1)}</strong></div>
                  <div><span>Y / KM</span><strong>{selectedTelemetry.point.y_km.toFixed(1)}</strong></div>
                  <div><span>Z / KM</span><strong>{selectedTelemetry.point.z_km.toFixed(1)}</strong></div>
                  <div><span>SAMPLES</span><strong>{selectedTelemetry.trackPoints}</strong></div>
                </div>
                <p className="telemetry-time">
                  PROPAGATED {new Date(selectedTelemetry.point.timestamp).toISOString()}
                </p>
                <button
                  className="screen-object"
                  onClick={() => {
                    setCommand(`screen ${selectedObject.norad_id} --window 72h --threshold 25km`);
                    setPaletteOpen(true);
                  }}
                >
                  SCREEN THIS OBJECT <span>-&gt;</span>
                </button>
              </>
            ) : <p className="empty">Loading propagated telemetry...</p>}
          </section>
        ) : <p className="empty">Select a monitored element.</p>}

        <div className="section-head event-heading"><span>EVENT INSPECTOR</span><span>LIVE</span></div>
        {selectedEvent ? (
          <div className="event-detail">
            <p className={`tier ${selectedEvent.tier}`}>{selectedEvent.tier}</p>
            <h2>{selectedEvent.miss_distance_km.toFixed(3)} <small>km miss</small></h2>
            <dl>
              <div><dt>TCA</dt><dd>{new Date(selectedEvent.tca).toISOString().slice(11, 19)} UTC</dd></div>
              <div><dt>Pc</dt><dd>{selectedEvent.probability_of_collision?.toExponential(2) ?? "—"}</dd></div>
              <div><dt>Event</dt><dd>{selectedEvent.id.slice(0, 8)}</dd></div>
            </dl>
            <button onClick={() => { setCommand(`event explain ${selectedEvent.id}`); setPaletteOpen(true); }}>EXPLAIN EVENT ↗</button>
          </div>
        ) : <p className="empty">No assessed conjunctions in the current ontology.</p>}

        <div className="job-panel">
          <div className="section-head"><span>ACTIVE PROCESS</span><span>{activeJob?.status ?? "IDLE"}</span></div>
          {activeJob ? <>
            <div className="progress"><i style={{ width: `${latestProgress * 100}%` }} /></div>
            <p className="active-command">&gt; {activeJob.command}</p>
            {["queued", "running"].includes(activeJob.status) &&
              <button className="cancel-job" type="button" onClick={cancelActiveJob}>REQUEST CANCELLATION</button>}
            <ol>
              {jobEvents.map((item) => (
                <li key={item.sequence} className={item.stage === "failed" ? "failed" : ""}>
                  <i /> <span>{item.message}</span><small>{Math.round(item.progress * 100)}%</small>
                </li>
              ))}
            </ol>
          </> : <p className="empty">Command worker ready.</p>}
        </div>
      </aside>

      <form className={`command-bar ${paletteOpen ? "expanded" : ""}`} onSubmit={execute}>
        {paletteOpen && <div className="suggestions">
          <span>APPROVED COMMANDS</span>
          {EXAMPLES.map((example) => <button type="button" key={example} onClick={() => setCommand(example)}>{example}</button>)}
        </div>}
        <div className="command-input">
          <span className="prompt">&gt;</span>
          <input
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            onFocus={() => setPaletteOpen(true)}
            aria-label="Operator command"
            spellCheck={false}
          />
          <span className="safe">ALLOWLISTED</span>
          <button disabled={busy} type="submit">{busy ? "QUEUING…" : "EXECUTE ↵"}</button>
        </div>
        {error && <p className="command-error">{error}</p>}
      </form>
    </main>
  );
}
