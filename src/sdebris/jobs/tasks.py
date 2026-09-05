"""Dramatiq entrypoints for durable Redis-backed screening jobs."""

from __future__ import annotations

import os

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from sdebris.jobs.manager import ScreeningJobManager
from sdebris.ontology.database import Database


redis_url = os.getenv("SDEBRIS_REDIS_URL")
if not redis_url:
    raise RuntimeError("SDEBRIS_REDIS_URL is required for the Redis job backend")

dramatiq.set_broker(RedisBroker(url=redis_url))


@dramatiq.actor(max_retries=0, time_limit=3_600_000)
def run_screening_job(job_id: str) -> None:
    database = Database()
    database.initialize()
    manager = ScreeningJobManager(database.session_factory, enable_executor=False)
    try:
        manager._run(job_id)
    finally:
        database.engine.dispose()
