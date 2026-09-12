"""Alembic environment, wired to ``app.config``.

The connection string is **not** in ``alembic.ini``. It is read via ``app.config.settings``, so
there is one source of truth and no credential in a committed file.

Migrations run against Neon's **direct** endpoint (``DATABASE_URL_DIRECT``), never the pooled
one. The pooled endpoint is pgbouncer in transaction mode, which cannot run DDL reliably inside
a transaction. It falls back to ``DATABASE_URL`` if the direct URL is unset — that usually works
and occasionally does not, which is the worst failure mode for a migration.

**There are no migrations yet.** ``alembic/versions/`` is empty on purpose — the data layer is
P2.2. Writing the first migration needs approval first (CLAUDE.md §7), and it should cover the
tables in docs/01-architecture.md §8 in one reviewed change.

    alembic revision --autogenerate -m "message"
    alembic upgrade head
"""

from logging.config import fileConfig

# app.models is imported for its side effect: importing it registers every model on
# Base.metadata so --autogenerate can see them. The package is an empty placeholder today; the
# import is here so the first model added is picked up without anyone having to remember it.
import app.models  # noqa: F401
from alembic import context
from app.config import settings
from app.db import Base, create_db_engine

config = context.config

# Inject the application's URL, overriding whatever alembic.ini does or does not say.
config.set_main_option("sqlalchemy.url", settings.alembic_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``alembic upgrade head --sql``)."""
    context.configure(
        url=settings.alembic_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run migrations against the live database."""
    # Built through app.db so the Neon connect settings cannot drift from the application's.
    connectable = create_db_engine(settings.alembic_url)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
