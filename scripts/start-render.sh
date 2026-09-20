#!/bin/sh
set -eu

python -m alembic upgrade head

# The Dramatiq worker only exists for the Redis job backend. On the free stack
# the backend is "thread", screening runs inside the API process, and starting
# the worker would only crash on the missing SDEBRIS_REDIS_URL.
if [ "${SDEBRIS_JOB_BACKEND:-thread}" = "redis" ]; then
  if [ -z "${SDEBRIS_REDIS_URL:-}" ]; then
    echo "SDEBRIS_JOB_BACKEND=redis requires SDEBRIS_REDIS_URL" >&2
    exit 1
  fi
  python -m dramatiq sdebris.jobs.tasks --processes 1 --threads 1 &
  worker_pid=$!
  trap 'kill "$worker_pid" 2>/dev/null || true' EXIT TERM INT
fi

python -m uvicorn sdebris.api.app:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers
