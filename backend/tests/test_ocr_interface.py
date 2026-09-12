"""OCR behind an interface — TRD FR-22, work package B6.

FR-22's acceptance test is unusual, and worth reading literally: *"swapping the engine via config
changes no calling code"*, and *"at least one alternate implementation must exist to prove the
interface holds"*. The deliverable is therefore the **interface**, not PaddleOCR. The adapter is
the replaceable part.

That matters for a reason beyond tidiness. `01-architecture.md` §9 keeps a cloud-OCR adapter
behind this interface as a fallback, and data residency may require an on-premise engine for a
government deployment. An interface that only ever had one implementation would not survive
either.

So the stub adapter is not scaffolding — it is the second implementation FR-22 demands, and it is
what every downstream test in this repository uses, because replaying a committed dump is
deterministic and needs no model, no image and no network.

**Nothing here converts a polygon to a millimetre.** OCR polygons include ascenders, descenders
and padding (CLAUDE.md §8); glyph measurement goes through connected components on the rectified
image, in B7. This suite asserts that boundary rather than trusting it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from app.services.vision.adapters.stub import StubOCREngine
from app.services.vision.ocr import (
    OCREngine,
    UnknownEngineError,
    Word,
    get_engine,
    register_engine,
)

FIXTURE = "roasted_chana_250g"


@pytest.fixture
def stub() -> StubOCREngine:
    return StubOCREngine.from_fixture(FIXTURE)


@pytest.fixture
def blank_image() -> np.ndarray:
    return np.full((800, 600), 240, dtype=np.uint8)


# --------------------------------------------------------------------------- the interface


def test_stub_satisfies_the_protocol(stub: StubOCREngine) -> None:
    """The runtime-checkable Protocol is the contract every adapter is held to."""
    assert isinstance(stub, OCREngine)


def test_paddle_adapter_satisfies_the_protocol_without_being_installed() -> None:
    """The adapter must conform structurally even where PaddleOCR is absent.

    Its heavy import is deferred to first use, so the interface can be verified — and the whole
    pipeline developed — on a machine with no OCR model downloaded.
    """
    from app.services.vision.adapters.paddle import PaddleOCREngine

    engine = PaddleOCREngine()
    assert isinstance(engine, OCREngine)


def test_two_working_implementations_exist() -> None:
    """FR-22 requires an alternate implementation to prove the interface holds."""
    from app.services.vision.adapters.paddle import PaddleOCREngine

    assert issubclass(StubOCREngine, OCREngine)
    assert issubclass(PaddleOCREngine, OCREngine)
    assert StubOCREngine is not PaddleOCREngine


# --------------------------------------------------------------------------- config swap


def test_engine_is_selected_by_config_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-22's acceptance test: swapping the engine changes no calling code.

    The caller asks for "the engine". Which class that is comes from configuration and nowhere
    else — no import of a concrete adapter at a call site, no branch on an engine name.
    """
    from app.services.vision import ocr

    monkeypatch.setattr(ocr.settings, "OCR_ENGINE", "stub")
    assert isinstance(get_engine(), StubOCREngine)

    monkeypatch.setattr(ocr.settings, "OCR_ENGINE", "paddle")
    from app.services.vision.adapters.paddle import PaddleOCREngine

    assert isinstance(get_engine(), PaddleOCREngine)


def test_an_explicit_name_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.vision import ocr

    monkeypatch.setattr(ocr.settings, "OCR_ENGINE", "paddle")

    assert isinstance(get_engine("stub"), StubOCREngine)


def test_an_unknown_engine_name_fails_loudly() -> None:
    """A typo in configuration must not silently fall back to a default engine — the pipeline
    would then run against something nobody chose."""
    with pytest.raises(UnknownEngineError, match="magic-ocr"):
        get_engine("magic-ocr")


def test_a_new_engine_can_be_registered_without_touching_the_resolver() -> None:
    """A third adapter — cloud OCR as an availability fallback, or an on-premise engine for a
    data-residency requirement — must be addable without editing this module's internals."""

    class NoopEngine:
        def detect_and_recognise(self, image: np.ndarray) -> list[Word]:
            return []

    register_engine("noop", NoopEngine)
    try:
        assert isinstance(get_engine("noop"), NoopEngine)
    finally:
        register_engine("noop", None)


# --------------------------------------------------------------------------- the Word contract


def test_words_carry_text_polygon_confidence_and_language(
    stub: StubOCREngine, blank_image: np.ndarray
) -> None:
    words = stub.detect_and_recognise(blank_image)

    assert words
    for word in words:
        assert word.text
        assert len(word.polygon) == 4, "a word polygon is four points"
        assert all(len(point) == 2 for point in word.polygon)
        assert 0.0 <= word.confidence <= 1.0
        assert word.language


def test_devanagari_survives_with_its_language_tag(
    stub: StubOCREngine, blank_image: np.ndarray
) -> None:
    """NFR-08: extraction handles Devanagari labels. The script must not be mangled, and the
    language tag must reach the extraction layer, which needs it to pick a normalisation table."""
    words = stub.detect_and_recognise(blank_image)

    hindi = [word for word in words if word.language == "hi"]
    assert hindi, "fixture should contain Devanagari"
    assert any("ऀ" <= character <= "ॿ" for character in hindi[0].text)
    assert hindi[0].text == "भुना चना"


def test_replay_is_deterministic(stub: StubOCREngine, blank_image: np.ndarray) -> None:
    """Every downstream test depends on this: the same dump yields the same words, every time."""
    first = stub.detect_and_recognise(blank_image)
    second = stub.detect_and_recognise(blank_image)

    assert [(w.text, w.confidence) for w in first] == [(w.text, w.confidence) for w in second]


def test_word_exposes_a_bounding_box_but_not_a_millimetre(
    stub: StubOCREngine, blank_image: np.ndarray
) -> None:
    """CLAUDE.md §8: OCR polygons are not glyph heights — they include ascenders, descenders and
    padding. A bounding box is useful for cropping a region to measure; it is not a measurement.

    So ``Word`` may expose pixel geometry and must not expose anything in millimetres.
    """
    word = stub.detect_and_recognise(blank_image)[0]

    _x, _y, width, height = word.bbox_px
    assert width > 0 and height > 0

    attribute_names = set(vars(word)) | {name for name in dir(word) if not name.startswith("_")}
    assert not any("_mm" in name for name in attribute_names), (
        "a Word must not carry millimetres; measurement is B7's job, from the rectified image"
    )


# --------------------------------------------------------------------------- boundaries


def test_ocr_module_does_not_convert_pixels_to_millimetres() -> None:
    """Source-level guard on the same boundary: nothing in the OCR layer may reference the
    metric scale. If it did, a polygon would eventually be divided by it."""
    from app.services.vision import ocr

    source = Path(ocr.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]

    assert "PX_PER_MM" not in source
    assert "px_per_mm" not in source


def test_the_interface_does_not_import_an_adapter_at_module_scope() -> None:
    """Importing the interface must not drag in an engine's dependencies.

    The registry names its built-in adapters — that is the point of a registry — but it imports
    them inside factory functions, so ``import ocr`` costs nothing. Only module-scope imports are
    inspected here; a deferred one is the design, not a violation.
    """
    from app.services.vision import ocr

    tree = ast.parse(Path(ocr.__file__).read_text(encoding="utf-8"))  # type: ignore[arg-type]

    module_scope: set[str] = set()
    for node in tree.body:  # top level only, deliberately not ast.walk
        if isinstance(node, ast.Import):
            module_scope.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_scope.add(node.module)

    offenders = sorted(
        name for name in module_scope if "adapters" in name or "paddle" in name.lower()
    )
    assert not offenders, f"ocr.py imports an adapter at module scope: {offenders}"


def test_importing_the_interface_does_not_load_a_heavy_engine() -> None:
    """The property the previous test exists to protect, asserted directly.

    A developer with no PaddleOCR installed must be able to import the OCR layer, build the
    pipeline around it, and run the whole suite against the stub.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.services.vision.ocr as m; "
            "print(any(k.startswith('paddle') for k in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "False", "importing ocr.py pulled in a heavy engine"


def test_paddle_adapter_reports_a_useful_error_when_the_engine_is_missing() -> None:
    """A missing heavy dependency must say what is missing and how to install it, rather than
    surfacing an ImportError from three frames deep."""
    from app.services.vision.adapters.paddle import PaddleOCREngine

    engine = PaddleOCREngine()
    try:
        import paddleocr  # noqa: F401
    except Exception:  # noqa: BLE001 - any failure to load means the engine is unavailable
        with pytest.raises(RuntimeError, match="paddleocr"):
            engine.detect_and_recognise(np.full((64, 64), 255, dtype=np.uint8))
    else:  # pragma: no cover - only where PaddleOCR is actually installed
        pytest.skip("PaddleOCR is installed; the missing-dependency path cannot be exercised")
