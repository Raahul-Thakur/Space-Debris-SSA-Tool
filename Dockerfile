FROM python:3.12-slim

# SDEBRIS_HOME: the package is installed into site-packages, so it cannot
# find configs/ or a writable data/ directory relative to itself. /app holds
# both and is owned by the user the service runs as.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SDEBRIS_HOME=/app

RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Exact, hash-checked versions from the lockfile, installed before the source
# is copied so the layer is reused until a dependency changes. Unpinned
# installs took whatever was newest on the day: that is how pandas 3 arrived
# and put every time of closest approach in 1970.
COPY requirements-lock.txt ./
RUN pip install --require-hashes -r requirements-lock.txt
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
RUN pip install --no-deps .

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl --fail http://127.0.0.1:${PORT:-10000}/health || exit 1

CMD ["sh", "scripts/start-render.sh"]
