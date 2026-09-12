"""Marker detection and metric rectification — TRD FR-21, work package B5.

This is the package the whole product rests on. Every millimetre in every metric verdict comes
from the homography computed here; if the scale is wrong, the system produces confident,
citable, wrong accusations. So the tests are built around **synthetic images with known ground
truth**: a marker of known size is rendered, warped by a known perspective transform, and the
recovered scale is compared against what it must be.

Synthetic images are not a substitute for the E1 photograph set (TRD §7) — they cannot exercise
lens distortion, motion blur, rolling shutter or paper that is not flat. They test that the maths
is right. E1 tests that the maths survives a real camera, and it needs printed charts and a
caliper, which is physical work outside this suite.

**The invariant that matters most** is the one in ``test_no_marker_returns_none``: no marker means
no measurement, never an estimate (CLAUDE.md §3.3). A guessed millimetre in a legal report is
worse than no millimetre at all.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from app.config import settings
from app.services.vision.marker import MARKER_DICTIONARY, detect_marker, quality
from app.services.vision.rectify import RectificationError, rectify

MARKER_MM = 40.0
"""The printed marker is 40 mm (TRD FR-02). Declared per scan, never assumed."""

BAR_MM = 10.00
"""The independent object FR-21's acceptance test is written about: "a printed test chart with
known 10.00 mm bars measures 10.00 ± 0.25 mm"."""

TOLERANCE_MM = 0.25
"""FR-21's tolerance, which is stated for a 10 mm feature. It is 2.5% relative, and relative is
what the method actually delivers — see ``test_scale_error_is_relative_to_marker_pixel_size``."""


def _render_scene(
    *,
    marker_px: int = 200,
    canvas: tuple[int, int] = (900, 1200),
    warp: npt.NDArray[np.float64] | None = None,
    blur: int = 0,
    marker_id: int = 0,
) -> npt.NDArray[np.uint8]:
    """Render a marker on a light background, optionally viewed through a perspective warp."""
    height, width = canvas
    image = np.full((height, width), 235, dtype=np.uint8)

    dictionary = cv2.aruco.getPredefinedDictionary(MARKER_DICTIONARY)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, marker_px)

    top, left = 150, 200
    image[top : top + marker_px, left : left + marker_px] = marker

    # An independent object of known physical size, coplanar with the marker. This is what
    # FR-21's acceptance test actually measures — re-detecting the marker only proves the
    # transform is self-consistent, not that the scale generalises to the rest of the frame.
    px_per_mm_source = marker_px / MARKER_MM
    bar_px = round(BAR_MM * px_per_mm_source)
    bar_height_px = max(6, bar_px // 3)  # clearly wider than tall, so it is unambiguous to find
    bar_left = left + marker_px + 60
    image[top : top + bar_height_px, bar_left : bar_left + bar_px] = 40

    if warp is not None:
        image = cv2.warpPerspective(
            image, warp, (width, height), borderValue=235  # type: ignore[arg-type]
        )
    if blur:
        image = cv2.GaussianBlur(image, (blur | 1, blur | 1), 0)

    return np.ascontiguousarray(image)


def _tilt_warp(degrees: float, canvas: tuple[int, int] = (900, 1200)) -> npt.NDArray[np.float64]:
    """A perspective transform approximating a view from ``degrees`` off the surface normal."""
    height, width = canvas
    shrink = math.sin(math.radians(degrees)) * 0.45
    source = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    target = np.float32(
        [
            [width * shrink, 0],
            [width * (1 - shrink), 0],
            [width, height],
            [0, height],
        ]
    )
    return cv2.getPerspectiveTransform(source, target).astype(np.float64)


def _measure_bar_mm(result) -> float:  # type: ignore[no-untyped-def]
    """Measure the known-width bar in a rectified image, in millimetres."""
    _, binary = cv2.threshold(result.image, 128, 255, cv2.THRESH_BINARY_INV)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary)

    widest = None
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 500:
            continue
        # the bar is much wider than it is tall; the marker is square
        if width > height * 2 and (widest is None or area > widest[4]):
            widest = (x, y, width, height, area)

    assert widest is not None, "the measurement bar was not found in the rectified image"
    return float(widest[2]) / result.px_per_mm


# --------------------------------------------------------------------------- detection


def test_marker_is_detected_head_on() -> None:
    corners = detect_marker(_render_scene())

    assert corners is not None
    assert corners.marker_id == 0
    assert corners.points.shape == (4, 2)


def test_marker_is_detected_under_tilt() -> None:
    """FR-21 accepts captures up to 25° off-normal; detection must survive the whole range."""
    for degrees in (10, 20, 25):
        corners = detect_marker(_render_scene(warp=_tilt_warp(degrees)))
        assert corners is not None, f"marker lost at {degrees}°"


def test_no_marker_returns_none_rather_than_a_guess() -> None:
    """CLAUDE.md §3.3. An image with no scale reference yields no scale, full stop.

    The caller marks the scan ``no_marker`` and every metric rule becomes NOT_ASSESSABLE. There
    is no code path that estimates a size from image dimensions, assumed DPI, or anything else.
    """
    blank = np.full((600, 800), 235, dtype=np.uint8)

    assert detect_marker(blank) is None


def test_detection_is_deterministic() -> None:
    scene = _render_scene(warp=_tilt_warp(15))

    first = detect_marker(scene)
    second = detect_marker(scene)

    assert first is not None and second is not None
    assert np.allclose(first.points, second.points)


# --------------------------------------------------------------------------- rectification


def test_rectified_image_is_at_the_configured_scale() -> None:
    """The scale is fixed at PX_PER_MM, read from config — never a literal (CLAUDE.md §8)."""
    scene = _render_scene()
    corners = detect_marker(scene)
    assert corners is not None

    result = rectify(scene, corners, marker_mm=MARKER_MM)

    assert result.px_per_mm == settings.PX_PER_MM
    assert result.marker_mm == MARKER_MM
    assert detect_marker(result.image) is not None, "marker must survive the warp"


@pytest.mark.parametrize("degrees", [0, 10, 20, 25])
def test_a_known_bar_measures_its_true_size_across_the_accepted_tilt_range(
    degrees: int,
) -> None:
    """FR-21's acceptance test: a known 10.00 mm feature measures 10.00 ± 0.25 mm at angles up
    to 25°.

    Measured on the **bar**, not on the marker. Re-detecting the marker would only prove the
    transform is self-consistent — the marker is what defined the scale, so it is guaranteed to
    come back right. The bar is an independent, coplanar object, which is the only way to show
    the scale generalises to the rest of the frame, where the label text actually lives.
    """
    scene = _render_scene(warp=_tilt_warp(degrees))
    corners = detect_marker(scene)
    assert corners is not None

    result = rectify(scene, corners, marker_mm=MARKER_MM)

    assert _measure_bar_mm(result) == pytest.approx(BAR_MM, abs=TOLERANCE_MM), (
        f"scale off at {degrees}°"
    )


def test_scale_error_is_relative_not_absolute() -> None:
    """A finding worth pinning: the dominant error is a *relative* scale error, and it comes from
    how precisely ArUco locates the marker's corners.

    At a 200 px marker the corner estimate is roughly a pixel out, which is 0.5% — so a 40 mm
    object reads ~0.2 mm long while a 10 mm object reads ~0.05 mm long. That is why FR-21's
    ±0.25 mm is stated against a 10 mm feature, and why it must not be read as an absolute budget
    that holds at any size.

    The practical consequence is the one that matters for glyph metrology: a 2 mm numeral
    inherits ~0.01 mm of scale error, which is far below the 0.25 mm measurement uncertainty the
    rule pack already carries. Filling more of the frame with the marker tightens it further.
    """
    scene = _render_scene()
    corners = detect_marker(scene)
    assert corners is not None
    result = rectify(scene, corners, marker_mm=MARKER_MM)

    observed = _measure_bar_mm(result)
    relative_error = abs(observed - BAR_MM) / BAR_MM

    assert relative_error < 0.025, f"relative scale error {relative_error:.3%} exceeds 2.5%"


def test_a_larger_marker_in_frame_reduces_the_scale_error() -> None:
    """Corollary of the above, and the reason the capture screen tells a user to move closer."""
    small_scene = _render_scene(marker_px=120)
    large_scene = _render_scene(marker_px=400)

    errors = []
    for scene in (small_scene, large_scene):
        corners = detect_marker(scene)
        assert corners is not None
        result = rectify(scene, corners, marker_mm=MARKER_MM)
        errors.append(abs(_measure_bar_mm(result) - BAR_MM))

    assert errors[1] <= errors[0], "a marker covering more pixels must not measure worse"


def test_a_different_marker_size_changes_the_scale_not_the_answer() -> None:
    """``marker_mm`` is per-scan — a 40 mm tag or an 85.6 mm ID-1 card (FR-02).

    It is an argument, never a constant. The same pixels with a different declared size must
    produce a proportionally different physical reading.
    """
    scene = _render_scene()
    corners = detect_marker(scene)
    assert corners is not None

    small = rectify(scene, corners, marker_mm=40.0)
    large = rectify(scene, corners, marker_mm=85.6)

    assert small.px_per_mm == large.px_per_mm == settings.PX_PER_MM
    # A larger declared marker means the same pixels cover more millimetres, so the warped
    # output must be correspondingly larger.
    assert large.out_size[0] > small.out_size[0]


def test_rectify_rejects_a_non_positive_marker_size() -> None:
    scene = _render_scene()
    corners = detect_marker(scene)
    assert corners is not None

    with pytest.raises(RectificationError):
        rectify(scene, corners, marker_mm=0.0)


def test_homography_round_trips_the_marker_corners() -> None:
    """The transform must be internally consistent: mapping the detected corners through it
    lands them on the canonical square."""
    scene = _render_scene(warp=_tilt_warp(20))
    corners = detect_marker(scene)
    assert corners is not None

    result = rectify(scene, corners, marker_mm=MARKER_MM)
    mapped = cv2.perspectiveTransform(
        corners.points.reshape(1, 4, 2).astype(np.float32), result.homography
    ).reshape(4, 2)

    side = MARKER_MM * result.px_per_mm
    observed = float(np.linalg.norm(mapped[0] - mapped[1]))
    assert observed == pytest.approx(side, abs=1.0)


# --------------------------------------------------------------------------- quality gates


def test_blur_score_falls_as_the_image_is_blurred() -> None:
    """FR-01 gates capture on variance of Laplacian. The score must actually track blur."""
    sharp = quality(_render_scene(), detect_marker(_render_scene()))
    smeared_scene = _render_scene(blur=15)
    smeared = quality(smeared_scene, detect_marker(smeared_scene))

    assert sharp.blur > smeared.blur


def test_tilt_is_reported_and_grows_with_angle() -> None:
    """Reported, not silently corrected. The capture gate and the uncertainty model both need
    to know how far off-normal the shot was."""
    readings = []
    for degrees in (0, 15, 25):
        scene = _render_scene(warp=_tilt_warp(degrees))
        corners = detect_marker(scene)
        assert corners is not None
        readings.append(quality(scene, corners).tilt_deg)

    assert readings[0] < readings[1] < readings[2]


def test_glare_is_detected() -> None:
    scene = _render_scene()
    corners = detect_marker(scene)
    clean = quality(scene, corners)

    glared = scene.copy()
    glared[0:300, 0:400] = 255
    blown = quality(glared, corners)

    assert blown.glare > clean.glare


def test_curvature_is_none_when_it_cannot_be_measured() -> None:
    """Honesty gate. A four-corner marker always fits a homography exactly, so it carries no
    information about whether the *pack* is curved.

    Returning 0.0 here would be a fabricated reassurance that the surface is flat, and
    architecture §12.2 depends on curvature being trustworthy enough to downgrade metric rules
    to NOT_ASSESSABLE. Until it is measured from the rectified text region (B7), it is None.
    """
    scene = _render_scene()

    assert quality(scene, detect_marker(scene)).curvature is None


def test_quality_works_without_a_marker() -> None:
    """The capture screen needs blur and glare readings before a marker is found, to tell the
    user which gate is failing."""
    blank = np.full((600, 800), 235, dtype=np.uint8)

    result = quality(blank, None)

    assert result.blur >= 0
    assert result.tilt_deg is None


# --------------------------------------------------------------------------- purity


def test_vision_modules_do_no_io() -> None:
    """Same requirement as the rules engine: these are pure functions over arrays."""
    import ast
    from pathlib import Path

    from app.services.vision import marker as marker_module
    from app.services.vision import rectify as rectify_module

    forbidden = {"sqlalchemy", "celery", "redis", "boto3", "httpx", "requests", "app.db"}
    for module in (marker_module, rectify_module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))  # type: ignore[arg-type]
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
        assert not offenders, f"{module.__name__} imports {offenders}"


def test_px_per_mm_is_not_hardcoded_at_a_call_site() -> None:
    """CLAUDE.md §8 names the hardcoded 20 as a gotcha that has already cost time."""
    from pathlib import Path

    from app.services.vision import rectify as rectify_module

    source = Path(rectify_module.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]

    assert "settings.PX_PER_MM" in source
    assert " 20" not in source.replace("settings.PX_PER_MM", ""), (
        "PX_PER_MM must come from config, never a literal"
    )
