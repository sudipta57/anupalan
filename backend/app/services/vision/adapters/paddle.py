"""PaddleOCR adapter — the production OCR engine (architecture §5 S4, §9).

PP-OCRv4, self-hosted, English and Devanagari. Chosen for data residency and for raw word
polygons, not on cost: `01-architecture.md` §9 is explicit that cloud OCR runs about ₹0.10 to ₹0.15
per image, which is negligible against the pricing, so do not re-argue this one on cost.

**The import is deferred to first use.** PaddleOCR and paddlepaddle are large, pull native
wheels, and download model weights on first run. Importing this module must not require any of
that, so the whole pipeline can be developed and tested on a machine that has never installed
them — the stub adapter stands in, and the interface is verified against both.

A missing dependency surfaces as a clear instruction, not an ImportError from three frames deep.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from app.services.vision.ocr import Word

_SCRIPT_TO_LANGUAGE = {"devanagari": "hi", "latin": "en"}


class OCREngineUnavailableError(RuntimeError):
    """PaddleOCR is not installed, or its models could not be loaded."""


class PaddleOCREngine:
    """An ``OCREngine`` backed by PaddleOCR PP-OCRv4."""

    def __init__(self, *, language: str = "en", use_angle_classifier: bool = True) -> None:
        self.language = language
        self.use_angle_classifier = use_angle_classifier
        self._reader: Any | None = None

    def _load(self) -> Any:
        """Construct the underlying reader on first use.

        Raises:
            OCREngineUnavailableError: paddleocr is not installed or the models are unavailable.
        """
        if self._reader is not None:
            return self._reader

        try:
            from paddleocr import PaddleOCR
        except Exception as exc:
            raise OCREngineUnavailableError(
                "paddleocr is not available. Install it with "
                "`pip install paddleocr paddlepaddle`, or set OCR_ENGINE=stub to run against "
                "recorded OCR dumps. See backend/README.md."
            ) from exc

        try:
            self._reader = PaddleOCR(
                use_angle_cls=self.use_angle_classifier,
                lang=self.language,
                show_log=False,
            )
        except Exception as exc:
            raise OCREngineUnavailableError(
                f"paddleocr is installed but could not initialise: {exc}"
            ) from exc

        return self._reader

    def detect_and_recognise(self, image: npt.NDArray[np.uint8]) -> list[Word]:
        """Detect and recognise text, returning word-level polygons.

        Polygons are returned exactly as the engine produced them. Nothing here reshapes them
        into a measurement — that boundary is the subject of CLAUDE.md §8.

        Raises:
            OCREngineUnavailableError: the engine could not be loaded.
        """
        reader = self._load()

        try:
            raw = reader.ocr(image, cls=self.use_angle_classifier)
        except Exception as exc:
            raise OCREngineUnavailableError(f"paddleocr failed on this image: {exc}") from exc

        return list(_to_words(raw))


def _to_words(raw: Any) -> list[Word]:
    """Convert PaddleOCR's nested output into ``Word`` objects.

    PaddleOCR returns one list per image; this adapter is called per image, so the first element
    is taken. An empty page yields an empty list, never ``None``, so callers never branch on it.
    """
    if not raw:
        return []

    page = raw[0] if isinstance(raw[0], list) else raw
    if not page:
        return []

    words: list[Word] = []
    for entry in page:
        try:
            polygon_raw, (text, confidence) = entry[0], entry[1]
        except (TypeError, ValueError, IndexError):
            continue

        if not text:
            continue

        polygon = tuple((float(point[0]), float(point[1])) for point in polygon_raw)
        words.append(
            Word(
                text=str(text),
                polygon=polygon,
                confidence=float(confidence),
                language=_language_of(str(text)),
            )
        )
    return words


def _language_of(text: str) -> str:
    """Tag the script a word is written in.

    The extraction layer needs this: a Devanagari numeral and a Latin one normalise differently,
    and NFR-08 requires Devanagari labels to survive the whole pipeline.
    """
    if any("ऀ" <= character <= "ॿ" for character in text):
        return _SCRIPT_TO_LANGUAGE["devanagari"]
    return _SCRIPT_TO_LANGUAGE["latin"]


__all__ = ["OCREngineUnavailableError", "PaddleOCREngine"]
