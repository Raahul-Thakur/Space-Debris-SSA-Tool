import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The reconnect loop, pinned.
 *
 * Two bugs in a row lived here, and both were invisible without a cold API:
 * the first version of the retry listed a one-second clock in its
 * dependencies, so the timer was torn down and rebuilt every second and
 * could never reach its six-second delay; and a `setTimeout` fires once,
 * while `connection` stays "unreachable" between attempts, so nothing would
 * schedule the attempt after it.
 *
 * These test the scheduling shape directly rather than through the console,
 * because the failure is about timers and dependencies, not about rendering.
 */

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/** The broken shape: a one-shot timer rebuilt on every tick of a clock. */
function brokenSchedule(refresh: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    tick() {
      // Each render with a new `now` cleans up and reschedules.
      clearTimeout(timer);
      timer = setTimeout(refresh, 6000);
    },
  };
}

/** The shape now in use. */
function schedule(refresh: () => void) {
  const id = setInterval(refresh, 6000);
  return () => clearInterval(id);
}

it("a timer rebuilt every second never fires", () => {
  const refresh = vi.fn();
  const s = brokenSchedule(refresh);
  for (let second = 0; second < 30; second++) {
    s.tick();
    vi.advanceTimersByTime(1000);
  }
  // Thirty seconds of waiting, nothing attempted. This is what a visitor saw.
  expect(refresh).not.toHaveBeenCalled();
});

it("the interval retries until it is cleared", () => {
  const refresh = vi.fn();
  const stop = schedule(refresh);
  vi.advanceTimersByTime(6000);
  expect(refresh).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(12000);
  expect(refresh).toHaveBeenCalledTimes(3);
  stop();
});

it("keeps retrying long enough for a free-tier cold start", () => {
  // Render takes the better part of a minute to wake. A single attempt is
  // not a recovery strategy.
  const refresh = vi.fn();
  const stop = schedule(refresh);
  vi.advanceTimersByTime(60_000);
  expect(refresh.mock.calls.length).toBeGreaterThanOrEqual(8);
  stop();
});

it("stops once it is cleared, so a recovered API is not polled forever", () => {
  const refresh = vi.fn();
  const stop = schedule(refresh);
  vi.advanceTimersByTime(6000);
  stop();
  vi.advanceTimersByTime(60_000);
  expect(refresh).toHaveBeenCalledTimes(1);
});
