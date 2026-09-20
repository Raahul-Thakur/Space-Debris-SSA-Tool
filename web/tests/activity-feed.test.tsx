import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ActivityFeed from "@/components/ActivityFeed";
import type { ActivityItem } from "@/lib/types";

const NOW = Date.parse("2026-09-20T12:00:00Z");

function item(overrides: Partial<ActivityItem> = {}): ActivityItem {
  return {
    id: "event:abc",
    kind: "conjunction",
    severity: "critical",
    title: "Conjunction 0.412 km",
    detail: "ISS / IRIDIUM 33 DEB",
    occurred_at: new Date(NOW - 45_000).toISOString(),
    entity_type: "ConjunctionEvent",
    entity_id: "abc",
    norad_id: "25544",
    payload: {},
    ...overrides
  };
}

it("renders streamed items with a relative age and a critical count", () => {
  render(<ActivityFeed items={[item()]} status="live" now={NOW} />);

  expect(screen.getByText("LIVE")).toBeInTheDocument();
  expect(screen.getByText("Conjunction 0.412 km")).toBeInTheDocument();
  expect(screen.getByText("45s")).toBeInTheDocument();
  expect(screen.getByText("1 CRIT")).toBeInTheDocument();
});

it("filters operational entries out of the risk view", () => {
  const items = [
    item(),
    item({ id: "command:1", kind: "command", severity: "info", title: "operator ran screen" })
  ];
  render(<ActivityFeed items={items} status="live" now={NOW} />);

  expect(screen.getByText("operator ran screen")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "RISK" }));
  expect(screen.queryByText("operator ran screen")).not.toBeInTheDocument();
  expect(screen.getByText("Conjunction 0.412 km")).toBeInTheDocument();
});

it("reports a dropped stream instead of looking idle", () => {
  render(<ActivityFeed items={[]} status="offline" now={NOW} />);

  expect(screen.getByText("OFFLINE")).toBeInTheDocument();
  expect(screen.getByText(/retrying in the background/i)).toBeInTheDocument();
});

it("hands the selected item back to the dashboard", () => {
  const onSelect = vi.fn();
  render(<ActivityFeed items={[item()]} status="live" now={NOW} onSelect={onSelect} />);

  fireEvent.click(screen.getByText("Conjunction 0.412 km"));
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ entity_id: "abc" }));
});
