import { expect, it } from "vitest";
import { RUNNABLE_SAMPLES, SAMPLE_QUERIES, matchSamples } from "@/lib/samples";

it("offers runnable samples that need no id substitution", () => {
  expect(RUNNABLE_SAMPLES.length).toBeGreaterThan(4);
  for (const sample of RUNNABLE_SAMPLES) {
    expect(sample.command).not.toContain("<");
  }
});

it("marks every placeholder sample so the console can warn first", () => {
  for (const sample of SAMPLE_QUERIES) {
    expect(sample.command.includes("<")).toBe(Boolean(sample.placeholder));
  }
});

it("ranks a prefix match above a description match", () => {
  const [first] = matchSamples("events list --tier");
  expect(first.command).toBe("events list --tier critical");
});

it("falls back to searching labels and descriptions", () => {
  const matches = matchSamples("hubble");
  expect(matches.length).toBeGreaterThan(0);
  expect(matches.every((sample) => /hubble/i.test(`${sample.label} ${sample.description}`))).toBe(
    true
  );
});

it("returns nothing for input outside the allowlist", () => {
  expect(matchSamples("rm -rf /")).toHaveLength(0);
});

it("shows the default set when nothing has been typed", () => {
  expect(matchSamples("")).toHaveLength(6);
});
