"""Rule pack loading and validation — TRD FR-26.

The acceptance test in the TRD is one sentence: *an invalid rule pack is rejected with a
line-level error and the previous pack stays active.* Both halves matter. Rejecting the pack
protects the verdicts; keeping the previous one active means a bad upload degrades to "yesterday's
rules" rather than to no rules at all, which is the difference between a stale report and no
report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.rules import loader
from app.services.rules.loader import RulePackError, active_pack, load_pack

PACKS = Path(__file__).parent / "fixtures" / "rulepacks"


# --------------------------------------------------------------------------- the shipped pack


def test_the_shipped_pack_loads_and_identifies_itself() -> None:
    pack = active_pack()

    assert pack.code == "LM-2011"
    assert pack.version == "1.0"
    assert pack.version_label == "LM-2011-v1.0"
    assert pack.rules, "the shipped pack must contain rules"


def test_every_shipped_rule_carries_the_fields_a_report_needs() -> None:
    """A rule without a citation cannot appear in a legal report, so the loader must reject one.

    This asserts the shipped pack satisfies that, which is also a check on the transcription.
    """
    for rule in active_pack().rules:
        assert rule.id, "every rule needs an id"
        assert rule.kind, f"{rule.id}: every rule needs a kind"
        assert rule.citation.strip(), f"{rule.id}: every rule needs a citation"
        assert rule.severity.strip(), f"{rule.id}: every rule needs a severity"
        assert rule.message.strip(), f"{rule.id}: every rule needs a message template"


def test_rule_ids_are_unique_in_the_shipped_pack() -> None:
    ids = [rule.id for rule in active_pack().rules]
    assert len(ids) == len(set(ids))


def test_tables_are_reachable_by_name() -> None:
    pack = active_pack()

    table = pack.table("numeral_height_by_weight_volume")
    assert table.rows, "Table-I must have rows"

    with pytest.raises(RulePackError):
        pack.table("no_such_table")


def test_checksum_is_stable_and_is_over_the_file_bytes() -> None:
    """Two loads of the same file agree; a different file does not."""
    first = load_pack(PACKS / "valid_minimal.yaml")
    second = load_pack(PACKS / "valid_minimal.yaml")

    assert first.checksum == second.checksum
    assert len(first.checksum) == 64, "sha256, hex"
    assert first.checksum != active_pack().checksum


# --------------------------------------------------------------------------- rejection


def test_missing_file_is_rejected() -> None:
    with pytest.raises(RulePackError, match="not found"):
        load_pack(PACKS / "does_not_exist.yaml")


def test_rule_without_a_citation_is_rejected_with_its_line() -> None:
    with pytest.raises(RulePackError) as excinfo:
        load_pack(PACKS / "missing_citation.yaml")

    message = str(excinfo.value)
    assert "citation" in message
    assert "TEST-PRESENCE" in message
    # The rule mapping starts at line 5 of the fixture, where `- id: TEST-PRESENCE` is.
    assert ":5" in message, f"error must name the offending line, got: {message}"


def test_unknown_rule_kind_is_rejected_and_names_the_rule() -> None:
    with pytest.raises(RulePackError) as excinfo:
        load_pack(PACKS / "unknown_kind.yaml")

    message = str(excinfo.value)
    assert "vibes" in message
    assert "TEST-WEIRD" in message


def test_unquoted_float_version_is_rejected() -> None:
    """YAML turns an unquoted 1.0 into a float, which would stamp findings "v1.0" one day and
    "v1" the next. Every finding carries this string (CLAUDE.md §3.6), so it must be a string."""
    with pytest.raises(RulePackError, match="must be a string"):
        load_pack(PACKS / "float_version.yaml")


def test_duplicate_rule_ids_are_rejected() -> None:
    """Two rules with one id means one citation silently wins. Reject at load, not at evaluation."""
    with pytest.raises(RulePackError) as excinfo:
        load_pack(PACKS / "duplicate_rule_id.yaml")

    assert "TEST-DUP" in str(excinfo.value)


# --------------------------------------------------------------------------- the FR-26 promise


def test_an_invalid_pack_leaves_the_previous_pack_active() -> None:
    """The load-bearing half of FR-26: a bad pack must not unseat a good one."""
    before = active_pack()

    with pytest.raises(RulePackError):
        loader.activate(PACKS / "missing_citation.yaml")

    after = active_pack()
    assert after.version_label == before.version_label
    assert after.checksum == before.checksum


def test_activate_swaps_the_pack_and_reload_restores_the_configured_one() -> None:
    original = active_pack()
    try:
        swapped = loader.activate(PACKS / "valid_minimal.yaml")
        assert swapped.version_label == "TEST-v0.1"
        assert active_pack().version_label == "TEST-v0.1"
    finally:
        loader.reload()

    assert active_pack().version_label == original.version_label
