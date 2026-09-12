"""Opaque cursors for the list endpoints (TRD §5: *cursor pagination*).

**Keyset, not offset.** ``LIMIT 20 OFFSET 200`` makes the database walk and discard two hundred rows
for every page, and — worse for a scan archive — it silently repeats and skips rows when something
is inserted while a user is paging. A keyset cursor carries the sort key of the last row seen, so
the next page starts exactly where the previous one stopped no matter what arrived in between.

**Opaque on purpose.** The value is base64 of a small JSON object. That is not obfuscation — anyone
can decode it — it is a statement that the contents are ours to change. A client that parsed a
cursor and constructed its own would be depending on the sort key of the moment, and the endpoint
could never be re-ordered again.

A malformed cursor is a **422 with an explanation**, never a 500 and never silently ignored.
Ignoring it would hand the caller page one while they believed they were on page nine, and a paging
loop that never terminates is the natural consequence.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any


class CursorError(ValueError):
    """A cursor that did not come from ``encode_cursor``, or no longer parses."""


def encode_cursor(payload: Mapping[str, str]) -> str:
    """Render a sort key as an opaque page token.

    Unpadded base64url, so the value survives a query string without escaping.
    """
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> dict[str, str]:
    """Read a page token back, or raise ``CursorError``.

    Every failure mode lands here rather than deeper in a query: bad base64, bad JSON, a JSON value
    that is not an object, and an object whose values are not strings. The last one matters because
    the parsed values go on to be compared against columns — a list or a dict arriving there would
    fail somewhere far less explicable.
    """
    padding = "=" * (-len(cursor) % 4)

    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
    except (binascii.Error, ValueError) as exc:
        raise CursorError("cursor is not valid base64") from exc

    try:
        parsed: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CursorError("cursor does not contain JSON") from exc

    if not isinstance(parsed, dict):
        raise CursorError("cursor is not an object")

    if not all(isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()):
        raise CursorError("cursor fields must be strings")

    return {str(key): str(value) for key, value in parsed.items()}


__all__ = ["CursorError", "decode_cursor", "encode_cursor"]
