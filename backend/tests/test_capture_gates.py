"""Capture gates measured server-side — FR-01, the interim of `03-implementation-plan.md` §P3.3.

The gate chips on the capture screen were driven by a timer: they turned green 2.4 seconds after
the screen opened, on any subject, because the ArUco frame processor they were meant to read was
never written. A green shutter over a frame with no marker lets an inspector submit a photograph
that cannot be rectified, and the failure surfaces much later, on the findings screen, as "no
rectified image".

So the test that matters is the first one below: **a frame with no marker must report no marker**,
on real pixels rather than a mock. Everything else here defends properties that are easy to lose
in a refactor — that tilt is null rather than zero when there is no plane to measure against, that
the endpoint stores nothing, and that it never returns a verdict.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator

import cv2
import numpy as np
import numpy.typing as npt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.vision.marker import MARKER_DICTIONARY
from tests.conftest import make_org, make_user


def sign_in(api: TestClient, phone: str) -> dict[str, str]:
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    body = requested.json()
    verified = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['access']}"}


@pytest.fixture
def api(db_session) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.routers.deps import db

    app.dependency_overrides[db] = lambda: db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def auth(db_session, api) -> dict[str, str]:  # type: ignore[no-untyped-def]
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    return sign_in(api, "+919812345678")


def blank(shade: int = 200, size: tuple[int, int] = (480, 640)) -> npt.NDArray[np.uint8]:
    """A frame with nothing in it — the desk the capture screen was pointed at."""
    return np.full(size, shade, dtype=np.uint8)


def with_marker(
    *, marker_px: int = 160, blur: int = 0, shade: int = 200
) -> npt.NDArray[np.uint8]:
    """A frame with a real ArUco 4x4_50 tag in it, rendered by OpenCV.

    A real tag rather than a stub: the whole point of this endpoint is that the detector runs on
    actual pixels, and a mocked detector would pass whether or not that were true.
    """
    image = blank(shade)
    dictionary = cv2.aruco.getPredefinedDictionary(MARKER_DICTIONARY)
    marker = cv2.aruco.generateImageMarker(dictionary, 0, marker_px)
    image[60 : 60 + marker_px, 80 : 80 + marker_px] = marker
    if blur:
        image = cv2.GaussianBlur(image, (blur, blur), 0)
    return image


def frame(image: npt.NDArray[np.uint8]) -> dict[str, str]:
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return {"frame_base64": base64.b64encode(buffer.tobytes()).decode("ascii")}


def post(api: TestClient, auth: dict[str, str], image: npt.NDArray[np.uint8]):  # type: ignore[no-untyped-def]
    return api.post("/v1/capture/gates", json=frame(image), headers=auth)


# --------------------------------------------------------------------------- the bug


def test_a_frame_with_no_marker_reports_no_marker(api, auth) -> None:  # type: ignore[no-untyped-def]
    """The simulation's failure, in one assertion.

    Pointed at a blank desk, the old evaluator said four corners after 2.4 seconds. This is what
    the screen has to be told instead.
    """
    response = post(api, auth, blank())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["marker_corners_in_frame"] == 0
    assert body["marker_id"] is None


def test_a_frame_with_a_marker_reports_four_corners(api, auth) -> None:  # type: ignore[no-untyped-def]
    """And the other half: a real tag is actually found, so the gate can ever open."""
    response = post(api, auth, with_marker())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["marker_corners_in_frame"] == 4
    assert body["marker_id"] == 0


# --------------------------------------------------------------------------- unknown is not fine


def test_tilt_is_unknown_rather_than_zero_without_a_marker(api, auth) -> None:  # type: ignore[no-untyped-def]
    """Tilt is measured against the marker's plane, so with no marker there is no angle.

    Null, never 0.0. Zero degrees is "held perfectly flat" — the best possible reading — and
    reporting it for a frame nobody could measure would turn an unanswerable question into a pass.
    CLAUDE.md §3.3 in miniature: a number that cannot be derived is not estimated.
    """
    body = post(api, auth, blank()).json()

    assert body["tilt_degrees"] is None


def test_tilt_is_measured_when_a_marker_is_present(api, auth) -> None:  # type: ignore[no-untyped-def]
    body = post(api, auth, with_marker()).json()

    assert body["tilt_degrees"] is not None
    # Rendered square-on, so the angle should be near zero rather than merely non-null.
    assert body["tilt_degrees"] < 5.0


# --------------------------------------------------------------------------- the other two gates


def test_a_blurred_frame_scores_lower_than_a_sharp_one(api, auth) -> None:  # type: ignore[no-untyped-def]
    """Relative, not absolute: the threshold lives in the client's rule module, not here.

    Pinning an absolute variance would put half the FR-01 policy on the server and half in
    `gates.ts`, and the two would drift.
    """
    sharp = post(api, auth, with_marker()).json()["blur_variance"]
    soft = post(api, auth, with_marker(blur=9)).json()["blur_variance"]

    assert soft < sharp


def test_a_blown_out_frame_reports_glare(api, auth) -> None:  # type: ignore[no-untyped-def]
    dim = post(api, auth, blank(shade=120)).json()["glare_fraction"]
    blown = post(api, auth, blank(shade=255)).json()["glare_fraction"]

    assert dim == pytest.approx(0.0)
    assert blown == pytest.approx(1.0)


# --------------------------------------------------------------------------- what it must not do


def test_the_endpoint_returns_measurements_and_never_a_verdict(api, auth) -> None:  # type: ignore[no-untyped-def]
    """No `can_capture`, no `pass`, no `blocking`.

    The shutter policy is `features/capture/gates.ts`, which is pure and tested without a camera.
    A verdict computed here would be a second copy of the thresholds, and the copy that ships is
    whichever one the reviewer did not read (CLAUDE.md §3.2 takes the same line on rule packs).
    """
    body = post(api, auth, with_marker()).json()

    assert set(body) == {
        "marker_corners_in_frame",
        "blur_variance",
        "glare_fraction",
        "tilt_degrees",
        "marker_id",
    }


def test_an_unauthenticated_request_is_refused(api) -> None:  # type: ignore[no-untyped-def]
    """A public image-decoding endpoint is a way to spend somebody else's CPU."""
    response = api.post("/v1/capture/gates", json=frame(blank()))

    assert response.status_code == 401


def test_an_oversized_frame_is_refused(api, auth, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The ceiling is what stops this being used to push photographs through the API process."""
    from app.config import settings

    monkeypatch.setattr(settings, "CAPTURE_FRAME_MAX_BYTES", 64)
    response = post(api, auth, with_marker())

    assert response.status_code == 413


def test_a_frame_that_is_not_an_image_is_refused(api, auth) -> None:  # type: ignore[no-untyped-def]
    response = api.post(
        "/v1/capture/gates",
        json={"frame_base64": base64.b64encode(b"not an image at all").decode("ascii")},
        headers=auth,
    )

    assert response.status_code == 422


def test_a_malformed_body_is_refused(api, auth) -> None:  # type: ignore[no-untyped-def]
    """`extra="forbid"`, like every request schema here: a mismatched key is a 422, not a drop."""
    response = api.post(
        "/v1/capture/gates",
        json={"frame_base64": "////", "threshold": 120},
        headers=auth,
    )

    assert response.status_code == 422
