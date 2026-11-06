"use client";

import dynamic from "next/dynamic";
import { Component, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import type { Trajectory } from "@/lib/types";

/*
 * Cesium is by far the heaviest thing on the site: about 1.1 MB of
 * compressed JavaScript in one chunk, plus three dozen worker and asset
 * files. `next/dynamic` keeps it out of the main bundle, but the chunk is
 * still fetched the moment <OrbitGlobe> is rendered, so where the globe is
 * rendered at all decides who pays for it.
 */
const OrbitGlobe = dynamic(() => import("@/components/OrbitGlobe"), { ssr: false });

/** Matches the phone breakpoint in globals.css, where the console stacks. */
export const PHONE_QUERY = "(max-width: 720px)";

type GlobeProps = {
  trajectories: Trajectory[];
  selectedNoradId: string | null;
  onSelect: (noradId: string) => void;
};

/**
 * Whether to start the globe without being asked.
 *
 * Read once, when the stage first renders, and never again: a desktop window
 * narrowed past the breakpoint keeps the globe it already paid for, and a
 * phone turned sideways does not suddenly start a megabyte download. The
 * console only renders this after its own client-side auth check, so there is
 * no server-rendered markup for the answer to disagree with. Without
 * matchMedia (jsdom, some embedded browsers) the answer is the old one: load.
 */
function startsImmediately(): boolean {
  try {
    return !window.matchMedia(PHONE_QUERY).matches;
  } catch {
    return true;
  }
}

/**
 * The globe, or on a phone a poster of it until the visitor asks.
 *
 * On a phone the globe is one panel in a long scrolling page, below the watch
 * list, and most visits are to read an event or type a command; making every
 * one of them download and compile Cesium first was most of the console's
 * first-load cost on mobile. Desktop, where the globe is the centre of the
 * screen, still loads it straight away.
 */
export default function GlobeStage(props: GlobeProps) {
  const [requested, setRequested] = useState(startsImmediately);

  if (!requested) {
    return <GlobePoster onShow={() => setRequested(true)} tracks={props.trajectories.length} />;
  }
  return (
    <GlobeErrorBoundary>
      <OrbitGlobe {...props} />
    </GlobeErrorBoundary>
  );
}

/**
 * A drawing of the plate in the same ink as the real one: the planet as a
 * flat disc with its graticule, and a few orbit tracks crossing it, one in
 * signal red. Inline SVG, so it costs a few hundred bytes and no request.
 */
function GlobePoster({ onShow, tracks }: { onShow: () => void; tracks: number }) {
  return (
    <div className="globe globe-poster">
      <svg viewBox="0 0 400 400" aria-hidden="true" focusable="false">
        <g fill="none" strokeWidth="1">
          <circle cx="200" cy="200" r="118" fill="#2b2f32" stroke="#4d5256" />
          <ellipse cx="200" cy="200" rx="118" ry="40" stroke="#4d5256" />
          <ellipse cx="200" cy="200" rx="118" ry="84" stroke="#4d5256" />
          <ellipse cx="200" cy="200" rx="40" ry="118" stroke="#4d5256" />
          <ellipse cx="200" cy="200" rx="84" ry="118" stroke="#4d5256" />
          <line x1="82" y1="200" x2="318" y2="200" stroke="#4d5256" />
          <line x1="200" y1="82" x2="200" y2="318" stroke="#4d5256" />
          <ellipse cx="200" cy="200" rx="172" ry="58" transform="rotate(-24 200 200)" stroke="#948f83" strokeOpacity=".55" />
          <ellipse cx="200" cy="200" rx="160" ry="92" transform="rotate(38 200 200)" stroke="#948f83" strokeOpacity=".55" />
          <ellipse cx="200" cy="200" rx="186" ry="34" transform="rotate(8 200 200)" stroke="#c02f18" strokeWidth="2" />
        </g>
        <rect x="377" y="174" width="7" height="7" fill="#c02f18" />
      </svg>
      <div className="globe-poster-copy">
        <p>ORBITAL PICTURE / +3H</p>
        <span>{tracks} TRACKS / TEME FRAME</span>
        <button type="button" onClick={onShow}>
          SHOW 3D GLOBE
        </button>
        <small>Loads the 3D viewer, about 1&nbsp;MB.</small>
      </div>
    </div>
  );
}

type BoundaryState = { failed: boolean };

/**
 * Keeps a globe failure inside the globe's own panel.
 *
 * Cesium needs WebGL, which is missing on some locked-down machines, old
 * phones and remote desktops, and its chunk can fail to download on a bad
 * connection. Either used to throw through the whole console and leave a
 * blank page, although nothing else on it depends on the globe: the watch
 * list, events and command bar work the same without it.
 */
export class GlobeErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    // Left in the console so a report from a visitor can say what failed.
    console.error("The 3D globe failed to start.", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="globe globe-poster globe-failed" role="status">
        <div className="globe-poster-copy">
          <p>3D GLOBE UNAVAILABLE</p>
          <span>
            This browser could not start the 3D viewer, which needs WebGL. Everything
            else in the console still works.
          </span>
          <button type="button" onClick={() => this.setState({ failed: false })}>
            TRY AGAIN
          </button>
        </div>
      </div>
    );
  }
}
