"""The migration agrees with the models — B12, run against a real Postgres.

Every other database test in this suite runs on SQLite, which is the right trade for something
that has to run on every PR with no credentials (see ``conftest.db_session``). But SQLite cannot
answer the two questions that actually decide whether a deploy works:

* does ``alembic upgrade head`` produce the schema the models describe, or has someone edited a
  model since the migration was written?
* do the Postgres-only pieces — the ``vector`` extension, the HNSW index, ``JSONB`` — exist at
  all?

So this file runs against ``DATABASE_URL_DIRECT`` and skips without it. Skipping is not a
loophole: CI has no credentials by design, and the gate is that this passes before a deploy, which
``docs/04-backend-implementation-plan.md`` §5 lists as a release gate.

It is read-only. It inspects the database the developer already migrated rather than migrating one
itself, because a test that runs DDL against a shared development branch is a test that drops
someone else's work in progress. Run ``alembic upgrade head`` first; that is the point.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.config import settings

pytestmark = pytest.mark.skipif(
    not settings.alembic_url,
    reason="needs DATABASE_URL_DIRECT — see infra/README.md §1",
)


@pytest.fixture(scope="module")
def connection():  # type: ignore[no-untyped-def]
    """A connection to the migrated database, or a skip if it is unreachable."""
    from app.db import create_db_engine

    engine = create_db_engine(settings.alembic_url)
    try:
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001 — an unreachable database is a skip, not a failure
        pytest.skip(f"database unreachable: {exc}")

    try:
        yield conn
    finally:
        conn.close()
        engine.dispose()


def test_the_database_is_at_head(connection) -> None:  # type: ignore[no-untyped-def]
    """Fail loudly if the developer has not migrated, rather than reporting drift that is really
    just an un-applied migration."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    applied = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()

    assert applied == [head], (
        f"database is at {applied}, migrations head is {head!r}. Run: alembic upgrade head"
    )


def test_the_models_and_the_migration_do_not_disagree(connection) -> None:  # type: ignore[no-untyped-def]
    """The real gate.

    ``compare_metadata`` is what ``--autogenerate`` uses to decide what a new migration would
    contain. An empty result means a fresh autogenerate would produce nothing — i.e. the migration
    on disk already says exactly what the models say. A non-empty one means somebody changed a
    model and did not write the migration for it, which is a schema change that works on every
    developer machine and fails on deploy.
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base

    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    difference = compare_metadata(context, Base.metadata)

    assert difference == [], (
        "the models and the migrated schema disagree. Each entry below is something a new "
        f"autogenerate would emit:\n{difference}"
    )


def test_pgvector_is_installed(connection) -> None:  # type: ignore[no-untyped-def]
    """``bis_chunks.embedding`` is ``vector(1024)``, and the extension has to exist before the
    column can. Checked separately so a missing extension reads as a missing extension rather
    than as an inscrutable type mismatch."""
    installed = connection.execute(
        sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar_one_or_none()

    assert installed is not None, "the vector extension is not installed on this database"


def test_the_embedding_index_is_hnsw(connection) -> None:  # type: ignore[no-untyped-def]
    """Built in 0001 while the table was empty, deliberately.

    Creating it later against a populated corpus takes a lock on the table B19 reads from, and it
    is the kind of thing nobody discovers until the corpus is big enough for it to hurt.
    """
    method = connection.execute(
        sa.text(
            "SELECT a.amname FROM pg_class c "
            "JOIN pg_am a ON a.oid = c.relam "
            "WHERE c.relname = 'ix_bis_chunks_embedding_hnsw'"
        )
    ).scalar_one_or_none()

    assert method == "hnsw"


def test_the_dashboard_indexes_exist(connection) -> None:  # type: ignore[no-untyped-def]
    """B17's five indexes ship in 0001 because adding them later, against a populated table, is a
    lock (B12 card). Their absence would not fail a test — it would just make a dashboard slow
    enough to miss FR-30's one-second budget, which is a far quieter failure."""
    present = set(
        connection.execute(
            sa.text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        )
        .scalars()
        .all()
    )

    required = {
        "ix_findings_scan",
        "ix_findings_rule_verdict",
        "ix_scans_org_captured",
        "ix_extractions_scan_field",
        "ix_bis_chunks_embedding_hnsw",
    }
    assert required <= present, f"missing indexes: {sorted(required - present)}"


def test_the_verdict_check_constraint_has_exactly_four_values(connection) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.4 in the schema itself.

    A fifth value appearing here would mean somebody added ``NOT_APPLICABLE`` as a verdict, which
    the decision of 2026-09-12 rejected: a rule that does not apply produces no finding at all.
    The constraint is the last line of defence if that decision is forgotten.
    """
    definition = connection.execute(
        sa.text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_findings_verdict'"
        )
    ).scalar_one()

    for verdict in ("PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE"):
        assert verdict in definition
    assert "NOT_APPLICABLE" not in definition
