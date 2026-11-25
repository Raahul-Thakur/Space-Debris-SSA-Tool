"""Database lifecycle helpers for local SQLite and deployed PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from sdebris.config import REPO_ROOT, load_config
from sdebris.ontology.orm import Base

#: How long a SQLite writer waits for a competing lock before giving up.
SQLITE_BUSY_TIMEOUT_MS = 10_000


def resolve_database_url(url: str | None = None) -> str:
    configured = url or os.getenv("SDEBRIS_DATABASE_URL") or load_config().ontology.database_url
    if configured.startswith("sqlite:///"):
        raw_path = configured.removeprefix("sqlite:///")
        if raw_path == ":memory:":
            return configured
        path = Path(raw_path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"
    return configured


def create_database_engine(url: str | None = None) -> Engine:
    database_url = resolve_database_url(url)
    if database_url.startswith("sqlite"):
        connect_args: dict[str, object] = {"check_same_thread": False}
    elif database_url.startswith("postgresql+psycopg"):
        # Supabase's transaction pooler (and any PgBouncer in transaction mode)
        # hands out a different server connection per transaction, while
        # psycopg starts preparing statements server-side once it has seen the
        # same query a few times. The prepared statement is then missing, or
        # worse, its name collides with one left by another client, which
        # surfaces as DuplicatePreparedStatement. Disabling the client-side
        # prepare cache is the supported way to use a transaction pooler.
        connect_args = {"prepare_threshold": None}
    else:
        connect_args = {}
    pool: dict[str, object] = {}
    if not database_url.startswith("sqlite"):
        # Sized for the thread pool FastAPI runs synchronous endpoints on, and
        # bounded in wait. The defaults (5 + 10 connections, 30 s timeout)
        # failed under load in the worst way: at 100 concurrent users every
        # request queued for a connection, waited thirty seconds and then
        # returned a 500. A short timeout turns that into a fast 503 the
        # client can retry (see the handler in sdebris.api.app). Supabase's
        # transaction pooler accepts far more clients than this per process.
        pool = {
            "pool_size": int(os.getenv("SDEBRIS_DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("SDEBRIS_DB_MAX_OVERFLOW", "10")),
            "pool_timeout": float(os.getenv("SDEBRIS_DB_POOL_TIMEOUT", "5")),
        }
    engine = create_engine(
        database_url, connect_args=connect_args, pool_pre_ping=True, **pool
    )
    if database_url.startswith("sqlite"):
        on_disk = ":memory:" not in database_url

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if on_disk:
                # The API holds long-lived readers open for the activity and
                # job-progress streams while worker threads write. Under the
                # default rollback journal those readers block every write and
                # the writer fails immediately with "database is locked", so
                # WAL (concurrent reader + writer) and a wait-instead-of-fail
                # busy timeout are both required.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.close()

    return engine


def init_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


class Database:
    """Own the engine and transaction factory for one application instance."""

    def __init__(self, url: str | None = None) -> None:
        self.engine = create_database_engine(url)
        self.session_factory = create_session_factory(self.engine)

    def initialize(self) -> None:
        # A database Alembic manages (every deployed one: the start script
        # migrates first) belongs to the migrations alone. create_all there
        # would create a table a migration had not, and the next migration
        # would then fail on it. Fresh local and test databases still get
        # the schema straight from the models.
        if inspect(self.engine).has_table("alembic_version"):
            return
        init_database(self.engine)

    def sessions(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session
