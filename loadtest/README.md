# Load tests

A [Locust](https://locust.io) profile shaped like real traffic, a seeder that
gives a local database realistic data, and the instructions for running both
safely. Results and what they led to are in
[docs/load-test.md](../docs/load-test.md).

```sh
python -m venv .venv-loadtest && .venv-loadtest/bin/pip install -r loadtest/requirements.txt
```

## Who the simulated users are

* **Visitor** (80 %): opens the console (platform watch list, assessed
  events, one batched trajectory read), reads an event explanation, looks at
  pricing or reloads, waiting 4–15 s between actions like a person.
* **Analyst** (20 %, signed in): jobs, watch list, account, activity feed and
  a console command every 5–20 s. Screening jobs only when
  `LOADTEST_SCREENINGS=1`.

## Locally (the numbers in docs/load-test.md)

1. A real Postgres, migrated and seeded. The seeder refuses hosted database
   URLs.

   ```sh
   export SDEBRIS_ENV=development
   export SDEBRIS_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5432/astra
   alembic upgrade head
   python loadtest/seed.py --objects 300 --targets 3 --watch 20
   ```

2. The API with the same limits as the deployed instance. On Linux, a cgroup
   gives it Render free's tenth of a CPU and 512 MB (`cpu.cfs_quota_us=10000`
   with the default 100 ms period); without one the numbers are only
   relative.

   ```sh
   uvicorn sdebris.api.app:app --port 8000 --proxy-headers --forwarded-allow-ips='*'
   ```

3. Optionally the edge cache in front, as in production:

   ```sh
   cd web && NEXT_PUBLIC_SDEBRIS_API_URL=http://127.0.0.1:8000 npm run build:cloudflare
   npx wrangler pages dev out --port 8788 \
     --binding SDEBRIS_API_URL=http://127.0.0.1:8000 --binding SDEBRIS_PROXY_TOKEN=<same as the API's>
   ```

4. Run, ramping 20 users a second:

   ```sh
   cd loadtest
   locust -f locustfile.py --headless -u 200 -r 20 -t 90s --host http://127.0.0.1:8000 --csv out/direct-200
   LOADTEST_PUBLIC_BASE=http://localhost:8788 \
     locust -f locustfile.py --headless -u 200 -r 20 -t 90s --host http://127.0.0.1:8000 --csv out/edge-200
   ```

   Locally each simulated visitor sends its own `X-Forwarded-For`, so the
   per-address rate limits see many people rather than one machine.

## Against production

Every request is a real request: it uses the instance's CPU, the database's
connections and, for signed-in users, the accounts' quotas. So:

* Run it at a quiet time, short (60–120 s) and ramped, and stop at the first
  sign of errors. Tell your host first if their terms ask for it.
* Public reads go through the edge, as real visitors' do:

  ```sh
  LOADTEST_TARGET=production LOADTEST_PUBLIC_BASE=https://<your-site> \
    locust -f locustfile.py --headless -u 50 -r 5 -t 90s --host https://<your-api> --csv out/prod-50
  ```

* Signed-in users need real tokens from test accounts, one per line, in a
  file that is never committed: `LOADTEST_TOKENS=tokens.txt`. Without it only
  Visitors run.
* Address spoofing is refused in production, so all traffic comes from one
  address and the per-address limits will start answering 429 well before
  the instance is busy. That is the limiter working. To measure capacity
  rather than the limiter, run locally.
* Screening jobs need `LOADTEST_SCREENINGS=1` **and**
  `LOADTEST_I_UNDERSTAND=1`.
