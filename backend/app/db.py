"""Database engine and session factory, against Neon (serverless Postgres + pgvector).

Deliberately minimal: engine construction, a session scope and a connectivity probe. The data
layer — models for every table in docs/01-architecture.md §8, and the org-scoped repository base
class that makes cross-org access impossible — is P2.2 work (TRD DR-xx, SR-xx).

Two Neon-specific things are load-bearing here, and both fail intermittently rather than loudly
if you remove them:

* **``prepare_threshold=None``.** Neon's pooled endpoint is pgbouncer in transaction mode.
  psycopg 3 starts using server-side prepared statements after a few executions of the same
  query, and pgbouncer cannot route those — you get ``prepared statement "_pg3_0" does not
  exist`` under load, never in testing.
* **``pool_pre_ping`` + ``pool_recycle``.** An idle Neon branch suspends, so pooled connections
  go stale. Pre-ping turns a dead connection into a transparent reconnect instead of an error.

Migrations use the **direct** endpoint, not the pooled one — see ``alembic/env.py`` and
``infra/README.md`` §1.

The engine is built lazily. There is no localhost fallback: an unset ``DATABASE_URL`` must surface
as a clear configuration error, not as a silent connection to an unrelated local database.

No model is defined here. ``app/models/`` owns those.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base every model inherits from.

    Declared here and nowhere else so ``alembic/env.py`` has one ``metadata`` to autogenerate
    against. No table is defined on it yet — models are P2.2 and live in ``app/models/``.
    """


class DatabaseNotConfiguredError(RuntimeError):
    """``DATABASE_URL`` is unset. Raised instead of falling back to a local default."""


def create_db_engine(url: str, *, echo: bool = False) -> Engine:
    """Build an engine with the settings Neon requires.

    Used for both the application engine and Alembic's, so the pgbouncer and cold-start handling
    cannot drift between them.
    """
    if not url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Copy backend/.env.example to backend/.env and paste your "
            "Neon connection strings — see infra/README.md §1."
        )

    return create_engine(
        url,
        future=True,
        echo=echo,
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
        connect_args={
            "connect_timeout": settings.DB_CONNECT_TIMEOUT,
            # Required for Neon's pooled endpoint. See the module docstring.
            "prepare_threshold": None,
        },
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine, building it on first use.

    Raises:
        DatabaseNotConfiguredError: ``DATABASE_URL`` is unset.
    """
    return create_db_engine(settings.DATABASE_URL, echo=settings.DEBUG)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on failure."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> None:
    """Raise if the database is unset or unreachable. Used by ``GET /health``."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
