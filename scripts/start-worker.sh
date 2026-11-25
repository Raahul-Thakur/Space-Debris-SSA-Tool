#!/bin/sh
# The screening worker, as its own service (render.paid.yaml). Screening is
# CPU-bound, so throughput scales with processes, one per CPU; the default
# suits a one-CPU instance.
set -eu
if [ -z "${SDEBRIS_REDIS_URL:-}" ]; then
  echo "the worker needs SDEBRIS_REDIS_URL" >&2
  exit 1
fi
exec python -m dramatiq sdebris.jobs.tasks \
  --processes "${SDEBRIS_WORKER_PROCESSES:-1}" --threads "${SDEBRIS_WORKER_THREADS:-1}"
