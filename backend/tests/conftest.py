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
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient over the real app, with exception handlers active.

    ``raise_server_exceptions=False`` so handler behaviour is what the client sees — an
    unhandled error must surface as the error envelope, not as a propagated exception.
    """
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


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
