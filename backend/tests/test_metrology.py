"""Glyph metrology — TRD FR-23, work package B7.

This module answers the question nobody else automates: *how tall is that numeral, in
millimetres*. Every metric verdict in the product is a comparison against what this returns, so
the failure mode to design against is not "no measurement" — it is a **confident wrong
measurement**, which produces a citable accusation against a compliant label.

Three properties are pinned here, in descending order of how much damage getting them wrong does.

**Measurement never comes from OCR polygons** (CLAUDE.md §8). An OCR box wraps a whole word
including ascenders, descenders and padding, so its height is not a glyph height. Measurement
runs connected components on the rectified image. The last test in this file checks that at the
source level, because the shortcut is tempting and the resulting error is invisible.

**A surface too curved to measure yields nothing.** A planar homography under-measures on a
curved pack (`01-architecture.md` §12.2). Returning a slightly-too-small number there is worse
than returning none, because it reads as a failed label.

**Uncertainty widens with the things that make a capture worse.** A blurry, tilted shot must
produce a wider band, which lands BORDERLINE rather than FAIL — the rule pack already knows what
to do with a wide band, but only if the band is honest.

Ground truth is synthetic and exact: glyphs are drawn as filled rectangles of a known pixel
height, so ``height_mm`` has one correct answer. Real type is exercised separately for sanity,
but a rendered font has no exact cap height to assert against.
"""

from __future__ import annotations

import ast
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from app.config import settings
from app.services.rules.types import BBox
from app.services.vision.marker import Quality
from app.services.vision.metrology import measure_text_span

BASELINE_UNCERTAINTY_MM = 0.25
"""The pack's ``meta.measurement.default_uncertainty_mm``. Passed in, never read from the pack
here — metrology is pure and does not load rule packs."""

PX_PER_MM = settings.PX_PER_MM


def _good_quality(**overrides: float | None) -> Quality:
    values: dict[str, float | None] = {
        "blur": 400.0,
        "glare": 0.0,
        "tilt_deg": 0.0,
        "curvature": None,
    }
    values.update(overrides)
    return Quality(**values)  # type: ignore[arg-type]


def _render_glyphs(
    heights_px: list[int],
    widths_px: list[int],
    *,
    baseline_y: int = 200,
    x_start: int = 60,
    gap: int = 14,
    canvas: tuple[int, int] = (300, 600),
    baseline_shift: list[int] | None = None,
) -> npt.NDArray[np.uint8]:
    """Draw glyphs as filled rectangles sitting on a common baseline.

    A rectangle is a connected component whose height is exact, which is the only way to assert a
    millimetre value against ground truth rather than against another estimate.
    """
    image = np.full(canvas, 255, dtype=np.uint8)
    x = x_start
    for index, (height, width) in enumerate(zip(heights_px, widths_px, strict=True)):
        shift = baseline_shift[index] if baseline_shift else 0
        bottom = baseline_y + shift
        image[bottom - height : bottom, x : x + width] = 0
        x += width + gap
    return image


def _full_bbox(image: npt.NDArray[np.uint8]) -> BBox:
    height, width = image.shape[:2]
    return BBox(x=0, y=0, width=float(width), height=float(height))


# --------------------------------------------------------------------------- exact ground truth


@pytest.mark.parametrize("height_px", [20, 30, 40, 50, 80, 120])
def test_glyph_height_is_recovered_exactly(height_px: int) -> None:
    """A glyph of known pixel height must convert to the right millimetre value.

    At PX_PER_MM = 20 these are 1.0, 1.5, 2.0, 2.5, 4.0 and 6.0 mm — the heights the rule pack's
    Table-I and Table-II actually key on.
    """
    image = _render_glyphs([height_px] * 3, [height_px // 2] * 3)

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="250",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert len(measurements) == 3
    for measurement in measurements:
        assert measurement.height_mm == pytest.approx(height_px / PX_PER_MM, abs=0.01)


def test_width_is_measured_alongside_height() -> None:
    """Rule 9(3)'s proviso is about the width-to-height ratio, so width must be real, not
    inferred from the height."""
    image = _render_glyphs([40, 40], [30, 8])

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="21",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    wide, narrow = measurements
    assert wide.width_mm == pytest.approx(30 / PX_PER_MM, abs=0.01)
    assert narrow.width_mm == pytest.approx(8 / PX_PER_MM, abs=0.01)
    assert wide.width_to_height_ratio == pytest.approx(0.75, abs=0.02)
    assert narrow.width_to_height_ratio == pytest.approx(0.20, abs=0.02)


def test_measurements_are_returned_in_reading_order() -> None:
    """Glyph order must match the text, or the character mapping below is meaningless."""
    image = _render_glyphs([40, 60, 30], [20, 20, 20])

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="250",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert [m.glyph for m in measurements] == ["2", "5", "0"]
    assert [round(m.height_mm or 0, 2) for m in measurements] == [2.0, 3.0, 1.5]


# --------------------------------------------------------------------------- noise and clustering


def test_speckle_is_dropped() -> None:
    """Dust, JPEG artefacts and print noise become tiny components. Measuring one as a glyph
    would report a sub-millimetre height for a declaration that is actually fine."""
    image = _render_glyphs([40, 40], [20, 20])
    image[50, 500] = 0
    image[51, 502] = 0
    image[120:122, 400:402] = 0

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="25",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert len(measurements) == 2
    assert all((m.height_mm or 0) >= 1.0 for m in measurements)


def test_a_second_text_line_is_a_separate_baseline_cluster() -> None:
    """Two lines of a declaration must not be averaged into one height."""
    image = np.full((400, 600), 255, dtype=np.uint8)
    top = _render_glyphs([40, 40], [20, 20], baseline_y=120, canvas=(400, 600))
    bottom = _render_glyphs([80, 80], [30, 30], baseline_y=320, canvas=(400, 600))
    image = np.minimum(top, bottom)

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text=None,
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    heights = sorted({round(m.height_mm or 0, 1) for m in measurements})
    assert heights == [2.0, 4.0], "the two lines must be measured separately, not averaged"


def test_only_the_requested_region_is_measured() -> None:
    """A declaration is measured inside its own bounding box; text elsewhere on the panel is
    somebody else's rule."""
    image = _render_glyphs([40, 40], [20, 20], baseline_y=100, canvas=(400, 600))
    far = _render_glyphs([120, 120], [60, 60], baseline_y=380, canvas=(400, 600))
    image = np.minimum(image, far)

    measurements = measure_text_span(
        image,
        BBox(x=0, y=0, width=600, height=200),
        _good_quality(),
        field_code="net_quantity",
        text=None,
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert measurements
    assert all((m.height_mm or 0) < 3.0 for m in measurements)


def test_an_empty_region_yields_no_measurements() -> None:
    """Nothing to measure is an empty list, never a zero. A zero-millimetre glyph would fail
    every metric rule in the pack."""
    blank = np.full((200, 400), 255, dtype=np.uint8)

    assert (
        measure_text_span(
            blank,
            _full_bbox(blank),
            _good_quality(),
            field_code="net_quantity",
            text=None,
            baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
        )
        == []
    )


# --------------------------------------------------------------------------- character mapping


def test_digits_are_marked_as_numerals() -> None:
    """Rule 9's Table-I and Table-II are written about numeral height, so the evaluator needs to
    know which components are digits."""
    image = _render_glyphs([40, 40, 40], [20, 20, 20])

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="250",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert all(m.is_numeral for m in measurements)
    assert [m.glyph for m in measurements] == ["2", "5", "0"]


def test_letters_are_not_marked_as_numerals() -> None:
    image = _render_glyphs([40, 40], [20, 20])

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="common_name",
        text="ab",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert not any(m.is_numeral for m in measurements)
    assert [m.glyph for m in measurements] == ["a", "b"]


def test_a_mismatched_character_count_does_not_mislabel_glyphs() -> None:
    """Connected components split and merge — a dot detaches, two letters touch. When the count
    does not match the text, a left-to-right zip would silently attach the wrong character to
    every measurement after the mismatch.

    The height is still reported, because it is still true. The glyph identity is not.
    """
    image = _render_glyphs([40, 40], [20, 20])

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="2500",  # four characters, two components
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert len(measurements) == 2
    assert all(m.glyph is None for m in measurements)
    assert all(m.height_mm is not None for m in measurements)
    assert all(m.is_numeral for m in measurements), (
        "an all-digit span is still numeral even when individual glyphs cannot be identified"
    )


def test_punctuation_is_not_measured_as_a_numeral() -> None:
    """Regression: a colon in a quantity declaration was failing compliant labels.

    "Net Qty: 250 g" measured through one OCR word box yields a component per glyph — including
    the two dots of the colon, at a fraction of a millimetre. With every component in a numeric
    span marked as a numeral, Rule 9's "at least" comparison took the smallest and reported a
    0.75 mm numeral on a label whose digits were a compliant 3.5 mm.

    A false FAIL is the failure mode that kills this product (TRD §7, E3). Cap height is what
    separates a digit from a dot when the character itself is unknown.
    """
    # Three cap-height glyphs and a colon: two small dots well above the baseline.
    image = _render_glyphs([40, 40, 40], [20, 20, 20], x_start=60)
    image[170:178, 190:198] = 0   # upper dot
    image[192:200, 190:198] = 0   # lower dot

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="250 g",  # count will not match, so glyph identity is unavailable
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    numerals = [m for m in measurements if m.is_numeral]
    assert numerals, "the cap-height digits must still be measured"
    assert min(m.height_mm or 0 for m in numerals) == pytest.approx(2.0, abs=0.05), (
        "the smallest 'numeral' must be a digit, not a punctuation mark"
    )
    assert any(not m.is_numeral for m in measurements), "the dots must be excluded"


def test_x_height_lowercase_is_not_counted_as_a_numeral() -> None:
    """Same reasoning one step up: lowercase letters sit below cap height and would
    under-measure a declaration if counted."""
    image = _render_glyphs([40, 24, 40], [20, 16, 20])

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="2x0 g",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    numerals = [m for m in measurements if m.is_numeral]
    assert len(numerals) == 2
    assert all((m.height_mm or 0) == pytest.approx(2.0, abs=0.05) for m in numerals)


# --------------------------------------------------------------------------- uncertainty


def test_uncertainty_starts_at_the_supplied_baseline() -> None:
    """The baseline comes from the pack, passed in by the caller. This module holds no
    millimetre constants (CLAUDE.md §3.2)."""
    image = _render_glyphs([40], [20])

    measurement = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="2",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )[0]

    assert measurement.uncertainty_mm == pytest.approx(BASELINE_UNCERTAINTY_MM, abs=0.02)


def test_uncertainty_widens_with_blur() -> None:
    """A blurry capture must produce a wider band, so a marginal glyph lands BORDERLINE instead
    of being confidently accused."""
    image = _render_glyphs([40], [20])
    kwargs = {
        "field_code": "net_quantity",
        "text": "2",
        "baseline_uncertainty_mm": BASELINE_UNCERTAINTY_MM,
    }

    sharp = measure_text_span(image, _full_bbox(image), _good_quality(blur=400.0), **kwargs)[0]
    soft = measure_text_span(image, _full_bbox(image), _good_quality(blur=40.0), **kwargs)[0]

    assert (soft.uncertainty_mm or 0) > (sharp.uncertainty_mm or 0)


def test_uncertainty_widens_with_tilt() -> None:
    image = _render_glyphs([40], [20])
    kwargs = {
        "field_code": "net_quantity",
        "text": "2",
        "baseline_uncertainty_mm": BASELINE_UNCERTAINTY_MM,
    }

    flat = measure_text_span(image, _full_bbox(image), _good_quality(tilt_deg=0.0), **kwargs)[0]
    angled = measure_text_span(
        image, _full_bbox(image), _good_quality(tilt_deg=24.0), **kwargs
    )[0]

    assert (angled.uncertainty_mm or 0) > (flat.uncertainty_mm or 0)


def test_unknown_tilt_is_treated_as_the_worst_case_not_the_best() -> None:
    """``tilt_deg`` is None when no marker was found, which means unknown, not flat (B5).

    Treating unknown as zero would report the narrowest possible band on the capture we know
    least about.
    """
    image = _render_glyphs([40], [20])
    kwargs = {
        "field_code": "net_quantity",
        "text": "2",
        "baseline_uncertainty_mm": BASELINE_UNCERTAINTY_MM,
    }

    flat = measure_text_span(image, _full_bbox(image), _good_quality(tilt_deg=0.0), **kwargs)[0]
    unknown = measure_text_span(
        image, _full_bbox(image), _good_quality(tilt_deg=None), **kwargs
    )[0]

    assert (unknown.uncertainty_mm or 0) > (flat.uncertainty_mm or 0)


# --------------------------------------------------------------------------- curvature


def test_a_bowed_baseline_yields_no_measurement() -> None:
    """Architecture §12.2: on a curved pack a planar homography under-measures, so the metric
    rules must go NOT_ASSESSABLE rather than report a confident wrong number.

    Curvature is detected here, not in B5 — four marker corners always fit a homography exactly
    and carry no curvature information. A text baseline that bows does.
    """
    bowed = _render_glyphs(
        [40] * 7,
        [20] * 7,
        baseline_shift=[0, -14, -24, -28, -24, -14, 0],
    )

    assert (
        measure_text_span(
            bowed,
            _full_bbox(bowed),
            _good_quality(),
            field_code="net_quantity",
            text=None,
            baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
        )
        == []
    )


def test_a_mild_bow_within_the_limit_is_still_measured() -> None:
    """The boundary matters in both directions. Real labels are never perfectly flat — paper
    lifts, pouches crease — and rejecting every imperfect surface would measure nothing at all.
    """
    gently_bowed = _render_glyphs(
        [40] * 7,
        [20] * 7,
        baseline_shift=[0, -2, -3, -4, -3, -2, 0],
    )

    measurements = measure_text_span(
        gently_bowed,
        _full_bbox(gently_bowed),
        _good_quality(),
        field_code="net_quantity",
        text=None,
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert len(measurements) == 7


def test_a_straight_baseline_is_measured_normally() -> None:
    """The curvature guard must not reject ordinary flat labels, or every scan becomes
    unassessable and the product measures nothing."""
    flat = _render_glyphs([40] * 7, [20] * 7)

    measurements = measure_text_span(
        flat,
        _full_bbox(flat),
        _good_quality(),
        field_code="net_quantity",
        text=None,
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert len(measurements) == 7


def test_curvature_reported_by_the_caller_also_blocks_measurement() -> None:
    """When an upstream stage has already established the surface is curved, honour it."""
    flat = _render_glyphs([40] * 5, [20] * 5)

    assert (
        measure_text_span(
            flat,
            _full_bbox(flat),
            _good_quality(curvature=9.0),
            field_code="net_quantity",
            text=None,
            baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
        )
        == []
    )


# --------------------------------------------------------------------------- real type, sanity


def test_rendered_text_measures_in_a_plausible_range() -> None:
    """Rectangles give exact ground truth but are not type. This checks the pipeline survives
    real glyph shapes — counters, thin strokes, varying widths — without asserting a cap height a
    rendered font does not precisely have.
    """
    image = np.full((200, 400), 255, dtype=np.uint8)
    cv2.putText(image, "250", (40, 140), cv2.FONT_HERSHEY_SIMPLEX, 3.0, 0, 6)

    measurements = measure_text_span(
        image,
        _full_bbox(image),
        _good_quality(),
        field_code="net_quantity",
        text="250",
        baseline_uncertainty_mm=BASELINE_UNCERTAINTY_MM,
    )

    assert measurements
    for measurement in measurements:
        assert 2.0 < (measurement.height_mm or 0) < 6.0


# --------------------------------------------------------------------------- boundaries


def test_metrology_never_touches_ocr_polygons() -> None:
    """CLAUDE.md §8, asserted at the source level because the shortcut is tempting and the
    resulting error is invisible: an OCR box includes ascenders, descenders and padding, so its
    height is not a glyph height."""
    from app.services.vision import metrology

    source = Path(metrology.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]

    assert "polygon" not in source.lower().replace("polygons", "").replace(
        "ocr polygon", ""
    ) or "Word" not in source, "metrology must not consume OCR word geometry"

    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "app.services.vision.ocr" not in imported, (
        "metrology must measure the rectified image, not OCR output"
    )


def test_metrology_does_no_io() -> None:
    from app.services.vision import metrology

    tree = ast.parse(Path(metrology.__file__).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    forbidden = {"sqlalchemy", "celery", "redis", "boto3", "httpx", "requests", "app.db"}

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = sorted(
        name
        for name in imported
        if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden)
    )
    assert not offenders, f"metrology imports {offenders}"
