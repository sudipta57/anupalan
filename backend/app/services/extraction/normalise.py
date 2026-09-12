"""Normalising extracted values into the shapes the rule pack compares against.

**The unit table is read from the rule pack, never written here** (CLAUDE.md §3.2). The pack's
``tables.unit_symbols`` names the prescribed symbols and the rejected variants — ``gms``, ``ltr``
and the rest — because which symbol is legal is a legal question that changes by amendment, not a
constant. A test greps this file for those strings to keep it that way.

**Normalising is additive, never destructive.** ``value_norm`` is the canonical form, and
``value_raw`` keeps exactly what the label said. That matters more than it looks: rule
``LM-QTY-UNIT-SYMBOL`` exists to fail a package for printing "250 gms" instead of "250 g", so a
normalisation that overwrote the raw text would erase the evidence for the rule that checks it.

Money is integer paise (CLAUDE.md §5). Lengths are float millimetres. Neither is ever a float
rupee.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.services.rules.loader import RulePack

_QUANTITY = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>[A-Za-z]+)",
    re.UNICODE,
)

_MONEY = re.compile(r"(?P<rupees>\d[\d,]*)(?:\.(?P<paise>\d{1,2}))?")

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def unit_table(pack: RulePack) -> tuple[dict[str, str], set[str]]:
    """Return ``(rejected_variant -> prescribed, accepted_symbols)`` from the pack."""
    table: Mapping[str, Any] = pack.table("unit_symbols").data

    rejected = {
        str(variant): str(prescribed)
        for variant, prescribed in (table.get("rejected_variants") or {}).items()
    }
    accepted = {
        str(symbol)
        for key, symbols in table.items()
        if key != "rejected_variants" and isinstance(symbols, list)
        for symbol in symbols
    }
    return rejected, accepted


def normalise_quantity(raw: str, pack: RulePack) -> str | None:
    """Canonicalise a net-quantity declaration to ``"<value> <symbol>"``.

    A rejected variant is mapped to its prescribed symbol so downstream comparisons are uniform.
    The raw text is preserved by the caller, because the rule that objects to the variant needs
    to see it.
    """
    match = _QUANTITY.search(raw)
    if match is None:
        return None

    rejected, accepted = unit_table(pack)
    unit = match.group("unit")
    canonical = rejected.get(unit) or rejected.get(unit.lower())

    if canonical is None:
        if unit in accepted:
            canonical = unit
        elif unit.lower() in {symbol.lower() for symbol in accepted}:
            # Case is a presentation choice, not a different unit: "ML" is "ml".
            canonical = next(
                symbol for symbol in accepted if symbol.lower() == unit.lower()
            )
        else:
            return None

    value = match.group("value").replace(",", "")
    if value.endswith(".0"):
        value = value[:-2]
    return f"{value} {canonical}"


def quantity_in_base_units(normalised: str) -> float | None:
    """Convert a normalised quantity to grams or millilitres — the Table-I lookup key.

    Returns None for a quantity by length, area or number, which keys Table-II on panel area
    instead.
    """
    match = _QUANTITY.search(normalised)
    if match is None:
        return None

    value = float(match.group("value"))
    unit = match.group("unit")

    multipliers = {"g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0, "L": 1000.0}
    multiplier = multipliers.get(unit)
    return value * multiplier if multiplier is not None else None


def normalise_money_paise(raw: str) -> str | None:
    """Convert a price declaration to integer paise, as a string.

    Integer paise, not float rupees (CLAUDE.md §5): a price is a legal declaration and binary
    floating point cannot represent ₹120.10 exactly.
    """
    match = _MONEY.search(raw)
    if match is None:
        return None

    rupees = int(match.group("rupees").replace(",", ""))
    paise_text = match.group("paise") or "0"
    paise = int(paise_text.ljust(2, "0"))
    return str(rupees * 100 + paise)


def normalise_month_year(raw: str) -> str | None:
    """Canonicalise a manufacture date to ``"MM/YYYY"``.

    Only month and year. Rule 6(1)(c) asks for the month and year of manufacture, packing or
    import — a day component is extra information, not a more precise answer, and inventing one
    would be wrong.
    """
    text = raw.upper()

    numeric = re.search(r"\b(0?[1-9]|1[0-2])\s*[/\-.]\s*((?:19|20)\d{2})\b", text)
    if numeric:
        return f"{int(numeric.group(1)):02d}/{numeric.group(2)}"

    iso = re.search(r"\b((?:19|20)\d{2})\s*[/\-.]\s*(0?[1-9]|1[0-2])\b", text)
    if iso:
        return f"{int(iso.group(2)):02d}/{iso.group(1)}"

    named = re.search(r"\b([A-Z]{3})[A-Z]*\.?\s*,?\s*((?:19|20)\d{2})\b", text)
    if named:
        month = _MONTH_NAMES.get(named.group(1).lower())
        if month is not None:
            return f"{month:02d}/{named.group(2)}"

    return None


def normalise_phone(raw: str) -> str | None:
    """Reduce a phone declaration to its digits, dropping a +91 country prefix."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    return digits if 8 <= len(digits) <= 12 else None


def collapse_whitespace(raw: str) -> str:
    """Normalise runs of whitespace, which OCR produces unpredictably around line breaks."""
    return " ".join(raw.split())


__all__ = [
    "collapse_whitespace",
    "normalise_money_paise",
    "normalise_month_year",
    "normalise_phone",
    "normalise_quantity",
    "quantity_in_base_units",
    "unit_table",
]
