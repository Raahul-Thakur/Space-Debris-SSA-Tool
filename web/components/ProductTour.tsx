"use client";

import { useCallback, useEffect, useRef } from "react";
import type { Driver } from "driver.js";

/** Bumping this re-offers the tour to people who already completed an older one. */
const TOUR_VERSION = "1";
const STORAGE_KEY = `astra.tour.completed.v${TOUR_VERSION}`;

type Step = {
  element?: string;
  title: string;
  description: string;
};

const STEPS: Step[] = [
  {
    title: "Welcome to Astra / SSA",
    description:
      "A governed space situational awareness console. Everything here runs on public two-line element sets and an SGP4 propagator — it is an educational model, not an operational system. This tour takes about a minute."
  },
  {
    element: '[data-tour="command-bar"]',
    title: "The console is the control surface",
    description:
      "Every action starts as a typed command. Commands are parsed against an allowlist and never passed to a shell, so there is no free-form execution. Press <kbd>Ctrl</kbd>+<kbd>K</kbd> at any time to focus it."
  },
  {
    element: '[data-tour="samples"]',
    title: "Start from a sample query",
    description:
      "Not sure what to type? The palette lists ready-made commands with a short note on what each one does and how long it takes. Click one to load it, then press Execute."
  },
  {
    element: '[data-tour="metrics"]',
    title: "Live counts",
    description:
      "Monitored objects, watch-tier events, and critical-tier events. These update from the server stream as screening runs complete — you never need to refresh the page."
  },
  {
    element: '[data-tour="object-list"]',
    title: "The monitored set",
    description:
      "Objects you have added with <code>monitor add</code>. Selecting one draws its propagated track on the globe and fills the telemetry panel on the right."
  },
  {
    element: '[data-tour="globe"]',
    title: "The orbital picture",
    description:
      "A three-hour forward propagation in the TEME frame for every monitored object. Drag to rotate, scroll to zoom, and click a track to select that object."
  },
  {
    element: '[data-tour="activity-feed"]',
    title: "Real-time activity",
    description:
      "A single chronological stream of conjunctions, alerts, job transitions, commands, and governance actions — from every operator, not just you. Filter it to RISK or OPS, or collapse it when the globe needs the room."
  },
  {
    element: '[data-tour="inspector"]',
    title: "Inspector",
    description:
      "Telemetry for the selected object, the most recent assessed conjunction, and the progress of whatever job is currently running. Screening jobs stream their stages here as they execute."
  },
  {
    element: '[data-tour="docs-link"]',
    title: "Documentation",
    description:
      "The full command reference, the concepts behind the numbers, and the methodology and its limitations. You can restart this tour from there at any time."
  }
];

export default function ProductTour({
  request,
  onPrepare,
  onFinish
}: {
  /**
   * A counter, not a boolean: the parent increments it to ask for the tour.
   * Nothing has to be reset when the tour ends, so its lifecycle never
   * round-trips through parent state — which is what made the tour restart
   * from step one every time the parent re-rendered (once a second, for the
   * clock).
   */
  request: number;
  /**
   * Runs before the first step. The dashboard uses it to reveal panels that are
   * only mounted on demand — a step whose anchor is absent is skipped, so the
   * command palette has to be open before the steps are built.
   */
  onPrepare?: () => void;
  /** Runs once the tour is dismissed, to undo whatever `onPrepare` revealed. */
  onFinish?: () => void;
}) {
  const driverRef = useRef<Driver | null>(null);
  // Not rendered, so a ref keeps the auto-start one-shot without a re-render.
  const autoStartedRef = useRef(false);
  // `start` awaits a dynamic import and a frame, so two overlapping calls (a
  // double click, or React's development double-invoke of effects) could each
  // build a driver and leave two popovers on screen. Every call takes a ticket;
  // only the newest one is allowed to finish.
  const runRef = useRef(0);
  // Set while the component is tearing itself down, so the resulting destroy
  // does not report a completed tour back to the parent.
  const silentRef = useRef(false);
  // Callers pass inline arrows, so these would change identity on every parent
  // render. Reading them through a ref keeps `start` stable: otherwise the
  // effect below re-runs on each render and restarts the tour from step one.
  const hooks = useRef({ onPrepare, onFinish });
  useEffect(() => {
    hooks.current = { onPrepare, onFinish };
  }, [onPrepare, onFinish]);

  /** Driver's own teardown hook: the instance is already gone by this point. */
  const finish = useCallback(() => {
    driverRef.current = null;
    if (silentRef.current) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, new Date().toISOString());
    } catch {
      // A blocked storage API only means the tour may be offered again.
    }
    hooks.current.onFinish?.();
  }, []);

  const start = useCallback(async () => {
    const ticket = ++runRef.current;
    silentRef.current = false;
    const { driver } = await import("driver.js");
    if (ticket !== runRef.current) return;
    hooks.current.onPrepare?.();
    // Let React commit whatever `onPrepare` revealed before anchors resolve.
    await new Promise((resolve) => requestAnimationFrame(resolve));
    if (ticket !== runRef.current) return;
    if (driverRef.current) {
      // Replacing a running tour is a restart, not a completion.
      silentRef.current = true;
      driverRef.current.destroy();
      silentRef.current = false;
    }
    const instance = driver({
      showProgress: true,
      overlayColor: "#02090b",
      overlayOpacity: 0.72,
      stagePadding: 6,
      stageRadius: 0,
      popoverClass: "astra-tour",
      nextBtnText: "NEXT →",
      prevBtnText: "← BACK",
      doneBtnText: "DONE",
      progressText: "{{current}} / {{total}}",
      // Steps whose anchor is hidden at this viewport (the inspector column is
      // dropped on narrow screens) are omitted rather than spotlighting nothing.
      steps: STEPS.filter(
        (step) => !step.element || document.querySelector(step.element)
      ).map((step) => ({
        element: step.element,
        popover: { title: step.title, description: step.description }
      })),
      onDestroyed: finish
    });
    driverRef.current = instance;
    instance.drive();
  }, [finish]);

  useEffect(() => {
    if (request > 0) void start();
  }, [request, start]);

  // First-time visitors are offered the tour once, after the shell has painted.
  useEffect(() => {
    if (autoStartedRef.current || request > 0) return;
    let seen = true;
    try {
      seen = Boolean(window.localStorage.getItem(STORAGE_KEY));
    } catch {
      seen = true;
    }
    if (seen) return;
    autoStartedRef.current = true;
    const timer = setTimeout(() => void start(), 900);
    return () => clearTimeout(timer);
  }, [request, start]);

  useEffect(
    () => () => {
      runRef.current += 1;
      silentRef.current = true;
      driverRef.current?.destroy();
    },
    []
  );

  return null;
}

/** Clear the completion flag so the tour auto-starts on the next visit. */
export function resetTour() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to reset when storage is unavailable.
  }
}
