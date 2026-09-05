"""Core domain models shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def parse_tle_epoch(line1: str) -> datetime:
    """Parse the epoch (UTC) encoded in columns 19-32 of TLE line 1.

    The field is ``YYDDD.DDDDDDDD`` where ``YY`` is a 2-digit year (57-99 -> 19xx,
    00-56 -> 20xx per the TLE convention) and ``DDD.DDDDDDDD`` is the fractional
    day-of-year.
    """
    epoch_field = line1[18:32].strip()
    yy = int(epoch_field[:2])
    day_of_year = float(epoch_field[2:])
    year = 1900 + yy if yy >= 57 else 2000 + yy
    start_of_year = datetime(year, 1, 1, tzinfo=timezone.utc)
    return start_of_year + timedelta(days=day_of_year - 1.0)


@dataclass(frozen=True)
class SpaceObject:
    """A catalog object backed by a two-line element set."""

    norad_id: str
    name: str
    line1: str
    line2: str

    @property
    def epoch(self) -> datetime:
        return parse_tle_epoch(self.line1)

    def age_days(self, reference: datetime | None = None) -> float:
        """Age of the TLE in days relative to ``reference`` (defaults to now)."""
        ref = reference or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return (ref - self.epoch).total_seconds() / 86400.0

    def is_stale(self, stale_after_days: float, reference: datetime | None = None) -> bool:
        return self.age_days(reference) > stale_after_days

    def to_dict(self) -> dict[str, str]:
        return {
            "norad_id": self.norad_id,
            "name": self.name,
            "line1": self.line1,
            "line2": self.line2,
            "epoch": self.epoch.isoformat(),
        }


def parse_tle_text(text: str) -> list[SpaceObject]:
    """Parse 2-line or 3-line TLE records from raw text."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    objects: list[SpaceObject] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and len(lines[i]) >= 60:
            name = None
            line1 = lines[i]
            i += 1
        else:
            name = lines[i].strip()
            i += 1
            if i >= len(lines):
                break
            line1 = lines[i]
            i += 1
        if i >= len(lines):
            break
        line2 = lines[i]
        i += 1
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            continue
        norad_id = line1[2:7].strip()
        objects.append(
            SpaceObject(
                norad_id=norad_id,
                name=name or f"OBJECT-{norad_id}",
                line1=line1,
                line2=line2,
            )
        )
    return objects
