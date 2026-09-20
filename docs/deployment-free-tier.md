# Free-tier public deployment

This deployment is intended for portfolio demonstration and community feedback,
not operational spaceflight decisions. The services below can be configured with
no paid resources, subject to each provider's current quotas and acceptable-use
policies.

## Architecture

Three services, all on free plans:

- **Vercel Hobby** serves the Next.js frontend and managed HTTPS. Both routes
  prerender as static files, so no serverless functions are involved.
- **Render Free Web Service** runs the Docker image containing FastAPI. Screening
  executes in the API process, so there is no separate worker and no Redis.
  Render free services sleep after inactivity, so first requests may be slow.
- **Supabase Free** provides PostgreSQL *and* passwordless authentication in one
  project.

**GitHub Actions** tests Python, the frontend, browser behavior, migrations,
dependencies, and the container on every pull request.

No service key belongs in source control. Copy `.env.example` locally and enter
secrets only in the hosting providers' encrypted environment-variable settings.

## 1. Supabase

1. Create a free project and enable email magic-link authentication.
2. Add the Vercel production URL and preview URLs to Auth redirect URLs.
3. Copy the transaction-pooler connection string. Change its scheme to
   `postgresql+psycopg://` and store it as `SDEBRIS_DATABASE_URL` on Render.
4. Set these Render variables using the project URL:

   ```text
   SDEBRIS_AUTH_JWKS_URL=https://PROJECT.supabase.co/auth/v1/.well-known/jwks.json
   SDEBRIS_AUTH_ISSUER=https://PROJECT.supabase.co/auth/v1
   SDEBRIS_AUTH_AUDIENCE=authenticated
   ```

Supabase is not optional in production. The API refuses to start without
`SDEBRIS_AUTH_JWKS_URL` when `SDEBRIS_ENV=production`, and the local
development-token endpoint returns `404` outside development, so a deployment
without a JWKS issuer has no way for anyone to sign in.

New authenticated users default to the read-only `viewer` role. Promote trusted
accounts by setting `app_metadata.role` to `analyst`, `operator`, or `admin` from
a trusted administrative environment. Never let a browser write app metadata.
Users must sign in again after a role change to receive a refreshed JWT.

## 2. Render API

Create a Blueprint from `render.yaml`. Enter every variable marked `sync: false`.
Set:

```text
SDEBRIS_CORS_ORIGINS=https://YOUR_VERCEL_DOMAIN
```

Vercel gives each preview deployment its own hostname, which cannot be listed in
advance. To let previews reach the API, also set a pattern that matches only your
own preview domains:

```text
SDEBRIS_CORS_ORIGIN_REGEX=https://YOUR_PROJECT-[a-z0-9-]+\.vercel\.app
```

Leave it unset to refuse previews. The pattern is matched against the whole
origin, so it cannot be widened accidentally by a suffix such as
`https://YOUR_PROJECT.attacker.example`. An invalid pattern fails at startup
rather than silently blocking every request.

The container applies migrations and then binds FastAPI to Render's `$PORT`.
`/health` is a process liveness check; `/ready` also verifies database
connectivity. Render terminates public TLS.

Free Render services sleep after inactivity and provide an ephemeral filesystem.
All durable application state therefore belongs in Supabase. Cached TLE files may
disappear safely and will be refreshed.

### Job execution on the free plan

`render.yaml` sets `SDEBRIS_JOB_BACKEND=thread`. Screening runs on a thread pool
inside the API process, which suits a single free instance and removes the need
for a Redis broker. The trade-off is durability: a job in flight is lost if the
instance restarts or sleeps. Screening runs are short, so in practice this means
re-running the command.

For a durable queue, set `SDEBRIS_JOB_BACKEND=redis` and supply
`SDEBRIS_REDIS_URL` (Upstash offers a free Redis database). The container then
also starts one Dramatiq worker. With the thread backend it starts no worker at
all.

## 3. Vercel frontend

Import the repository, set the root directory to `web`, and configure:

```text
NEXT_PUBLIC_SDEBRIS_API_URL=https://YOUR_API.onrender.com
NEXT_PUBLIC_SUPABASE_URL=https://PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_PUBLISHABLE_ANON_KEY
```

`NEXT_PUBLIC_*` values are inlined at build time, so changing one requires a
redeploy rather than only an environment-variable edit.

The build script copies Cesium's runtime assets into `public/cesium` (about
23 MB, git-ignored and regenerated on every build), so no extra configuration is
needed for the globe.

The Supabase anon/publishable key is designed for browser use. The service-role
key is privileged and must never be added to Vercel or exposed as `NEXT_PUBLIC_*`.

## 4. Backups

Supabase Free does not provide point-in-time recovery. Run a logical backup
before migrations and periodically from a trusted computer with `pg_dump`:

```powershell
.\scripts\backup_database.ps1 -DatabaseUrl $env:SDEBRIS_DATABASE_URL
```

Backup files are ignored by Git. Store encrypted copies in a private location.
Test recovery periodically with `pg_restore` into a disposable database.

## 5. Public-launch checklist

- Confirm `/health`, `/ready`, and `/methodology` return successfully.
- Confirm an anonymous mutation returns `401`.
- Confirm a viewer cannot start screening and receives `403`.
- Confirm an analyst can enqueue a screening and receives progress events.
- Confirm the live activity stream connects: the console header should read
  `STREAM LIVE` rather than `STREAM OFFLINE`.
- Restrict Supabase redirects and API CORS to the deployed domains.
- Enable repository branch protection and required CI checks.
- Add issue templates for bug reports and scientific-method feedback.
- Put the non-operational limitation in the repository description and launch post.

## Free-tier limitations

This stack may cold-start, pause after inactivity, and enforce storage, bandwidth,
or build quotas. It is public-deployment-ready for a low-traffic portfolio, not
high availability. Configure spend caps or omit billing details where providers
allow it; exceeding a free quota should suspend service rather than incur charges.

Three consequences are specific to this application:

- **Cold starts are visible.** After the Render service sleeps, the first request
  can take roughly a minute. The console degrades honestly rather than breaking:
  the activity feed reconnects with exponential backoff and its header reports
  `RECONNECTING`, then `OFFLINE` after repeated failures, while continuing to
  retry.
- **An open dashboard keeps the service awake.** The console holds a Server-Sent
  Events connection open for the activity feed, so the instance does not idle
  while anyone has the page open. That keeps the app responsive but consumes free
  instance hours continuously; a single forgotten tab can spend the monthly
  allowance.
- **Supabase free projects pause after a period of inactivity** and need to be
  resumed from the dashboard, which matters for a portfolio link that is visited
  irregularly.

If the cold starts and pauses become a problem, the component to move first is
the API: an always-on host (for example an Oracle Cloud Always Free VM) removes
both, and the frontend and database can stay where they are.
