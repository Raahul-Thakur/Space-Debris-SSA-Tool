import { act, render } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ProductTour from "@/components/ProductTour";

/** The slice of driver.js's config this suite asserts on. */
type TourConfig = {
  steps: Array<{ element?: string }>;
  onDestroyed: () => void;
};

const { driver, drive, destroy } = vi.hoisted(() => {
  const drive = vi.fn();
  const destroy = vi.fn();
  // The parameter is what gives `driver.mock.calls` its config type.
  const driver = vi.fn((config: unknown) => {
    void config;
    return { drive, destroy };
  });
  return { driver, drive, destroy };
});
vi.mock("driver.js", () => ({ driver }));

/** Let the dynamic import and the requestAnimationFrame in `start` settle. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  driver.mockClear();
  drive.mockClear();
  destroy.mockClear();
  window.localStorage.clear();
});

it("builds one tour when the parent asks for it", async () => {
  render(<ProductTour request={1} />);
  await settle();

  expect(driver).toHaveBeenCalledTimes(1);
  expect(drive).toHaveBeenCalledTimes(1);
});

it("does not restart when the parent re-renders for unrelated reasons", async () => {
  // The dashboard re-renders every second to advance its clock. A tour that
  // rebuilt itself on each of those would never leave the first step.
  const { rerender } = render(<ProductTour request={1} onFinish={() => {}} />);
  await settle();
  expect(driver).toHaveBeenCalledTimes(1);

  for (let tick = 0; tick < 3; tick += 1) {
    rerender(<ProductTour request={1} onFinish={() => {}} />);
    await settle();
  }

  expect(driver).toHaveBeenCalledTimes(1);
  expect(destroy).not.toHaveBeenCalled();
});

it("restarts when the parent asks again", async () => {
  const { rerender } = render(<ProductTour request={1} />);
  await settle();
  rerender(<ProductTour request={2} />);
  await settle();

  expect(driver).toHaveBeenCalledTimes(2);
  expect(drive).toHaveBeenCalledTimes(2);
});

it("reveals on-demand anchors before the steps are built", async () => {
  const order: string[] = [];
  driver.mockImplementationOnce(() => {
    order.push("built");
    return { drive, destroy };
  });

  render(<ProductTour request={1} onPrepare={() => order.push("prepared")} />);
  await settle();

  expect(order).toEqual(["prepared", "built"]);
});

it("skips steps whose anchor is not on the page", async () => {
  document.body.insertAdjacentHTML("beforeend", '<div data-tour="command-bar"></div>');
  render(<ProductTour request={1} />);
  await settle();

  const config = driver.mock.calls[0][0] as TourConfig;
  const anchors = config.steps.map((step) => step.element);
  expect(anchors).toContain('[data-tour="command-bar"]');
  expect(anchors).not.toContain('[data-tour="activity-feed"]');
  // The opening step has no anchor and must always survive the filter.
  expect(anchors).toContain(undefined);
});

it("records completion so the tour is not auto-offered again", async () => {
  render(<ProductTour request={1} />);
  await settle();

  const config = driver.mock.calls[0][0] as TourConfig;
  act(() => config.onDestroyed());

  expect(window.localStorage.getItem("astra.tour.completed.v1")).toBeTruthy();
});
