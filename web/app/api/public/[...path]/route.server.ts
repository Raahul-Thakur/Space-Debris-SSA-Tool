/**
 * The public proxy when the site runs as a Next.js server: `next dev`, and a
 * Next server deployment such as Vercel.
 *
 * Production on Cloudflare Pages is a static export, which cannot contain a
 * route handler, so the same proxy runs there as a Pages Function
 * (functions/api/public/[[path]].ts). The `.server.ts` extension is what
 * keeps this file out of that export: next.config.mjs only treats it as a
 * route when the build is not a static one.
 *
 * The `next.revalidate` option stores each upstream answer in the
 * framework's data cache, shared across invocations, so the API sees at most
 * one request per path per interval however many people are reading.
 */

import { proxyPublicRead } from "@/lib/publicProxy";

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> }
) {
  const { path } = await context.params;
  return proxyPublicRead({
    path: (path ?? []).join("/"),
    requestUrl: request.url,
    upstream: process.env.NEXT_PUBLIC_SDEBRIS_API_URL ?? "http://127.0.0.1:8000",
    token: process.env.SDEBRIS_PROXY_TOKEN,
    // Caching is opt-in; without this the data cache is bypassed and every
    // visitor reaches the API again, which is the whole problem.
    fetcher: (url, init, route) =>
      fetch(url, { ...init, next: { revalidate: route.revalidate } } as RequestInit)
  });
}
