"""Minimal JSON-schema checking for LLM responses.

Only the subset the extraction call site needs — ``type: object``, ``required``, and the declared
type of each top-level property. Written out rather than pulling a schema library because the
schemas involved are flat field maps, and because the failure has to be *reported*, not raised:
a schema violation is an ``LLMResult`` with ``ok=False``, never an exception (see provider.py).
"""

from __future__ import annotations

from typing import Any

_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def violations(payload: Any, schema: dict[str, Any]) -> list[str]:
    """Return every way ``payload`` fails ``schema``. Empty means it conforms."""
    problems: list[str] = []

    expected = schema.get("type")
    if expected == "object" and not isinstance(payload, dict):
        return [f"expected a JSON object, got {type(payload).__name__}"]

    if not isinstance(payload, dict):
        return problems

    for name in schema.get("required", []):
        if name not in payload:
            problems.append(f"missing required property {name!r}")

    properties: dict[str, Any] = schema.get("properties", {})
    for name, definition in properties.items():
        if name not in payload or payload[name] is None:
            continue
        declared = definition.get("type")
        if declared is None:
            continue
        python_type = _JSON_TYPES.get(declared)
        if python_type is not None and not isinstance(payload[name], python_type):
            problems.append(
                f"property {name!r} should be {declared}, got {type(payload[name]).__name__}"
            )

    return problems


__all__ = ["violations"]
