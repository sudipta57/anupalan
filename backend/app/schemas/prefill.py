"""Context prefill over the wire — FR-03.

One photograph in, a list of *proposed* form values out. Nothing here is a verdict, nothing here
is stored against a scan, and nothing here is evidence — see ``services/prefill.py`` for why that
distinction is what lets the image arrive by this path at all.

**The image comes in the body, base64, rather than by a presigned URL.** Every other image in this
system is uploaded straight to object storage precisely so the API never handles bytes
(architecture §10), and that rule is about *evidence*: the scan's own photographs, whose hash is
the chain a report cites. This is a throwaway thumbnail — a few hundred kilobytes, downscaled on
the phone, read once and deleted — and the presign dance costs it three round trips on a market's
3G while a person waits at a form. Base64 rather than multipart because it needs no new method on
the app's transport interface, which is deliberately narrow (``mobile/src/api/transport.ts``); the
33% inflation of a quarter-megabyte is worth less than a branch in the transport.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

from app.schemas.base import StrictModel

PrefillContentType = Literal["image/jpeg", "image/png", "image/webp"]
"""What may be sent for a read. Narrower than the scan upload allow-list on purpose: this is one
photograph from one camera, and there is no reason for it to be anything else."""

PREFILL_CONTENT_TYPES: tuple[str, ...] = get_args(PrefillContentType)
"""The same set as a tuple, for the router's extension mapping. Derived rather than written twice
so the two cannot drift."""


class PrefillCreateIn(StrictModel):
    """A label photograph to read for the context form."""

    image_base64: str = Field(
        min_length=1,
        max_length=8 * 1024 * 1024,
        description="The photograph, base64-encoded, downscaled by the client. The decoded size "
        "is checked against PREFILL_MAX_BYTES; this length cap is the cheap first refusal so a "
        "very large body is rejected before it is decoded.",
    )
    content_type: PrefillContentType = Field(
        default="image/jpeg",
        description="Media type of the encoded bytes. Decides the scratch object's extension "
        "only — recognition reads the bytes, not this.",
    )


class PrefillAcceptedOut(BaseModel):
    """The read has been queued. Poll ``GET /v1/prefill/{prefill_id}``."""

    prefill_id: str
    status: Literal["reading"] = "reading"


class SuggestionOut(BaseModel):
    """One proposed product-context value, with the reading it came from.

    ``source_text`` and ``from_field_code`` are not decoration. A filled form field that cannot
    say where its value came from asks the user to trust it; one that can says "this is what I
    read on the pack, check it", which is the only version of this feature that is safe to ship
    (CLAUDE.md §3.1).
    """

    field: str = Field(
        description="A profile field name: name, net_qty_value, net_qty_unit or is_imported. "
        "Never surface, pack_type, pdp_area_cm2, channel or category_code — see "
        "services/extraction/prefill.NEVER_SUGGESTED for why each is excluded."
    )
    value: str = Field(description="Always a string, including for is_imported ('true').")
    confidence: float = Field(
        ge=0,
        le=1,
        description="Inherited unchanged from the declaration this was read from. Below FR-06's "
        "0.75 the machine does not believe its own reading, and the client says so.",
    )
    from_field_code: str = Field(description="The declaration the value was read from.")
    source_text: str = Field(description="What was recognised, verbatim.")


class PrefillOut(BaseModel):
    """The state of one prefill."""

    prefill_id: str
    status: Literal["reading", "ready", "failed"]
    suggestions: list[SuggestionOut] = Field(default_factory=list)
    word_count: int = Field(
        default=0,
        description="Words recognised. Zero with no suggestions means the photograph was read "
        "and had nothing usable on it, which is a different thing from the read failing.",
    )
    reduced: bool = Field(
        default=False,
        description="True when extraction ran pattern-only. No pattern reads a common name, so a "
        "reduced read will not propose a product name.",
    )


__all__ = [
    "PREFILL_CONTENT_TYPES",
    "PrefillAcceptedOut",
    "PrefillContentType",
    "PrefillCreateIn",
    "PrefillOut",
    "SuggestionOut",
]
