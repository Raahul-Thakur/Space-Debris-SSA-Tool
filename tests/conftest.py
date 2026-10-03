"""Test-session isolation from developer and deployment configuration.

A developer's ``.env`` points at whatever they happen to be working against —
quite possibly a live Supabase project with real authentication. Nothing in the
test suite should change behaviour because of it, and nothing in the test suite
should ever reach that database.

This runs at collection time, before any test imports the application, because
``create_app`` reads the environment while it is being constructed.
"""

from __future__ import annotations

import os

#: Variables that would otherwise redirect the suite at real infrastructure or
#: switch it to an authentication mode its fixtures cannot satisfy.
LEAKY_VARIABLES = (
    "SDEBRIS_DATABASE_URL",
    "SDEBRIS_AUTH_JWKS_URL",
    "SDEBRIS_AUTH_ISSUER",
    "SDEBRIS_AUTH_AUDIENCE",
    "SDEBRIS_BILLING_WEBHOOK_SECRET",
    "SDEBRIS_REDIS_URL",
    "SDEBRIS_JOB_BACKEND",
    "SDEBRIS_ENV",
)

# Stop sdebris.config.load_env() from reading the file at all.
os.environ["SDEBRIS_SKIP_DOTENV"] = "1"

# And drop anything already exported into this shell, so a developer who has
# sourced their production configuration still gets a hermetic run.
for name in LEAKY_VARIABLES:
    os.environ.pop(name, None)
