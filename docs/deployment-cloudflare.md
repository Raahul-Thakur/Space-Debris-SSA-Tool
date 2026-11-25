# Cloudflare Pages frontend

The website runs on **Cloudflare Pages** as a static export plus one Pages
Function. It replaces Vercel Hobby, whose terms do not allow commercial use;
Cloudflare's free plan does. The API stays on Render and the database and
sign-in on Supabase, as in the [free-tier deployment](deployment-free-tier.md).

## What runs where

| Piece | Where | Source |
|-------|-------|--------|
| Every page (HTML, JS, Cesium assets, icons, preview image) | Cloudflare CDN, as static files | `npm run build:cloudflare` → `web/out/` |
| Security and cache headers | Cloudflare Pages | `web/public/_headers` |
| `/api/public/*`, the cached public-read proxy | Pages Function | `web/functions/api/public/[[path]].ts` |
| What that proxy may forward | Shared with the Next.js route | `web/lib/publicProxy.ts` |

Signed-in requests go from the browser straight to the API with a bearer
token, exactly as before, and are never cached.

The proxy keeps each public answer in Cloudflare's edge cache for ten times
its freshness window. A fresh copy is served without contacting the API; a
stale one is served at once while the API is refreshed in the background, so
visitors still see the orbital picture while the Render instance is waking.

!!! note "Edge cache and `*.pages.dev`"
    Cloudflare documents that the Cache API has no effect on `*.workers.dev`
    hostnames. If the same applies to your `*.pages.dev` address, the proxy
    still works but every read reaches the API, which then relies on its own
    in-memory cache and rate limits. Responses carry an `x-astra-cache`
    header (`MISS`, `HIT`, `STALE`): if a second identical request still says
    `MISS`, add a custom domain to the Pages project to turn the edge cache on.

## Set up the project

1. **Create the project.** Cloudflare dashboard → *Workers & Pages* →
   *Create* → *Pages* → *Connect to Git*, and pick this repository.
2. **Build settings:**

    | Setting | Value |
    |---------|-------|
    | Production branch | `main` |
    | Root directory | `web` |
    | Build command | `npm run build:cloudflare` |
    | Build output directory | `out` |

3. **Build-time variables** (*Settings → Variables and secrets*, type
   *Text*). `NEXT_PUBLIC_*` values are baked into the static files at build
   time, so a change needs a redeploy:

    | Name | Value |
    |------|-------|
    | `NODE_VERSION` | `22` |
    | `NEXT_PUBLIC_SDEBRIS_API_URL` | `https://sdebris-api.onrender.com` |
    | `NEXT_PUBLIC_SUPABASE_URL` | your Supabase project URL |
    | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | your Supabase publishable key |
    | `NEXT_PUBLIC_SITE_URL` | the site's public address, e.g. `https://astra-ssa.pages.dev` |
    | `NEXT_PUBLIC_CF_ANALYTICS_TOKEN` | optional; see [Visitor analytics](#visitor-analytics-optional) |

4. **Runtime variables for the proxy** (same page; these are read by the
   function on each request):

    | Name | Type | Value |
    |------|------|-------|
    | `SDEBRIS_API_URL` | Text | `https://sdebris-api.onrender.com` |
    | `SDEBRIS_PROXY_TOKEN` | **Secret** | the same value as `SDEBRIS_PROXY_TOKEN` on Render |

5. **Deploy**, then open the `*.pages.dev` address.

## Visitor analytics (optional)

The site can count page visits with **Cloudflare Web Analytics**. It is off
unless you turn it on, because it is a third-party script: the beacon loads
from `https://static.cloudflareinsights.com/beacon.min.js` and reports to
`https://cloudflareinsights.com/cdn-cgi/rum`. Cloudflare describes it as
cookie-free and not based on fingerprinting; the privacy page repeats that
description, attributed to Cloudflare, and states what it collects.

The privacy page, the beacon and the CSP all follow one build variable, so
they cannot disagree: without it no script is added and the privacy page
says there is no visitor analytics; with it every page gets the beacon and
the privacy page describes it and lists it among the processors.

To turn it on:

1. Cloudflare dashboard → *Analytics & Logs* → *Web Analytics* → *Add a
   site*, and enter the site's hostname (the `*.pages.dev` address or your
   custom domain). The labels in the dashboard move from time to time; the
   product is called Web Analytics.
2. Choose the manual, JavaScript-snippet setup and copy the `token` value
   out of the snippet it shows (`data-cf-beacon='{"token": "…"}'`). The
   token is not a secret: it ends up in every page's HTML.
3. In the Pages project, *Settings → Variables and secrets*, add
   `NEXT_PUBLIC_CF_ANALYTICS_TOKEN` (type *Text*) with that value, and
   redeploy. Like every `NEXT_PUBLIC_*` value it is read at build time.
4. Check it: `curl -s https://astra-ssa.pages.dev/ | grep cloudflareinsights`
   shows the beacon, and visits appear in the Web Analytics dashboard after a
   few minutes.

To turn it off, delete the variable and redeploy.

!!! warning "Use the token, not the one-click option"
    Pages can also enable Web Analytics from the project itself, in which
    case Cloudflare adds the beacon to pages as it serves them. Prefer the
    token route above. With the one-click option the script is added outside
    the build, so the privacy page (which follows the build variable) would
    still say there is no analytics, and how the injected script interacts
    with the per-page CSP rules written by `scripts/csp-hashes.mjs` has not
    been tested here; if it arrives as an inline script, its hash would be
    missing and an enforced policy would block it.

`web/public/_headers` already allows both origins (`script-src
https://static.cloudflareinsights.com`, `connect-src
https://cloudflareinsights.com`), whether or not the token is set.

The API's own usage figures (active accounts, sign-ups, screenings, latency)
need no setup: an admin opens `/admin` on the site, which reads
`GET /admin/stats`. Its latency figures are per API process, held in memory
and reset when the instance restarts or wakes from sleep.

## Point the other services at the new address

The address changes from `astra-ssa.vercel.app` to your Pages address (or a
custom domain). Three services check it:

- **Render (API):** add the new origin to `SDEBRIS_CORS_ORIGINS`, keeping the
  Vercel one until you retire it, e.g.
  `https://astra-ssa.pages.dev,https://astra-ssa.vercel.app`. Set
  `SDEBRIS_SITE_URL` to the new address so checkout returns there.
- **Supabase (sign-in):** *Authentication → URL Configuration*: set the
  *Site URL* to the new address and add it to *Redirect URLs*.
- **Dodo Payments:** nothing to change; checkout's return address comes from
  `SDEBRIS_SITE_URL`.

Then update the link in your Instagram bio and posts.

## Check it

```bash
# Pages and headers
curl -sI https://astra-ssa.pages.dev/ | grep -iE "x-frame|nosniff"

# The proxy: the second call should say HIT
curl -s -o /dev/null -D - https://astra-ssa.pages.dev/api/public/objects | grep -i x-astra-cache
curl -s -o /dev/null -D - https://astra-ssa.pages.dev/api/public/objects | grep -i x-astra-cache
```

Sign in, run a screening, and open the pricing page to confirm checkout
starts.

## Enforcing the CSP

`web/public/_headers` sets a `Content-Security-Policy-Report-Only` header:
browsers report what the policy would block and block nothing. The build
(`scripts/csp-hashes.mjs`) adds each page's inline-script hashes and writes
one rule per page, so check the result in `out/_headers`, not the source.

1. On the live address, open the browser's developer tools → *Console*, and
   go through the site: the console page (let the globe load, and on a phone
   press *Show 3D globe*), the guided tour, docs, pricing, sign-in with each
   provider, the account page, and checkout as far as the payment page.
   Any line starting `[Report Only]` is something the policy would block.
2. If the API or Supabase address differs from the one in `connect-src`
   (for example a custom API domain), edit `connect-src` to match first.
3. When a full pass shows no `[Report Only]` lines, rename the header in
   `web/public/_headers` from `Content-Security-Policy-Report-Only` to
   `Content-Security-Policy` and redeploy. The build carries the new name
   into every per-page rule. Then repeat step 1 once: a blocked request now
   shows as `Refused to …` instead.

To back out, rename it back and redeploy; nothing else depends on it.

## Run it locally

```bash
cd web
npm run build:cloudflare
npx wrangler pages dev out \
  --binding SDEBRIS_API_URL=http://127.0.0.1:8000 \
  --binding SDEBRIS_PROXY_TOKEN=local
```

`npm run dev` still works as before: under `next dev` the same proxy runs as
the Next.js route in `app/api/public/[...path]/route.server.ts`.

## Retiring Vercel

The repository still builds for Vercel (a normal `next build` includes the
route handler), so the Vercel site keeps working during the switch. Once the
Pages site is live and the services above point at it, delete the Vercel
project, then remove the Vercel origin from `SDEBRIS_CORS_ORIGINS`.
