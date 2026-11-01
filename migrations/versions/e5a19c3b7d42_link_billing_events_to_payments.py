"""link billing events to payments

A refund or dispute names only the payment it reverses. To withdraw the
subscription that payment paid for, the ledger has to remember which
subscription each payment belonged to.

Revision ID: e5a19c3b7d42
Revises: c41d8a62f09b
Create Date: 2026-11-01 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'e5a19c3b7d42'
down_revision: str | Sequence[str] | None = 'c41d8a62f09b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('billing_events') as batch:
        batch.add_column(sa.Column('payment_id', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('subscription_id', sa.String(length=255), nullable=True))
    op.create_index(
        'ix_billing_events_payment_id', 'billing_events', ['payment_id']
    )


def downgrade() -> None:
    op.drop_index('ix_billing_events_payment_id', table_name='billing_events')
    with op.batch_alter_table('billing_events') as batch:
        batch.drop_column('subscription_id')
        batch.drop_column('payment_id')
