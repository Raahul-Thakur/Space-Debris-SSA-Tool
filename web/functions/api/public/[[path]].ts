/**
 * The public proxy on Cloudflare Pages, at /api/public/*.
 *
 * The site itself is a static export served from Cloudflare's CDN; this
 * function is the only code that runs per request. What it may proxy, and
 * how, is shared with the Next.js route in lib/publicProxy.ts. What it adds
 * is the edge cache.
 *
 * Cloudflare's Cache API stores a response for as long as its Cache-Control
 * allows, but does not implement stale-while-revalidate. That behaviour is
 * the reason the cache exists: the API sleeps on its free tier and takes
 * most of a minute to wake, and a visitor arriving then should see the last
 * good picture at once. So entries are stored for ten times their freshness
 * window with the time they were fetched, a fresh hit is served as is, and a
 * stale hit is served immediately while a refresh runs in the background.
 *
 * Configure in the Pages project (Settings -> Variables and secrets):
 *   SDEBRIS_API_URL      the API's address, e.g. https://sdebris-api.onrender.com
 *   SDEBRIS_PROXY_TOKEN  the shared secret also set on the API (a secret)
 */

import {
  canonicalQuery,
  findPublicRoute,
  json,
  proxyPublicRead,
  sharedCacheControl,
  type PublicRoute
} from "../../../lib/publicProxy";

type Env = {
  SDEBRIS_API_URL?: string;
  SDEBRIS_PROXY_TOKEN?: string;
};

/** The parts of a Pages Function context this uses. */
type Context = {
  request: Request;
  env: Env;
  params: { path?: string | string[] };
  waitUntil(promise: Promise<unknown>): void;
};

/** Header recording when a cached copy was fetched, in epoch milliseconds. */
export const FETCHED_AT = "x-astra-fetched-at";
/** How many freshness windows a stale copy is kept to cover a sleeping API. */
export const STALE_WINDOWS = 10;

function edgeCache(): Cache | undefined {
  return (globalThis as { caches?: { default?: Cache } }).caches?.default;
}

function toClient(body: BodyInit | null, route: PublicRoute, state: string): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": sharedCacheControl(route),
      "x-astra-cache": state
    }
  });
}

export async function onRequestGet(context: Context): Promise<Response> {
  const raw = context.params.path;
  const path = Array.isArray(raw) ? raw.join("/") : raw ?? "";
  const route = findPublicRoute(path);
  const proxy = () =>
    proxyPublicRead({
      path,
      requestUrl: context.request.url,
      upstream: context.env.SDEBRIS_API_URL,
      token: context.env.SDEBRIS_PROXY_TOKEN
    });

  const cache = edgeCache();
  if (!route || !cache) return proxy();

  const url = new URL(context.request.url);
  // Keyed on the canonical question, so reordered or junk parameters share
  // one entry, and never on anything the visitor sent besides the path.
  const key = new Request(`${url.origin}/api/public/${path}${canonicalQuery(url)}`);

  const refresh = async (): Promise<Response> => {
    const response = await proxy();
    if (response.status !== 200) return response;
    const body = await response.text();
    await cache.put(
      key,
      new Response(body, {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `public, max-age=${route.revalidate * (STALE_WINDOWS + 1)}`,
          [FETCHED_AT]: String(Date.now())
        }
      })
    );
    return toClient(body, route, "MISS");
  };

  const hit = await cache.match(key);
  if (hit) {
    const age = Date.now() - Number(hit.headers.get(FETCHED_AT) ?? 0);
    if (age < route.revalidate * 1000) return toClient(hit.body, route, "HIT");
    // Stale: answer now from the copy, refresh behind the visitor. A failed
    // refresh leaves the copy in place for the next visitor to try again.
    context.waitUntil(refresh().catch(() => undefined));
    return toClient(hit.body, route, "STALE");
  }
  return refresh();
}

/** Reads only. Anything else is refused rather than falling through. */
export async function onRequest(): Promise<Response> {
  return json("this endpoint only serves reads", 405);
}
