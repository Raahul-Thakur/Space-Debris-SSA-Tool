/**
 * Cloudflare Web Analytics, switched on only by configuration.
 *
 * When `NEXT_PUBLIC_CF_ANALYTICS_TOKEN` is set at build time the root layout
 * adds Cloudflare's beacon to every page, and the privacy page says so; when
 * it is unset neither happens, so a build without the token loads no
 * third-party script at all. Like every NEXT_PUBLIC_ value it is baked in at
 * build time, so turning it on or off needs a redeploy.
 *
 * The token is not a secret: it identifies the site to Cloudflare and is
 * visible in every page's HTML once enabled.
 */
export const CF_ANALYTICS_TOKEN = (process.env.NEXT_PUBLIC_CF_ANALYTICS_TOKEN ?? "").trim();

export const CF_BEACON_SRC = "https://static.cloudflareinsights.com/beacon.min.js";

export const analyticsEnabled = CF_ANALYTICS_TOKEN.length > 0;

/** The `data-cf-beacon` attribute's value: JSON, as Cloudflare's snippet has it. */
export function beaconConfig(token: string = CF_ANALYTICS_TOKEN): string {
  return JSON.stringify({ token });
}
