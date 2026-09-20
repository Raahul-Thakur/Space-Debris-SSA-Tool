"""Database lifecycle helpers for local SQLite and deployed PostgreSQL."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
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
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
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
        init_database(self.engine)

    def sessions(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session
