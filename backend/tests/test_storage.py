"""Object storage adapter — backend work package B4, supporting TRD FR-20 and architecture §10.

Three properties are being pinned here, and only one of them is about talking to S3.

**The org prefix is not optional.** Every key starts with the owning org's id. Org isolation is
enforced in the repository layer for the database (CLAUDE.md §3.7), but object storage is a
second door into the same data, and a key built without an org prefix is a door left open.

**Limits are enforced when the URL is issued, not after the bytes land.** A presigned URL is a
capability handed to a device we do not control. Whatever the policy is, it has to be baked into
the signature.

**The hash is taken of the bytes as received.** Evidence integrity (architecture §10) depends on
the image hash being of the original upload — before EXIF stripping, before rectification, before
anything. A hash taken after processing proves only that we did not corrupt our own output.

The real-bucket test is opt-in and skips without credentials, so this suite runs in CI where no
R2 credentials exist.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

import pytest

from app.services.storage import (
    ObjectStore,
    StorageError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
    build_key,
    strip_exif,
)

ORG = "11111111-1111-4111-8111-111111111111"
SCAN = "22222222-2222-4222-8222-222222222222"
ASSET = "33333333-3333-4333-8333-333333333333"


class FakeS3Client:
    """Records calls instead of making them. Enough surface for the adapter, nothing more."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.presign_calls: list[dict[str, Any]] = []
        self.put_calls: list[dict[str, Any]] = []

    def generate_presigned_url(
        self,
        operation: str,
        Params: dict[str, Any],  # noqa: N803 - boto3's own PascalCase parameter
        ExpiresIn: int,  # noqa: N803 - boto3's own PascalCase parameter
    ) -> str:
        self.presign_calls.append(
            {"operation": operation, "params": Params, "expires_in": ExpiresIn}
        )
        return f"https://example.invalid/{Params['Key']}?sig=fake&exp={ExpiresIn}"

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": '"fake"'}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}


@pytest.fixture
def store() -> ObjectStore:
    return ObjectStore(client=FakeS3Client(), bucket="test-bucket", presign_expiry_seconds=900)


# --------------------------------------------------------------------------- key layout


def test_key_carries_the_org_prefix_first() -> None:
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    assert key == f"{ORG}/{SCAN}/raw/{ASSET}.jpg"
    assert key.startswith(f"{ORG}/"), "the org prefix must come first or it isolates nothing"


def test_key_rejects_traversal_and_empty_segments() -> None:
    """A key is assembled from values that arrive over HTTP. None of them may escape the prefix."""
    with pytest.raises(StorageError):
        build_key(org_id="..", scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    with pytest.raises(StorageError):
        build_key(org_id=ORG, scan_id="a/../../b", kind="raw", asset_id=ASSET, extension="jpg")

    with pytest.raises(StorageError):
        build_key(org_id="", scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")


def test_key_rejects_an_unknown_asset_kind() -> None:
    with pytest.raises(StorageError):
        build_key(org_id=ORG, scan_id=SCAN, kind="not-a-kind", asset_id=ASSET, extension="jpg")


# --------------------------------------------------------------------------- presigning


def test_presign_put_returns_a_url_and_the_limits_it_was_signed_with(store: ObjectStore) -> None:
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    upload = store.presign_put(key, content_type="image/jpeg", size_limit=1_000_000)

    assert upload.key == key
    assert upload.url.startswith("https://")
    assert upload.max_bytes == 1_000_000
    assert upload.headers["Content-Type"] == "image/jpeg"
    assert upload.expires_in == 900


def test_presign_put_refuses_a_content_type_outside_the_allow_list(store: ObjectStore) -> None:
    """An allow-list, not a deny-list. A camera produces a small, known set of types."""
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="svg")

    with pytest.raises(UnsupportedMediaTypeError):
        store.presign_put(key, content_type="image/svg+xml", size_limit=1_000)


def test_presign_put_refuses_a_size_limit_above_the_configured_ceiling(store: ObjectStore) -> None:
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    with pytest.raises(UploadTooLargeError):
        store.presign_put(key, content_type="image/jpeg", size_limit=999_999_999)


def test_presign_put_signs_the_content_type_so_it_cannot_be_swapped(store: ObjectStore) -> None:
    """If the type is not part of the signature, the allow-list is advisory."""
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    store.presign_put(key, content_type="image/jpeg", size_limit=1_000_000)

    params = store.client.presign_calls[0]["params"]  # type: ignore[attr-defined]
    assert params["ContentType"] == "image/jpeg"
    assert "ACL" not in params, "R2 rejects per-object ACLs; access is presigned-only"


def test_presign_get_honours_an_explicit_expiry(store: ObjectStore) -> None:
    key = build_key(org_id=ORG, scan_id=SCAN, kind="rectified", asset_id=ASSET, extension="png")

    store.presign_get(key, expires_in=60)

    assert store.client.presign_calls[0]["expires_in"] == 60  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- hashing


def test_put_bytes_hashes_what_it_received(store: ObjectStore) -> None:
    """Architecture §10: the recorded hash is of the bytes as received, before any processing."""
    payload = b"\xff\xd8\xff\xe0 not really a jpeg but bytes are bytes"
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    stored = store.put_bytes(key, payload, content_type="image/jpeg")

    assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    assert stored.size == len(payload)
    assert stored.key == key


def test_round_trip_returns_the_same_bytes(store: ObjectStore) -> None:
    payload = b"round trip"
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    store.put_bytes(key, payload, content_type="image/jpeg")

    assert store.get_bytes(key) == payload


def test_put_bytes_enforces_the_size_ceiling(store: ObjectStore) -> None:
    key = build_key(org_id=ORG, scan_id=SCAN, kind="raw", asset_id=ASSET, extension="jpg")

    with pytest.raises(UploadTooLargeError):
        store.put_bytes(key, b"x" * (16 * 1024 * 1024), content_type="image/jpeg")


# --------------------------------------------------------------------------- EXIF


def test_strip_exif_removes_metadata_and_keeps_the_picture() -> None:
    """A label photo carries the device, the timestamp and — in Mode A — the inspector's GPS
    position. Anything served is stripped (architecture §10).

    ``strip_exif`` rebuilds the image from its pixel data rather than deleting named tags, so
    every metadata block goes at once: EXIF, XMP, IPTC and any private maker note. This asserts
    that on ordinary scalar tags; GPS lives in the same block and leaves with it. The pixels must
    survive.
    """
    from PIL import Image

    original = Image.new("RGB", (24, 16), color=(120, 30, 30))
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "AnupalanTestCamera"  # Make
    exif[0x0110] = "SecretModel9000"  # Model
    exif[0x0132] = "2026:10:01 09:30:00"  # DateTime
    original.save(buffer, format="JPEG", exif=exif)
    with_exif = buffer.getvalue()

    assert Image.open(io.BytesIO(with_exif)).getexif(), "fixture should start with EXIF"
    assert b"AnupalanTestCamera" in with_exif

    cleaned = strip_exif(with_exif)
    reopened = Image.open(io.BytesIO(cleaned))

    assert not reopened.getexif()
    assert reopened.size == (24, 16)
    assert b"AnupalanTestCamera" not in cleaned
    assert b"SecretModel9000" not in cleaned
    assert b"2026:10:01" not in cleaned


def test_strip_exif_raises_rather_than_returning_unstripped_bytes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Regression: this function was once a silent no-op.

    An invalid encoder argument made the re-encode raise, a broad ``except`` caught it, and the
    ORIGINAL bytes were returned — metadata and all — with no error anywhere. A security function
    that fails open is worse than one that is missing, because it is believed. If the payload is
    an image and stripping fails, it must raise.
    """
    from PIL import Image

    original = Image.new("RGB", (8, 8), color=(1, 2, 3))
    buffer = io.BytesIO()
    original.save(buffer, format="JPEG")
    payload = buffer.getvalue()

    def exploding_save(self, fp, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("encoder unavailable")

    monkeypatch.setattr(Image.Image, "save", exploding_save)

    with pytest.raises(StorageError, match="Refusing to return the original bytes"):
        strip_exif(payload)


def test_strip_exif_leaves_a_non_image_untouched() -> None:
    """The pipeline stores JSON and PDFs through the same adapter; stripping must not corrupt
    something that has no EXIF to begin with."""
    payload = b'{"findings": []}'

    assert strip_exif(payload) == payload


# --------------------------------------------------------------------------- real bucket


@pytest.mark.skipif(
    not __import__("app.config", fromlist=["settings"]).settings.S3_BUCKET,
    reason="no S3/R2 credentials configured",
)
def test_real_bucket_round_trip() -> None:
    """Opt-in. Proves the adapter works against the actual endpoint, not just the fake."""
    from app.services.storage import get_store

    real = get_store()
    key = build_key(
        org_id=ORG, scan_id=SCAN, kind="raw", asset_id="connectivity-probe", extension="txt"
    )
    payload = b"anupalan storage round trip"

    stored = real.put_bytes(key, payload, content_type="text/plain")
    try:
        assert real.get_bytes(key) == payload
        assert stored.sha256 == hashlib.sha256(payload).hexdigest()
    finally:
        real.delete(key)
