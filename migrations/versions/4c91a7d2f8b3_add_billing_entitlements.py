"""add billing entitlements

Revision ID: 4c91a7d2f8b3
Revises: 0b38e47e6e81
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '4c91a7d2f8b3'
down_revision: str | Sequence[str] | None = '0b38e47e6e81'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'entitlements',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('plan', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('external_ref', sa.String(length=255), nullable=True),
        sa.Column('granted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_ref', name='uq_entitlement_external_ref'),
    )
    op.create_index('ix_entitlements_email', 'entitlements', ['email'])
    op.create_index('ix_entitlements_subject', 'entitlements', ['subject'])
    op.create_index(
        'ix_entitlement_email_status', 'entitlements', ['email', 'status']
    )

    op.create_table(
        'billing_events',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('outcome', sa.String(length=64), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'event_id', name='uq_billing_event_identity'),
    )


def downgrade() -> None:
    op.drop_table('billing_events')
    op.drop_index('ix_entitlement_email_status', table_name='entitlements')
    op.drop_index('ix_entitlements_subject', table_name='entitlements')
    op.drop_index('ix_entitlements_email', table_name='entitlements')
    op.drop_table('entitlements')
