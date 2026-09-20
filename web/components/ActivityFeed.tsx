"use client";

import { useMemo, useState } from "react";
import type { ActivityItem } from "@/lib/types";
import type { FeedStatus } from "@/lib/useActivityFeed";

const KIND_LABELS: Record<ActivityItem["kind"], string> = {
  conjunction: "CDM",
  alert: "ALRT",
  job: "JOB",
  command: "CMD",
  monitoring: "WTCH",
  governance: "GOV"
};

const FILTERS = [
  { id: "all", label: "ALL" },
  { id: "risk", label: "RISK" },
  { id: "ops", label: "OPS" }
] as const;

type FilterId = (typeof FILTERS)[number]["id"];

const RISK_KINDS = new Set<ActivityItem["kind"]>(["conjunction", "alert"]);

function relativeTime(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

export default function ActivityFeed({
  items,
  status,
  now,
  onSelect
}: {
  items: ActivityItem[];
  status: FeedStatus;
  /** Ticking clock from the parent, so every row re-ages together. */
  now: number;
  onSelect?: (item: ActivityItem) => void;
}) {
  const [filter, setFilter] = useState<FilterId>("all");
  const [collapsed, setCollapsed] = useState(false);

  const visible = useMemo(() => {
    if (filter === "risk") return items.filter((item) => RISK_KINDS.has(item.kind));
    if (filter === "ops") return items.filter((item) => !RISK_KINDS.has(item.kind));
    return items;
  }, [items, filter]);

  const criticalCount = useMemo(
    () => items.filter((item) => item.severity === "critical").length,
    [items]
  );

  return (
    <section
      className={`activity-feed ${collapsed ? "collapsed" : ""}`}
      data-tour="activity-feed"
      aria-label="Live activity feed"
    >
      <header>
        <span className={`feed-status ${status}`}>
          <i />
          {status === "live" ? "LIVE" : status.toUpperCase()}
        </span>
        <span className="feed-title">ACTIVITY</span>
        {criticalCount > 0 && <span className="feed-critical">{criticalCount} CRIT</span>}
        <button
          type="button"
          className="feed-toggle"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
        >
          {collapsed ? "+" : "–"}
        </button>
      </header>

      {!collapsed && (
        <>
          <div className="feed-filters" role="group" aria-label="Filter activity">
            {FILTERS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={filter === option.id ? "active" : ""}
                aria-pressed={filter === option.id}
                onClick={() => setFilter(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>

          <ol className="feed-list">
            {visible.length ? (
              visible.map((item) => (
                <li key={item.id} className={`feed-row ${item.severity}`}>
                  <button type="button" onClick={() => onSelect?.(item)}>
                    <span className="feed-kind">{KIND_LABELS[item.kind]}</span>
                    <span className="feed-body">
                      <strong>{item.title}</strong>
                      <small>{item.detail}</small>
                    </span>
                    <span className="feed-age">{relativeTime(item.occurred_at, now)}</span>
                  </button>
                </li>
              ))
            ) : (
              <li className="feed-idle">
                {status === "offline"
                  ? "Stream unavailable. Retrying in the background."
                  : "Listening. Run a command to generate activity."}
              </li>
            )}
          </ol>
        </>
      )}
    </section>
  );
}
