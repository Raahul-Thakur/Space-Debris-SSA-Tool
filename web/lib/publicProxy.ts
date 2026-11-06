/**
 * The caching front door for the public orbital picture, independent of host.
 *
 * The console used to call the API directly from the browser, which meant
 * every visitor's page load reached the instance the API runs on: around
 * twenty-three requests, most of them propagations, against a tenth of a CPU.
 * Measured, that allowed about thirty page loads a minute for the whole site.
 * Nothing about those requests was per-visitor -- the rows are platform-owned
 * and the answers identical -- so the work was repeated for no reason.
 *
 * Two hosts run this: a Cloudflare Pages Function in production
 * (functions/api/public/[[path]].ts) and the Next.js route used by
 * `next dev` and by a Next server deployment
 * (app/api/public/[...path]/route.server.ts). Each adds its own cache in
 * front; what is proxied, and how, lives only here.
 *
 * This proxies reads and nothing else. Anything a signed-in caller does keeps
 * going straight to the API with its bearer token, because those answers
 * differ per account and must never land in a shared cache.
 */

export type PublicRoute = { pattern: RegExp; revalidate: number };

/**
 * Exactly which upstream paths may be reached, and how long each may be held.
 *
 * An allow-list rather than a filter. This route runs without a bearer token
 * and its responses go into a cache that everybody shares, so a path reaching
 * it by accident would be both an authorisation hole and a way to serve one
 * account's rows to the next visitor. Every entry below is a read that
 * returns the same bytes to everyone; nothing scoped to a principal is here,
 * and nothing should be added without checking that it takes no principal.
 */
export const ROUTES: PublicRoute[] = [
  { pattern: /^ontology$/, revalidate: 3600 },
  { pattern: /^methodology$/, revalidate: 3600 },
  // The platform's watch list only. Plain `monitoring` stays off this list:
  // it adds the caller's own objects, which must never be shared.
  { pattern: /^monitoring\/platform$/, revalidate: 300 },
  { pattern: /^objects$/, revalidate: 300 },
  { pattern: /^objects\/[\w-]{1,16}$/, revalidate: 300 },
  { pattern: /^objects\/[\w-]{1,16}\/trajectory$/, revalidate: 300 },
  { pattern: /^trajectories$/, revalidate: 300 },
  { pattern: /^events$/, revalidate: 300 },
  { pattern: /^events\/assessed$/, revalidate: 300 },
  { pattern: /^events\/[\w-]{1,64}\/explanation$/, revalidate: 900 }
];

/**
 * Query parameters that may be forwarded.
 *
 * Unrecognised ones are dropped rather than passed on. Each distinct query
 * string is a separate cache entry and a separate upstream request, so
 * forwarding arbitrary parameters would let one visitor fill the cache with
 * variations of the same question and push every real entry out of it.
 */
export const PARAMS = [
  "limit",
  "norad_id",
  "norad_ids",
  "offset",
  "status",
  "step_sec",
  "tier",
  "window_hours"
];

/** Longest query value accepted, sized for a full batch of NORAD ids. */
export const MAX_PARAM_LENGTH = 512;

export function findPublicRoute(path: string): PublicRoute | undefined {
  return ROUTES.find((candidate) => candidate.pattern.test(path));
}

export function canonicalQuery(url: URL): string {
  const params = new URLSearchParams();
  // Sorted, so that the same question asked with its parameters in a
  // different order is one cache entry rather than several.
  for (const name of PARAMS) {
    const value = url.searchParams.get(name);
    if (value !== null && value.length <= MAX_PARAM_LENGTH) {
      params.set(name, value);
    }
  }
  params.sort();
  const query = params.toString();
  return query ? `?${query}` : "";
}

/**
 * What a shared, successful answer tells the browser and any cache in front.
 *
 * `s-maxage` is read by shared caches, `max-age` by the browser. The browser
 * keeps its copy for a shorter time so that someone who has just run a
 * screening sees the result when they reload.
 */
export function sharedCacheControl(route: PublicRoute): string {
  return (
    `public, max-age=60, s-maxage=${route.revalidate}, ` +
    `stale-while-revalidate=${route.revalidate * 10}`
  );
}

export function json(detail: string, status: number): Response {
  return Response.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}

export type UpstreamFetch = (
  url: string,
  init: RequestInit,
  route: PublicRoute
) => Promise<Response>;

export type ProxyOptions = {
  /** The path below /api/public, without a leading slash. */
  path: string;
  /** The URL the visitor requested, for its query string. */
  requestUrl: string;
  /** The API's base URL. */
  upstream: string | undefined;
  /**
   * Shared secret telling the API this request arrived through the cache.
   * Server-side only: it must never reach the browser bundle. The API meters
   * anonymous traffic by address, and behind a proxy every visitor shares
   * one, so without this the second visitor would be throttled.
   */
  token: string | undefined;
  /** How to reach the upstream; each host adds its own caching here. */
  fetcher?: UpstreamFetch;
};

/** Forward one allow-listed public read and shape the answer for sharing. */
export async function proxyPublicRead(options: ProxyOptions): Promise<Response> {
  const route = findPublicRoute(options.path);
  if (!route) return json("not a cacheable public route", 404);
  if (!options.upstream) return json("the public API address is not configured", 503);

  const target =
    `${options.upstream.replace(/\/+$/, "")}/${options.path}` +
    canonicalQuery(new URL(options.requestUrl));
  const fetcher: UpstreamFetch = options.fetcher ?? ((url, init) => fetch(url, init));

  let upstream: Response;
  try {
    upstream = await fetcher(
      target,
      {
        headers: {
          Accept: "application/json",
          ...(options.token ? { "x-sdebris-proxy": options.token } : {})
        }
      },
      route
    );
  } catch {
    // The instance sleeps when idle and takes most of a minute to wake. Say
    // so plainly rather than returning an empty picture, which the console
    // would otherwise render as "no objects in the catalogue".
    return json("the orbital picture is waking up; retrying shortly", 503);
  }

  const body = await upstream.text();

  if (!upstream.ok) {
    // Never cache a failure. A cached 500 would outlive the fault that
    // caused it and keep the site broken after the API recovered.
    return new Response(body, {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
    });
  }

  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": sharedCacheControl(route) }
  });
}
