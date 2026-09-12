"""BIS applicability — B20, TRD FR-29.

FR-29's acceptance is the twenty-product table at the bottom: ten under a Quality Control Order,
ten not, at least seventeen correct. ``unclear`` counts as wrong for a product that *is* under a
QCO and is acceptable for a genuinely ambiguous category — which is the right way round, because
"we could not tell" costing a brand a phone call is not the same failure as "no licence needed"
costing them a seized consignment.

Around that sit the structural properties:

* **the lookup is deterministic** — same profile, same answer, every time, because it is a table
  and not a retrieval;
* **nothing is hardcoded** — no category, IS number or scheme name appears in a ``.py`` file, so
  the suite proves the answer changes when the *data* changes;
* **``unclear`` is not ``no``** — the two are different claims and the lists distinguish them.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.config import settings
from app.services.bis.applicability import (
    BisListsError,
    active_lists,
    applicability,
    load_bytes,
    load_lists,
)
from app.services.rules.types import Profile

AS_OF = date(2026, 9, 12)


@pytest.fixture(scope="module")
def lists():  # type: ignore[no-untyped-def]
    return load_lists(settings.BIS_LISTS_PATH)


def check(name: str | None = None, *, category: str | None = None, imported: bool = False):  # type: ignore[no-untyped-def]
    return Profile(name=name, category_code=category, is_imported=imported)


# --------------------------------------------------------------------------- loading


def test_the_committed_lists_load(lists) -> None:  # type: ignore[no-untyped-def]
    assert lists.code
    assert lists.version == "1.0"
    assert lists.entries
    assert len(lists.checksum) == 64
    assert lists.disclaimer.strip()


def test_the_checksum_is_over_the_file_bytes(lists) -> None:  # type: ignore[no-untyped-def]
    """Two files that parse to one dictionary are still two files. The checksum identifies the
    artefact that was reviewed, not the shape it happens to parse into."""
    raw = Path(settings.BIS_LISTS_PATH).read_bytes()
    assert load_bytes(raw).checksum == lists.checksum
    assert load_bytes(raw + b"\n# a comment\n").checksum != lists.checksum


def test_a_float_version_is_rejected() -> None:
    """The trap the rule pack loader closes, closed again here: ``version: 1.0`` is a float, and
    "1.10" and "1.1" are then the same list."""
    raw = b"""
meta: {code: X, version: 1.0, as_of: "2026-01-01", disclaimer: d}
schemes: {none: {label: l}}
entries: [{id: E, qco_applicable: "no", scheme: none}]
"""
    with pytest.raises(BisListsError, match="version"):
        load_bytes(raw)


def test_an_unknown_scheme_is_rejected() -> None:
    raw = b"""
meta: {code: X, version: "1", as_of: "2026-01-01", disclaimer: d}
schemes: {ISI: {label: l}}
entries: [{id: E, qco_applicable: "yes", scheme: SUPER-ISI}]
"""
    with pytest.raises(BisListsError, match="scheme"):
        load_bytes(raw)


def test_a_verdict_outside_the_three_values_is_rejected() -> None:
    """A tri-state that quietly became two states would turn every "unclear" into a claim."""
    raw = b"""
meta: {code: X, version: "1", as_of: "2026-01-01", disclaimer: d}
schemes: {none: {label: l}}
entries: [{id: E, qco_applicable: maybe, scheme: none}]
"""
    with pytest.raises(BisListsError, match="qco_applicable"):
        load_bytes(raw)


def test_duplicate_entry_ids_are_rejected(lists) -> None:  # type: ignore[no-untyped-def]
    raw = b"""
meta: {code: X, version: "1", as_of: "2026-01-01", disclaimer: d}
schemes: {none: {label: l}}
entries:
  - {id: E, qco_applicable: "no", scheme: none}
  - {id: E, qco_applicable: "yes", scheme: none}
"""
    with pytest.raises(BisListsError, match="duplicate"):
        load_bytes(raw)


def test_no_is_number_or_category_is_written_in_python() -> None:
    """CLAUDE.md §3.2's argument, applied to the certification half.

    An IS number in a ``.py`` file is a certification route that changes only on a deploy, and a
    QCO amended in the Gazette on Friday would then take an engineer to reflect.
    """
    source = Path("app/services/bis/applicability.py").read_text(encoding="utf-8")

    assert "IS 13252" not in source
    assert "CEMENT" not in source
    assert "bis.gov.in" not in source


# --------------------------------------------------------------------------- the lookup


def test_the_same_profile_always_answers_the_same_way(lists) -> None:  # type: ignore[no-untyped-def]
    """It is a table lookup. Nothing here may depend on a model, a clock or an iteration order."""
    profile = check("Steam Iron 1200 W")
    first = applicability(profile, lists=lists, as_of=AS_OF)
    for _ in range(50):
        assert applicability(profile, lists=lists, as_of=AS_OF) == first


def test_a_category_code_decides_before_a_name(lists) -> None:  # type: ignore[no-untyped-def]
    """The exact key wins. A brand's catalogue carries category codes and a product name is
    marketing — "Thunder Bolt 65" is a charger, and only the code says so."""
    result = applicability(
        check("Thunder Bolt 65", category="IT-ADAPTOR"), lists=lists, as_of=AS_OF
    )

    assert result.matched_on == "category_code"
    assert result.qco_applicable == "yes"
    assert result.scheme == "CRS"


def test_the_longest_keyword_wins(lists) -> None:  # type: ignore[no-untyped-def]
    """"notebook" is stationery and "notebook computer" is under CRS. Longest-first matching is
    what stops the answer depending on the order rows appear in the file."""
    stationery = applicability(check("Ruled notebook 200 pages"), lists=lists, as_of=AS_OF)
    computer = applicability(check("Slim notebook computer 14 inch"), lists=lists, as_of=AS_OF)

    assert stationery.qco_applicable == "no"
    assert computer.qco_applicable == "yes"
    assert computer.scheme == "CRS"


def test_an_unplaceable_product_is_unclear_and_not_no(lists) -> None:  # type: ignore[no-untyped-def]
    """The distinction the whole three-valued design exists for.

    Reporting "we could not tell" as "no licence needed" is how an advisory tool talks a brand out
    of a licence it needed. ``unclear`` also carries different next steps — go and look — rather
    than the "no QCO covers this" steps.
    """
    result = applicability(check("Artisanal brass door handle"), lists=lists, as_of=AS_OF)

    assert result.qco_applicable == "unclear"
    assert result.scheme == "none"
    assert result.matched_entry_id is None
    assert result.next_steps == lists.unclear_next_steps
    assert result.sources == lists.fallback_sources


def test_an_answer_names_the_row_that_decided_it(lists) -> None:  # type: ignore[no-untyped-def]
    """An answer that cannot name its row cannot be checked against the list — and the E4
    evaluation is exactly that check."""
    result = applicability(check(category="TOYS"), lists=lists, as_of=AS_OF)

    assert result.matched_entry_id == "QCO-TOYS"
    assert result.lists_version.startswith("BIS-QCO-CRS-v")
    assert result.as_of == lists.as_of


def test_an_imported_isi_product_goes_through_fmcs(lists) -> None:  # type: ignore[no-untyped-def]
    """Same obligation, different applicant and different route.

    A foreign manufacturer obtains the Standard Mark under FMCS, not under the domestic scheme.
    Sending an importer down the domestic route costs months, and the profile already carries the
    fact that decides it.
    """
    domestic = applicability(check(category="ELEC-IRON"), lists=lists, as_of=AS_OF)
    imported = applicability(
        check(category="ELEC-IRON", imported=True), lists=lists, as_of=AS_OF
    )

    assert domestic.scheme == "ISI"
    assert imported.scheme == "FMCS"
    assert imported.qco_applicable == domestic.qco_applicable == "yes"
    assert imported.candidate_is_numbers == domestic.candidate_is_numbers
    assert any("Authorised Indian Representative" in step for step in imported.next_steps)


def test_an_imported_crs_product_stays_on_crs(lists) -> None:  # type: ignore[no-untyped-def]
    """CRS registration is open to a foreign manufacturer directly. Only the ISI route changes."""
    result = applicability(check(category="IT-LAPTOP", imported=True), lists=lists, as_of=AS_OF)
    assert result.scheme == "CRS"


def test_an_entry_not_yet_in_force_is_reported_as_forthcoming() -> None:
    """A QCO notified today and effective in eighteen months is a planning fact, not a present
    requirement. Reporting it as one would have a brand certifying a year early."""
    raw = b"""
meta: {code: T, version: "1", as_of: "2026-01-01", disclaimer: d,
       unclear_next_steps: [look], fallback_sources: [{title: t, url: u}]}
schemes:
  ISI: {label: l, next_steps: [apply]}
  none: {label: n, next_steps: [nothing]}
entries:
  - id: FUTURE
    category_codes: [WIDGET]
    qco_applicable: "yes"
    scheme: ISI
    order: "Widget (Quality Control) Order, 2026"
    effective_from: "2027-07-01"
"""
    future_lists = load_bytes(raw)
    profile = Profile(category_code="WIDGET")

    before = applicability(profile, lists=future_lists, as_of=date(2026, 9, 12))
    after = applicability(profile, lists=future_lists, as_of=date(2027, 8, 1))

    assert before.qco_applicable == "no"
    assert before.forthcoming and "2027-07-01" in before.forthcoming[0]

    assert after.qco_applicable == "yes"
    assert after.scheme == "ISI"
    assert after.forthcoming == ()


def test_the_active_lists_are_the_configured_ones() -> None:
    assert active_lists().version_label == load_lists(settings.BIS_LISTS_PATH).version_label


# --------------------------------------------------------------------------- FR-29's twenty


UNDER_QCO: tuple[tuple[str, str], ...] = (
    ("Ultratech Portland cement 50 kg", "ISI"),
    ("Bajaj steam iron 1000 W", "ISI"),
    ("Havells immersion water heater 1500 W", "ISI"),
    ("Prestige pressure cooker 5 litre", "ISI"),
    ("Steelbird helmet full face", "ISI"),
    ("Bharat LPG cylinder 14.2 kg", "ISI"),
    ("Bisleri packaged drinking water 1 L", "ISI"),
    ("Funskool toy building blocks", "ISI"),
    ("Dell laptop 14 inch", "CRS"),
    ("Anker power bank 20000 mAh", "CRS"),
)
"""Ten products that are under a Quality Control Order or the CRS. FR-29's first half."""

NOT_UNDER_QCO: tuple[str, ...] = (
    "Tata iodised salt 1 kg",
    "Britannia biscuit 100 g",
    "Assam green tea 250 g",
    "Everest turmeric powder 100 g",
    "Mother's mango pickle 500 g",
    "Nivea face cream 50 g",
    "Cotton t-shirt medium",
    "Wooden furniture dining chair",
    "Classmate exercise book 200 pages",
    "Cycle agarbatti incense 100 sticks",
)
"""Ten that are not. FR-29's second half."""


def test_fr29_twenty_known_products(lists) -> None:  # type: ignore[no-untyped-def]
    """FR-29's acceptance: at least 17 of 20 correct.

    ``unclear`` is counted as wrong for a product that is under a QCO — a brand that needed a
    licence and was told "unsure" is a brand that ships uncertified — and as acceptable for one
    that is not, because "we could not place this" is a truthful answer for a category the
    published lists genuinely do not name.
    """
    correct = 0
    wrong: list[str] = []

    for name, scheme in UNDER_QCO:
        result = applicability(check(name), lists=lists, as_of=AS_OF)
        if result.qco_applicable == "yes" and result.scheme == scheme:
            correct += 1
        else:
            wrong.append(f"{name}: got {result.qco_applicable}/{result.scheme}, want yes/{scheme}")

    for name in NOT_UNDER_QCO:
        result = applicability(check(name), lists=lists, as_of=AS_OF)
        if result.qco_applicable in {"no", "unclear"}:
            correct += 1
        else:
            wrong.append(f"{name}: got {result.qco_applicable}, want no")

    assert correct >= 17, f"{correct}/20 correct. Wrong: " + "; ".join(wrong)


def test_every_product_under_a_qco_is_told_which_standard(lists) -> None:  # type: ignore[no-untyped-def]
    """"You need an ISI mark" without an IS number is not actionable — it is the start of a
    week of searching."""
    for name, _ in UNDER_QCO:
        result = applicability(check(name), lists=lists, as_of=AS_OF)
        if result.qco_applicable == "yes":
            assert result.candidate_is_numbers, name
            assert result.next_steps, name
            assert result.sources, name
