/**
 * A caching front door for the public orbital picture.
 *
 * The console used to call the API directly from the browser, which meant
 * every visitor's page load reached the instance the API runs on: around
 * twenty-three requests, most of them propagations, against a tenth of a CPU.
 * Measured, that allowed about thirty page loads a minute for the whole site.
 * Nothing about those requests was per-visitor -- the rows are platform-owned
 * and the answers identical -- so the work was repeated for no reason.
 *
 * Routing them through here puts two caches in the way. The `next.revalidate`
 * option below stores the upstream response in the framework's data cache,
 * shared across every invocation, so the API sees at most one request per
 * path per interval however many people are reading. The `Cache-Control`
 * header on the way out lets the edge network answer most requests without
 * invoking this function at all.
 *
 * The second cache is why this is worth doing rather than simply caching
 * inside the API: a response served from the edge never touches the instance,
 * so it stays fast while the instance is asleep, and it does not consume the
 * free tier's hours.
 *
 * This proxies reads and nothing else. Anything a signed-in caller does keeps
 * going straight to the API with its bearer token, because those answers
 * differ per account and must never land in a shared cache.
 */

const UPSTREAM =
  process.env.NEXT_PUBLIC_SDEBRIS_API_URL ?? "http://127.0.0.1:8000";

/**
 * Shared secret telling the API this request arrived through the cache.
 *
 * Server-side only, deliberately not `NEXT_PUBLIC_`: it must not reach the
 * browser bundle. The API meters anonymous traffic by address, and behind a
 * proxy every visitor shares one, so without this the second person to open
 * the site would be throttled as though they were the first one again.
 */
const PROXY_TOKEN = process.env.SDEBRIS_PROXY_TOKEN;

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
const ROUTES: { pattern: RegExp; revalidate: number }[] = [
  { pattern: /^ontology$/, revalidate: 3600 },
  { pattern: /^methodology$/, revalidate: 3600 },
  { pattern: /^objects$/, revalidate: 300 },
  { pattern: /^objects\/[\w-]{1,16}$/, revalidate: 300 },
  { pattern: /^objects\/[\w-]{1,16}\/trajectory$/, revalidate: 300 },
  { pattern: /^trajectories$/, revalidate: 300 },
  { pattern: /^events$/, revalidate: 300 },
  { pattern: /^events\/assessed$/, revalidate: 300 },
  { pattern: /^events\/[\w-]{1,64}\/explanation$/, revalidate: 900 },
];

/**
 * Query parameters that may be forwarded.
 *
 * Unrecognised ones are dropped rather than passed on. Each distinct query
 * string is a separate cache entry and a separate upstream request, so
 * forwarding arbitrary parameters would let one visitor fill the cache with
 * variations of the same question and push every real entry out of it.
 */
const PARAMS = [
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
const MAX_PARAM_LENGTH = 512;

function canonicalQuery(url: URL): string {
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

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  const upstreamPath = (path ?? []).join("/");
  const route = ROUTES.find((candidate) => candidate.pattern.test(upstreamPath));

  if (!route) {
    return Response.json(
      { detail: "not a cacheable public route" },
      { status: 404, headers: { "Cache-Control": "no-store" } }
    );
  }

  const target = `${UPSTREAM}/${upstreamPath}${canonicalQuery(new URL(request.url))}`;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      headers: {
        Accept: "application/json",
        ...(PROXY_TOKEN ? { "x-sdebris-proxy": PROXY_TOKEN } : {})
      },
      // Caching is opt-in; without this the data cache is bypassed and every
      // visitor reaches the API again, which is the whole problem.
      next: { revalidate: route.revalidate }
    });
  } catch {
    // The instance sleeps when idle and takes most of a minute to wake. Say
    // so plainly rather than returning an empty picture, which the console
    // would otherwise render as "no objects in the catalogue".
    return Response.json(
      { detail: "the orbital picture is waking up; retrying shortly" },
      { status: 503, headers: { "Cache-Control": "no-store" } }
    );
  }

  const body = await upstream.text();

  if (!upstream.ok) {
    // Never cache a failure. A cached 500 would outlive the fault that
    // caused it and keep the site broken after the API recovered.
    return new Response(body, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store"
      }
    });
  }

  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      // `s-maxage` is read by the edge, `max-age` by the browser. The browser
      // keeps its copy for a shorter time so that someone who has just run a
      // screening sees the result when they reload.
      "Cache-Control":
        `public, max-age=60, s-maxage=${route.revalidate}, ` +
        `stale-while-revalidate=${route.revalidate * 10}`
    }
  });
}
