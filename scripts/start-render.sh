#!/bin/sh
set -eu

python -m alembic upgrade head

# The Dramatiq worker only exists for the Redis job backend. On the free stack
# the backend is "thread", screening runs inside the API process, and starting
# the worker would only crash on the missing SDEBRIS_REDIS_URL.
#
# On the paid stack (render.paid.yaml) the worker is its own service, running
# scripts/start-worker.sh, and SDEBRIS_EMBEDDED_WORKER=false keeps a second
# copy from starting here.
if [ "${SDEBRIS_JOB_BACKEND:-thread}" = "redis" ] && [ "${SDEBRIS_EMBEDDED_WORKER:-true}" = "true" ]; then
  if [ -z "${SDEBRIS_REDIS_URL:-}" ]; then
    echo "SDEBRIS_JOB_BACKEND=redis requires SDEBRIS_REDIS_URL" >&2
    exit 1
  fi
  python -m dramatiq sdebris.jobs.tasks --processes 1 --threads 1 &
  worker_pid=$!
  trap 'kill "$worker_pid" 2>/dev/null || true' EXIT TERM INT
fi

# WEB_CONCURRENCY API processes (default 1). More than one needs Redis, for
# the shared limits and queue; the API refuses to start otherwise.
python -m uvicorn sdebris.api.app:app --host 0.0.0.0 --port "${PORT:-10000}" \
  --proxy-headers --workers "${WEB_CONCURRENCY:-1}"
