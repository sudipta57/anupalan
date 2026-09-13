"""Capture gates — measure a live preview frame so the shutter can be honest (FR-01).

    POST /v1/capture/gates   {frame_base64} -> {marker_corners_in_frame, blur_variance,
                                               glare_fraction, tilt_degrees, marker_id}

**Why this endpoint exists.** The four gate chips on the capture screen were driven by a timer:
they went green 2.4 seconds after the screen opened, on any subject, because the ArUco frame
processor they were meant to read was never written (`docs/05-frontend-plan.md` §45 deferred it).
A green shutter over a frame with no marker is worse than no gate at all — it lets an inspector
submit a photograph that cannot be rectified, and the failure surfaces much later as "no rectified
image" on the findings screen. `docs/03-implementation-plan.md` §P3.3 sanctions exactly this
interim: *"ship the interim version that uploads a frame every 500 ms for server-side gate checks,
and swap later."*

**This does not break "the API never proxies image bytes"** (`routers/scans.py`). That rule is
about *scan assets* — evidence photographs, which go straight to object storage under a declared
SHA-256 because they must be durable, auditable and untouched. A gate frame is the opposite of
evidence on every axis, and this module is built so that stays true:

* it is **never stored** — not in object storage, not in Redis, not in a database row. The bytes
  live in one request handler's local and are gone when it returns;
* it opens **no database session** and writes **no audit entry**, because nothing is created and
  nothing is judged;
* it is a **downscaled preview frame**, not the photograph. The scan is still measured by the
  pipeline off the full-resolution original.

**It runs in the API process rather than the worker**, which is the opposite of `prefill`. Prefill
goes to the worker because it needs OCR models the API must not load. A gate check needs ArUco
detection and a Laplacian — tens of milliseconds of OpenCV on a small frame, no model weights —
and it is on a latency budget a broker round trip would blow. Nothing here imports the OCR stack.

**It measures; it does not decide.** The thresholds stay on the client, in `features/capture/
gates.ts`, which is the module that already owns the FR-01 policy and is unit-tested without a
camera. Returning a verdict from here would put half the gate policy on each side of the wire and
guarantee they drift.
"""

from __future__ import annotations

import base64
import binascii

import cv2
import numpy as np
import numpy.typing as npt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.routers.deps import CurrentPrincipal, requires
from app.schemas.base import StrictModel
from app.services.auth.rbac import Permission
from app.services.vision.marker import detect_marker, quality

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/capture", tags=["capture"])


class GateFrameIn(StrictModel):
    """One preview frame, base64-encoded."""

    frame_base64: str = Field(min_length=4, description="A JPEG, PNG or WebP preview frame")


class GateMetricsOut(BaseModel):
    """The four FR-01 signals, in the shape the client's `FrameMetrics` already has.

    Field-for-field with `mobile/src/features/capture/gates.ts`, so the adapter is a rename and
    there is nowhere for a unit or a meaning to shift in translation.
    """

    marker_corners_in_frame: int = Field(
        ge=0, le=4, description="How many of the marker's four corners are inside the frame"
    )
    blur_variance: float = Field(description="Variance of the Laplacian. Higher is sharper.")
    glare_fraction: float = Field(description="Fraction of pixels at or above 250 luminance")
    tilt_degrees: float | None = Field(
        default=None,
        description=(
            "Angle between the marker plane and the camera axis. Null when no marker was found — "
            "with no plane there is no angle, and 'unknown' is not 'fine' (CLAUDE.md §3.3)."
        ),
    )
    marker_id: int | None = Field(
        default=None, description="Which ArUco id was seen. Null when none was."
    )


def _decode(payload: GateFrameIn) -> npt.NDArray[np.uint8]:
    """The frame as greyscale pixels, refusing anything malformed or oversized.

    Greyscale because every signal below is computed from luminance: the marker detector greys the
    image itself, and blur and glare are defined on it. Decoding colour would trade memory and time
    for nothing.
    """
    try:
        raw = base64.b64decode(payload.frame_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="frame_base64 is not valid base64",
        ) from exc

    if len(raw) > settings.CAPTURE_FRAME_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"a gate frame must be under {settings.CAPTURE_FRAME_MAX_BYTES} bytes. Send a "
                "downscaled preview — this endpoint never measures a millimetre, so resolution "
                "beyond marker detection buys nothing and costs the frame rate."
            ),
        )

    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="frame_base64 did not decode to an image",
        )

    image: npt.NDArray[np.uint8] = decoded.astype(np.uint8)
    return image


@router.post(
    "/gates",
    response_model=GateMetricsOut,
    summary="Measure a preview frame against the FR-01 capture gates",
    dependencies=[Depends(requires(Permission.SCAN_CREATE))],
)
def gates(payload: GateFrameIn, principal: CurrentPrincipal) -> GateMetricsOut:
    """Report what is actually in front of the camera.

    ``principal`` is unused beyond the permission check above, and that is the point: there is no
    org-scoped resource here to look up, because nothing is stored. It stays in the signature so
    the endpoint cannot be reached unauthenticated — a public image-decoding endpoint is a way to
    spend somebody else's CPU.
    """
    image = _decode(payload)

    corners = detect_marker(image)
    signals = quality(image, corners)

    return GateMetricsOut(
        # Four or none. The detector returns a complete quadrilateral or nothing at all, so a
        # partially-visible marker reads as absent rather than as three corners — which is the
        # honest answer, since three corners give no homography (gates.ts says the same).
        marker_corners_in_frame=4 if corners is not None else 0,
        blur_variance=signals.blur,
        glare_fraction=signals.glare,
        tilt_degrees=signals.tilt_deg,
        marker_id=corners.marker_id if corners is not None else None,
    )


__all__ = ["router"]
