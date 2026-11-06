import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FETCHED_AT, onRequest, onRequestGet } from "../functions/api/public/[[path]]";

/**
 * The public proxy as it runs on Cloudflare Pages.
 *
 * What may be proxied is pinned in public-proxy.test.ts against the shared
 * module. What these pin is the edge cache that stands in for the one
 * Vercel provided: a fresh copy is served without touching the API, and a
 * stale one is still served at once while the API, which sleeps on its free
 * tier, is woken in the background.
 */

class MemoryCache {
  store = new Map<string, Response>();
  async match(request: Request) {
    const hit = this.store.get(request.url);
    return hit ? hit.clone() : undefined;
  }
  async put(request: Request, response: Response) {
    this.store.set(request.url, response.clone());
  }
}

const fetchMock = vi.fn();
let cache: MemoryCache;
let pending: Promise<unknown>[];

function context(path: string, query = "", env = { SDEBRIS_API_URL: "https://api.example.test" }) {
  return {
    request: new Request(`https://astra.test/api/public/${path}${query}`),
    env: { ...env, SDEBRIS_PROXY_TOKEN: "edge-secret" },
    params: { path: path.split("/") },
    waitUntil: (promise: Promise<unknown>) => pending.push(promise)
  };
}

beforeEach(() => {
  cache = new MemoryCache();
  pending = [];
  vi.stubGlobal("caches", { default: cache });
  fetchMock.mockReset().mockImplementation(async () =>
    new Response(JSON.stringify([{ norad_id: "25544" }]), { status: 200 })
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("fetches once, then answers from the edge", async () => {
  const first = await onRequestGet(context("objects"));
  const second = await onRequestGet(context("objects"));
  expect(first.headers.get("x-astra-cache")).toBe("MISS");
  expect(second.headers.get("x-astra-cache")).toBe("HIT");
  expect(await second.json()).toEqual([{ norad_id: "25544" }]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("identifies itself to the API with the shared secret", async () => {
  await onRequestGet(context("objects"));
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("https://api.example.test/objects");
  expect((init.headers as Record<string, string>)["x-sdebris-proxy"]).toBe("edge-secret");
});

it("serves a stale copy at once and refreshes behind the visitor", async () => {
  await onRequestGet(context("objects"));
  // Six minutes on: past the five-minute freshness window for objects.
  const stored = cache.store.get("https://astra.test/api/public/objects")!;
  const aged = new Response(await stored.clone().text(), { headers: stored.headers });
  aged.headers.set(FETCHED_AT, String(Date.now() - 6 * 60 * 1000));
  cache.store.set("https://astra.test/api/public/objects", aged);

  const response = await onRequestGet(context("objects"));
  expect(response.headers.get("x-astra-cache")).toBe("STALE");
  expect(pending).toHaveLength(1);
  await Promise.all(pending);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect((await onRequestGet(context("objects"))).headers.get("x-astra-cache")).toBe("HIT");
});

it("keeps the stale copy when the API is still asleep", async () => {
  await onRequestGet(context("objects"));
  const stored = cache.store.get("https://astra.test/api/public/objects")!;
  const aged = new Response(await stored.clone().text(), { headers: stored.headers });
  aged.headers.set(FETCHED_AT, String(Date.now() - 6 * 60 * 1000));
  cache.store.set("https://astra.test/api/public/objects", aged);
  fetchMock.mockRejectedValue(new Error("connection refused"));

  const response = await onRequestGet(context("objects"));
  await Promise.all(pending);
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual([{ norad_id: "25544" }]);
});

it("never caches a failure", async () => {
  fetchMock.mockImplementation(async () => new Response("{}", { status: 500 }));
  const response = await onRequestGet(context("objects"));
  expect(response.status).toBe(500);
  expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(cache.store.size).toBe(0);
});

it("shares one entry for the same question asked differently", async () => {
  await onRequestGet(context("trajectories", "?window_hours=3&norad_ids=25544&junk=1"));
  await onRequestGet(context("trajectories", "?norad_ids=25544&window_hours=3"));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect([...cache.store.keys()]).toEqual([
    "https://astra.test/api/public/trajectories?norad_ids=25544&window_hours=3"
  ]);
});

it("refuses a path that is scoped to an account, and caches nothing", async () => {
  const response = await onRequestGet(context("monitoring"));
  expect(response.status).toBe(404);
  expect(fetchMock).not.toHaveBeenCalled();
  expect(cache.store.size).toBe(0);
});

it("refuses anything but a read", async () => {
  expect((await onRequest()).status).toBe(405);
});

it("says so when the API address is not configured", async () => {
  const response = await onRequestGet(context("objects", "", { SDEBRIS_API_URL: "" }));
  expect(response.status).toBe(503);
  expect(fetchMock).not.toHaveBeenCalled();
});
