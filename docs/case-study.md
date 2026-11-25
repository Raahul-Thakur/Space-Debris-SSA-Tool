# Case study: Astra / SSA

*A space-debris conjunction screening platform, built and run by one
engineer, on a $0 stack that can move to a paid one by deploying one file.*

Live: [astra-ssa.pages.dev](https://astra-ssa.pages.dev) ·
Code: [github.com/raahul-thakur/space-debris-ssa-tool](https://github.com/raahul-thakur/space-debris-ssa-tool)

## The product

Thousands of satellites and pieces of debris share low Earth orbit. A
*conjunction* is a close approach between two of them. Operators need to know
which ones matter, early, and why.

Astra pulls the public catalogue (CelesTrak), propagates every object with
SGP4, screens a target against the catalogue, refines each candidate to its
time of closest approach, computes a collision probability (Foster's method in
the encounter plane) and ranks the result into critical / watch / nominal.
The console shows it on a 3D globe with a plain-language explanation of each
event, and a command line (`watch add 20580`, `events list --tier watch`,
`screen 20580 --window 72h`) drives it. Anyone can browse; signing in adds a
personal watch list, screenings, alerts and a live activity feed.

## Architecture

```text
 Browser ──▶ Cloudflare Pages (static Next.js) ──▶ Pages Function: /api/public/*
                                                     │  edge cache, stale-while-revalidate,
                                                     │  allow-listed routes and parameters
                                                     ▼
   signed-in requests (bearer JWT) ─────────────▶ FastAPI on Render ──▶ Supabase Postgres
                                                     │                    (RLS on, migrations
                                                     │                     by Alembic)
                                                     ├─▶ Redis (paid stack): job queue,
                                                     │     shared rate limits, stream slots,
                                                     │     response cache
                                                     └─▶ screening worker (paid stack)
   Supabase Auth (JWKS-verified JWTs) · Dodo Payments (signed webhooks) · GitHub Actions
   (CI, scheduled screening every 6 h, nightly backups)
```

The decisions that shaped it:

* **Split the traffic by who can share an answer.** The orbital picture is
  the same for everyone, so public reads go through an edge cache and most
  never reach the API. Anything tied to an account goes direct, with a token,
  and is never cached. The edge function only forwards an allow-list of
  routes and query parameters, so nobody can fill the cache with variations
  or reach a private route through it.
* **One ontology, three kinds of data.** Reference data (objects, element
  sets) is shared and admin-written. Derived facts (conjunctions, risk) are
  deterministic, so public. Work products (screenings, watch lists, alerts,
  commands, audit) belong to the person who made them. One module
  (`sdebris.tenancy`) expresses these rules; endpoints pass it a column and a
  principal rather than writing their own filters.
* **Designed to run free, built to scale.** The free stack is one 0.1-CPU
  instance with screening on an in-process pool. Everything that would have
  to be shared across processes has a Redis implementation behind the same
  interface, and the paid stack is a ready blueprint (`render.paid.yaml`).

Stack: Python 3.12, FastAPI, SQLAlchemy, Alembic, SGP4/NumPy, Dramatiq,
Next.js 16 (static export), TypeScript, CesiumJS, Cloudflare Pages
Functions, Supabase, Render, Redis, GitHub Actions.

## Performance and load

Method in full: [Load test](load-test.md). In short: a Locust profile shaped
like real users (80 % anonymous browsing, 20 % signed in), a real Postgres
seeded with a synthetic catalogue run through the real pipeline, and the API
held by a Linux cgroup to each Render plan's CPU and memory.

**The first run found three real problems.** At 100 users the free instance
collapsed: throughput fell as load rose, p95 hit 34 s and 8.7 % of requests
failed. The causes:

1. **The database pool** waited 30 s for a connection and then returned a
   500, so overload became a hang. Now sized, bounded at 5 s, and a full
   pool is a fast `503 Retry-After`.
2. **An N+1 query** in the live activity feed: 480 queries per read,
   repeated every 2 s per signed-in user. Batched to 8 queries; 338 ms →
   10 ms. Fixing it also found a correctness bug (a client far behind lost
   the newest items).
3. **Pricing** was read from the API by every visitor; now edge-cached.

**Results, same test, before and after:**

| Configuration | Users | p95 | p99 | Errors |
|---|---:|---:|---:|---:|
| Free, direct, before | 100 | 34 s | — | 8.7 % |
| Free, direct, after | 100 | 5.7 s | 8.5 s | 0.8 % |
| Free, via edge, after | 200 | 590 ms | 1.4 s | 0 % |
| Starter (0.5 CPU) + Redis, via edge | 1,600 | 130 ms | 220 ms | 0 % |
| Standard (1 CPU, 2 processes) + Redis, direct | 400 | 94 ms | 130 ms | 0 % |
| Standard (1 CPU, 2 processes) + Redis, via edge | 1,200 | 120 ms | 170 ms | 0 % |

The free tier's ceiling is its tenth of a CPU, and it now degrades with fast,
retryable errors rather than hangs. The paid stack (about $42 a month) serves
more than six times the users at a tenth of the latency.

**Correct under concurrency, not just fast.** With several API processes and
a separate worker, limits must hold across all of them. Job admission is
serialised by a Postgres advisory lock (three simultaneous submissions from
one account across two processes: exactly one admitted). Rate limits and
live-stream slots are atomic Lua scripts in Redis, with leases so a crashed
process cannot hold slots. If Redis fails, each falls back to the in-process
version within 250 ms: limits loosen to per-process, they never disappear,
and the site stays up.

## Security

Found and fixed in a full audit before launch, then covered by tests:

* **Rate-limit bypass.** Sending *any* `Authorization` header, even a made-up
  one, skipped metering. Metering is now keyed on a verified identity, with
  per-address limits for anonymous callers that read the proxy-appended,
  unspoofable end of `X-Forwarded-For`. Expensive endpoints are budgeted in
  units of work, not requests.
* **Authentication.** Supabase JWTs verified against the JWKS with issuer
  and audience checks. The development-token route is not registered at all
  outside development, and an unset environment means production, so a
  misconfigured deploy fails closed and refuses to start.
* **Authorization.** Tenancy rules in one module; another account's row is
  a 404, not a 403, because confirming an id exists is a disclosure.
  Row-level security is on for every table with no policies, so Supabase's
  auto-generated public data API can read nothing; only the API's own role
  reaches the data.
* **Payments.** Webhooks verified by HMAC signature and timestamp, processed
  idempotently (a unique provider + event id), and only the two known
  product ids can grant Pro. Sales stay closed behind a switch during the
  free beta.
* **Input.** The console's command line is parsed against an allow-list
  grammar and never reaches a shell. Trajectory requests are bounded in
  total samples; the response cache is bounded by entries and bytes.
* **Supply chain.** Python dependencies hash-pinned in a lockfile and
  audited (`pip-audit`) in CI; `npm audit` gates the frontend; GitHub
  Actions pinned by commit SHA; the container runs as a non-root user.
  The production build refused a vulnerable Next.js release, and the upgrade
  shipped the same day.
* **Privacy.** No cookies for analytics; the optional web analytics are
  Cloudflare's cookieless ones. Usage statistics are counts over records the
  service already keeps, with no identifiers leaving the database.

Still open, and said plainly: the Content Security Policy runs in
report-only mode until its reports are clean; error tracking is wired but
optional.

## Engineering practice

* 340+ backend tests and 140+ frontend tests, run in CI on Python 3.10–3.12
  with a real Redis, plus Playwright end-to-end tests and a migration check
  against the models.
* Every fix in this document came with a test that failed before it.
* Nightly database backups (GitHub Actions), a scheduled screening every six
  hours, and a health endpoint that reports whether shared state is
  reachable.
* Documentation for every deployment and operational decision, published
  with MkDocs.

## Real usage

Measured by the product itself, not estimated: an admin-only
`/admin/stats` page reports daily and weekly active accounts, new accounts,
screenings run and their durations, watch lists, waitlist sign-ups and
live per-route latency, all as aggregate counts. Page views come from
Cloudflare Web Analytics (cookieless).

| Since beta launch | Figure |
|---|---:|
| Accounts | *to fill from /admin/stats* |
| Weekly active accounts | |
| Screenings run | |
| Pro waitlist sign-ups | |
| Unique visitors (Cloudflare) | |
| API p95 latency in production | |

## What I would do next

* Open Pro once the payments go-live checklist is complete, and move to the
  paid stack when signed-in concurrency or paying users call for it (the
  criteria are in [Scaling](scaling.md)).
* Replace the 2-second polling behind live feeds with Postgres
  `LISTEN/NOTIFY`, the next limit past a few hundred concurrent signed-in
  users.
* Enforce the Content Security Policy.
