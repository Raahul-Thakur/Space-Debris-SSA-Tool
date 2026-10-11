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
3. Confirm the project signs tokens **asymmetrically**. Under
   *Authentication -> JWT Keys*, the active key must be ES256 or RS256. The API
   verifies tokens through the JWKS endpoint and accepts only those two
   algorithms, so a project still on the legacy shared HS256 secret publishes an
   empty key set and every signed-in request fails with `401`. Migrating to a
   signing key is done from that page and needs no code change.
4. Copy the transaction-pooler connection string. Change its scheme to
   `postgresql+psycopg://` and store it as `SDEBRIS_DATABASE_URL` on Render.
   The pooler runs on port 6543 and is reachable over IPv4; the direct
   connection on 5432 is IPv6-only on the free tier and will not resolve from
   many networks.
5. Set these Render variables using the project URL:

   ```text
   SDEBRIS_AUTH_JWKS_URL=https://PROJECT.supabase.co/auth/v1/.well-known/jwks.json
   SDEBRIS_AUTH_ISSUER=https://PROJECT.supabase.co/auth/v1
   SDEBRIS_AUTH_AUDIENCE=authenticated
   ```

### Pushing the schema

Render applies migrations on every deploy, so a deployed stack needs nothing
further. To build the schema by hand — before the first deploy, or to run a
local API against the hosted database — put the pooler URL in `.env` at the
repository root and run:

```bash
alembic upgrade head
```

`.env` is read by the API, the CLI and Alembic alike, and never overrides a
variable already set in the real environment.

### Why the tables are closed to PostgREST

Supabase publishes every table in the `public` schema through PostgREST, and the
anon key that authorises those requests is compiled into the browser bundle.
This platform never reads its data that way: the frontend holds a Supabase JWT
only in order to call the API, which connects to Postgres as the owning role and
applies its own role and quota checks.

That leaves PostgREST as pure attack surface. Without intervention, anyone with
the public anon key could read `entitlements` straight out of the database —
customer emails and plan status — and write to it. Migration
`8f2d4e1a6b07_restrict_postgrest_exposure` closes it with two independent locks:
privileges are revoked from `anon` and `authenticated`, including the default
privileges that would otherwise be inherited by tables added later, and row
level security is enabled on every table with no policy attached. An empty
policy set denies every row to every non-owning role, so a privilege granted
back by mistake still yields nothing.

There are deliberately no per-user policies. Nothing ever connects as an end
user, so a policy written against `auth.uid()` would gate a code path that does
not exist, while reading as though the data were protected by it.

Confirm the lock after migrating, from the SQL editor:

```sql
set role anon;
select * from entitlements;   -- expected: permission denied for table entitlements
reset role;
select tablename from pg_tables
where schemaname = 'public' and not rowsecurity;   -- expected: no rows
```

Supabase is not optional in production. The API refuses to start without
`SDEBRIS_AUTH_JWKS_URL` when `SDEBRIS_ENV=production`, and the local
development-token endpoint returns `404` outside development, so a deployment
without a JWKS issuer has no way for anyone to sign in.

### Roles are assigned automatically

Roles are not set by hand. Migration `b7e3c05d19af` installs a Supabase custom
access token hook, `public.custom_access_token_hook`, which stamps
`app_metadata.role` into every JWT as it is minted. The mapping lives in the
`role_grants` table, keyed by email: an exact match wins, and the `*` row
supplies the default for everyone else.

Enable it once, in the dashboard: **Authentication -> Hooks -> Customize Access
Token (JWT) Claims**, selecting `custom_access_token_hook`. Until that is done
the function exists but nothing calls it, and every account falls back to
`viewer` — the API treats a missing or unrecognised role as `viewer`, so an
unconfigured hook fails safe rather than open.

Granting someone `operator`, which is a job function rather than something
bought, is one row:

```sql
insert into role_grants (email, role, note)
values ('person@example.com', 'operator', 'Runs case workflow');
```

Raising the default once the ontology is per-tenant is one update:

```sql
update role_grants set role = 'analyst' where email = '*';
```

Neither needs a migration or a redeploy; both take effect at the person's next
sign-in, because a JWT keeps whatever claims it was issued with until it
expires. The same applies to a revocation — plan changes are read live from the
database on every request, but a *role* change requires a new token, which is
one reason billing is deliberately not expressed as a role.

The hook overwrites `app_metadata.role` rather than merging it, so a value a
client managed to get into its own metadata cannot survive into a verified
token.

### What an anonymous visitor can see

The public picture is deliberately real: the tracked catalogue, element sets,
propagated trajectories, conjunction events and their plain-language
explanations are all readable without an account, so the dashboard means
something before anyone signs up. Operational state is not: monitoring cases,
the activity feed, billing and every write require a token.

Anonymous traffic is metered by client address instead of by principal, since
there is no identity to meter. Reads get a generous per-minute budget;
trajectory propagation, which runs SGP4 over a grid of up to 8640 points, gets
a much tighter one. Behind a proxy the address is taken from the rightmost
`X-Forwarded-For` hop, which the caller cannot forge.

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
SDEBRIS_PROXY_TOKEN=SHARED_WITH_RENDER
```

`SDEBRIS_PROXY_TOKEN` is deliberately not a `NEXT_PUBLIC_` value: it is read
by the caching route handler on the server, and shipping it to the browser
would let anyone spend the rate-limit exemption it buys. Set the same value
on Render. See [capacity.md](capacity.md).

`NEXT_PUBLIC_*` values are inlined at build time, so changing one requires a
redeploy rather than only an environment-variable edit.

The build script copies Cesium's runtime assets into `public/cesium` (about
23 MB, git-ignored and regenerated on every build), so no extra configuration is
needed for the globe.

The Supabase anon/publishable key is designed for browser use. The service-role
key is privileged and must never be added to Vercel or exposed as `NEXT_PUBLIC_*`.

## 4. Billing (Dodo Payments)

Dodo Payments is a merchant of record: it is the legal seller, collects in USD
worldwide, handles VAT/GST/sales tax, and remits to an Indian bank account.
That is what makes it workable where Stripe is not.

Create a product for the Pro plan, then point its webhook at:

```text
https://YOUR_API.onrender.com/billing/webhook
```

Copy the signing secret into Render as `SDEBRIS_BILLING_WEBHOOK_SECRET`. Until
that variable is set the endpoint returns `503` for every delivery — it never
falls back to trusting unsigned input.

Deliveries are verified against the [Standard Webhooks](https://www.standardwebhooks.com)
scheme: `webhook-id`, `webhook-timestamp` and `webhook-signature` headers over
an HMAC-SHA256 of `{id}.{timestamp}.{body}`, with a five-minute replay window.
**Check the header and event names against Dodo's current documentation before
going live** — the signature algorithm is a published standard and stable, but
event naming is the part most likely to have changed. The names this build
recognises are in `GRANTING_EVENTS` and `REVOKING_EVENTS` in
`src/sdebris/billing/webhooks.py`; adding one is a dictionary entry.

Grants are keyed on the buyer's email, because that is all a merchant of record
knows at checkout. The auth subject is attached on their first signed-in
request, so buying and signing up can happen in either order. Every delivery is
recorded in `billing_events` and is idempotent on the provider's event id, so a
retry renews a grant rather than stacking a second one.

To comp an account without a payment, insert a row in `entitlements` with
`plan='pro'`, `status='active'`, the person's email, and a null `expires_at`
for lifetime access.

## 5. Backups

Supabase Free does not provide point-in-time recovery. Run a logical backup
before migrations and periodically from a trusted computer with `pg_dump`:

```powershell
.\scripts\backup_database.ps1 -DatabaseUrl $env:SDEBRIS_DATABASE_URL
```

Backup files are ignored by Git. Store encrypted copies in a private location.
Test recovery periodically with `pg_restore` into a disposable database.

## 6. Public-launch checklist

- Confirm `/health`, `/ready`, and `/methodology` return successfully.
- Confirm an anonymous mutation returns `401`.
- Confirm a viewer cannot start screening and receives `403`.
- Confirm an analyst can enqueue a screening and receives progress events.
- Confirm `/billing/webhook` returns `400` for an unsigned delivery.
- Confirm a free account is refused a window over 24 hours with `402`.
- Confirm the live activity stream connects: the console header should read
  `STREAM LIVE` rather than `STREAM OFFLINE`.
- Restrict Supabase redirects and API CORS to the deployed domains.
- Enable repository branch protection and required CI checks.
- Add issue templates for bug reports and scientific-method feedback.
- Put the non-operational limitation in the repository description and launch post.
- Enable the GitHub and Google providers in Supabase, and check each button
  completes a round trip rather than returning "Unsupported provider".
- Configure custom SMTP and raise the email rate limit. Until this is done the
  project can send about two messages an hour and public sign-up by email does
  not work; OAuth is unaffected.
- Confirm the email template contains `{{ .Token }}`, or no code is sent.
- Set `SDEBRIS_PROXY_TOKEN` to the same value on Render and Vercel.
- Set the `SDEBRIS_API_URL` repository variable so the keep-warm workflow runs.
- Confirm `/api/public/monitoring` returns 404 and `/api/public/events/assessed`
  returns 200: the first is the cache's authorisation boundary.

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
- **Instance hours are the binding constraint, not traffic.** The console holds a
  Server-Sent Events connection open for the activity feed, so the instance does
  not idle while anyone has the page open, and the keep-warm workflow pings it
  deliberately for eighteen hours a day. Both spend from the same 750-hour monthly
  allowance, which is shared across every free service on the account. Public
  reads no longer contribute, because they are served from the edge without
  reaching the instance at all.
- **Supabase free projects pause after a period of inactivity** and need to be
  resumed from the dashboard, which matters for a portfolio link that is visited
  irregularly.

If the cold starts and pauses become a problem, the component to move first is
the API: an always-on host (for example an Oracle Cloud Always Free VM) removes
both, and the frontend and database can stay where they are.
