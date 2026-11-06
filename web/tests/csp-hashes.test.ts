import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import {
  MAX_LINE,
  addInlineScriptHashes,
  inlineScripts,
  routeFor
} from "../scripts/csp-hashes.mjs";

/**
 * The build step that lets the CSP drop 'unsafe-inline'.
 *
 * Its failure modes are silent in report-only mode and fatal once enforced:
 * a wrong hash blocks a page's scripts, a page with no rule falls back to the
 * general policy and blocks them too, and two policies on one response are
 * both enforced. So each is pinned here, against the real _headers file.
 */

const HEADERS = readFileSync(resolve(__dirname, "../public/_headers"), "utf8");
const page = (scripts: string[]) =>
  `<html><head><script src="/_next/a.js" async=""></script>${scripts
    .map((body) => `<script>${body}</script>`)
    .join("")}</head></html>`;
const hash = (text: string) =>
  `'sha256-${createHash("sha256").update(text).digest("base64")}'`;

it("finds inline scripts and skips external ones", () => {
  expect(inlineScripts(page(["a()", "b()"]))).toEqual(["a()", "b()"]);
  expect(inlineScripts('<script type="application/ld+json">{}</script>')).toEqual([]);
});

it("maps exported files to the paths Pages serves them at", () => {
  expect(routeFor("index.html")).toBe("/");
  expect(routeFor("docs.html")).toBe("/docs");
  expect(routeFor("404.html")).toBe("/404");
});

it("writes one rule per page that replaces the general policy", () => {
  const out = addInlineScriptHashes(
    HEADERS,
    new Map([
      ["/", page(["home()"])],
      ["/docs", page(["docs()"])],
      ["/404", page(["missing()"])]
    ])
  );
  const docsRule = out.slice(out.indexOf("\n/docs\n"));
  // Detached first: Pages joins repeated headers with a comma, and the
  // browser would then enforce both policies.
  expect(docsRule).toMatch(/^\n\/docs\n\s+! Content-Security-Policy-Report-Only\n\s+Content-Security-Policy-Report-Only: /);
  expect(docsRule.split("\n")[3]).toContain(hash("docs()"));
  expect(docsRule.split("\n")[3]).not.toContain(hash("home()"));
  // Unknown paths get 404.html, which is served under the general rule.
  const general = out.split("\n").find((line) => line.includes("Report-Only:"))!;
  expect(general).toContain(hash("missing()"));
  expect(out.split("\n").every((line) => line.length <= MAX_LINE)).toBe(true);
});

it("never needs 'unsafe-inline' for scripts", () => {
  // A hash in script-src makes browsers ignore 'unsafe-inline' anyway, so
  // having both would be misleading as well as pointless.
  const policy = HEADERS.split("\n").find((line) => line.includes("Report-Only:"))!;
  const scriptSrc = policy.split(";").find((part) => part.trim().startsWith("script-src"))!;
  expect(scriptSrc).not.toContain("'unsafe-inline'");
});

it("refuses a line Cloudflare would drop", () => {
  const scripts = Array.from({ length: 40 }, (_, i) => `s${i}()`);
  expect(() => addInlineScriptHashes(HEADERS, new Map([["/", page(scripts)]]))).toThrow(
    /limit/
  );
});
