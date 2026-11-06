// Give every exported page a Content-Security-Policy that names its own
// inline scripts by hash, so the policy needs no 'unsafe-inline'.
//
// A static export cannot use nonces: there is no server to mint one per
// response. What it can do is hash. Each page carries a handful of inline
// scripts -- the theme bootstrap, Turbopack's chunk list and React's flight
// data -- whose text is fixed at build time, so their SHA-256 hashes are
// known as soon as the export is written. This step reads the policy from
// the `/*` rule in out/_headers (copied from public/_headers), adds the
// hashes for 404.html there (it is what Pages serves for any unknown path),
// and writes one rule per page that detaches the general policy and sets the
// same one with that page's hashes. The `!` detach matters: Pages joins
// repeated headers with a comma, and two comma-joined policies are both
// enforced, so the general one would block the page's scripts.
//
// Run by build-static.mjs after `next build`. Exported for the tests.
import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { pathToFileURL } from "node:url";

/** Cloudflare Pages ignores a _headers line longer than this. */
export const MAX_LINE = 2000;

const POLICY_LINE = /^(\s+)(Content-Security-Policy(?:-Report-Only)?):[ \t]*(.+)$/m;

/** The text of every inline <script> (one without a src) in a page. */
export function inlineScripts(html) {
  const scripts = [];
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    if (/\bsrc\s*=/i.test(match[1])) continue;
    // JSON data blocks are not executed, so the policy does not apply.
    if (/\btype\s*=\s*["']?application\/(ld\+)?json/i.test(match[1])) continue;
    if (match[2].length) scripts.push(match[2]);
  }
  return scripts;
}

export function sha256Source(text) {
  return `'sha256-${createHash("sha256").update(text, "utf8").digest("base64")}'`;
}

/** The policy with these hashes appended to its script-src directive. */
export function withHashes(policy, hashes) {
  const unique = [...new Set(hashes)];
  if (!unique.length) return policy;
  if (!/(^|;)\s*script-src\b/.test(policy)) {
    throw new Error("The Content-Security-Policy has no script-src directive to add hashes to.");
  }
  return policy.replace(/((?:^|;)\s*script-src\b[^;]*)/, (directive) => `${directive} ${unique.join(" ")}`);
}

/** `index.html` -> `/`, `docs.html` -> `/docs`, `a/b.html` -> `/a/b`. */
export function routeFor(file) {
  const path = file.split(sep).join("/").replace(/\.html$/, "");
  if (path === "index") return "/";
  return `/${path.replace(/\/index$/, "")}`;
}

/**
 * Rewrite a _headers file for these pages.
 *
 * `pages` maps each page's route to its HTML. The route "/404" is the
 * not-found page, whose hashes go on the general `/*` rule.
 */
export function addInlineScriptHashes(headers, pages) {
  const found = headers.match(POLICY_LINE);
  if (!found) throw new Error("No Content-Security-Policy line found in _headers.");
  const [line, indent, name, policy] = found;
  const notFound = pages.get("/404");
  const general = withHashes(policy.trim(), notFound ? inlineScripts(notFound).map(sha256Source) : []);
  let out = headers.replace(line, `${indent}${name}: ${general}`);

  const rules = [];
  for (const [route, html] of [...pages].sort(([a], [b]) => a.localeCompare(b))) {
    if (route === "/404") continue;
    const hashes = inlineScripts(html).map(sha256Source);
    rules.push(
      `${route}\n${indent}! ${name}\n${indent}${name}: ${withHashes(policy.trim(), hashes)}\n`
    );
  }
  out = `${out.trimEnd()}\n\n# Per-page policies with inline-script hashes, added by scripts/csp-hashes.mjs.\n${rules.join("\n")}`;

  const long = out.split("\n").find((text) => text.length > MAX_LINE);
  if (long) {
    // Pages would drop the line silently, and with it the page's policy.
    throw new Error(`A _headers line is ${long.length} characters; Cloudflare's limit is ${MAX_LINE}.`);
  }
  return out;
}

async function htmlFiles(dir, root = dir) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "_next" || entry.name === "cesium") continue;
      files.push(...(await htmlFiles(path, root)));
    } else if (entry.name.endsWith(".html")) {
      files.push(relative(root, path));
    }
  }
  return files;
}

export async function hashExport(outDir) {
  const headersPath = join(outDir, "_headers");
  const pages = new Map();
  for (const file of await htmlFiles(outDir)) {
    pages.set(routeFor(file), await readFile(join(outDir, file), "utf8"));
  }
  await writeFile(headersPath, addInlineScriptHashes(await readFile(headersPath, "utf8"), pages));
  return pages.size;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const count = await hashExport(process.argv[2] ?? "out");
  console.log(`csp-hashes: wrote inline-script hashes for ${count} pages to _headers`);
}
