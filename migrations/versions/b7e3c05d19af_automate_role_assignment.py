"""automate role assignment

Roles were previously set by hand in Supabase, which meant a new account had
whatever ``app_metadata`` happened to contain and the platform owner had to
remember to promote themselves. This replaces that with a Supabase custom
access token hook: a function the auth service calls while minting a JWT,
which stamps the role into the claims the API already reads.

The mapping lives in ``role_grants``, keyed by email:

  * an exact email match wins, which is how the owner gets ``admin`` and how
    ``operator`` is granted on request, since operator is a job function
    rather than something bought or self-selected;
  * otherwise the ``*`` row supplies the default for every new account.

Keeping the default in a row rather than in this function means raising it
from ``viewer`` to ``analyst``, once per-user data ownership exists, is one
UPDATE against one row -- no migration, no redeploy, and it applies to
everyone's next sign-in.

Nothing is backfilled. The hook runs at token issuance, so existing accounts
pick up their role the next time they sign in.

Enabling it is a dashboard step, because Supabase registers hooks outside the
database: Authentication -> Hooks -> Customize Access Token (JWT) Claims,
pointing at ``public.custom_access_token_hook``.

Revision ID: b7e3c05d19af
Revises: 8f2d4e1a6b07
Create Date: 2026-10-03 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b7e3c05d19af'
down_revision: str | Sequence[str] | None = '8f2d4e1a6b07'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The role every account gets unless its email is listed explicitly. Deliberately
#: the least privileged one: analyst can write to the ontology, which is still a
#: single shared dataset, so self-service analyst has to wait for tenancy.
DEFAULT_ROLE = 'viewer'

#: The platform owner.
OWNER_EMAIL = 'raahul.thakurr01@gmail.com'

#: Supabase's auth service connects as this role and is what executes the hook.
AUTH_ADMIN = 'supabase_auth_admin'


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


def upgrade() -> None:
    op.create_table(
        'role_grants',
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=32), nullable=False),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column(
            'granted_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint('email', name='pk_role_grants'),
        sa.CheckConstraint(
            "role IN ('viewer', 'analyst', 'operator', 'admin')",
            name='ck_role_grants_known_role',
        ),
    )

    grants = sa.table(
        'role_grants',
        sa.column('email', sa.String),
        sa.column('role', sa.String),
        sa.column('note', sa.Text),
    )
    op.bulk_insert(
        grants,
        [
            {
                'email': '*',
                'role': DEFAULT_ROLE,
                'note': (
                    'Default for every account without an explicit row. '
                    'Raise to analyst once the ontology is per-tenant.'
                ),
            },
            {'email': OWNER_EMAIL, 'role': 'admin', 'note': 'Platform owner.'},
        ],
    )

    if not _is_postgres():
        # SQLite development keeps the table (so the rows can be inspected and
        # tested) but has no Supabase auth service to install a hook into.
        return

    # The lockdown migration enabled RLS on every table that existed then; this
    # one arrives later and has to close itself.
    op.execute("ALTER TABLE public.role_grants ENABLE ROW LEVEL SECURITY")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = '{AUTH_ADMIN}'
            ) THEN
                -- Not a Supabase project. The table is still useful as the
                -- record of who holds which role.
                RETURN;
            END IF;

            GRANT USAGE ON SCHEMA public TO {AUTH_ADMIN};
            GRANT SELECT ON public.role_grants TO {AUTH_ADMIN};

            -- RLS is on with no policy, which denies every non-owning role.
            -- The auth service needs an explicit way through, and only to read.
            DROP POLICY IF EXISTS role_grants_auth_admin_read ON public.role_grants;
            CREATE POLICY role_grants_auth_admin_read ON public.role_grants
                FOR SELECT TO {AUTH_ADMIN} USING (true);
        END
        $$;
        """
    )

    # SECURITY INVOKER (the default): the hook runs as the auth service, which
    # holds exactly the one grant and one policy above. A SECURITY DEFINER
    # function would run as the table owner and could read anything in the
    # database, which this does not need.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.custom_access_token_hook(event jsonb)
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SET search_path = public
        AS $$
        DECLARE
            claims        jsonb;
            metadata      jsonb;
            caller_email  text;
            resolved_role text;
        BEGIN
            claims := COALESCE(event -> 'claims', '{{}}'::jsonb);
            caller_email := lower(COALESCE(claims ->> 'email', ''));

            SELECT role INTO resolved_role
            FROM public.role_grants
            WHERE email = caller_email;

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
                -- A hook that raises blocks sign-in entirely. Failing open to
                -- the unmodified event is safe here because the API treats a
                -- missing or unrecognised role as viewer.
                RETURN event;
        END;
        $$;
        """
    )

    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{AUTH_ADMIN}') THEN
                GRANT EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb)
                    TO {AUTH_ADMIN};
            END IF;
            -- Nobody else may call it, and in particular no browser-facing role.
            REVOKE EXECUTE ON FUNCTION public.custom_access_token_hook(jsonb)
                FROM PUBLIC, anon, authenticated;
        EXCEPTION
            WHEN undefined_object THEN
                NULL;  -- anon/authenticated absent outside Supabase
        END
        $$;
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute(
            "DROP FUNCTION IF EXISTS public.custom_access_token_hook(jsonb)"
        )
        op.execute(
            "DROP POLICY IF EXISTS role_grants_auth_admin_read ON public.role_grants"
        )
    op.drop_table('role_grants')
