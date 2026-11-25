# Load test

How much traffic the platform takes before it slows down or fails, what broke
first, and what was changed because of it. The kit to repeat any of this is in
[`loadtest/`](https://github.com/raahul-thakur/space-debris-ssa-tool/tree/main/loadtest).

## Method

* **Traffic shape.** A [Locust](https://locust.io) profile of two kinds of
  user. *Visitors* (80 %) open the console, which makes the same three public
  reads a browser does, then read an event explanation, look at pricing or
  reload, pausing 4–15 s like a person. *Analysts* (20 %) are signed in and
  read their jobs, watch list, account and live activity feed, and run a
  console command, every 5–20 s. Users ramp in at 20 a second and each run
  lasts 90 s.
* **Data.** A real Postgres 16, migrated with the production migrations and
  seeded with a synthetic 300-object low-Earth-orbit catalogue screened by
  the real pipeline: 158 conjunction events, 20 watched objects.
* **Limits.** The API runs inside a Linux cgroup with the CPU and memory of
  the Render plan being tested, so the numbers mean the same as they would
  there. Free is a tenth of a CPU and 512 MB.
* **Edge.** "Through the edge" means the Cloudflare Pages Function and its
  cache, run locally with `wrangler pages dev`, in front of the API, as in
  production.
* **Caveat.** Everything (Postgres, Redis, the edge emulator, the API and
  Locust itself) ran on one 4-core machine. At the top of the paid runs, the
  load generator was competing for the same CPUs, so those runs show a floor
  on capacity, not the ceiling.

Latencies are end to end, in milliseconds. "Fail" counts any non-2xx answer
or a connection error.

## Free tier: the first run

Render free (0.1 CPU, 512 MB), one process, as deployed at the time.

| Users | Path | req/s | p50 | p95 | p99 | Fail |
|---:|---|---:|---:|---:|---:|---:|
| 50 | direct | 8.5 | 1,100 | 3,900 | — | 0 % |
| 100 | direct | 7.6 | 2,100 | 34,000 | — | 8.7 % |
| 200 | direct | 1.2 | 35,000 | 58,000 | — | 74 % |
| 400 | edge | 52.2 | 17 | 88 | 26,000 | 0.2 % |

Two things were visible at once. Through the edge, public pages stayed fast
at 400 users (p95 under 100 ms) because the instance barely saw them. And
everything that had to reach the instance fell over badly, not gracefully:
throughput *dropped* as load rose, and requests hung for 30 s before
failing.

## What broke, and the fixes

1. **The database connection pool.** SQLAlchemy's default pool is 5
   connections plus 10 overflow, and a request waits up to **30 s** for one.
   At 100 users every request queued for a connection, waited the full 30 s
   and then returned a 500. The hang was worse than the error: it held a
   thread the whole time, so the queue grew faster than it drained.
   *Fix:* the pool is sized for the API's thread pool and the wait is
   bounded at 5 s (`SDEBRIS_DB_POOL_SIZE`, `_MAX_OVERFLOW`, `_TIMEOUT`); an
   exhausted pool is now a fast **503 with `Retry-After`**, which clients and
   the edge can act on.
2. **An N+1 query in the live activity feed.** One read of a day's feed was
   **480 queries / 338 ms**: three lookups per conjunction event. Every
   signed-in console repeats that read every 2 s over its live stream, so a
   few signed-in users were enough to saturate a tenth of a CPU. *Fix:*
   batched lookups, **8 queries / 10 ms**. While there, a correctness bug
   turned up: a client more than 200 items behind received the *oldest* 200
   and silently missed the newest. Both are covered by a test.
3. **Pricing was read from the instance by every visitor.** The pricing page
   is the one most likely to be linked from a post. *Fix:* anonymous
   visitors read it through the edge cache, like the console's public reads.

## Free tier, after the fixes

| Users | Path | req/s | p50 | p95 | p99 | Fail |
|---:|---|---:|---:|---:|---:|---:|
| 50 | direct | 8.7 | 18 | 3,900 | 5,900 | 0 % |
| 100 | direct | **16.9** | 330 | **5,700** | 8,500 | **0.8 %** |
| 200 | direct | **18.2** | 5,400 | 14,000 | 18,000 | 6.8 % |
| 100 | edge | 20.1 | 10 | 200 | 3,400 | 0 % |
| 200 | edge | 39.1 | 11 | **590** | **1,400** | **0 %** |
| 400 | edge | 68.6 | 11 | 4,600 | **6,900** | 0.1 % |

At 100 users direct, throughput more than doubled, p95 fell from 34 s to
5.7 s and failures from 8.7 % to 0.8 %. At 200 users the instance now
degrades instead of collapsing: it serves 15× the throughput and the
failures it does return are fast 503s, not 30-second hangs. Behind the edge,
200 users see no errors and a p99 of 1.4 s, and at 400 every public read is
still under 150 ms at p99; only signed-in requests, which must reach the
instance, slow down.

That is the honest limit of the free tier: **a tenth of a CPU**. Public
traffic is solved by the edge; signed-in traffic is bounded by the CPU.

## Paid tiers, with the scaling upgrade

The same test against the stack in `render.paid.yaml`: Redis for the job
queue and for rate limits, live-stream slots and the response cache shared
across processes, a separate screening worker. See [Scaling](scaling.md).

**Render Standard** (1 CPU, 2 GB), two API processes:

| Users | Path | req/s | p50 | p95 | p99 | Fail |
|---:|---|---:|---:|---:|---:|---:|
| 100 | direct | 20.7 | 12 | 100 | 150 | 0 % |
| 200 | direct | 38.5 | 12 | 80 | 110 | 0 % |
| 400 | direct | 76.9 | 14 | 94 | 130 | 0 % |
| 800 | edge | 136.0 | 17 | 110 | 150 | 0 % |
| 1,200 | edge | **183.5** | 28 | **120** | **170** | **0 %** |

At 1,200 users the signed-in routes were p95 32–84 ms: the live activity
feed 84 ms, the account 39 ms.

**Render Starter** (0.5 CPU, 512 MB), one API process:

| Users | Path | req/s | p50 | p95 | p99 | Fail |
|---:|---|---:|---:|---:|---:|---:|
| 200 | direct | 41.1 | 8 | 130 | 170 | 0 % |
| 400 | direct | 75.6 | 12 | 250 | 410 | 0 % |
| 800 | direct | 52.0 | 340 | 30,000 | 46,000 | 8.6 % |
| 800 | edge | 137.0 | 14 | 99 | 140 | 0 % |
| 1,600 | edge | 170.8 | 37 | **130** | **220** | **0 %** |

Starter direct breaks between 400 and 800 users; with the edge in front it
was still at p95 130 ms with no errors at 1,600, where the load generator,
not the API, was the bottleneck.

## Concurrency correctness

Load is not only latency. With two API processes and a separate worker,
three simultaneous screening requests from one account were sent to the
API: exactly one was admitted and two were refused with 429. Admission is
serialised across processes by a Postgres advisory lock, and the per-account
rate limits by atomic Redis scripts, each covered by tests.

## Running it against production

`loadtest/README.md` has the commands. In short: short, ramped runs at a
quiet time; public reads through the edge as real visitors' are; signed-in
users only with tokens from test accounts; no address spoofing (refused by
the script), so the per-address rate limits will answer 429 well before the
instance is busy, which is the limiter doing its job. To measure capacity,
run locally.
