"""add the Pro waitlist

Paid plans are closed during the beta; this holds the people who want to
hear when they open.

Revision ID: a83b6f1d2c94
Revises: f7c2d9a41e06
Create Date: 2026-11-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a83b6f1d2c94'
down_revision: str | Sequence[str] | None = 'f7c2d9a41e06'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'waitlist_entries',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('interest', sa.String(length=32), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uq_waitlist_email'),
    )
    # Closed to Supabase's public API like every other table (8f2d4e1a6b07).
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE public.waitlist_entries ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('waitlist_entries')
