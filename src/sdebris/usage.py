"""Aggregate usage figures for the admin page, from records the service keeps anyway.

Nothing here adds tracking. Every figure is a count over rows that already
exist for the product to work -- command executions, screening jobs, watch
lists, conjunction events and the waitlist -- and only counts leave this
module: no account identifiers, emails or commands. That is what lets the
privacy page describe the admin statistics as aggregate counts from the
service's own records.

Two portability decisions shape the queries:

* **Date bucketing** differs between SQLite (strings, ``strftime``) and
  PostgreSQL (``date_trunc``). Instead of branching, each bucket is a ``CASE``
  over precomputed UTC boundaries, which both dialects evaluate identically,
  and the grouping happens in SQL. A result is therefore at most one row per
  bucket (and status), however many rows the tables hold.
* **Percentiles** have no common SQL spelling. PostgreSQL computes them with
  ``percentile_disc``; elsewhere (SQLite, i.e. local development) the
  durations of at most ``DURATION_SAMPLE_LIMIT`` recent jobs are read and
  ranked in Python. Both are nearest-rank, so the two give the same answer.

An "account" is the actor recorded on those rows: the signed-in email, or
the auth subject when there is no email. Platform rows (a NULL watcher) are
not accounts and are left out.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, case, func, select, union_all
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from sdebris.latency import percentile
from sdebris.ontology.enums import JobStatus
from sdebris.ontology.orm import (
    CommandExecutionRecord,
    ConjunctionEventRecord,
    MonitoredObjectRecord,
    ScreeningJobRecord,
    WaitlistEntryRecord,
)

#: Days in the daily series, and weeks in the weekly one.
DAILY_DAYS = 30
WEEKLY_WEEKS = 12
#: Most job durations read for a percentile where SQL cannot compute one.
DURATION_SAMPLE_LIMIT = 10_000


def _as_utc(value: datetime) -> datetime:
    # SQLite hands timestamps back without a zone; everything stored is UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _bucket(column, edges: list[datetime]) -> ColumnElement[int]:
    """Index of the half-open interval ``[edges[i], edges[i + 1])`` holding ``column``.

    Callers filter ``column >= edges[0]``; anything at or after the last edge
    (a row written a moment after ``now`` was taken) falls in the last bucket.
    """
    whens = [(column >= edge, index) for index, edge in reversed(list(enumerate(edges)))]
    return case(*whens, else_=0)


def _grouped(inner: Select, *keys: str) -> Select:
    """``SELECT keys, count(*) ... GROUP BY keys`` over a subquery.

    Grouping on the subquery's columns, rather than repeating the ``CASE``
    in ``GROUP BY``, matters on PostgreSQL: each repetition binds its own
    parameters, and the server would then refuse the select list as not
    grouped.
    """
    sub = inner.subquery()
    columns = [sub.c[key] for key in keys]
    return select(*columns, func.count().label("n")).group_by(*columns)


def _counts(session: Session, statement: Select) -> dict[int, int]:
    """``{bucket: count}`` from a two-column grouped query."""
    return {int(bucket): int(count) for bucket, count in session.execute(statement)}


def _activity():
    """Every (account, moment) the service has a record of an account acting."""
    return union_all(
        select(
            CommandExecutionRecord.actor.label("actor"),
            CommandExecutionRecord.created_at.label("at"),
        ),
        select(
            ScreeningJobRecord.actor.label("actor"),
            ScreeningJobRecord.created_at.label("at"),
        ),
        select(
            MonitoredObjectRecord.added_by.label("actor"),
            MonitoredObjectRecord.created_at.label("at"),
        ).where(MonitoredObjectRecord.added_by.is_not(None)),
    ).subquery("activity")


def _daily_edges(today: date) -> list[datetime]:
    start = today - timedelta(days=DAILY_DAYS - 1)
    return [
        datetime.combine(start + timedelta(days=n), time.min, tzinfo=timezone.utc)
        for n in range(DAILY_DAYS)
    ]


def _weekly_edges(today: date) -> list[datetime]:
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=WEEKLY_WEEKS - 1)
    return [
        datetime.combine(start + timedelta(weeks=n), time.min, tzinfo=timezone.utc)
        for n in range(WEEKLY_WEEKS)
    ]


def _accounts(session: Session, now: datetime) -> dict[str, object]:
    activity = _activity()
    windows = {"1d": 1, "7d": 7, "30d": 30}
    row = session.execute(
        select(
            *[
                func.count(
                    func.distinct(
                        case((activity.c.at >= now - timedelta(days=days), activity.c.actor))
                    )
                ).label(name)
                for name, days in windows.items()
            ],
            func.count(func.distinct(activity.c.actor)).label("all_time"),
        )
    ).one()
    active = {name: int(getattr(row, name)) for name in windows}

    edges = _weekly_edges(now.date())
    first_seen = (
        select(activity.c.actor, func.min(activity.c.at).label("first_seen"))
        .group_by(activity.c.actor)
        .subquery("first_seen")
    )
    counts = _counts(
        session,
        _grouped(
            select(_bucket(first_seen.c.first_seen, edges).label("bucket")).where(first_seen.c.first_seen >= edges[0]),
            "bucket",
        ),
    )
    return {
        "active": active,
        "total": int(row.all_time),
        "new_per_week": [
            {"week_start": edge.date().isoformat(), "count": int(counts.get(index, 0))}
            for index, edge in enumerate(edges)
        ],
    }


def _job_durations(session: Session, since: datetime) -> dict[str, object]:
    """Median and p95 seconds from a job starting to it finishing.

    Measured from ``started_at`` -- the run itself -- falling back to
    ``created_at`` for a job with no recorded start. Succeeded jobs only: a
    cancelled or failed one ends early and would flatter the figures.
    """
    began = func.coalesce(ScreeningJobRecord.started_at, ScreeningJobRecord.created_at)
    finished = (
        ScreeningJobRecord.status == JobStatus.SUCCEEDED.value,
        ScreeningJobRecord.completed_at.is_not(None),
        ScreeningJobRecord.created_at >= since,
    )
    if session.get_bind().dialect.name == "postgresql":
        seconds = func.extract("epoch", ScreeningJobRecord.completed_at - began)
        row = session.execute(
            select(
                func.count(),
                func.percentile_disc(0.5).within_group(seconds),
                func.percentile_disc(0.95).within_group(seconds),
            ).where(*finished)
        ).one()
        samples, median, p95 = int(row[0]), row[1], row[2]
    else:
        pairs = session.execute(
            select(began.label("began"), ScreeningJobRecord.completed_at)
            .where(*finished)
            .order_by(ScreeningJobRecord.created_at.desc())
            .limit(DURATION_SAMPLE_LIMIT)
        ).all()
        values = sorted(
            max(0.0, (_as_utc(done) - _as_utc(_parse(start))).total_seconds())
            for start, done in pairs
        )
        samples = len(values)
        median, p95 = percentile(values, 0.5), percentile(values, 0.95)
    return {
        "samples": samples,
        "median_seconds": None if median is None else round(float(median), 2),
        "p95_seconds": None if p95 is None else round(float(p95), 2),
    }


def _parse(value: datetime | str) -> datetime:
    # ``coalesce`` loses the column type on SQLite, so the value can come
    # back as the stored text rather than a datetime.
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _screening_jobs(session: Session, now: datetime) -> dict[str, object]:
    edges = _daily_edges(now.date())
    job = ScreeningJobRecord
    rows = session.execute(
        _grouped(
            select(_bucket(job.created_at, edges).label("bucket"), job.status.label("status"))
            .where(job.created_at >= edges[0]),
            "bucket",
            "status",
        )
    ).all()
    per_day: list[dict[str, object]] = [
        {"date": edge.date().isoformat(), "total": 0, "by_status": {}} for edge in edges
    ]
    totals: dict[str, int] = {}
    for bucket, status, count in rows:
        day = per_day[int(bucket)]
        day["by_status"][status] = int(count)
        day["total"] += int(count)
        totals[status] = totals.get(status, 0) + int(count)

    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    this_month, all_time = session.execute(
        select(
            func.count(case((job.created_at >= month_start, 1))),
            func.count(),
        ).select_from(job)
    ).one()
    return {
        "total": int(all_time),
        "this_month": int(this_month),
        "last_30_days": {"total": sum(totals.values()), "by_status": totals},
        "per_day": per_day,
        "duration_last_30_days": _job_durations(session, edges[0]),
    }


def _commands(session: Session, now: datetime) -> dict[str, object]:
    edges = _daily_edges(now.date())
    command = CommandExecutionRecord
    counts = _counts(
        session,
        _grouped(
            select(_bucket(command.created_at, edges).label("bucket")).where(command.created_at >= edges[0]),
            "bucket",
        ),
    )
    total = session.scalar(select(func.count()).select_from(command)) or 0
    return {
        "total": int(total),
        "per_day": [
            {"date": edge.date().isoformat(), "count": int(counts.get(index, 0))}
            for index, edge in enumerate(edges)
        ],
    }


def _conjunctions(session: Session, now: datetime) -> dict[str, int]:
    event = ConjunctionEventRecord
    stored, upcoming = session.execute(
        select(func.count(), func.count(case((event.tca > now, 1)))).select_from(event)
    ).one()
    return {"stored": int(stored), "upcoming": int(upcoming)}


def _waitlist(session: Session) -> dict[str, object]:
    entry = WaitlistEntryRecord
    rows = session.execute(
        select(entry.interest, func.count()).group_by(entry.interest)
    ).all()
    by_interest = {(interest or "unspecified"): int(count) for interest, count in rows}
    return {"total": sum(by_interest.values()), "by_interest": by_interest}


def _monitored(session: Session) -> dict[str, int]:
    watch = MonitoredObjectRecord
    total, by_accounts, active = session.execute(
        select(
            func.count(),
            func.count(watch.added_by),
            func.count(case((watch.active.is_(True), 1))),
        ).select_from(watch)
    ).one()
    return {
        "total": int(total),
        "active": int(active),
        "by_accounts": int(by_accounts),
        "platform": int(total) - int(by_accounts),
    }


def usage_stats(session: Session, now: datetime | None = None) -> dict[str, object]:
    """Every aggregate on the admin page, as of ``now`` (UTC)."""
    now = _as_utc(now or datetime.now(timezone.utc))
    return {
        "as_of": now.isoformat(),
        "accounts": _accounts(session, now),
        "screening_jobs": _screening_jobs(session, now),
        "commands": _commands(session, now),
        "conjunction_events": _conjunctions(session, now),
        "waitlist": _waitlist(session),
        "monitored_objects": _monitored(session),
    }


__all__ = ["usage_stats"]
