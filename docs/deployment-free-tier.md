# Free-tier public deployment

This deployment is intended for portfolio demonstration and community feedback,
not operational spaceflight decisions. The services below can be configured with
no paid resources, subject to each provider's current quotas and acceptable-use
policies.

## Architecture

- **Vercel Hobby** serves the Next.js frontend and managed HTTPS.
- **Render Free Web Service** runs the Docker image containing FastAPI and one
  Dramatiq worker. It can sleep after inactivity, so first requests may be slow.
- **Supabase Free** provides PostgreSQL and passwordless authentication.
- **Upstash Redis Free** persists queued Dramatiq messages.
- **GitHub Actions** tests Python, the frontend, browser behavior, migrations,
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

New authenticated users default to the read-only `viewer` role. Promote trusted
accounts by setting `app_metadata.role` to `analyst`, `operator`, or `admin` from
a trusted administrative environment. Never let a browser write app metadata.
Users must sign in again after a role change to receive a refreshed JWT.

## 2. Upstash

Create one free Redis database in a region close to Render. Copy its TLS
connection URL (`rediss://...`) into Render as `SDEBRIS_REDIS_URL`.

## 3. Render API and worker

Create a Blueprint from `render.yaml`. Enter every variable marked `sync: false`.
Set:

```text
SDEBRIS_CORS_ORIGINS=https://YOUR_VERCEL_DOMAIN
```

The container applies migrations, starts one Dramatiq worker, and then binds
FastAPI to Render's `$PORT`. `/health` is a process liveness check; `/ready`
also verifies database connectivity. Render terminates public TLS.

Free Render services sleep after inactivity and provide an ephemeral filesystem.
All durable application state therefore belongs in Supabase or Upstash. Cached
TLE files may disappear safely and will be refreshed.

## 4. Vercel frontend

Import the repository, set the root directory to `web`, and configure:

```text
NEXT_PUBLIC_SDEBRIS_API_URL=https://YOUR_API.onrender.com
NEXT_PUBLIC_SUPABASE_URL=https://PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_PUBLISHABLE_ANON_KEY
```

The Supabase anon/publishable key is designed for browser use. The service-role
key is privileged and must never be added to Vercel or exposed as `NEXT_PUBLIC_*`.

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
- Restrict Supabase redirects and API CORS to the deployed domains.
- Enable repository branch protection and required CI checks.
- Add issue templates for bug reports and scientific-method feedback.
- Put the non-operational limitation in the repository description and launch post.

## Free-tier limitations

This stack may cold-start, pause after inactivity, and enforce storage, bandwidth,
or build quotas. It is public-deployment-ready for a low-traffic portfolio, not
high availability. Configure spend caps or omit billing details where providers
allow it; exceeding a free quota should suspend service rather than incur charges.
