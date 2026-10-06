import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  getSeenEventsServerSnapshot,
  getSeenEventsSnapshot,
  markEventsSeen,
  parseSeenEvents,
  subscribeToSeenEvents
} from "@/lib/seenEvents";

beforeEach(() => {
  window.localStorage.clear();
  // Also clears the module's cached snapshot. Writing localStorage directly
  // would not: the cache is invalidated only by a write through this module
  // or by a storage event from another tab, which is correct for a single
  // tab but means tests have to reset it the same way.
  markEventsSeen([]);
});
afterEach(() => vi.restoreAllMocks());

it("reports nothing seen on a browser that has never visited", () => {
  expect(parseSeenEvents(getSeenEventsSnapshot()).size).toBe(0);
});

it("remembers the conjunctions a visitor has been shown", () => {
  markEventsSeen(["a", "b"]);
  const seen = parseSeenEvents(getSeenEventsSnapshot());
  expect(seen.has("a")).toBe(true);
  expect(seen.has("b")).toBe(true);
  expect(seen.has("c")).toBe(false);
});

it("returns a stable snapshot so React does not loop", () => {
  markEventsSeen(["a"]);
  expect(getSeenEventsSnapshot()).toBe(getSeenEventsSnapshot());
});

it("notifies subscribers when the set changes", () => {
  const listener = vi.fn();
  const unsubscribe = subscribeToSeenEvents(listener);
  markEventsSeen(["a"]);
  expect(listener).toHaveBeenCalled();
  unsubscribe();
});

it("stops notifying after unsubscribe", () => {
  const listener = vi.fn();
  subscribeToSeenEvents(listener)();
  markEventsSeen(["a"]);
  expect(listener).not.toHaveBeenCalled();
});

it("treats the server as having seen nothing", () => {
  // Rendering "3 new" on the server and "0 new" on the client, or the
  // reverse, is a hydration mismatch; the server must have one answer.
  expect(parseSeenEvents(getSeenEventsServerSnapshot()).size).toBe(0);
});

it("survives storage being unavailable", () => {
  // Private browsing, or site data blocked.
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("denied");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied");
  });
  expect(() => markEventsSeen(["a"])).not.toThrow();
  expect(() => parseSeenEvents(getSeenEventsSnapshot())).not.toThrow();
});

it("under-reports rather than claiming everything is new when storage is corrupt", () => {
  // Whatever is in storage, a value that will not parse must read as "seen
  // nothing" rather than throwing or marking every conjunction as new.
  expect(parseSeenEvents("not json").size).toBe(0);
  expect(parseSeenEvents("").size).toBe(0);
});

it("ignores a stored value that is not a list", () => {
  expect(parseSeenEvents('{"a":1}').size).toBe(0);
});

it("does not record the same conjunction twice", () => {
  markEventsSeen(["a", "a", "b"]);
  expect(parseSeenEvents(getSeenEventsSnapshot()).size).toBe(2);
});
