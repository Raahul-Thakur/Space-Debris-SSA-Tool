"""scope work products to a principal

Until now the ontology was one shared workspace: every signed-in account saw
and could edit everyone else's screening runs, cases and alerts. That is why
new accounts have been held at ``viewer``.

Five tables already recorded who acted -- ``screening_jobs``,
``command_executions``, ``audit_actions``, ``operator_decisions`` and
``monitored_objects`` (as ``added_by``). This adds the same thing to the four
that did not.

The column is ``actor`` rather than ``owner`` because ``space_objects.owner``
already means the organisation operating the satellite, and reusing the word
for tenancy would make both unreadable.

NULL means the platform produced the row -- a scheduled screening, a CLI run,
a seed -- and those rows stay visible to everyone. Existing rows are therefore
left NULL rather than being attributed to whoever happens to be the first
account: they were produced by the pipeline, and the public dashboard is built
from exactly these.

Conjunction events and risk assessments deliberately get no actor. They are
computed from public elements by a deterministic model, so two principals
screening the same object get the same answer and there is nothing in the
result to keep private. The *run* is scoped, because screening activity
reveals operational interest even when its output does not.

Revision ID: c41d8a62f09b
Revises: b7e3c05d19af
Create Date: 2026-10-06 11:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c41d8a62f09b'
down_revision: str | Sequence[str] | None = 'b7e3c05d19af'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Work-product tables that did not already record who acted.
SCOPED_TABLES = (
    'screening_runs',
    'monitoring_cases',
    'alerts',
    'maneuver_scenarios',
)


def upgrade() -> None:
    # monitored_objects already recorded who added a row, but as NOT NULL, so
    # it could not express "the platform added this". The public globe is
    # exactly that set, so the column joins the same convention as the rest.
    # monitored_objects carried two assumptions from the single-workspace
    # design: that an adder is always a person (NOT NULL), and that an object
    # is watched by at most one party anywhere (UNIQUE on space_object_id).
    # Per-principal watch lists need both relaxed -- the platform's own list
    # is the public globe, and two people must be able to track the same
    # object without one displacing the other.
    with op.batch_alter_table('monitored_objects') as batch:
        batch.alter_column(
            'added_by', existing_type=sa.String(length=255), nullable=True
        )

    # The single-watcher rule was a UNIQUE INDEX in both dialects, not a named
    # constraint, because the column declared unique and index together. It is
    # replaced by a per-watcher one plus a plain lookup index.
    op.drop_index(
        'ix_monitored_objects_space_object_id', table_name='monitored_objects'
    )
    op.create_index(
        'ix_monitored_objects_space_object_id',
        'monitored_objects',
        ['space_object_id'],
    )
    op.create_index(
        'uq_monitored_object_watcher',
        'monitored_objects',
        ['space_object_id', 'added_by'],
        unique=True,
    )
    op.create_index(
        'ix_monitored_objects_added_by', 'monitored_objects', ['added_by']
    )

    for table in SCOPED_TABLES:
        op.add_column(
            table, sa.Column('actor', sa.String(length=255), nullable=True)
        )
        # Every scoped read filters on this column, so it is indexed from the
        # start rather than after the first slow query.
        op.create_index(f'ix_{table}_actor', table, ['actor'])


def downgrade() -> None:
    for table in reversed(SCOPED_TABLES):
        op.drop_index(f'ix_{table}_actor', table_name=table)
        op.drop_column(table, 'actor')

    # Restoring NOT NULL requires the platform rows to be attributed to
    # someone, so they are stamped before the constraint goes back on.
    op.execute(
        "UPDATE monitored_objects SET added_by = 'platform' WHERE added_by IS NULL"
    )
    op.drop_index('ix_monitored_objects_added_by', table_name='monitored_objects')
    op.drop_index('uq_monitored_object_watcher', table_name='monitored_objects')
    # Going back to one watcher per object means dropping every duplicate.
    op.execute(
        """
        DELETE FROM monitored_objects
        WHERE id NOT IN (
            SELECT MIN(id) FROM monitored_objects GROUP BY space_object_id
        )
        """
    )
    op.drop_index(
        'ix_monitored_objects_space_object_id', table_name='monitored_objects'
    )
    op.create_index(
        'ix_monitored_objects_space_object_id',
        'monitored_objects',
        ['space_object_id'],
        unique=True,
    )
    with op.batch_alter_table('monitored_objects') as batch:
        batch.alter_column(
            'added_by', existing_type=sa.String(length=255), nullable=False
        )
