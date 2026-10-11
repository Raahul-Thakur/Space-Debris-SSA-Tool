import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The caching front door, pinned.
 *
 * Two different kinds of failure live in this file. The first is a capacity
 * failure: if the proxy stops caching, every visitor reaches the API again
 * and the site returns to roughly thirty page loads a minute in total.
 *
 * The second is worse. This route runs with no bearer token and its answers
 * are stored in a cache that every visitor shares. A path that reaches it
 * without being on the allow-list is both an authorisation bypass and a way
 * to serve one account's rows to the next person who asks. `/monitoring` is
 * the live example: it looks like a public read, it is reachable without
 * signing in, and it returns the caller's own watched objects in addition to
 * the platform's. It must never be proxied.
 */

const fetchMock = vi.fn();

async function load(env: Record<string, string> = {}) {
  vi.resetModules();
  process.env.NEXT_PUBLIC_SDEBRIS_API_URL = "https://api.example.test";
  for (const [key, value] of Object.entries(env)) process.env[key] = value;
  return import("@/app/api/public/[...path]/route");
}

type Handler = (
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) => Promise<Response>;

function call(route: { GET: Handler }, path: string, query = ""): Promise<Response> {
  return route.GET(
    new Request(`https://site.test/api/public/${path}${query}`),
    { params: Promise.resolve({ path: path.split("/") }) }
  );
}

function upstreamOk(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

beforeEach(() => {
  // A fresh Response per call: a body can only be read once, so handing
  // the same object back twice would fail inside the route rather than
  // testing it.
  fetchMock.mockReset().mockImplementation(async () => upstreamOk([{ norad_id: "25544" }]));
  vi.stubGlobal("fetch", fetchMock);
  delete process.env.SDEBRIS_PROXY_TOKEN;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ----------------------------------------------------------- the boundary
it("refuses a path that is scoped to an account", async () => {
  const route = await load();
  for (const path of ["monitoring", "billing/me", "screening-jobs", "cases", "activity"]) {
    const response = await call(route, path);
    expect(response.status, path).toBe(404);
  }
  // Not merely refused at the end: never asked for in the first place.
  expect(fetchMock).not.toHaveBeenCalled();
});

it("refuses a write however it is dressed up", async () => {
  const route = await load();
  // Only GET is exported, so anything else is a 405 from the framework; this
  // pins that no write path was added to the allow-list by accident.
  expect(route).not.toHaveProperty("POST");
  expect(route).not.toHaveProperty("DELETE");
});

it("cannot be walked out of its own prefix", async () => {
  const route = await load();
  for (const path of ["objects/../billing/me", "objects/25544/../../cases"]) {
    expect((await call(route, path)).status).toBe(404);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

it("passes an allow-listed read upstream", async () => {
  const route = await load();
  const response = await call(route, "events/assessed");
  expect(response.status).toBe(200);
  expect(fetchMock.mock.calls[0][0]).toBe("https://api.example.test/events/assessed");
});

// -------------------------------------------------------------- the cache
it("asks the framework to hold the answer", async () => {
  const route = await load();
  await call(route, "objects");
  expect(fetchMock.mock.calls[0][1].next).toEqual({ revalidate: 300 });
});

it("holds the ontology far longer than the picture", async () => {
  const route = await load();
  await call(route, "ontology");
  expect(fetchMock.mock.calls[0][1].next).toEqual({ revalidate: 3600 });
});

it("tells the edge it may share the answer", async () => {
  const route = await load();
  const directive = (await call(route, "objects")).headers.get("cache-control");
  expect(directive).toContain("s-maxage=300");
  expect(directive).toContain("stale-while-revalidate");
});

// ------------------------------------------------------------ the cache key
it("drops parameters it does not recognise", async () => {
  const route = await load();
  await call(route, "objects", "?limit=5&cachebuster=12345");
  // Otherwise one visitor could fill the cache with variants of one question
  // and evict every real entry.
  expect(fetchMock.mock.calls[0][0]).toBe("https://api.example.test/objects?limit=5");
});

it("treats the same question asked in a different order as one question", async () => {
  const route = await load();
  await call(route, "trajectories", "?norad_ids=25544&step_sec=180");
  await call(route, "trajectories", "?step_sec=180&norad_ids=25544");
  expect(fetchMock.mock.calls[0][0]).toBe(fetchMock.mock.calls[1][0]);
});

it("will not forward an absurdly long value", async () => {
  const route = await load();
  await call(route, "objects", `?limit=${"9".repeat(600)}`);
  expect(fetchMock.mock.calls[0][0]).toBe("https://api.example.test/objects");
});

// ------------------------------------------------------------- the secret
it("identifies itself to the API when a secret is configured", async () => {
  const route = await load({ SDEBRIS_PROXY_TOKEN: "shared" });
  await call(route, "objects");
  expect(fetchMock.mock.calls[0][1].headers["x-sdebris-proxy"]).toBe("shared");
});

it("sends no such header when none is configured", async () => {
  const route = await load();
  await call(route, "objects");
  expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty("x-sdebris-proxy");
});

it("never forwards an authorization header", async () => {
  const route = await load({ SDEBRIS_PROXY_TOKEN: "shared" });
  await call(route, "objects");
  const headers = fetchMock.mock.calls[0][1].headers;
  // A bearer token would vary the answer without varying the cache key,
  // which is precisely how one account's rows would reach another.
  expect(Object.keys(headers).map((k) => k.toLowerCase())).not.toContain("authorization");
});

// ------------------------------------------------------------- the failures
it("does not cache an upstream failure", async () => {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "boom" }), { status: 500 })
  );
  const route = await load();
  const response = await call(route, "objects");
  // A cached 500 outlives the fault that caused it and keeps the site broken
  // after the API has recovered.
  expect(response.status).toBe(500);
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it("says the API is waking rather than that there is nothing to show", async () => {
  fetchMock.mockRejectedValueOnce(new Error("ECONNREFUSED"));
  const route = await load();
  const response = await call(route, "objects");
  expect(response.status).toBe(503);
  expect((await response.json()).detail).toMatch(/waking up/i);
  expect(response.headers.get("cache-control")).toBe("no-store");
});

it("passes a 404 through as a 404", async () => {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify({ detail: "object not found" }), { status: 404 })
  );
  const route = await load();
  expect((await call(route, "objects/00000")).status).toBe(404);
});
