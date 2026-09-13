"""Context prefill — read a label photograph so the user does not have to type the form (FR-03).

Two endpoints and no resource. A prefill has no database row, no scan and no history: it is a
question asked of one photograph, answered within a minute, and then gone
(``services/prefill.py`` explains why it is built that way).

    POST /v1/prefill            → 202 {prefill_id, status: "reading"}
    GET  /v1/prefill/{id}       → {status, suggestions, word_count, reduced}

**Its own prefix rather than under ``/scans``** because it is not a scan and must not read as
one. No scan exists at this point in the flow, and one may never exist — the user is still at the
form, and may abandon it.

**Nothing here can fail the capture path.** The app asks for a prefill while showing a form that
already works; every answer this can give, including no answer at all, leaves that form working.
So a disabled feature is a 503, a broker that is down is still a 202 with a prefill that never
becomes ready, and an id that does not resolve is a 404 the client treats as "type it yourself".
The one thing the app must never get is a reason to stop and deal with an error, which is why the
only 4xx here are for a request that is malformed or too large.

**Org scoping is in the store key, not in a check after the read** (``prefill._key``), so a
prefill id from another org does not resolve and the answer is 404 — the same answer as an id that
never existed, never 403 (CLAUDE.md §3.7).

**Neither endpoint opens a database session**, and neither writes an audit entry. There is nothing
to audit: no record is created, nothing is judged, and the photograph is deleted unread-from
within the minute. The auditable event on this path is ``scan.create``, which happens later, from
a profile the user affirmed.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import settings
from app.routers.deps import CurrentPrincipal, PrefillEnqueuer, requires
from app.schemas.prefill import (
    PrefillAcceptedOut,
    PrefillCreateIn,
    PrefillOut,
    SuggestionOut,
)
from app.services.auth.rbac import Permission
from app.services.prefill import PrefillRecord, get_store, new_prefill_id
from app.services.storage import StorageError, build_prefill_key, strip_exif
from app.services.storage import get_store as get_object_store

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/prefill", tags=["prefill"])

_EXTENSION_FOR = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
"""Scratch-key extension per accepted content type. The accepted set is the schema's Literal; this
only decides how the key is spelled."""


def _decoded(payload: PrefillCreateIn) -> bytes:
    """The image bytes, refusing anything malformed or over the ceiling.

    Size is checked **after** decoding, against the real byte count, because base64 length is a
    proxy and the ceiling is about how much the worker will be asked to read.
    """
    try:
        image = base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="image_base64 is not valid base64",
        ) from exc

    if not image:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="image_base64 decoded to nothing",
        )

    if len(image) > settings.PREFILL_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"image is {len(image)} bytes; the ceiling is {settings.PREFILL_MAX_BYTES}. "
                "Downscale before sending — prefill reads words and never measures, so a "
                "thumbnail is enough."
            ),
        )

    return image


@router.post(
    "",
    response_model=PrefillAcceptedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Read a label photograph to prefill the product context form",
    dependencies=[Depends(requires(Permission.SCAN_CREATE))],
)
def create_prefill(
    payload: PrefillCreateIn,
    principal: CurrentPrincipal,
    enqueue: PrefillEnqueuer,
) -> PrefillAcceptedOut:
    """Accept a photograph and queue it to be read (FR-03).

    Returns immediately with an id to poll. The read happens in the worker, which is where the OCR
    models live — the API process does not load them and must not start doing so on a request
    path.

    Permissioned as ``SCAN_CREATE``: prefill is part of creating a scan, and anyone who may not
    create one has no use for a form to be filled.
    """
    if not settings.PREFILL_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="context prefill is disabled; the product context form still works by hand",
        )

    image = _decoded(payload)
    prefill_id = new_prefill_id()

    key = build_prefill_key(
        org_id=str(principal.org_id),
        prefill_id=prefill_id,
        extension=_EXTENSION_FOR[payload.content_type],
    )

    try:
        # EXIF is stripped even though this object is deleted minutes from now. It carries the
        # device, the time and often the inspector's coordinates (`storage.strip_exif`), and a
        # short life is not a reason to write it down at all.
        get_object_store().put_bytes(key, strip_exif(image), payload.content_type)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Marked `reading` before the enqueue, so a client that polls between the two gets "reading"
    # rather than a 404 it would read as "gone".
    get_store().put(str(principal.org_id), PrefillRecord.reading(prefill_id))
    enqueue(prefill_id, str(principal.org_id), key)

    return PrefillAcceptedOut(prefill_id=prefill_id)


@router.get(
    "/{prefill_id}",
    response_model=PrefillOut,
    summary="Collect what a label photograph suggests for the context form",
    dependencies=[Depends(requires(Permission.SCAN_CREATE))],
)
def get_prefill(
    prefill_id: str,
    principal: CurrentPrincipal,
    response: Response,
) -> PrefillOut:
    """Return one prefill, or 404 once it has expired.

    ``no-store`` because the answer changes from ``reading`` to ``ready`` within seconds and a
    cached ``reading`` is a form that never fills.
    """
    record = get_store().get(str(principal.org_id), prefill_id)

    if record is None:
        # Unknown, expired, or another org's (CLAUDE.md §3.7). One answer for all three.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="prefill not found")

    response.headers["Cache-Control"] = "no-store"

    return PrefillOut(
        prefill_id=record.prefill_id,
        status=record.status,
        suggestions=[
            SuggestionOut(
                field=item.field,
                value=item.value,
                confidence=item.confidence,
                from_field_code=item.from_field_code,
                source_text=item.source_text,
            )
            for item in record.suggestions
        ],
        word_count=record.word_count,
        reduced=record.reduced,
    )


__all__ = ["router"]
