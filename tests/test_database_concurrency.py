"""SQLite must tolerate the long-lived readers the streaming endpoints hold."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy import select, text

from sdebris.ontology.database import Database
from sdebris.ontology.orm import CommandExecutionRecord, SpaceObjectRecord


def test_sqlite_uses_wal_and_a_busy_timeout(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'wal.db').as_posix()}")
    database.initialize()
    with database.session_factory() as session:
        assert session.scalar(text("PRAGMA journal_mode")) == "wal"
        assert session.scalar(text("PRAGMA busy_timeout")) >= 1000


def test_a_write_succeeds_while_a_reader_session_is_open(tmp_path) -> None:
    """Reproduces the feed poller racing a command write."""
    database = Database(f"sqlite:///{(tmp_path / 'race.db').as_posix()}")
    database.initialize()

    with database.session_factory() as seed:
        seed.add(SpaceObjectRecord(norad_id="25544", name="ISS"))
        seed.commit()

    reader_open = threading.Event()
    reader_done = threading.Event()
    failure: list[BaseException] = []

    def hold_reader() -> None:
        try:
            with database.session_factory() as session:
                session.scalars(select(SpaceObjectRecord)).all()
                reader_open.set()
                reader_done.wait(timeout=10)
                session.scalars(select(SpaceObjectRecord)).all()
        # Deliberately broad: whatever the reader thread hits has to reach the
        # main thread, which asserts on it below, rather than vanish.
        except Exception as exc:  # noqa: BLE001
            failure.append(exc)
            reader_open.set()

    reader = threading.Thread(target=hold_reader)
    reader.start()
    assert reader_open.wait(timeout=10)

    try:
        with database.session_factory() as writer:
            writer.add(
                CommandExecutionRecord(
                    actor="tester",
                    role="analyst",
                    raw_command="screen 25544",
                    parsed_action="screen",
                    arguments={},
                    status="succeeded",
                    completed_at=datetime.now(timezone.utc),
                )
            )
            writer.commit()
    finally:
        reader_done.set()
        reader.join(timeout=10)

    assert not failure, failure
    with database.session_factory() as session:
        assert session.scalars(select(CommandExecutionRecord)).all()


def test_an_exhausted_connection_pool_is_a_fast_503_not_a_500() -> None:
    """At 100 users the pool waited 30 s per request and then returned a 500."""
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import TimeoutError as PoolTimeoutError

    from sdebris.api.app import create_app

    app = create_app("sqlite:///:memory:")

    @app.get("/__pool_exhausted")
    def exhausted():
        raise PoolTimeoutError("QueuePool limit reached")

    with TestClient(app) as client:
        response = client.get("/__pool_exhausted")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"


def test_the_postgres_pool_is_sized_and_bounded(monkeypatch) -> None:
    from sdebris.ontology.database import create_database_engine

    monkeypatch.setenv("SDEBRIS_DB_POOL_SIZE", "7")
    engine = create_database_engine("postgresql+psycopg://u:p@localhost:1/db")
    assert engine.pool.size() == 7
    assert engine.pool._timeout == 5.0
