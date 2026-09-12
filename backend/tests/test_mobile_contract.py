"""The bodies the mobile client actually sends, against the schemas that receive them.

Every request schema inherits ``StrictModel``, which sets ``extra="forbid"``. That is the right
default and it has a sharp edge: a client sending ``requestId`` where the server expects
``request_id`` gets a **422**, not a field quietly dropped. Sign-in fails at the first call; a
refresh fails in a way the transport reads as a dead session and signs the user out.

So this file pins the wire spelling from the *other* side. The literals below are copied from what
``mobile/src/api/endpoints.ts`` constructs — not from the schemas — so a rename on either side
fails here rather than on a phone.

They are deliberately literal rather than generated. A generator that read the schemas to build the
bodies would agree with itself no matter what the client sends.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import OtpRequestIn, OtpVerifyIn, RefreshIn
from app.schemas.findings import ConfirmFieldsIn
from app.schemas.scans import ScanCreateIn

SHA = "a" * 64


def test_the_otp_request_body_is_accepted() -> None:
    assert OtpRequestIn.model_validate({"phone": "+919812345678"})


def test_the_otp_verify_body_is_accepted() -> None:
    """`request_id`, not `requestId` — the whole of sign-in depends on this one spelling."""
    body = {"request_id": "b3f1c2d4-5e6a-4b7c-8d9e-0f1a2b3c4d5e", "code": "123456"}

    assert OtpVerifyIn.model_validate(body)


def test_a_camel_cased_verify_body_is_refused_rather_than_ignored() -> None:
    """The failure mode this file exists for, asserted directly."""
    with pytest.raises(ValidationError):
        OtpVerifyIn.model_validate(
            {"requestId": "b3f1c2d4-5e6a-4b7c-8d9e-0f1a2b3c4d5e", "code": "123456"}
        )


def test_the_refresh_body_is_accepted() -> None:
    """`refresh`, not `refreshToken`.

    A mismatch here is worse than a failed call: the client treats a failed refresh as the end of a
    session, so the wrong spelling would sign users out every time an access token expired.
    """
    assert RefreshIn.model_validate({"refresh": "a-refresh-token"})


def test_the_create_scan_body_is_accepted() -> None:
    """The full body the queue runner sends, including the per-asset hash it computes on device."""
    body = {
        "profile": {
            "is_imported": False,
            "surface": "printed",
            "qty_basis": "weight_or_volume",
            "channel": "retail",
            "net_qty_in_g_or_ml": 1000.0,
            "pdp_area_cm2": 70.0,
            "net_qty_value": 1.0,
            "net_qty_unit": "kg",
            "pack_type": "flexible",
            "category_code": "food.flour",
            "name": "Sampoorna Whole Wheat Atta 1 kg",
        },
        "marker_type": "aruco_4x4_50",
        "marker_mm": 40.0,
        "assets": [
            {"content_type": "image/jpeg", "size_bytes": 2_400_000, "sha256": SHA, "kind": "raw"}
        ],
        "captured_at": "2026-09-12T06:00:00.000Z",
        "geo_lat": 23.4,
        "geo_lon": 88.5,
        "geo_accuracy_m": 12.0,
        "district": "Nadia",
    }

    parsed = ScanCreateIn.model_validate(body)

    assert parsed.district == "Nadia"
    assert parsed.assets[0].sha256 == SHA
    # The rule pack addresses these names. A rename here breaks a pack, not just a client.
    assert parsed.profile.net_qty_in_g_or_ml == 1000.0
    assert parsed.profile.is_imported is False


def test_a_mode_b_create_scan_body_is_accepted() -> None:
    """No location at all, which is the normal case for industry and not a missing value."""
    body = {
        "profile": {"qty_basis": "weight_or_volume", "surface": "printed"},
        "marker_type": "id1_card",
        "marker_mm": 85.6,
        "assets": [
            {"content_type": "image/jpeg", "size_bytes": 1024, "sha256": SHA, "kind": "raw"}
        ],
        "captured_at": "2026-09-12T06:00:00.000Z",
        "district": None,
    }

    parsed = ScanCreateIn.model_validate(body)

    assert parsed.district is None
    assert parsed.geo_lat is None


def test_the_confirm_fields_body_is_accepted() -> None:
    """The one body needing no translation — `code` and `value` are spelled alike on both sides."""
    body = {"fields": [{"code": "mrp", "value": "MRP Rs. 250.00 (inclusive of all taxes)"}]}

    assert ConfirmFieldsIn.model_validate(body)


def test_an_asset_declared_without_a_hash_is_refused() -> None:
    """The hash is what makes the declaration checkable. Optional, it would be decorative."""
    with pytest.raises(ValidationError):
        ScanCreateIn.model_validate(
            {
                "profile": {},
                "marker_type": "aruco_4x4_50",
                "marker_mm": 40.0,
                "assets": [{"content_type": "image/jpeg", "size_bytes": 1024}],
                "captured_at": "2026-09-12T06:00:00.000Z",
            }
        )


def test_an_uppercase_hash_is_refused() -> None:
    """The client lowercases its hex for exactly this reason — the pattern is `^[0-9a-f]{64}$`."""
    with pytest.raises(ValidationError):
        ScanCreateIn.model_validate(
            {
                "profile": {},
                "marker_type": "aruco_4x4_50",
                "marker_mm": 40.0,
                "assets": [
                    {"content_type": "image/jpeg", "size_bytes": 1024, "sha256": "A" * 64}
                ],
                "captured_at": "2026-09-12T06:00:00.000Z",
            }
        )
