import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import CommandPalette from "@/components/CommandPalette";
import type { SampleQuery } from "@/lib/samples";

const SAMPLE: SampleQuery = {
  command: "screen 25544 --window 72h",
  label: "Screen the ISS",
  description: "Three-day look-ahead against the debris cloud.",
  category: "Screening",
  role: "analyst",
  duration: "~40s"
};

const PROPOSAL = {
  command: "screen 25544 --window 24h",
  rationale: "ISS (ZARYA) → NORAD 25544 · 'this week' → 24h (capped: your plan screens up to 24h)"
};

function renderPalette(props: Partial<Parameters<typeof CommandPalette>[0]> = {}) {
  const onAccept = vi.fn();
  render(
    <CommandPalette
      matches={[]}
      activeIndex={-1}
      onPick={vi.fn()}
      onHover={vi.fn()}
      onAcceptInterpretation={onAccept}
      {...props}
    />
  );
  return { onAccept };
}

it("offers a translation of what was typed", () => {
  renderPalette({ interpretation: PROPOSAL });
  expect(screen.getByText("screen 25544 --window 24h")).toBeInTheDocument();
  expect(screen.getByText(/IN PLAIN ENGLISH/i)).toBeInTheDocument();
});

it("shows why the command says what it says", () => {
  // A proposal the operator cannot check is a proposal they have to trust.
  renderPalette({ interpretation: PROPOSAL });
  expect(screen.getByText(/NORAD 25544/)).toBeInTheDocument();
  expect(screen.getByText(/capped/)).toBeInTheDocument();
});

it("loads the proposal into the input when accepted", () => {
  const { onAccept } = renderPalette({ interpretation: PROPOSAL });
  fireEvent.mouseDown(screen.getByText("screen 25544 --window 24h"));
  expect(onAccept).toHaveBeenCalledWith("screen 25544 --window 24h");
});

it("never runs the proposal on its own", () => {
  // Accepting fills the command bar; the operator still presses Execute.
  const { onAccept } = renderPalette({ interpretation: PROPOSAL });
  expect(onAccept).not.toHaveBeenCalled();
});

it("shows nothing when the request could not be translated", () => {
  renderPalette({ interpretation: { command: null, rationale: "Could not tell." } });
  expect(screen.queryByText(/IN PLAIN ENGLISH/i)).not.toBeInTheDocument();
});

it("invites plain English when nothing matches and translation is available", () => {
  renderPalette({ canInterpret: true });
  expect(screen.getByText(/plain English/i)).toBeInTheDocument();
});

it("does not invite plain English without an account", () => {
  renderPalette({ canInterpret: false });
  expect(screen.getByText(/outside the allowlist are rejected/i)).toBeInTheDocument();
  expect(screen.queryByText(/Describe what you want/i)).not.toBeInTheDocument();
});

it("still lists sample commands alongside a translation", () => {
  renderPalette({ matches: [SAMPLE], interpretation: PROPOSAL });
  expect(screen.getByText("screen 25544 --window 72h")).toBeInTheDocument();
  expect(screen.getByText("screen 25544 --window 24h")).toBeInTheDocument();
});
