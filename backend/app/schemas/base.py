"""The base every request schema inherits from (B13).

Two behaviours, both about closing a door rather than shaping data.

**Unknown fields are refused, not ignored.** Pydantic's default is to drop what it does not
recognise, which silently turns a client's typo into a missing value and a request the server
never complains about. ``extra="forbid"`` makes the mismatch visible at the boundary where it is
cheap to fix.

**A body may never carry ``org_id``.** Every repository in the system is scoped by it
(CLAUDE.md §3.7), so a value a caller could influence is a way past the tenant boundary. The org
comes from the verified access token and nowhere else, and a request that tries to supply one is a
**400 with an explanation** — not a silent drop. Silently dropping it would be equally safe and
would also conceal a client bug, or an attacker probing for exactly this, until neither could be
traced.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class BodyOrgIdError(Exception):
    """A request body carried an ``org_id``.

    Not a ``ValueError``: pydantic converts those into a 422 validation error alongside ordinary
    field problems, and this is not an ordinary field problem. Raising something pydantic passes
    through lets ``main.py`` answer 400 with a message that says what to do instead.
    """

    def __init__(self, field: str = "org_id") -> None:
        super().__init__(
            f"{field} is taken from the access token and cannot be supplied in the request body"
        )
        self.field = field


class StrictModel(BaseModel):
    """Base for request bodies."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _refuse_tenancy_fields(cls, data: Any) -> Any:
        """Reject a body that names its own org before any field is parsed."""
        if isinstance(data, dict) and "org_id" in data:
            raise BodyOrgIdError()
        return data


__all__ = ["BodyOrgIdError", "StrictModel"]
