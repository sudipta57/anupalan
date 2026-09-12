"""Replay OCR adapter — the second implementation TRD FR-22 requires.

Not scaffolding. FR-22 says *"at least one alternate implementation must exist to prove the
interface holds"*, and this is it: a full ``OCREngine`` that returns recorded words instead of
running a model.

It is also what every downstream test in this repository uses. Extraction, the rules engine and
the pipeline all need OCR output, and none of them should need a model, a GPU, an image or a
network to be tested. Replaying a committed dump makes those tests deterministic, which matters
more here than usual: ``evaluate()`` is required to be byte-identical across runs (FR-25), and a
non-deterministic OCR stage upstream would make that untestable end to end.

Dumps live in ``tests/fixtures/ocr/`` and are recorded from a real engine run, so the shapes are
real even though the execution is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from app.services.vision.ocr import Word

DEFAULT_FIXTURE = "roasted_chana_250g"

_FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "ocr"


class StubOCREngine:
    """An ``OCREngine`` that returns a fixed word list, ignoring the image it is given."""

    def __init__(self, words: list[Word]) -> None:
        self._words = list(words)

    @classmethod
    def from_fixture(cls, name: str = DEFAULT_FIXTURE) -> StubOCREngine:
        """Load a recorded dump from ``tests/fixtures/ocr/<name>.json``."""
        path = _FIXTURE_ROOT / f"{name}.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"OCR fixture {name!r} not found at {path}. "
                "Recorded dumps live in tests/fixtures/ocr/ — see tests/fixtures/README.md."
            )
        raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return cls([_word_from_dict(entry) for entry in raw])

    @classmethod
    def from_words(cls, words: list[Word]) -> StubOCREngine:
        """Build directly from words, for a test that needs a shape no fixture covers."""
        return cls(words)

    def detect_and_recognise(self, image: npt.NDArray[np.uint8]) -> list[Word]:
        """Return the recorded words.

        The image is accepted and ignored — the signature is the interface's, not this
        implementation's convenience.
        """
        del image
        return list(self._words)


def _word_from_dict(entry: dict[str, Any]) -> Word:
    return Word(
        text=entry["text"],
        polygon=tuple((float(x), float(y)) for x, y in entry["polygon"]),
        confidence=float(entry["confidence"]),
        language=entry.get("language", "en"),
    )


__all__ = ["DEFAULT_FIXTURE", "StubOCREngine"]
