# Scaling

The platform runs free today and is built to move to a paid stack by
deploying one file, `render.paid.yaml`, with no code change. This page is
what that stack is, what each part buys, and when to switch.

## The two stacks

| | Free (`render.yaml`) | Paid (`render.paid.yaml`) |
|---|---|---|
| API | Render free: 0.1 CPU, 512 MB, sleeps when idle | Render Standard: 1 CPU, 2 GB, always on |
| API processes | 1 | 2 (`WEB_CONCURRENCY`) |
| Screening jobs | Thread pool inside the API | Separate worker service, Redis queue |
| Rate limits, stream slots, response cache | In process memory | Shared in Redis |
| Edge | Cloudflare Pages + edge cache | Same |
| Database | Supabase Postgres | Same |
| Cost | $0 | About $42/month (Standard $25, worker $7, Key Value $10) |
| Measured | 200 users via edge, p99 1.4 s, 0 errors | 1,200 users via edge, p99 170 ms, 0 errors |

Measurements and method: [Load test](load-test.md).

## What each part buys

**More CPU.** The free instance's limit is not code; it is a tenth of a CPU.
After the load-test fixes, every signed-in request costs a few milliseconds
of CPU, and at 0.1 CPU that is a few hundred per second at best. A full CPU
is ten times that.

**Several API processes.** Python runs one thread of Python at a time per
process. Two processes use a whole CPU and keep one slow request from
holding up the others.

Several processes are only correct if they agree on the limits. In process
memory, two workers would each allow the full anonymous allowance, so the
site would allow twice what it says. With `SDEBRIS_REDIS_URL` set, the rate
limits, the count of open live streams and the response cache move to Redis
(`src/sdebris/shared_state.py`). Each check-and-record is one Lua script, so
it is atomic across every process. The API refuses to start with
`WEB_CONCURRENCY` above 1 and no Redis.

**A separate worker.** A screening propagates the whole catalogue and can
take minutes of CPU. In the API process it competes with the requests the
API is serving. On its own service it does not, it survives an API deploy
(the job waits in Redis), and the worker can be scaled on its own.

Two things had to change for jobs to be correct across processes:

* *Admission.* "May this account start a job?" and inserting the job must
  be one step, or two simultaneous requests could both pass a limit only one
  fits under. Within a process that was a lock; across processes it is now a
  Postgres advisory lock held until the insert commits.
* *Progress numbering.* The worker writes a job's progress and the API
  writes its cancellation; both number the job's events. A per-job advisory
  lock keeps the numbers unique.

**Redis as an accelerator, not a dependency.** If Redis stops answering,
each call falls back to the in-process version within 250 ms and logs once:
limits become per-process (looser, never absent), the cache becomes local,
and the site keeps serving. `/health` reports whether Redis is reachable.
Under memory pressure Redis evicts only keys that expire anyway (cache
entries, rate-limit windows), never a queued job.

## When to switch

Switch when one of these is true, not before:

* People sign in and use the console at the same time, in numbers: the free
  tier's signed-in requests slow down past ~100 concurrent users.
* Pro opens for sale. Paying users should not wait for an instance to wake
  up (30–60 s on the free tier) or lose a screening to a deploy.
* The instance's own latency (`/admin/stats`) shows p95 climbing.

Starter (0.5 CPU, 512 MB, $7) with one API process and Redis is a cheaper
first step: in the load test it held 800 users through the edge at p95
99 ms. Set `plan: starter` and `WEB_CONCURRENCY: "1"` in the blueprint.

## Switching

1. Render: New > Blueprint, select `render.paid.yaml`. Fill in the secrets
   marked `sync: false` with the free stack's values.
2. Wait for `/health` on the new service to show
   `"shared_state": {"backend": "redis", "reachable": true}`.
3. Cloudflare Pages: point `SDEBRIS_API_URL` and `NEXT_PUBLIC_SDEBRIS_API_URL`
   at the new service, and redeploy.
4. Remove the free service once traffic has moved.

The keep-warm workflow can then be disabled: a paid instance does not sleep.

## Beyond one instance

The design does not stop at one web instance. Everything that must agree
between processes is in Redis or Postgres, so adding instances behind
Render's load balancer needs no code change. The next limits would be:

* **Database connections.** Each process holds up to `SDEBRIS_DB_POOL_SIZE`
  plus `SDEBRIS_DB_MAX_OVERFLOW`. Use Supabase's transaction pooler and keep
  the total under its limit.
* **Live streams.** Each open activity feed is a poll of the database every
  2 s. Past a few hundred concurrent signed-in users, replace polling with
  Postgres `LISTEN/NOTIFY` or Redis pub/sub fan-out.
