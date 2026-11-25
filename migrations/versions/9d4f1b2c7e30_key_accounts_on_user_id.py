"""key accounts on the user id, not the email

Every work product (screening runs and jobs, commands, watch-list entries,
cases, decisions, alerts, scenarios, audit actions) recorded its owner as the
signed-in email. An account that changed its email lost every row it owned,
and role grants matched on email alone.

The API now records the auth subject (the Supabase user id), which never
changes. This migration:

  * rewrites existing owners from email to user id, using Supabase's
    ``auth.users`` table, for rows whose email belongs to a known account.
    Rows of an email with no account are left as they are; platform rows
    (NULL) are untouched;
  * adds ``role_grants.user_id``, fills it from ``auth.users``, and makes the
    token hook match on it first, then on the email of a grant not yet bound
    to an account, then on the ``*`` default. A grant made by email before
    the person signs up still works; once bound, only that account holds it.

Outside Supabase (no ``auth.users``) only the column is added.

Revision ID: 9d4f1b2c7e30
Revises: a83b6f1d2c94
Create Date: 2026-11-25 07:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '9d4f1b2c7e30'
down_revision: str | Sequence[str] | None = 'a83b6f1d2c94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ROLE = 'viewer'

#: (table, column) pairs that hold an owner.
OWNER_COLUMNS = (
    ('screening_runs', 'actor'),
    ('monitoring_cases', 'actor'),
    ('maneuver_scenarios', 'actor'),
    ('alerts', 'actor'),
    ('alerts', 'acknowledged_by'),
    ('operator_decisions', 'actor'),
    ('audit_actions', 'actor'),
    ('monitored_objects', 'added_by'),
    ('screening_jobs', 'actor'),
    ('command_executions', 'actor'),
)


def _hook(match_user_id: bool) -> str:
    by_id = (
        """
            SELECT role INTO resolved_role
            FROM public.role_grants
            WHERE user_id = caller_id;
"""
        if match_user_id
        else ""
    )
    # Once a grant is bound to an account, its email no longer grants
    # anything: whoever holds that address later is not that account.
    email_guard = " AND user_id IS NULL" if match_user_id else ""
    return f"""
        CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SET search_path = public
        AS $$
        DECLARE
            claims        jsonb;
            metadata      jsonb;
            caller_id     text;
            caller_email  text;
            resolved_role text;
        BEGIN
            claims := COALESCE(event -> 'claims', '{{}}'::jsonb);
            caller_id := COALESCE(event ->> 'user_id', claims ->> 'sub', '');
            caller_email := lower(COALESCE(claims ->> 'email', ''));
{by_id}
            IF resolved_role IS NULL THEN
                SELECT role INTO resolved_role
                FROM public.role_grants
                WHERE email = caller_email{email_guard};
            END IF;

            IF resolved_role IS NULL THEN
                SELECT role INTO resolved_role
                FROM public.role_grants
                WHERE email = '*';
            END IF;

            resolved_role := COALESCE(resolved_role, '{DEFAULT_ROLE}');

            metadata := COALESCE(claims -> 'app_metadata', '{{}}'::jsonb);
            metadata := jsonb_set(metadata, '{{role}}', to_jsonb(resolved_role));
            claims := jsonb_set(claims, '{{app_metadata}}', metadata);

            RETURN jsonb_set(event, '{{claims}}', claims);
        EXCEPTION
            WHEN OTHERS THEN
                -- Failing open to the unmodified event is safe: the API treats
                -- a missing or unrecognised role as viewer.
                RETURN event;
        END;
        $$;
        """


def _has_supabase_auth() -> bool:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return False
    return bind.execute(sa.text("SELECT to_regclass('auth.users') IS NOT NULL")).scalar()


def upgrade() -> None:
    with op.batch_alter_table('role_grants') as batch:
        batch.add_column(sa.Column('user_id', sa.String(length=64), nullable=True))
        batch.create_unique_constraint('uq_role_grants_user_id', ['user_id'])

    if op.get_bind().dialect.name != 'postgresql':
        return
    # CREATE OR REPLACE keeps the function's grants (EXECUTE for the auth
    # service only), set up by b7e3c05d19af.
    op.execute(_hook(match_user_id=True))
    if not _has_supabase_auth():
        return

    op.execute(
        """
        UPDATE public.role_grants g SET user_id = u.id::text
        FROM auth.users u
        WHERE g.email <> '*' AND lower(u.email) = lower(g.email)
        """
    )
    for table, column in OWNER_COLUMNS:
        op.execute(
            f"""
            UPDATE public.{table} t SET {column} = u.id::text
            FROM auth.users u
            WHERE t.{column} IS NOT NULL AND lower(t.{column}) = lower(u.email)
            """
        )


def downgrade() -> None:
    # Owners are not rewritten back to emails: an account may have changed
    # its email since, and the API that reads them as ids would be gone.
    if op.get_bind().dialect.name == 'postgresql':
        op.execute(_hook(match_user_id=False))
    with op.batch_alter_table('role_grants') as batch:
        batch.drop_constraint('uq_role_grants_user_id', type_='unique')
        batch.drop_column('user_id')
