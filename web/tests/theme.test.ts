import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The theme preference, pinned.
 *
 * Three things here are easy to get wrong and invisible when they are:
 * a choice that is not remembered, a page that flashes white before React
 * hydrates, and the two dark-token blocks in the stylesheet drifting apart
 * because a media query and an attribute selector cannot share a rule.
 */

let media: { matches: boolean; listeners: Set<() => void> };

async function load() {
  vi.resetModules();
  return import("@/lib/theme");
}

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  media = { matches: false, listeners: new Set() };
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("dark") ? media.matches : false,
    addEventListener: (_: string, fn: () => void) => media.listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => media.listeners.delete(fn)
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  // Restored here rather than inside the tests that install them: an
  // inline restore is skipped when an assertion fails, and a leaked
  // throwing localStorage then fails every test after it.
  vi.restoreAllMocks();
});

// ------------------------------------------------------------ the default
it("follows the system until somebody chooses", async () => {
  media.matches = true;
  const { getThemeSnapshot } = await load();
  expect(getThemeSnapshot()).toBe("dark");
});

it("leaves the attribute off while following the system", async () => {
  // The attribute is what overrides the stylesheet's media query. Setting it
  // unnecessarily would freeze the page against a later system change.
  media.matches = true;
  const { subscribeToTheme } = await load();
  subscribeToTheme(() => {})();
  expect(document.documentElement.dataset.theme).toBeUndefined();
});

it("survives a browser that has no matchMedia at all", async () => {
  // jsdom has no implementation, and nor do some embedded browsers. An
  // unguarded subscription here took down every page carrying the toggle,
  // which is every page -- and the failure looked like a sign-in bug.
  vi.unstubAllGlobals();
  const { subscribeToTheme, getThemeSnapshot, setTheme } = await load();
  let stop: (() => void) | undefined;
  expect(() => {
    stop = subscribeToTheme(() => {});
  }).not.toThrow();
  expect(getThemeSnapshot()).toBe("light");
  setTheme("dark");
  expect(getThemeSnapshot()).toBe("dark");
  stop?.();
});

// ------------------------------------------------------------- the choice
it("remembers a choice across a reload", async () => {
  const first = await load();
  first.setTheme("dark");
  // A reload is a fresh module with the same storage.
  const second = await load();
  expect(second.getThemeSnapshot()).toBe("dark");
});

it("lets an explicit choice outrank the system in both directions", async () => {
  media.matches = true;
  const { setTheme, getThemeSnapshot } = await load();
  setTheme("light");
  expect(getThemeSnapshot()).toBe("light");
  expect(document.documentElement.dataset.theme).toBe("light");
});

it("tells its subscribers when the choice changes", async () => {
  const { subscribeToTheme, setTheme, getThemeSnapshot } = await load();
  const seen: string[] = [];
  const stop = subscribeToTheme(() => seen.push(getThemeSnapshot()));
  setTheme("dark");
  setTheme("light");
  stop();
  expect(seen).toEqual(["dark", "light"]);
});

it("settles a second tab that switched theme", async () => {
  const { subscribeToTheme, getThemeSnapshot } = await load();
  const stop = subscribeToTheme(() => {});
  window.localStorage.setItem("astra.theme", "dark");
  window.dispatchEvent(new StorageEvent("storage", { key: "astra.theme" }));
  expect(getThemeSnapshot()).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  stop();
});

it("reports light to the server, which cannot know the device", async () => {
  const { getThemeServerSnapshot } = await load();
  expect(getThemeServerSnapshot()).toBe("light");
});

// --------------------------------------------------------- hostile storage
it("still switches when storage refuses the write", async () => {
  const { setTheme, getThemeSnapshot } = await load();
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("site data blocked");
  });
  setTheme("dark");
  // Forgotten on reload, but refusing to switch at all would be worse.
  expect(getThemeSnapshot()).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
});

it("ignores a stored value that is not a theme", async () => {
  window.localStorage.setItem("astra.theme", "aubergine");
  const { getThemeSnapshot } = await load();
  expect(getThemeSnapshot()).toBe("light");
});

// ------------------------------------------------------------- the flash
it("sets the attribute before paint without throwing on blocked storage", async () => {
  const { THEME_BOOTSTRAP } = await load();
  window.localStorage.setItem("astra.theme", "dark");
  new Function(THEME_BOOTSTRAP)();
  expect(document.documentElement.dataset.theme).toBe("dark");

  // Same script, storage throwing: it runs render-blocking in <head>, so an
  // exception here would leave the whole document unstyled.
  delete document.documentElement.dataset.theme;
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(() => new Function(THEME_BOOTSTRAP)()).not.toThrow();
});

// ------------------------------------------------------------ the stylesheet
// Resolved from the working directory: under jsdom `import.meta.url` is
// not a file URL, and vitest runs from the web package root.
const CSS = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

/** Every `--token: value;` declared inside one rule body. */
function tokens(body: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [, name, value] of body.matchAll(/(--[\w-]+|color-scheme)\s*:\s*([^;]+);/g)) {
    out[name] = value.trim();
  }
  return out;
}

function ruleBody(selector: string): string {
  const at = CSS.indexOf(selector);
  expect(at, `${selector} is missing from globals.css`).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

it("keeps the two dark blocks identical", () => {
  // They exist twice because a media query and an attribute selector cannot
  // be combined. Nothing but this test stops them drifting.
  const bySystem = tokens(ruleBody(':root:not([data-theme="light"])'));
  const byChoice = tokens(ruleBody(':root[data-theme="dark"]'));
  expect(Object.keys(bySystem).length).toBeGreaterThan(10);
  expect(byChoice).toEqual(bySystem);
});

it("redefines every surface token the light theme declares", () => {
  const light = tokens(ruleBody(":root {"));
  const dark = tokens(ruleBody(':root[data-theme="dark"]'));
  // Fonts and the globe plate are deliberately shared; everything that
  // describes the page surface has to be answered for, or a dark page keeps
  // a light rule or an unreadable signal colour somewhere.
  const surfaces = Object.keys(light).filter(
    (name) =>
      /^--(paper|ink|rule|slab|signal|watch|nominal)/.test(name) && !name.startsWith("--plate")
  );
  expect(surfaces.length).toBeGreaterThan(8);
  for (const name of surfaces) expect(dark, name).toHaveProperty(name);
});

it("declares a colour scheme in both themes", () => {
  // Without it the browser keeps light scrollbars and form controls on a
  // dark page, and flashes white between navigations.
  expect(tokens(ruleBody(":root {"))["color-scheme"]).toBe("light");
  expect(tokens(ruleBody(':root[data-theme="dark"]'))["color-scheme"]).toBe("dark");
});

it("lets every page except the console scroll", () => {
  // The clip used to be the default with the documentation carved out, which
  // silently cut the bottom off the sign-in page.
  expect(CSS).toMatch(/body\s*\{[^}]*overflow:\s*auto/);
  expect(CSS).toMatch(/body:has\(\.shell\)\s*\{\s*overflow:\s*hidden/);
});
