"""Tenancy and identity — ``orgs`` and ``users`` (docs/01-architecture.md §8).

``orgs.mode`` is the Mode A / Mode B switch of architecture §3. It is an **org-level** attribute,
not a per-user or per-scan one: rule evaluation is identical in both modes, and only the
surrounding features differ (evidence integrity and locked editing for enforcement, remediation
and bulk import for industry). Putting it on the org is what keeps that promise checkable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, checked_enum, org_fk, uuid_pk

ORG_MODES: tuple[str, ...] = ("enforcement", "industry")
"""Architecture §3. Enforcement is the Legal Metrology officer; industry is the brand."""

USER_ROLES: tuple[str, ...] = ("admin", "inspector", "analyst", "viewer")
"""Architecture §10. The RBAC dependency in ``services/auth/rbac.py`` reads exactly this tuple."""


class Org(TimestampMixin, Base):
    """A tenant. Every other org-owned row points back here."""

    __tablename__ = "orgs"
    __table_args__ = (checked_enum("ck_orgs_mode", "mode", ORG_MODES),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    mode: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    state: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    """Indian state. Mode A groups enforcement dashboards by it (FR-30)."""


class User(TimestampMixin, Base):
    """A person, belonging to exactly one org.

    ``phone`` is globally unique because it *is* the credential: there is no password, and
    ``POST /v1/auth/otp/request`` resolves a phone to a user before any token exists. One person
    working for two orgs needs two numbers in v1; a membership table is the v2 shape.
    """

    __tablename__ = "users"
    __table_args__ = (checked_enum("ck_users_role", "role", USER_ROLES),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    role: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    phone: Mapped[str] = mapped_column(sa.String(20), nullable=False, unique=True, index=True)
    """E.164, including the country code."""

    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    full_name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    """Cleared rather than deleted. An inspector's scans must outlive their account."""

    last_login_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


__all__ = ["ORG_MODES", "USER_ROLES", "Org", "User"]
