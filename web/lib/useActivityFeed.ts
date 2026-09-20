"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamSse } from "./api";
import type { ActivityItem, ActivitySnapshot } from "./types";

export type FeedStatus = "connecting" | "live" | "reconnecting" | "offline";

/** Newest-first cap on what the feed keeps in memory. */
const MAX_ITEMS = 120;
const BASE_RETRY_MS = 1_500;
const MAX_RETRY_MS = 20_000;

type FeedState = {
  items: ActivityItem[];
  status: FeedStatus;
  /** Timestamp of the last frame received, heartbeats included. */
  lastContactAt: string | null;
};

function merge(current: ActivityItem[], incoming: ActivityItem[]): ActivityItem[] {
  if (!incoming.length) return current;
  const seen = new Set(current.map((item) => item.id));
  const fresh = incoming.filter((item) => !seen.has(item.id));
  if (!fresh.length) return current;
  return [...fresh.reverse(), ...current].slice(0, MAX_ITEMS);
}

/**
 * Subscribe to the unified server activity stream.
 *
 * The feed starts from a snapshot so the dashboard is populated on first paint,
 * then holds an SSE connection open. Dropped connections resume from the last
 * cursor with exponential backoff, so nothing is replayed twice and nothing is
 * silently lost while the browser was asleep.
 */
export function useActivityFeed(enabled: boolean, onItems?: (items: ActivityItem[]) => void) {
  const [state, setState] = useState<FeedState>({
    items: [],
    status: "connecting",
    lastContactAt: null
  });
  const cursorRef = useRef<string | null>(null);
  // Held in a ref so a caller passing an inline callback does not tear down
  // and re-open the stream on every render.
  const notifyRef = useRef(onItems);
  useEffect(() => {
    notifyRef.current = onItems;
  }, [onItems]);

  const ingest = useCallback((incoming: ActivityItem[]) => {
    if (!incoming.length) return;
    for (const item of incoming) {
      if (!cursorRef.current || item.occurred_at > cursorRef.current) {
        cursorRef.current = item.occurred_at;
      }
    }
    setState((current) => ({
      ...current,
      items: merge(current.items, incoming),
      lastContactAt: new Date().toISOString()
    }));
    notifyRef.current?.(incoming);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const controllers = new Set<AbortController>();

    async function connect() {
      if (cancelled) return;
      const controller = new AbortController();
      controllers.add(controller);
      try {
        if (!cursorRef.current) {
          const snapshot = await api<ActivitySnapshot>("/activity?limit=50");
          if (cancelled) return;
          cursorRef.current = snapshot.cursor;
          setState((current) => ({
            ...current,
            items: [...snapshot.items].reverse().slice(0, MAX_ITEMS),
            lastContactAt: snapshot.server_time
          }));
        }
        const since = encodeURIComponent(cursorRef.current ?? "");
        setState((current) => ({ ...current, status: "live" }));
        attempt = 0;
        await streamSse<ActivityItem>(
          `/stream/activity?since=${since}`,
          (item) => ingest([item]),
          controller.signal
        );
      } catch {
        if (cancelled || controller.signal.aborted) return;
      } finally {
        controllers.delete(controller);
      }
      if (cancelled) return;
      // A clean end-of-stream is still a dropped subscription: retry.
      attempt += 1;
      setState((current) => ({
        ...current,
        status: attempt > 3 ? "offline" : "reconnecting"
      }));
      const delay = Math.min(BASE_RETRY_MS * 2 ** (attempt - 1), MAX_RETRY_MS);
      retryTimer = setTimeout(connect, delay);
    }

    void connect();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      for (const controller of controllers) controller.abort();
    };
  }, [enabled, ingest]);

  return state;
}
