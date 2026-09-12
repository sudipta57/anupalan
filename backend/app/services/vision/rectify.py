"""Metric rectification — TRD FR-21, architecture §5 S3.

Takes an image and a detected marker of **declared** physical size, and warps the image onto a
canonical plane at a fixed scale. After this step one pixel is one known fraction of a
millimetre, everywhere in the frame, and every downstream measurement is a division.

Two decisions carry the weight here.

**The scale is fixed, not derived per image.** Everything warps to ``settings.PX_PER_MM``. The
alternative — keeping each image at whatever scale its marker implies and carrying a per-image
factor alongside every measurement — means one missed conversion is a silently wrong millimetre
in a legal report. One conversion, in one place (see `docs/decisions.md`).

**The marker's size is an argument, never a constant.** A scan may use the 40 mm printed tag or
an ID-1 card at 85.60 mm (TRD FR-02), and the app records which. ``marker_mm`` comes from the
scan record; this module never assumes it.

Pure functions over arrays. No I/O, no global state.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from app.config import settings
from app.services.vision.marker import MarkerCorners


class RectificationError(ValueError):
    """The image could not be rectified against the given marker."""


@dataclass(frozen=True)
class Rectified:
    """An image warped onto the metric plane."""

    image: npt.NDArray[np.uint8]
    px_per_mm: int
    """Pixels per millimetre in ``image``. Divide any pixel distance by this to get millimetres."""

    homography: npt.NDArray[np.float64]
    """The transform applied, kept so evidence boxes can be mapped back to the original frame."""

    out_size: tuple[int, int]
    """``(width, height)`` of ``image``, in pixels."""

    marker_mm: float
    """The physical marker size this rectification was computed against."""

    def to_mm(self, pixels: float) -> float:
        """Convert a distance in rectified pixels to millimetres."""
        return pixels / self.px_per_mm


def rectify(
    image: npt.NDArray[np.uint8],
    corners: MarkerCorners,
    marker_mm: float,
) -> Rectified:
    """Warp ``image`` so that the marker measures ``marker_mm`` at the configured scale.

    Args:
        image: the captured frame.
        corners: the marker's detected corners, from ``detect_marker``.
        marker_mm: the marker's true physical size in millimetres, as declared for this scan.

    Returns:
        The rectified image and the transform that produced it.

    Raises:
        RectificationError: ``marker_mm`` is not positive, or the corners are degenerate.
    """
    if marker_mm <= 0:
        raise RectificationError(
            f"marker_mm must be positive, got {marker_mm!r}. It is declared per scan "
            "(TRD FR-02) and must never be assumed."
        )

    px_per_mm = settings.PX_PER_MM
    side_px = marker_mm * px_per_mm

    source = corners.points.astype(np.float32)
    if cv2.contourArea(source) <= 0:
        raise RectificationError("marker corners are degenerate; cannot compute a homography")

    height, width = image.shape[:2]

    # Place the marker at a fixed offset rather than at the origin, so the rest of the package —
    # which is what actually gets measured — stays inside the output frame. The package extends
    # in every direction from the marker, so the margin is generous and symmetric.
    margin = side_px
    target = np.array(
        [
            [margin, margin],
            [margin + side_px, margin],
            [margin + side_px, margin + side_px],
            [margin, margin + side_px],
        ],
        dtype=np.float32,
    )

    homography = cv2.getPerspectiveTransform(source, target).astype(np.float64)

    # Size the output so the whole original frame survives the warp where it can, scaled by how
    # much the marker had to grow. A frame that is cropped here loses label text that the OCR
    # stage would then never see.
    original_side = max(corners.side_lengths_px)
    growth = side_px / original_side if original_side > 0 else 1.0
    out_width = int(min(max(width * growth, side_px + 2 * margin), 8000))
    out_height = int(min(max(height * growth, side_px + 2 * margin), 8000))

    warped = cv2.warpPerspective(
        image,
        homography,
        (out_width, out_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )

    return Rectified(
        image=np.ascontiguousarray(warped),
        px_per_mm=px_per_mm,
        homography=homography,
        out_size=(out_width, out_height),
        marker_mm=marker_mm,
    )


__all__ = ["RectificationError", "Rectified", "rectify"]
