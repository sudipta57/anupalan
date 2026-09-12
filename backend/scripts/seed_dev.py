"""Seed a development database with the two accounts the app needs to sign in.

    python -m scripts.seed_dev

**Development and staging only.** It refuses to run against ``ENV=production``: the accounts it
creates are known phone numbers with no second factor, and the whole point of the OTP echo it
assumes is that no SMS gateway is configured.

Two orgs, because the app is two products over one backend and every screen has a Mode A and a
Mode B variant (`docs/01-architecture.md` §3). Signing in as only an inspector would leave half the
app untestable — the bulk listing check and the BIS screens are not even in the enforcement tab bar.

**Idempotent.** Re-running it adopts what is already there rather than inserting a second copy, so
it is safe to run after a partial failure or on a database somebody else has already touched. It
never deletes anything.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import sqlalchemy as sa

from app.config import settings
from app.db import session_scope
from app.models import Org, User
from app.models.catalog import Product

ENFORCEMENT_PHONE = "+919812345678"
INDUSTRY_PHONE = "+919876543210"


def _org(session: Any, *, name: str, mode: str, state: str) -> Org:
    existing = session.execute(sa.select(Org).where(Org.name == name)).scalar_one_or_none()
    if existing is not None:
        return existing

    org = Org(id=uuid.uuid4(), name=name, mode=mode, state=state)
    session.add(org)
    session.flush()
    return org


def _user(session: Any, *, org: Org, phone: str, role: str, full_name: str) -> User:
    existing = session.execute(sa.select(User).where(User.phone == phone)).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        role=role,
        phone=phone,
        full_name=full_name,
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def _product(session: Any, *, org: Org, name: str, **fields: Any) -> Product:
    existing = session.execute(
        sa.select(Product).where(Product.org_id == org.id, Product.name == name)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    product = Product(id=uuid.uuid4(), org_id=org.id, name=name, **fields)
    session.add(product)
    session.flush()
    return product


def main() -> int:
    if settings.ENV.lower().startswith("prod"):
        print("refusing to seed a production database", file=sys.stderr)
        return 1

    with session_scope() as session:
        enforcement = _org(
            session, name="Legal Metrology, Nadia", mode="enforcement", state="West Bengal"
        )
        inspector = _user(
            session,
            org=enforcement,
            phone=ENFORCEMENT_PHONE,
            role="inspector",
            full_name="Inspector (dev)",
        )

        industry = _org(session, name="Annapurna Foods", mode="industry", state="West Bengal")
        analyst = _user(
            session,
            org=industry,
            phone=INDUSTRY_PHONE,
            role="analyst",
            full_name="Analyst (dev)",
        )

        # A small catalogue, so the context form's picker and the history product filter have
        # something to show. Every field here is one a catalogue genuinely holds.
        _product(
            session,
            org=industry,
            name="Sampoorna Whole Wheat Atta 1 kg",
            brand="Annapurna",
            category_code="food.flour",
            pack_type="flexible",
            surface="printed",
            net_qty_value=1.0,
            net_qty_unit="kg",
        )
        _product(
            session,
            org=industry,
            name="Digestive Biscuits 180 g",
            brand="Annapurna",
            category_code="food.bakery",
            pack_type="flexible",
            surface="printed",
            net_qty_value=180.0,
            net_qty_unit="g",
        )

        print("seeded:")
        print(f"  Mode A  {inspector.phone}  {enforcement.name} ({enforcement.mode})")
        print(f"  Mode B  {analyst.phone}  {industry.name} ({industry.mode})")
        print()
        print("Sign in with either number. The code is returned in the response body while")
        print("OTP_ECHO_IN_RESPONSE is on, and the app's sign-in screen fills it in for you.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
