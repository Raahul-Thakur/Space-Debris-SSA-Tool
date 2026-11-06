"""reserve founding seats at checkout

The founding-seat cap was checked only when a checkout started, against
seats already paid for, so it could be oversold. A hold reserves a seat for
the length of a checkout.

Revision ID: f7c2d9a41e06
Revises: e5a19c3b7d42
Create Date: 2026-11-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'f7c2d9a41e06'
down_revision: str | Sequence[str] | None = 'e5a19c3b7d42'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'founding_seat_holds',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_founding_seat_holds_subject', 'founding_seat_holds', ['subject']
    )
    # Every other table is closed to Supabase's public API (8f2d4e1a6b07);
    # default privileges already withhold grants, and this keeps RLS on too.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE public.founding_seat_holds ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_index('ix_founding_seat_holds_subject', table_name='founding_seat_holds')
    op.drop_table('founding_seat_holds')
