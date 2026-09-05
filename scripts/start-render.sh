#!/bin/sh
set -eu

python -m alembic upgrade head
python -m dramatiq sdebris.jobs.tasks --processes 1 --threads 1 &
worker_pid=$!
trap 'kill "$worker_pid" 2>/dev/null || true' EXIT TERM INT
python -m uvicorn sdebris.api.app:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers
