"""Text detection and recognition behind an interface — TRD FR-22, architecture §5 S4.

**The interface is the deliverable here; the engine is the replaceable part.** FR-22 asks that
swapping the engine change no calling code, and requires a second working implementation to prove
the interface holds. That is not tidiness for its own sake: `01-architecture.md` §9 keeps a
cloud-OCR adapter behind this boundary as an availability fallback, and a government deployment
may have to run wholly on-premise. An interface with exactly one implementation would survive
neither.

**Polygons are not measurements.** A ``Word`` carries pixel geometry — enough to crop the region
a declaration occupies — and deliberately carries nothing in millimetres. OCR boxes include
ascenders, descenders and padding, so a box height is not a glyph height (CLAUDE.md §8). Metric
measurement happens in ``metrology.py``, by connected components on the rectified image. Nothing
in this module imports the metric scale, so a polygon cannot accidentally be divided by it.

No vendor name appears in this module. Which engine runs is decided by ``settings.OCR_ENGINE``
and resolved through the registry below.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from app.config import settings

Point = tuple[float, float]
Polygon = Sequence[Point]


class UnknownEngineError(LookupError):
    """The configured or requested OCR engine name is not registered.

    Raised rather than falling back to a default: a typo in configuration must not quietly run
    the pipeline against an engine nobody chose.
    """


@dataclass(frozen=True)
class Word:
    """One recognised word with the region it was read from.

    ``polygon`` is four points in image pixel coordinates, in reading order from the top-left
    corner. It locates text; it does not size it.
    """

    text: str
    polygon: tuple[Point, ...]
    confidence: float
    language: str = "en"
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def bbox_px(self) -> tuple[float, float, float, float]:
        """Axis-aligned bounds as ``(x, y, width, height)`` in pixels.

        For cropping a region to measure, never for measuring it — see the module docstring.
        """
        xs = [point[0] for point in self.polygon]
        ys = [point[1] for point in self.polygon]
        return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @property
    def is_devanagari(self) -> bool:
        """True when the text contains Devanagari, which NFR-08 requires end-to-end support for."""
        return any("ऀ" <= character <= "ॿ" for character in self.text)


@runtime_checkable
class OCREngine(Protocol):
    """What every OCR adapter must provide.

    One method, deliberately. A wider interface would be harder for an alternate engine to
    satisfy, and the pipeline needs exactly this.
    """

    def detect_and_recognise(
        self, image: npt.NDArray[np.uint8]
    ) -> list[Word]: ...


_REGISTRY: dict[str, Callable[[], OCREngine]] = {}


def register_engine(name: str, factory: Callable[[], OCREngine] | None) -> None:
    """Register (or, with ``None``, remove) an engine under ``name``.

    Exists so a third adapter — cloud OCR as a fallback, or an on-premise engine chosen for data
    residency — can be added without editing this module.
    """
    if factory is None:
        _REGISTRY.pop(name, None)
        return
    _REGISTRY[name] = factory


def _default_registry() -> dict[str, Callable[[], OCREngine]]:
    """Built-in engines, imported lazily so that neither adapter's dependencies are needed to
    import this module."""

    def _stub() -> OCREngine:
        from app.services.vision.adapters.stub import StubOCREngine

        return StubOCREngine.from_fixture()

    def _paddle() -> OCREngine:
        from app.services.vision.adapters.paddle import PaddleOCREngine

        return PaddleOCREngine()

    return {"stub": _stub, "paddle": _paddle}


def get_engine(name: str | None = None) -> OCREngine:
    """Return the OCR engine to use.

    Args:
        name: an explicit engine name. Defaults to ``settings.OCR_ENGINE``, which is the only
            thing that selects an engine in production — no caller branches on it.

    Raises:
        UnknownEngineError: no engine is registered under that name.
    """
    resolved = name or settings.OCR_ENGINE
    factories = {**_default_registry(), **_REGISTRY}

    try:
        factory = factories[resolved]
    except KeyError as exc:
        raise UnknownEngineError(
            f"no OCR engine registered as {resolved!r}; "
            f"available: {', '.join(sorted(factories))}"
        ) from exc

    return factory()


__all__ = [
    "OCREngine",
    "Point",
    "Polygon",
    "UnknownEngineError",
    "Word",
    "get_engine",
    "register_engine",
]
