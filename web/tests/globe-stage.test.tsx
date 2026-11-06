import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * When the globe is fetched, and what a failure looks like.
 *
 * `next/dynamic` fetches Cesium's chunk the moment the dynamic component
 * renders, so "is the globe rendered" is exactly "has the phone paid for
 * Cesium". The stub stands in for that chunk and counts its renders. (That
 * the real chunk is not requested before the tap was checked in a browser
 * against the static export, with the iPhone 13 profile.)
 */

const { globeRenders } = vi.hoisted(() => ({ globeRenders: vi.fn() }));
vi.mock("next/dynamic", () => ({
  default: () =>
    function StubGlobe() {
      globeRenders();
      return <div data-testid="cesium-globe" />;
    }
}));

import GlobeStage, { GlobeErrorBoundary, PHONE_QUERY } from "@/components/GlobeStage";

function viewport(phone: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === PHONE_QUERY ? phone : false,
    addEventListener() {},
    removeEventListener() {}
  }));
}

const props = { trajectories: [], selectedNoradId: null, onSelect: () => {} };

beforeEach(() => globeRenders.mockClear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("starts the globe straight away on a desktop", () => {
  viewport(false);
  render(<GlobeStage {...props} />);
  expect(screen.getByTestId("cesium-globe")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /show 3d globe/i })).toBeNull();
});

it("shows a poster on a phone and loads nothing until asked", async () => {
  viewport(true);
  render(<GlobeStage {...props} />);
  expect(globeRenders).not.toHaveBeenCalled();
  expect(screen.queryByTestId("cesium-globe")).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: /show 3d globe/i }));
  expect(screen.getByTestId("cesium-globe")).toBeInTheDocument();
});

it("keeps the old behaviour where matchMedia is missing", () => {
  // jsdom has none, and nor do some embedded browsers: load, as before.
  vi.stubGlobal("matchMedia", undefined);
  render(<GlobeStage {...props} />);
  expect(screen.getByTestId("cesium-globe")).toBeInTheDocument();
});

it("contains a globe failure inside the globe panel", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  let broken = true;
  function Flaky() {
    if (broken) throw new Error("WebGL is not supported");
    return <p>globe</p>;
  }
  render(
    <main>
      <GlobeErrorBoundary>
        <Flaky />
      </GlobeErrorBoundary>
      <p>command bar</p>
    </main>
  );
  expect(screen.getByText(/3D globe unavailable/i)).toBeInTheDocument();
  // The rest of the console is untouched.
  expect(screen.getByText("command bar")).toBeInTheDocument();

  broken = false;
  await userEvent.click(screen.getByRole("button", { name: /try again/i }));
  expect(screen.getByText("globe")).toBeInTheDocument();
});
