"""Local SQLite cache for TLE records with epoch tracking and staleness flags."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sdebris.models import SpaceObject

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tle (
    norad_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    line1      TEXT NOT NULL,
    line2      TEXT NOT NULL,
    epoch      TEXT NOT NULL,      -- ISO-8601 UTC, parsed from the TLE
    source     TEXT,               -- e.g. the CelesTrak group
    fetched_at TEXT NOT NULL       -- ISO-8601 UTC, when we ingested it
);
CREATE INDEX IF NOT EXISTS idx_tle_source ON tle(source);
"""


class TLECache:
    """A thin SQLite wrapper. One row per NORAD id; newer epochs replace older."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TLECache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def upsert(self, objects: list[SpaceObject], source: str | None = None) -> int:
        """Insert/refresh objects. An incoming row only replaces an existing one
        if its epoch is newer (or equal). Returns the number of rows written."""
        now = datetime.now(timezone.utc).isoformat()
        written = 0
        for obj in objects:
            existing = self._conn.execute(
                "SELECT epoch FROM tle WHERE norad_id = ?", (obj.norad_id,)
            ).fetchone()
            incoming_epoch = obj.epoch.isoformat()
            if existing is not None and existing["epoch"] > incoming_epoch:
                continue
            self._conn.execute(
                """
                INSERT INTO tle (norad_id, name, line1, line2, epoch, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(norad_id) DO UPDATE SET
                    name=excluded.name, line1=excluded.line1, line2=excluded.line2,
                    epoch=excluded.epoch, source=excluded.source, fetched_at=excluded.fetched_at
                """,
                (obj.norad_id, obj.name, obj.line1, obj.line2, incoming_epoch, source, now),
            )
            written += 1
        self._conn.commit()
        return written

    def _row_to_object(self, row: sqlite3.Row) -> SpaceObject:
        return SpaceObject(
            norad_id=row["norad_id"],
            name=row["name"],
            line1=row["line1"],
            line2=row["line2"],
        )

    def get(self, norad_id: str) -> SpaceObject | None:
        row = self._conn.execute(
            "SELECT * FROM tle WHERE norad_id = ?", (str(norad_id),)
        ).fetchone()
        return self._row_to_object(row) if row else None

    def all(self, source: str | None = None) -> list[SpaceObject]:
        if source is None:
            rows = self._conn.execute("SELECT * FROM tle ORDER BY norad_id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tle WHERE source = ? ORDER BY norad_id", (source,)
            ).fetchall()
        return [self._row_to_object(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM tle").fetchone()[0])

    def last_fetched_at(self) -> datetime | None:
        """Return the most recent catalog fetch timestamp, if the cache has data."""
        row = self._conn.execute("SELECT MAX(fetched_at) FROM tle").fetchone()
        value = row[0] if row else None
        return datetime.fromisoformat(value) if value else None

    def stale_ids(self, stale_after_days: float, reference: datetime | None = None) -> list[str]:
        """NORAD ids whose cached TLE is older than the staleness threshold."""
        return [obj.norad_id for obj in self.all() if obj.is_stale(stale_after_days, reference)]
