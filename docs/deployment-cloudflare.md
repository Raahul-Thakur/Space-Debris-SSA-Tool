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

4. **Runtime variables for the proxy** (same page; these are read by the
   function on each request):

    | Name | Type | Value |
    |------|------|-------|
    | `SDEBRIS_API_URL` | Text | `https://sdebris-api.onrender.com` |
    | `SDEBRIS_PROXY_TOKEN` | **Secret** | the same value as `SDEBRIS_PROXY_TOKEN` on Render |

5. **Deploy**, then open the `*.pages.dev` address.

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
