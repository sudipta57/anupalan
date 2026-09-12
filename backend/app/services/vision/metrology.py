"""Glyph metrology — TRD FR-23, architecture §5 S5.

Measures the physical size of printed characters on the rectified plane. This is the module the
whole differentiator rests on: "is the net quantity numeral at least 2 mm tall" is the check
nobody else automates, and it is answered here.

**Measurement runs on pixels, not on OCR output.** An OCR polygon wraps a whole word including
ascenders, descenders and inter-line padding, so its height is not a glyph height (CLAUDE.md §8).
This module takes the rectified image and a region, thresholds it, and measures connected
components. It does not import the OCR layer at all; the recognised `text` is passed in only to
label components with the character they correspond to, never to size them.

**Nothing here invents a length.** Three situations produce no measurement rather than a
plausible one:

* nothing measurable in the region — an empty list, never a zero, because a zero-millimetre glyph
  fails every metric rule in the pack;
* a baseline that bows, which means the surface is not planar and a planar homography is
  under-measuring it (architecture §12.2);
* a caller that already knows the surface is curved.

The rule pack turns each of those into NOT_ASSESSABLE, which is the honest verdict.

**Uncertainty is an output, not an afterthought.** Every measurement carries a band that widens
with blur and viewing angle. The rule pack compares against that band, so a marginal glyph on a
poor capture lands BORDERLINE instead of being confidently accused. The baseline value comes from
the pack and is passed in — this module holds no millimetre constants.

Pure functions over arrays. No I/O, no global state.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from app.config import settings
from app.services.rules.types import BBox, Measurement
from app.services.vision.marker import Quality

METHOD = "connected_components"
"""Recorded on every Measurement, so a finding can say how its number was obtained."""


@dataclass(frozen=True)
class _Component:
    """One connected blob, in coordinates local to the measured region."""

    x: int
    y: int
    width: int
    height: int
    area: int

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def centre_x(self) -> float:
        return self.x + self.width / 2.0


def _crop(
    image: npt.NDArray[np.uint8], bbox: BBox
) -> tuple[npt.NDArray[np.uint8], int, int]:
    """Return the region of interest plus its offset in the full image."""
    height, width = image.shape[:2]
    left = max(0, int(bbox.x))
    top = max(0, int(bbox.y))
    right = min(width, int(bbox.x + bbox.width))
    bottom = min(height, int(bbox.y + bbox.height))
    if right <= left or bottom <= top:
        return np.zeros((0, 0), dtype=np.uint8), left, top
    return image[top:bottom, left:right], left, top


def _binarise(region: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    """Adaptive threshold to ink-on-white, tolerant of uneven lighting across a package face."""
    grey = region if region.ndim == 2 else cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    # Block size must be odd and larger than a glyph stroke; 35 px at 20 px/mm is ~1.75 mm,
    # comfortably wider than the strokes being measured and narrower than a lighting gradient.
    thresholded = cv2.adaptiveThreshold(
        grey, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 35, 10
    )
    binary: npt.NDArray[np.uint8] = thresholded.astype(np.uint8)
    return binary


def _components(binary: npt.NDArray[np.uint8]) -> list[_Component]:
    """Find glyph-sized connected components, dropping speckle.

    Dust, print noise and JPEG artefacts all become tiny components. Measuring one as a glyph
    would report a sub-millimetre height for a declaration that is in fact compliant.
    """
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    found: list[_Component] = []
    for index in range(1, count):  # 0 is the background
        x, y, width, height, area = (int(value) for value in stats[index])
        if area < settings.GLYPH_MIN_AREA_PX or height < settings.GLYPH_MIN_HEIGHT_PX:
            continue
        found.append(_Component(x=x, y=y, width=width, height=height, area=area))
    return found


def _cluster_by_baseline(components: list[_Component]) -> list[list[_Component]]:
    """Group components into text lines by the y of their bottom edge.

    Two lines of a declaration must not be averaged into one height: a 4 mm brand name above a
    1.8 mm quantity would otherwise measure as a compliant 2.9 mm.

    The tolerance scales with glyph height rather than being a fixed number of pixels, and that
    is load-bearing rather than cosmetic. A **curved** surface is precisely the case where a
    single text line's baseline is not flat — clustering it strictly would split one bowed line
    into several short clusters, each too small to fit a line through, and the curvature check
    below would then see nothing wrong. Half a glyph height comfortably absorbs a bow while
    staying far smaller than the gap between real lines.
    """
    if not components:
        return []

    ordered = sorted(components, key=lambda component: component.bottom)
    clusters: list[list[_Component]] = [[ordered[0]]]
    for component in ordered[1:]:
        current = clusters[-1]
        # Compare against the nearest neighbour already in the cluster, not against its mean.
        # A mean drifts as members join, which pushes the ends of a bowed line out into clusters
        # of their own — losing exactly the shape the curvature check needs to see.
        previous = current[-1]
        median_height = float(np.median([member.height for member in current]))
        tolerance = max(settings.BASELINE_TOLERANCE_PX, 0.5 * median_height)

        if abs(component.bottom - previous.bottom) <= tolerance:
            current.append(component)
        else:
            clusters.append([component])

    return [sorted(cluster, key=lambda component: component.x) for cluster in clusters]


def _baseline_residual_mm(cluster: list[_Component], px_per_mm: int) -> float:
    """How far the cluster's baseline departs from a straight line, in millimetres.

    On a flat label the bottoms of the glyphs in one line are collinear. On a bottle or a pouch
    the rectified baseline bows, and the amount it bows is a direct measure of how badly the
    planar assumption is being violated.

    Fewer than three components carries no information — any two points are collinear — so those
    report zero rather than a fabricated curvature.
    """
    if len(cluster) < 3:
        return 0.0

    xs = np.array([component.centre_x for component in cluster], dtype=np.float64)
    ys = np.array([float(component.bottom) for component in cluster], dtype=np.float64)
    if np.ptp(xs) <= 0:
        return 0.0

    slope, intercept = np.polyfit(xs, ys, 1)
    residuals = ys - (slope * xs + intercept)
    return float(np.sqrt(np.mean(residuals**2)) / px_per_mm)


def _uncertainty_mm(baseline_mm: float, quality: Quality, px_per_mm: int) -> float:
    """Widen the measurement band according to how bad the capture was.

    Two multipliers, both anchored on the FR-01 capture gates so the numbers mean the same thing
    here as they do on the camera screen:

    * **blur** — at or above the sharpness gate the multiplier is 1; below it the band grows in
      proportion to how far short the frame fell, capped so a hopeless frame does not produce an
      absurd band.
    * **tilt** — 1 at dead-on, 2 at the maximum accepted angle, because foreshortening error
      grows with angle.

    An unknown tilt (no marker, so no plane to measure against) is treated as the **worst** case,
    not the best. Reporting the narrowest band on the capture we know least about is exactly
    backwards.

    The result never goes below one pixel, which is the floor of what the rectified image can
    resolve regardless of how good the capture was.
    """
    blur_factor = 1.0
    if quality.blur < settings.BLUR_REFERENCE:
        blur_factor = min(3.0, settings.BLUR_REFERENCE / max(quality.blur, 1.0))

    if quality.tilt_deg is None:
        tilt_factor = 2.0
    else:
        tilt_factor = 1.0 + min(1.0, abs(quality.tilt_deg) / settings.TILT_REFERENCE_DEG)

    one_pixel_mm = 1.0 / px_per_mm
    return max(one_pixel_mm, baseline_mm * blur_factor * tilt_factor)


def _assign_glyphs(components: list[_Component], text: str | None) -> list[str | None]:
    """Map recognised characters onto measured components, left to right.

    Only when the counts agree. Connected components split and merge — a dot detaches from its
    stem, two letters touch and become one blob — and a left-to-right zip across a mismatch
    silently attaches the wrong character to every measurement after it. The height stays true
    either way; only the identity is withheld.
    """
    characters = [character for character in (text or "") if not character.isspace()]
    if characters and len(characters) == len(components):
        return list(characters)
    return [None] * len(components)


def _span_is_numeric(text: str | None) -> bool:
    """True when a span is predominantly digits.

    Lets Rule 9's Table-I and Table-II still apply to a quantity declaration whose individual
    glyphs could not be identified, since the rule is about the numerals in that declaration and
    the declaration is known to be numeric.
    """
    characters = [character for character in (text or "") if not character.isspace()]
    if not characters:
        return False
    digits = sum(1 for character in characters if character.isdigit())
    return digits > 0 and digits >= len(characters) / 2


def _is_cap_height(component: _Component, cap: float) -> bool:
    """Whether a component reaches the cap height of its text line.

    Digits are cap-height glyphs. Punctuation is not, and neither is x-height lowercase, so this
    is what distinguishes them when the character itself is unknown.
    """
    return cap > 0 and component.height >= settings.CAP_HEIGHT_RATIO * cap


def _is_mark(glyph: str | None, component: _Component, cap: float) -> bool:
    """Whether a component is punctuation rather than a letter or a numeral.

    Known character: anything that is neither alphanumeric nor whitespace.
    Unknown character: far enough below the line's cap height that no letter reaches it.
    """
    if glyph is not None:
        return not glyph.isalnum()
    return cap > 0 and component.height < settings.MARK_HEIGHT_RATIO * cap


def _is_numeral(
    glyph: str | None, component: _Component, cap: float, *, span_numeric: bool
) -> bool:
    """Decide whether a component should count towards a numeral-height rule.

    When the character is known, this is simply whether it is a digit.

    When it is not — connected components split and merge, so alignment often fails — the
    fallback is: the declaration is predominantly numeric *and* this component reaches the line's
    cap height. Both halves are needed. Without the cap-height half, the two dots of the colon in
    "Net Qty: 250 g" are measured as numerals, Rule 9's "at least" comparison takes the smallest,
    and a label whose numerals are a compliant 3.5 mm is failed on a 0.75 mm dot.

    A false FAIL is the failure mode that kills this product (TRD §7, E3), so the conservative
    reading wins: a component that cannot be shown to be a numeral is not treated as one.
    """
    if glyph is not None:
        return glyph.isdigit()
    return span_numeric and _is_cap_height(component, cap)


def measure_text_span(
    warped: npt.NDArray[np.uint8],
    bbox: BBox,
    quality: Quality,
    *,
    field_code: str,
    baseline_uncertainty_mm: float,
    text: str | None = None,
    px_per_mm: int | None = None,
    curvature_limit_mm: float | None = None,
) -> list[Measurement]:
    """Measure every glyph in one region of the rectified image.

    Args:
        warped: the rectified image, at ``px_per_mm``.
        bbox: the region holding the declaration, in rectified pixels.
        quality: capture quality, used to widen the uncertainty band.
        field_code: which declaration these measurements belong to.
        baseline_uncertainty_mm: the pack's default uncertainty. Passed in rather than read,
            so this module stays pure and holds no millimetre constants (CLAUDE.md §3.2).
        text: the recognised text for this span, used only to label components with their
            character. Never used to size anything.
        px_per_mm: override the configured scale. Defaults to ``settings.PX_PER_MM``, which is
            never written as a literal at a call site (CLAUDE.md §8).
        curvature_limit_mm: override the baseline-bow limit past which the surface is treated as
            unmeasurable.

    Returns:
        One measurement per glyph, in reading order. **Empty** when nothing could be measured, or
        when the surface is too curved to measure on — never a zero, never an estimate.
    """
    scale = px_per_mm if px_per_mm is not None else settings.PX_PER_MM
    limit = (
        curvature_limit_mm
        if curvature_limit_mm is not None
        else settings.CURVATURE_MAX_RESIDUAL_MM
    )

    # An upstream stage that already established the surface is curved is believed. `None` means
    # unknown, which is not the same as flat, so it does not block measurement on its own — the
    # baseline check below is what actually decides.
    if quality.curvature is not None and quality.curvature > limit:
        return []

    region, offset_x, offset_y = _crop(warped, bbox)
    if region.size == 0:
        return []

    clusters = _cluster_by_baseline(_components(_binarise(region)))
    if not clusters:
        return []

    if any(_baseline_residual_mm(cluster, scale) > limit for cluster in clusters):
        # The surface is not planar. A planar homography under-measures here, and a number that
        # is confidently 8% short reads as a failed label (architecture §12.2).
        return []

    uncertainty = _uncertainty_mm(baseline_uncertainty_mm, quality, scale)
    span_numeric = _span_is_numeric(text)

    ordered = [component for cluster in clusters for component in cluster]
    glyphs = _assign_glyphs(ordered, text)

    # Cap height per line, so a component can be told apart from punctuation without knowing
    # which character it is. See _is_cap_height for why this matters.
    #
    # A cluster of one is not a text line, it is an isolated mark — the upper dot of a colon sits
    # well above the baseline and clusters alone. Letting it set its own cap height would make
    # every such mark trivially cap-height, which is the bug this guard exists to prevent, so a
    # lone component is measured against the tallest glyph in the whole region instead.
    region_tallest = float(max(component.height for cluster in clusters for component in cluster))
    cap_by_component: dict[int, float] = {}
    for cluster in clusters:
        tallest = (
            float(max(component.height for component in cluster))
            if len(cluster) > 1
            else region_tallest
        )
        for component in cluster:
            cap_by_component[id(component)] = tallest

    measurements: list[Measurement] = []
    for component, glyph in zip(ordered, glyphs, strict=True):
        cap = cap_by_component[id(component)]
        measurements.append(
            Measurement(
                field_code=field_code,
                glyph=glyph,
                height_mm=component.height / scale,
                width_mm=component.width / scale,
                uncertainty_mm=uncertainty,
                is_numeral=_is_numeral(glyph, component, cap, span_numeric=span_numeric),
                is_mark=_is_mark(glyph, component, cap),
                method=METHOD,
            )
        )
    del offset_x, offset_y  # kept for symmetry with future bbox mapping; not needed for sizes
    return measurements


__all__ = ["METHOD", "measure_text_span"]
