import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

/**
 * The faint text greys, held to WCAG AA.
 *
 * They carry the console's smallest type, so a later "slightly lighter"
 * tweak is exactly how they failed before. The values are read from the
 * stylesheet, so a change there is checked here without editing this file.
 */

const css = readFileSync(resolve(__dirname, "../app/globals.css"), "utf8");

/** The value of `name` in the first block that starts with `selector`. */
function token(selector: string, name: string): string {
  const block = css.slice(css.indexOf(selector));
  const match = block.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i"));
  if (!match) throw new Error(`${name} not found under ${selector}`);
  return match[1];
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const LIGHT = ":root {";
const DARK = ':root[data-theme="dark"]';

it.each([
  ["light --ink-faint", LIGHT, "--ink-faint", ["--paper", "--paper-sunk", "--paper-band"]],
  ["dark --ink-faint", DARK, "--ink-faint", ["--paper", "--paper-sunk", "--paper-band"]],
  ["--plate-faint", LIGHT, "--plate-faint", ["--plate", "--plate-sunk", "--slab"]]
] as const)("%s reaches 4.5:1 on every surface it is used on", (_label, scope, fg, backgrounds) => {
  for (const bg of backgrounds) {
    expect(ratio(token(scope, fg), token(scope, bg))).toBeGreaterThanOrEqual(4.5);
  }
});

it("--plate-faint also reaches 4.5:1 on the dark theme's slab", () => {
  // The plate tokens are not redefined for dark, but the slab is.
  expect(ratio(token(LIGHT, "--plate-faint"), token(DARK, "--slab"))).toBeGreaterThanOrEqual(4.5);
});
