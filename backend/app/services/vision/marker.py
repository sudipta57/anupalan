"""ArUco marker detection and capture quality — TRD FR-01, FR-21; architecture §5 S1.

The marker is the reason this product can answer "how tall is that numeral, in millimetres".
Without a physical reference of known size in frame, the question has no answer at all — not a
worse answer, no answer (architecture §9, "Scale reference"). So the contract of this module is
narrow and absolute: it either finds a marker and reports exactly where its corners are, or it
returns ``None``. There is no estimation path, no fallback to assumed DPI, no inference from
image dimensions.

``quality`` reports the four capture gates of FR-01 — blur, glare, tilt, and curvature — so the
camera screen can tell a user *which* gate is failing and the uncertainty model downstream can
widen its band. It reports; it never silently corrects.

Pure functions over arrays. No I/O, no global state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

MARKER_DICTIONARY = cv2.aruco.DICT_4X4_50
"""The dictionary the printed marker and the app-issued PVC card both use (architecture §5 S1).

The 4x4_50 dictionary is chosen for robustness at small print sizes rather than for capacity:
50 ids is far more than this product needs, and a coarser grid survives a phone camera at 40 cm
better than a denser one would.
"""


@dataclass(frozen=True)
class MarkerCorners:
    """The four detected corners of one marker, in image pixel coordinates.

    Order is the ArUco convention — top-left, top-right, bottom-right, bottom-left, as seen in
    the marker's own frame — which is what makes the homography in ``rectify`` unambiguous.
    """

    points: npt.NDArray[np.float32]
    marker_id: int

    @property
    def side_lengths_px(self) -> tuple[float, float, float, float]:
        """The four side lengths, clockwise from the top edge."""
        sides = [
            float(np.linalg.norm(self.points[i] - self.points[(i + 1) % 4])) for i in range(4)
        ]
        return (sides[0], sides[1], sides[2], sides[3])


@dataclass(frozen=True)
class Quality:
    """Capture quality signals (TRD FR-01).

    ``tilt_deg`` and ``curvature`` are ``None`` when they cannot be derived — with no marker
    there is no plane to measure an angle against. ``None`` means "unknown", never "fine".
    """

    blur: float
    """Variance of the Laplacian. Higher is sharper; FR-01 gates at 120."""

    glare: float
    """Fraction of pixels at or above 250 luminance. FR-01 gates at 2%."""

    tilt_deg: float | None
    """Approximate angle between the marker plane normal and the camera axis. FR-01 gates at 25°."""

    curvature: float | None
    """Surface curvature, when measurable. See ``quality`` for why this is currently always None."""


def _to_grey(image: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
    if image.ndim == 2:
        return image
    grey: npt.NDArray[np.uint8] = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.uint8)
    return grey


def detect_marker(image: npt.NDArray[np.uint8]) -> MarkerCorners | None:
    """Locate the scale marker in ``image``.

    Returns:
        The marker's corners, or ``None`` if no marker is present. ``None`` is a complete answer:
        the caller marks the scan ``no_marker`` and every metric rule becomes NOT_ASSESSABLE
        (architecture §11). Nothing in this module estimates a scale without one.
    """
    grey = _to_grey(image)

    dictionary = cv2.aruco.getPredefinedDictionary(MARKER_DICTIONARY)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    corners, ids, _rejected = detector.detectMarkers(grey)

    if ids is None or len(ids) == 0:
        return None

    # With several markers in frame, take the largest: it is the closest to the camera and
    # therefore the one carrying the most pixels per millimetre.
    areas = [cv2.contourArea(quad.reshape(4, 2).astype(np.float32)) for quad in corners]
    best = int(np.argmax(areas))

    # OpenCV 4.x returns ids shaped (N, 1); 5.x returns (N,). Flatten so this works on both
    # rather than tying the pipeline to one OpenCV major version.
    return MarkerCorners(
        points=np.asarray(corners[best]).reshape(4, 2).astype(np.float32),
        marker_id=int(np.ravel(ids)[best]),
    )


def _blur_score(grey: npt.NDArray[np.uint8]) -> float:
    return float(cv2.Laplacian(grey, cv2.CV_64F).var())


def _glare_fraction(grey: npt.NDArray[np.uint8]) -> float:
    return float(np.count_nonzero(grey >= 250) / grey.size)


def _tilt_degrees(corners: MarkerCorners) -> float:
    """Approximate the viewing angle from the marker's foreshortening.

    A square viewed square-on projects to a square; viewed off-normal, one pair of opposite sides
    shortens relative to the other. The ratio of the shorter mean to the longer gives the cosine
    of the viewing angle closely enough for a capture gate.

    This is an approximation, and it is used as one: it drives the FR-01 shutter gate and widens
    the measurement uncertainty band. It is deliberately **not** used to correct a measurement —
    a proper angle needs camera intrinsics this pipeline does not have, and a corrected number
    would carry more confidence than the input supports.
    """
    top, right, bottom, left = corners.side_lengths_px
    horizontal = (top + bottom) / 2.0
    vertical = (right + left) / 2.0
    if horizontal <= 0 or vertical <= 0:
        return 0.0

    ratio = min(horizontal, vertical) / max(horizontal, vertical)
    return float(math.degrees(math.acos(max(0.0, min(1.0, ratio)))))


def quality(
    image: npt.NDArray[np.uint8], corners: MarkerCorners | None
) -> Quality:
    """Report the capture gates of FR-01.

    ``curvature`` is always ``None`` today, and that is a deliberate refusal rather than an
    omission. Four coplanar points always fit a homography exactly, so a marker's corners carry
    no information about whether the *package* is curved. Architecture §12.2 downgrades metric
    rules to NOT_ASSESSABLE on high curvature, which only works if the curvature figure can be
    trusted; returning ``0.0`` here would assert flatness nobody measured. Real curvature
    estimation reads the rectified text region and belongs with glyph metrology (B7).
    """
    grey = _to_grey(image)
    return Quality(
        blur=_blur_score(grey),
        glare=_glare_fraction(grey),
        tilt_deg=_tilt_degrees(corners) if corners is not None else None,
        curvature=None,
    )


__all__ = ["MARKER_DICTIONARY", "MarkerCorners", "Quality", "detect_marker", "quality"]
