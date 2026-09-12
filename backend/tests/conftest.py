"""Shared pytest fixtures and the golden-file contract (B0).

Two things live here:

* the ``client`` fixture over the real FastAPI app;
* the fixture loaders and the golden-file helper every pipeline test uses.

**The golden-file rule (CLAUDE.md §6).** A golden file pins committed output. A diff in one is a
deliberate, reviewed change, never a silent update. ``--update-golden`` exists so a reviewed
change is one command rather than hand-editing JSON, and it is off by default, prints a loud
warning, and fails the run it rewrites — so a rewrite can never be mistaken for a pass.
"""

from __future__ import annotations

import json
import uuid
import warnings
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- options


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--update-golden``."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help=(
            "Rewrite golden fixture files from the current output. "
            "Off by default. The run still FAILS, so the rewrite must be reviewed and re-run."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``golden`` marker (``--strict-markers`` is on)."""
    config.addinivalue_line("markers", "golden: pins committed output; a diff must be reviewed")


# --------------------------------------------------------------------------- app


@pytest.fixture(autouse=True)
def _rate_limiting_off() -> Iterator[None]:
    """Disable rate limiting for every suite except the one that tests it.

    The whole suite reaches the app from one client address, so a per-IP ceiling meant for a
    minute of real traffic is exhausted by a few test files and every later test gets a 429 for
    reasons that have nothing to do with what it is checking.

    Turning a guard off in conftest is worth being uneasy about, which is why
    ``tests/test_hardening.py`` turns it back on explicitly and is the only place the limiter's
    behaviour is asserted. The counter is reset on the way in and out, so no test can inherit
    another's count.
    """
    from app.config import settings
    from app.services.ratelimit import reset_limiter

    original = settings.RATE_LIMIT_ENABLED
    settings.RATE_LIMIT_ENABLED = False
    reset_limiter()
    try:
        yield
    finally:
        settings.RATE_LIMIT_ENABLED = original
        reset_limiter()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient over the real app, with exception handlers active.

    ``raise_server_exceptions=False`` so handler behaviour is what the client sees — an
    unhandled error must surface as the error envelope, not as a propagated exception.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to resolve a name or open a connection.

    The ingredient cross-check (B29, B30) fetches manufacturer websites, and CI must never do that:
    a suite that passes only while some brand's site is up is not a suite. Its tests inject a fake
    resolver and a fake transport, and this fixture proves they did — a code path that quietly fell
    back to the real network fails here instead of passing on a developer's laptop.
    """
    import socket

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a test tried to use the network; inject a fake resolver/transport")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


# --------------------------------------------------------------------------- database


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session over an in-memory SQLite database with the full schema built.

    Why SQLite and not Neon: ``CLAUDE.md`` §6 requires the org-isolation suite to run on **every
    PR**, and CI holds no datastore credentials (``.github/workflows/ci.yml``). What these suites
    actually test is the repository's filtering and the role matrix — logic that lives in Python
    and behaves identically on either engine. The Postgres-specific column types are declared
    through ``with_variant`` in ``app/models/base.py``, so this is the same model file production
    uses, not a parallel one that could drift.

    What SQLite cannot check — that the migration and the models agree, that pgvector and the HNSW
    index exist — is checked by ``tests/test_migration.py``, which runs against a real Neon branch
    and skips without credentials.

    Foreign keys are switched on explicitly. SQLite ignores them by default, and the composite
    ``(scan_id, org_id)`` keys are the constraint that makes a mis-scoped row impossible — a
    guarantee worth actually exercising.
    """
    from app.models import Base

    # StaticPool and check_same_thread: TestClient runs the app in a worker thread, and an
    # in-memory SQLite database lives inside a single connection that is otherwise bound to the
    # thread that opened it. Without both, an API test sees an empty schema — or a
    # ProgrammingError at teardown — for reasons that have nothing to do with what it is testing.
    engine = sa.create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_org(session: Session, *, name: str, mode: str = "enforcement") -> Any:
    """Insert an org and return it."""
    from app.models import Org

    org = Org(id=uuid.uuid4(), name=name, mode=mode, state="West Bengal")
    session.add(org)
    session.flush()
    return org


def make_user(session: Session, *, org: Any, phone: str, role: str = "inspector") -> Any:
    """Insert a user in an org and return it."""
    from app.models import User

    user = User(id=uuid.uuid4(), org_id=org.id, role=role, phone=phone, full_name=f"user {phone}")
    session.add(user)
    session.flush()
    return user


def make_scan(session: Session, *, org: Any, status: str = "complete") -> Any:
    """Insert a minimally complete scan in an org and return it."""
    from app.models import Scan

    scan = Scan(
        id=uuid.uuid4(),
        org_id=org.id,
        status=status,
        captured_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={},
        profile={"surface": "printed", "net_qty_in_g_or_ml": 250.0},
    )
    session.add(scan)
    session.flush()
    return scan


# --------------------------------------------------------------------------- fixture loaders


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(
            f"fixture not found: {path}\n"
            f"Fixtures are committed data — see {FIXTURES / 'README.md'} for the layout."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile(name: str) -> dict[str, Any]:
    """Load ``tests/fixtures/profiles/<name>.json``."""
    return dict(_read_json(FIXTURES / "profiles" / f"{name}.json"))


def load_ocr_dump(name: str) -> list[dict[str, Any]]:
    """Load ``tests/fixtures/ocr/<name>.json`` — a recorded OCR word list.

    This is what the stub OCR adapter (B6) replays, so extraction and rules tests never need a
    model, an image, or a network.
    """
    return list(_read_json(FIXTURES / "ocr" / f"{name}.json"))


def load_expected_findings(name: str) -> dict[str, Any]:
    """Load ``tests/fixtures/findings/<name>.json`` — a golden findings blob."""
    return dict(_read_json(FIXTURES / "findings" / f"{name}.json"))


@pytest.fixture
def fixtures_dir() -> Path:
    """The committed fixture root."""
    return FIXTURES


# --------------------------------------------------------------------------- golden files


@pytest.fixture
def assert_golden(request: pytest.FixtureRequest) -> Any:
    """Compare a payload against a committed golden file.

        def test_pipeline(assert_golden):
            assert_golden("scan_250g_printed", produce_findings())

    Serialisation is canonical — sorted keys, two-space indent, trailing newline — so a diff is
    a content change and never a formatting one.
    """
    update: bool = bool(request.config.getoption("--update-golden"))

    def _assert(name: str, payload: Any, *, subdir: str = "findings") -> None:
        path = FIXTURES / subdir / f"{name}.json"
        serialised = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

        if update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialised, encoding="utf-8")
            warnings.warn(
                f"golden file rewritten: {path}. Review the diff before committing.",
                stacklevel=2,
            )
            pytest.fail(
                f"--update-golden rewrote {path.name}. "
                "This run fails by design: review the diff, then re-run without the flag."
            )

        if not path.is_file():
            pytest.fail(
                f"golden file missing: {path}\n"
                f"Create it with:  pytest {request.node.nodeid} --update-golden"
            )

        expected = path.read_text(encoding="utf-8")
        assert serialised == expected, (
            f"output differs from the golden file {path.name}.\n"
            "A golden diff must be a deliberate, reviewed change (CLAUDE.md §6). "
            "If this change is intended, re-run with --update-golden and commit the diff."
        )

    return _assert
