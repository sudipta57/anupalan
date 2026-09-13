"""Object storage adapter — backend work package B4, supporting TRD FR-20 and architecture §10.

Speaks the **S3 API**, never anything R2-specific. The provider is recorded in
`docs/01-architecture.md` §9, not in this module and not in the setting names: an on-premise
MinIO deployment — which a government buyer may require — must be an endpoint change, not a code
change.

Three things this module treats as non-negotiable:

**Every key begins with the owning org's id.** Org isolation is enforced in ``repositories/`` for
the database (CLAUDE.md §3.7), but object storage is a second door into the same evidence. A key
assembled without an org prefix, or one where a path segment escaped it, is that door left open —
so ``build_key`` validates every segment rather than trusting the caller.

**Limits are signed in, not checked afterwards.** A presigned URL is a capability handed to a
device nobody controls. A size or type rule enforced after the bytes arrive has already cost the
bandwidth it existed to save, and cannot be enforced at all if the upload goes straight to the
bucket.

**The hash is of the bytes as received.** Evidence integrity depends on the image hash covering
the original upload — before EXIF stripping, before rectification. A hash taken after processing
proves only that we did not corrupt our own output.

R2 rejects per-object ACLs, so nothing here sets one; buckets are private and every read is
presigned, which §10 required regardless.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Protocol

from app.config import settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

ASSET_KINDS = frozenset({"raw", "rectified", "annotated", "report", "export"})
"""Asset kinds a key may name. ``raw``/``rectified``/``annotated`` mirror the ``scan_assets.kind``
column in architecture §8; ``report`` and ``export`` cover generated documents."""

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
"""One key segment. Deliberately strict: no slashes, no leading dot, nothing that could climb out
of the org prefix. These values arrive over HTTP."""


class StorageError(RuntimeError):
    """A storage operation could not be performed as asked."""


class UnsupportedMediaTypeError(StorageError):
    """The content type is not on the allow-list."""


class UploadTooLargeError(StorageError):
    """The upload exceeds the configured ceiling."""


@dataclass(frozen=True)
class PresignedUpload:
    """A capability to write exactly one object, under stated limits."""

    key: str
    url: str
    headers: dict[str, str]
    max_bytes: int
    expires_in: int


@dataclass(frozen=True)
class StoredObject:
    """The result of a write, carrying the hash taken on the way in."""

    key: str
    sha256: str
    size: int
    content_type: str


class S3Client(Protocol):
    """The slice of the S3 client this module uses.

    Declared as a Protocol so the adapter can be tested against a fake without boto3, and so the
    dependency surface is visible rather than implied.
    """

    def generate_presigned_url(
        self, operation: str, Params: dict[str, Any], ExpiresIn: int  # noqa: N803
    ) -> str: ...

    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]: ...  # noqa: N803


def build_key(
    *, org_id: str, scan_id: str, kind: str, asset_id: str, extension: str
) -> str:
    """Assemble an object key as ``{org_id}/{scan_id}/{kind}/{asset_id}.{ext}``.

    Every segment is validated. The org prefix comes first and cannot be escaped.

    Raises:
        StorageError: a segment is empty, malformed, or attempts traversal, or ``kind`` is not a
            known asset kind.
    """
    if kind not in ASSET_KINDS:
        raise StorageError(
            f"unknown asset kind {kind!r}; expected one of {', '.join(sorted(ASSET_KINDS))}"
        )

    for label, value in (("org_id", org_id), ("scan_id", scan_id), ("asset_id", asset_id)):
        if not _SEGMENT.match(value or ""):
            raise StorageError(f"{label} {value!r} is not a valid key segment")

    clean_extension = extension.lstrip(".").lower()
    if not re.match(r"^[a-z0-9]{1,8}$", clean_extension):
        raise StorageError(f"extension {extension!r} is not valid")

    return f"{org_id}/{scan_id}/{kind}/{asset_id}.{clean_extension}"


PREFILL_PREFIX = "prefill"
"""Key prefix for context-prefill scratch images (FR-03).

Its own top-level prefix, not a ``kind`` under a scan, because these objects belong to no scan and
must not be reachable as a scan asset. The worker deletes each one as soon as it has read it; the
bucket carries a short lifecycle rule on this prefix as the backstop for a worker that died
between the upload and the read (``infra/README.md``).
"""


def build_prefill_key(*, org_id: str, prefill_id: str, extension: str) -> str:
    """Assemble a scratch key as ``prefill/{org_id}/{prefill_id}.{ext}``.

    Same validation as ``build_key`` and the same guarantee: the org prefix comes first and cannot
    be escaped.

    Raises:
        StorageError: a segment is empty, malformed, or attempts traversal.
    """
    for label, value in (("org_id", org_id), ("prefill_id", prefill_id)):
        if not _SEGMENT.match(value or ""):
            raise StorageError(f"{label} {value!r} is not a valid key segment")

    clean_extension = extension.lstrip(".").lower()
    if not re.match(r"^[a-z0-9]{1,8}$", clean_extension):
        raise StorageError(f"extension {extension!r} is not valid")

    return f"{PREFILL_PREFIX}/{org_id}/{prefill_id}.{clean_extension}"


def strip_exif(data: bytes) -> bytes:
    """Return ``data`` with image metadata removed, or unchanged if it is not an image.

    A photograph of a label carries the device, the timestamp and — in Mode A — the inspector's
    GPS position. Location is collected deliberately and disclosed in-app (architecture §10); it
    must not also leak silently through an image served to somebody else.

    Metadata is dropped by rebuilding the image from its pixel data rather than by deleting named
    tags, so every block goes at once — EXIF, XMP, IPTC and any private maker note — instead of
    only the ones somebody thought to enumerate.

    Non-images pass through untouched: the same adapter stores JSON and PDFs.

    Raises:
        StorageError: the payload is an image but could not be re-encoded. This fails loudly on
            purpose. Returning the original bytes would hand back a file that still carries the
            metadata this function exists to remove, and nothing downstream would know.
    """
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # noqa: BLE001 - not an image Pillow recognises; nothing to strip
        return data

    image_format = image.format
    if image_format is None:
        return data

    try:
        # JPEG has no alpha channel and no palette; converting first avoids failing on a PNG-like
        # mode that arrived with a .jpg content type.
        source = image.convert("RGB") if (
            image_format == "JPEG" and image.mode not in {"RGB", "L", "CMYK"}
        ) else image

        # frombytes on the raw pixel buffer produces an image with an empty ``info`` dict, so
        # nothing carries over. Also avoids getdata(), deprecated in Pillow 12.
        cleaned = Image.frombytes(source.mode, source.size, source.tobytes())

        buffer = io.BytesIO()
        save_kwargs: dict[str, Any] = {"format": image_format}
        if image_format == "JPEG":
            save_kwargs["quality"] = 95
        cleaned.save(buffer, **save_kwargs)
        return buffer.getvalue()
    except Exception as exc:
        raise StorageError(
            f"could not strip metadata from a {image_format} image: {exc}. "
            "Refusing to return the original bytes, which still carry it."
        ) from exc


class ObjectStore:
    """S3-API object storage, scoped to one bucket."""

    def __init__(
        self,
        *,
        client: S3Client,
        bucket: str,
        presign_expiry_seconds: int,
        max_bytes: int | None = None,
        allowed_content_types: frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.presign_expiry_seconds = presign_expiry_seconds
        self.max_bytes = max_bytes if max_bytes is not None else settings.UPLOAD_MAX_BYTES
        self.allowed_content_types = (
            allowed_content_types
            if allowed_content_types is not None
            else frozenset(settings.UPLOAD_ALLOWED_CONTENT_TYPES)
        )

    # ------------------------------------------------------------------ guards

    def _check_content_type(self, content_type: str) -> None:
        if content_type not in self.allowed_content_types:
            raise UnsupportedMediaTypeError(
                f"content type {content_type!r} is not accepted; allowed: "
                f"{', '.join(sorted(self.allowed_content_types))}"
            )

    def _check_size(self, size: int) -> None:
        if size > self.max_bytes:
            raise UploadTooLargeError(
                f"{size} bytes exceeds the {self.max_bytes} byte ceiling"
            )

    # ------------------------------------------------------------------ presigning

    def presign_put(
        self, key: str, content_type: str, size_limit: int
    ) -> PresignedUpload:
        """Issue a capability to upload one object.

        The content type is part of the signature, so a client cannot present one type to the
        allow-list and upload another.
        """
        self._check_content_type(content_type)
        self._check_size(size_limit)

        url = self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self.presign_expiry_seconds,
        )
        return PresignedUpload(
            key=key,
            url=url,
            headers={"Content-Type": content_type},
            max_bytes=size_limit,
            expires_in=self.presign_expiry_seconds,
        )

    def presign_get(self, key: str, expires_in: int | None = None) -> str:
        """Issue a time-limited read URL. Buckets are private; this is the only read path."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in if expires_in is not None else self.presign_expiry_seconds,
        )

    # ------------------------------------------------------------------ transfer

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        """Write bytes and return their SHA-256, taken before the write.

        The hash covers exactly what arrived. Nothing in this method transforms the payload —
        EXIF stripping is a separate, explicit step applied to what gets *served*.
        """
        self._check_size(len(data))
        digest = hashlib.sha256(data).hexdigest()

        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            # No ACL: R2 rejects per-object ACLs and the bucket is private by policy.
        )
        return StoredObject(
            key=key, sha256=digest, size=len(data), content_type=content_type
        )

    def get_bytes(self, key: str) -> bytes:
        """Read an object's bytes."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"could not read {key!r}: {exc}") from exc
        body: Any = response["Body"]
        read = body.read()
        return bytes(read)

    def delete(self, key: str) -> None:
        """Delete an object. Used by the integration test; evidence is never deleted in Mode A."""
        delete_object = getattr(self.client, "delete_object", None)
        if delete_object is None:
            raise StorageError("this client does not support delete_object")
        delete_object(Bucket=self.bucket, Key=key)


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    """Return the process-wide object store, built from settings on first use.

    boto3 is imported here rather than at module scope so that importing this module — and using
    ``build_key`` or ``strip_exif`` — does not require it.
    """
    if not settings.S3_BUCKET:
        raise StorageError(
            "S3_BUCKET is not set. Copy backend/.env.example to backend/.env and paste your "
            "Cloudflare R2 values — see infra/README.md §3."
        )

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.S3_USE_PATH_STYLE else "virtual"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    return ObjectStore(
        client=client,
        bucket=settings.S3_BUCKET,
        presign_expiry_seconds=settings.S3_PRESIGN_EXPIRY_SECONDS,
    )


__all__ = [
    "ASSET_KINDS",
    "ObjectStore",
    "PresignedUpload",
    "S3Client",
    "StorageError",
    "StoredObject",
    "UnsupportedMediaTypeError",
    "UploadTooLargeError",
    "build_key",
    "get_store",
    "strip_exif",
]
