"""Ingredient vocabulary and source registry loading — B25.

Both files are data on the same terms as a rule pack (CLAUDE.md §3.2, §3.6): validated at load with
the line of the problem, checksummed over the raw bytes, and versioned by a string. A registry entry
decides which websites the worker is allowed to fetch, so its validation is also a security
boundary — an entry that could smuggle in a scheme, a path, a port or an IP literal would be a way
to point the fetcher somewhere nobody reviewed.
"""

from __future__ import annotations

import hashlib

import pytest

from app.config import settings
from app.services.ingredients.data import (
    IngredientDataError,
    load_registry,
    load_registry_bytes,
    load_vocabulary,
    load_vocabulary_bytes,
)
from tests.ingredients_support import REGISTRY_YAML, VOCABULARY_YAML

# --------------------------------------------------------------------------- committed files


def test_the_committed_vocabulary_loads() -> None:
    vocabulary = load_vocabulary(settings.INGREDIENTS_VOCABULARY_PATH)
    assert vocabulary.version == "1.0"
    assert vocabulary.version_label == "ING-VOCAB-v1.0"
    assert len(vocabulary.checksum) == 64
    assert vocabulary.disclaimer.strip()
    assert vocabulary.locate.headings
    assert 0 < vocabulary.policy.pct_tolerance_points <= vocabulary.policy.pct_borderline_points


def test_the_committed_registry_loads() -> None:
    registry = load_registry(settings.INGREDIENTS_SOURCES_PATH)
    assert registry.version == "1.0"
    assert len(registry.checksum) == 64


def test_the_committed_registry_lists_no_marketplace() -> None:
    """Marketplace text is written by sellers. A marketplace in the registry would make a seller's
    typo the manufacturer's word."""
    registry = load_registry(settings.INGREDIENTS_SOURCES_PATH)
    marketplaces = ("amazon.", "flipkart.", "bigbasket.", "jiomart.", "blinkit.", "zepto")
    for brand in registry.brands:
        for domain in brand.domains:
            assert not any(name in domain for name in marketplaces), domain


# --------------------------------------------------------------------------- vocabulary


def test_the_checksum_is_over_the_file_bytes() -> None:
    raw = VOCABULARY_YAML.encode("utf-8")
    assert load_vocabulary_bytes(raw).checksum == hashlib.sha256(raw).hexdigest()

    # A comment changes the artefact, and so the checksum, without changing what it parses to.
    commented = raw + b"\n# reviewed\n"
    assert load_vocabulary_bytes(commented).checksum != load_vocabulary_bytes(raw).checksum


def test_a_float_version_is_refused() -> None:
    raw = VOCABULARY_YAML.replace('version: "1.0"', "version: 1.0").encode("utf-8")
    with pytest.raises(IngredientDataError, match="version must be a string"):
        load_vocabulary_bytes(raw)


def test_errors_name_the_line() -> None:
    raw = VOCABULARY_YAML.replace("pct_tolerance_points: 1.0", "pct_tolerance_points: lots")
    with pytest.raises(IngredientDataError, match=r"line \d+"):
        load_vocabulary_bytes(raw.encode("utf-8"))


def test_borderline_below_tolerance_is_refused() -> None:
    """A band narrower than the tolerance would make UNCLEAR unreachable and every percentage just
    past tolerance a hard difference."""
    raw = VOCABULARY_YAML.replace("pct_borderline_points: 2.0", "pct_borderline_points: 0.5")
    with pytest.raises(IngredientDataError, match="pct_borderline_points"):
        load_vocabulary_bytes(raw.encode("utf-8"))


def test_a_synonym_claimed_by_two_canonicals_is_refused() -> None:
    raw = VOCABULARY_YAML.replace("names: [atta]", "names: [atta, sucrose]")
    with pytest.raises(IngredientDataError, match="sucrose"):
        load_vocabulary_bytes(raw.encode("utf-8"))


def test_missing_headings_are_refused() -> None:
    raw = VOCABULARY_YAML.replace("headings: [ingredients, ingredient, सामग्री]", "headings: []")
    with pytest.raises(IngredientDataError, match="headings"):
        load_vocabulary_bytes(raw.encode("utf-8"))


def test_coverage_outside_zero_to_one_is_refused() -> None:
    raw = VOCABULARY_YAML.replace("name_token_coverage: 0.6", "name_token_coverage: 1.5")
    with pytest.raises(IngredientDataError, match="name_token_coverage"):
        load_vocabulary_bytes(raw.encode("utf-8"))


def test_devanagari_headings_survive_loading() -> None:
    assert "सामग्री" in load_vocabulary_bytes(VOCABULARY_YAML.encode("utf-8")).locate.headings


# --------------------------------------------------------------------------- registry


def test_the_registry_resolves_brand_names_case_insensitively() -> None:
    registry = load_registry_bytes(REGISTRY_YAML.encode("utf-8"))
    brand = registry.brand_named("  SUNFIELD foods ")
    assert brand is not None
    assert brand.id == "sunfield"
    assert registry.brand_named("Moonfield") is None


@pytest.mark.parametrize(
    "domain",
    [
        "https://sunfield.example",
        "sunfield.example/products",
        "sunfield.example:8443",
        "127.0.0.1",
        "localhost",
        "sunfield..example",
        "*.sunfield.example",
        "",
    ],
)
def test_a_domain_that_is_not_a_bare_hostname_is_refused(domain: str) -> None:
    raw = REGISTRY_YAML.replace("domains: [sunfield.example]", f'domains: ["{domain}"]')
    with pytest.raises(IngredientDataError, match="domain"):
        load_registry_bytes(raw.encode("utf-8"))


def test_one_domain_cannot_belong_to_two_brands() -> None:
    raw = REGISTRY_YAML.replace(
        "domains: [rivermill.example, shop-rivermill.example]",
        "domains: [rivermill.example, sunfield.example]",
    )
    with pytest.raises(IngredientDataError, match=r"sunfield\.example"):
        load_registry_bytes(raw.encode("utf-8"))


def test_duplicate_brand_ids_are_refused() -> None:
    raw = REGISTRY_YAML.replace("id: rivermill", "id: sunfield")
    with pytest.raises(IngredientDataError, match="duplicate"):
        load_registry_bytes(raw.encode("utf-8"))


def test_domains_are_stored_lowercase() -> None:
    raw = REGISTRY_YAML.replace("domains: [sunfield.example]", "domains: [SunField.Example]")
    brand = load_registry_bytes(raw.encode("utf-8")).brand_named("Sunfield")
    assert brand is not None
    assert brand.domains == ("sunfield.example",)
