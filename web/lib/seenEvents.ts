/**
 * Which conjunctions this browser has already been shown.
 *
 * Exposed as an external store rather than as state seeded in an effect, so
 * React reads it through `useSyncExternalStore`: that gives a defined
 * server snapshot (nothing seen) and avoids a hydration mismatch, and it
 * notifies every reader when the set changes — including another tab.
 *
 * Conjunction rows carry no creation timestamp, so "new since last visit" is
 * tracked by identity. That also behaves correctly when a re-screen produces
 * the same encounter again: it is the same event, and stays seen.
 *
 * Nothing here is authoritative. It lives only in this browser, it is a
 * convenience for a visitor without an account, and every path through it
 * tolerates storage being unavailable.
 */

const KEY = "astra.seen-events";
const EMPTY = "[]";

type Listener = () => void;
const listeners = new Set<Listener>();

/** Cached so repeated snapshots return a stable reference. */
let snapshot: string | null = null;

function read(): string {
  try {
    return window.localStorage.getItem(KEY) ?? EMPTY;
  } catch {
    // Private browsing, or site data blocked. Nothing is marked seen, which
    // is the safer failure: it under-reports what is new rather than
    // claiming everything is.
    return EMPTY;
  }
}

export function subscribeToSeenEvents(listener: Listener): () => void {
  listeners.add(listener);
  // Another tab marking events seen should settle this one too.
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === KEY) {
      snapshot = null;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function getSeenEventsSnapshot(): string {
  snapshot ??= read();
  return snapshot;
}

/** The server has no browser storage, so nothing has been seen there. */
export function getSeenEventsServerSnapshot(): string {
  return EMPTY;
}

export function parseSeenEvents(raw: string): Set<string> {
  try {
    const parsed: unknown = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

export function markEventsSeen(ids: readonly string[]): void {
  const serialised = JSON.stringify([...new Set(ids)]);
  try {
    window.localStorage.setItem(KEY, serialised);
  } catch {
    // The badge simply reappears next visit.
  }
  // Updated even when the write failed, so the banner still dismisses for
  // this session rather than appearing stuck.
  snapshot = serialised;
  for (const listener of listeners) listener();
}
