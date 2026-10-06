"""Who may see which rows.

The ontology holds three kinds of thing, and they are scoped differently.

*Reference data* -- space objects, element sets, sensor observations, the
ephemeris derived from them -- describes the physical world. There is one ISS.
Everyone reads the same rows, and only the ingestion pipeline or an
administrator writes them.

*Derived facts* -- conjunction events and their risk assessments -- are
computed from that reference data by a deterministic model. Two principals
screening the same object get the same answer, so there is nothing to keep
private in the result, and the public dashboard is built from exactly these
rows.

*Work products* -- screening runs, watch lists, cases, decisions, alerts,
manoeuvre scenarios, jobs, commands and the audit trail -- record what a
particular principal did. These are scoped. Screening activity reveals
operational interest even when the result does not, which is why the run is
private while the conjunction it found is not.

A NULL actor means the platform produced the row: a scheduled screening, a
CLI run, a seed. Those are visible to everyone, which is what lets an
anonymous visitor see a real picture rather than an empty one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy import ColumnElement, or_
from sqlalchemy.sql import Select

from sdebris.ontology.enums import OperatorRole

#: Rows produced by the platform rather than by a principal.
PLATFORM = None


@runtime_checkable
class Principal(Protocol):
    """The part of an authenticated principal that scoping depends on.

    Structural rather than an import of ``sdebris.auth``: that module pulls in
    FastAPI, and the ontology service is also used by the CLI, which must keep
    working on a base install without the API extras.
    """

    @property
    def actor(self) -> str: ...

    @property
    def role(self) -> OperatorRole: ...


def sees_everything(principal: Principal | None) -> bool:
    """Only an administrator reads across principals."""
    return principal is not None and principal.role is OperatorRole.ADMIN


def visibility_filter(
    column: ColumnElement[str | None], principal: Principal | None
) -> ColumnElement[bool] | None:
    """The predicate restricting ``column`` to what ``principal`` may read.

    Returns ``None`` when no restriction applies, so a caller can tell "see
    everything" apart from "see nothing" rather than having to pass a
    tautology into the query.
    """
    if sees_everything(principal):
        return None
    if principal is None:
        # Anonymous: the platform's own rows, and nothing belonging to anyone.
        return column.is_(None)
    return or_(column.is_(None), column == principal.actor)


def scope(
    statement: Select, column: ColumnElement[str | None], principal: Principal | None
) -> Select:
    """Narrow ``statement`` to the rows ``principal`` may read."""
    predicate = visibility_filter(column, principal)
    return statement if predicate is None else statement.where(predicate)


def owns(
    row_actor: str | None, principal: Principal | None, *, platform_is_public: bool = True
) -> bool:
    """Whether ``principal`` may act on a row with this actor.

    Writes are stricter than reads. A platform-owned row is readable by
    everyone but must not be mutated by whoever happens to find it, so callers
    performing a write pass ``platform_is_public=False``.
    """
    if sees_everything(principal):
        return True
    if principal is None:
        return False
    if row_actor is None:
        return platform_is_public
    return row_actor == principal.actor
