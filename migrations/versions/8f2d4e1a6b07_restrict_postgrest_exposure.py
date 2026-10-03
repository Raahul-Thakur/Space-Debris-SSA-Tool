"""restrict postgrest exposure

Supabase publishes every table in ``public`` through PostgREST, and the anon
key that authorises those requests is shipped to the browser. This platform
never reads its data that way: the frontend holds a Supabase JWT only to call
the FastAPI service, which connects to Postgres as the owning role and applies
its own role and quota checks.

So the whole of PostgREST is attack surface with nothing behind it. This
migration closes it, with two independent locks:

1. Privileges are revoked from ``anon`` and ``authenticated``, including the
   default privileges that would otherwise be granted to tables created later.
   PostgREST cannot see a table it has no grant on.
2. Row level security is enabled on every table, with no policy attached. An
   empty policy set denies every row to every non-owning role, so a privilege
   granted back by mistake still yields nothing.

The owning role bypasses RLS (there is no FORCE), which is what lets the API
keep working untouched.

Both steps are Postgres-only; on SQLite, used for local development, this is a
no-op.

Revision ID: 8f2d4e1a6b07
Revises: 4c91a7d2f8b3
Create Date: 2026-10-03 18:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = '8f2d4e1a6b07'
down_revision: str | Sequence[str] | None = '4c91a7d2f8b3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Roles PostgREST authenticates as. They are absent from a plain Postgres
#: instance, so every statement that names them is guarded.
EXPOSED_ROLES = ('anon', 'authenticated')


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


def upgrade() -> None:
    if not _is_postgres():
        return

    for role in EXPOSED_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role};
                    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role};
                    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {role};
                    REVOKE ALL ON SCHEMA public FROM {role};
                    -- Tables added by a later migration must not inherit the
                    -- grants Supabase sets up for the owning role.
                    ALTER DEFAULT PRIVILEGES IN SCHEMA public
                        REVOKE ALL ON TABLES FROM {role};
                    ALTER DEFAULT PRIVILEGES IN SCHEMA public
                        REVOKE ALL ON SEQUENCES FROM {role};
                    ALTER DEFAULT PRIVILEGES IN SCHEMA public
                        REVOKE ALL ON FUNCTIONS FROM {role};
                END IF;
            END
            $$;
            """
        )

    # Every table, rather than a fixed list, so a table introduced by a future
    # migration cannot be forgotten here.
    op.execute(
        """
        DO $$
        DECLARE
            target record;
        BEGIN
            FOR target IN
                SELECT tablename FROM pg_tables WHERE schemaname = 'public'
            LOOP
                EXECUTE format(
                    'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',
                    target.tablename
                );
            END LOOP;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Reopen the schema to PostgREST.

    This restores the exposure the upgrade exists to remove, so it is here for
    migration symmetry rather than as something to run against a live project.
    """
    if not _is_postgres():
        return

    op.execute(
        """
        DO $$
        DECLARE
            target record;
        BEGIN
            FOR target IN
                SELECT tablename FROM pg_tables WHERE schemaname = 'public'
            LOOP
                EXECUTE format(
                    'ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY',
                    target.tablename
                );
            END LOOP;
        END
        $$;
        """
    )

    for role in EXPOSED_ROLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    GRANT USAGE ON SCHEMA public TO {role};
                    ALTER DEFAULT PRIVILEGES IN SCHEMA public
                        GRANT ALL ON TABLES TO {role};
                    ALTER DEFAULT PRIVILEGES IN SCHEMA public
                        GRANT ALL ON SEQUENCES TO {role};
                    ALTER DEFAULT PRIVILEGES IN SCHEMA public
                        GRANT ALL ON FUNCTIONS TO {role};
                    GRANT ALL ON ALL TABLES IN SCHEMA public TO {role};
                    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {role};
                    GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO {role};
                END IF;
            END
            $$;
            """
        )
