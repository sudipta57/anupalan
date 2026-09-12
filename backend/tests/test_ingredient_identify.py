"""Is this page the scanned product? — B28.

Deterministic, no model. A model asked "is this the same product" would say yes to a plausible page,
and comparing a label against the wrong variant produces a confident false difference. So the check
is words on the page against words on the pack, with thresholds from the vocabulary
(CLAUDE.md §3.2), and a brand is resolved only through the reviewed registry — never guessed.
"""

from __future__ import annotations

from app.services.ingredients.html_text import PageText
from app.services.ingredients.identify import ProductIdentity, resolve_brand, same_product
from tests.ingredients_support import registry, vocabulary

POLICY = vocabulary().match
REGISTRY = registry()
SUNFIELD = REGISTRY.brand_named("Sunfield")
assert SUNFIELD is not None


def page(title: str, headings: tuple[str, ...] = (), text: str = "") -> PageText:
    body = "\n\n".join([title, *headings, text])
    return PageText(text=body, title=title, headings=headings)


def oats(
    name: str = "Sunfield Masala Oats 500 g", qty: float | None = 500.0, unit: str | None = "g"
) -> ProductIdentity:
    return ProductIdentity(brand="Sunfield", name=name, net_qty_value=qty, net_qty_unit=unit)


# --------------------------------------------------------------------------- brand


def test_a_declared_brand_resolves_through_the_registry() -> None:
    brand = resolve_brand(oats(), REGISTRY)
    assert brand is not None
    assert brand.id == "sunfield"


def test_without_a_brand_the_product_name_prefix_is_used() -> None:
    brand = resolve_brand(ProductIdentity(brand=None, name="River Mill Whole Wheat Atta"), REGISTRY)
    assert brand is not None
    assert brand.id == "rivermill"


def test_an_unregistered_brand_is_not_guessed() -> None:
    assert resolve_brand(ProductIdentity(brand=None, name="Moonfield Oats"), REGISTRY) is None


def test_a_declared_brand_is_not_overridden_by_the_name() -> None:
    """The operator said the brand is Moonfield. A name that happens to start with a registered
    brand does not make it that brand's product."""
    identity = ProductIdentity(brand="Moonfield", name="Sunfield Style Oats")
    assert resolve_brand(identity, REGISTRY) is None


def test_a_brand_word_inside_the_name_is_not_a_prefix_match() -> None:
    assert (
        resolve_brand(ProductIdentity(brand=None, name="Classic Sunfield Oats"), REGISTRY) is None
    )


# --------------------------------------------------------------------------- same product


def test_the_right_page_matches() -> None:
    result = same_product(
        page("Sunfield Masala Oats | Sunfield Foods", ("Masala Oats",)), oats(), SUNFIELD, POLICY
    )
    assert result.matched is True
    assert result.reason is None
    assert result.coverage == 1.0


def test_a_page_that_never_names_the_brand_does_not_match() -> None:
    result = same_product(page("Masala Oats", ("Masala Oats",)), oats(), SUNFIELD, POLICY)
    assert result.matched is False
    assert result.reason == "brand_absent"


def test_the_brand_may_appear_anywhere_on_the_page() -> None:
    result = same_product(
        page("Masala Oats", ("Masala Oats",), text="© Sunfield Foods Pvt Ltd"),
        oats(),
        SUNFIELD,
        POLICY,
    )
    assert result.matched is True


def test_too_few_name_words_in_the_title_does_not_match() -> None:
    identity = oats("Sunfield Masala Oats Tangy Tomato Twist")
    result = same_product(
        page("Sunfield Masala Oats", ("Masala Oats",)), identity, SUNFIELD, POLICY
    )
    assert result.matched is False
    assert result.reason == "name_coverage_low"
    assert result.coverage == 0.4


def test_coverage_exactly_at_the_threshold_matches() -> None:
    identity = oats("Sunfield Masala Oats Tangy Tomato Twist")
    result = same_product(page("Sunfield", ("Masala Oats Tangy",)), identity, SUNFIELD, POLICY)
    assert result.matched is True
    assert result.coverage == 0.6


def test_brand_words_stop_words_and_quantities_do_not_count_towards_coverage() -> None:
    identity = oats("Sunfield Oats with Honey 500 g")
    result = same_product(page("Sunfield Honey Oats"), identity, SUNFIELD, POLICY)
    assert result.matched is True
    assert result.coverage == 1.0


def test_body_text_does_not_count_towards_name_coverage() -> None:
    """A product-listing page mentions every product in its body. Only the title and the main
    headings say which product the page is about."""
    result = same_product(
        page("Sunfield Breakfast Range", text="Masala Oats, Classic Oats, Muesli"),
        oats(),
        SUNFIELD,
        POLICY,
    )
    assert result.matched is False
    assert result.reason == "name_coverage_low"


def test_a_name_that_is_only_the_brand_cannot_be_identified() -> None:
    result = same_product(page("Sunfield"), oats("Sunfield 500 g"), SUNFIELD, POLICY)
    assert result.matched is False
    assert result.reason == "name_not_identifiable"


# --------------------------------------------------------------------------- pack size


def test_a_different_pack_size_in_the_title_does_not_match() -> None:
    result = same_product(page("Sunfield Masala Oats 1 kg"), oats(), SUNFIELD, POLICY)
    assert result.matched is False
    assert result.reason == "pack_size_mismatch"


def test_the_scanned_size_among_several_matches() -> None:
    result = same_product(
        page("Sunfield Masala Oats", ("Available in 1 kg | 500g",)), oats(), SUNFIELD, POLICY
    )
    assert result.matched is True


def test_sizes_compare_across_units() -> None:
    result = same_product(
        page("Sunfield Masala Oats 500 g"), oats(qty=0.5, unit="kg"), SUNFIELD, POLICY
    )
    assert result.matched is True


def test_mass_and_volume_are_not_the_same_size() -> None:
    result = same_product(page("Sunfield Masala Oats 500 g"), oats(unit="ml"), SUNFIELD, POLICY)
    assert result.matched is False
    assert result.reason == "pack_size_mismatch"


def test_no_size_on_the_page_is_not_a_mismatch() -> None:
    assert same_product(page("Sunfield Masala Oats"), oats(), SUNFIELD, POLICY).matched is True


def test_a_quantity_in_the_body_is_not_a_pack_size() -> None:
    """Nutrition tables say "per 100 g". That is not the pack."""
    result = same_product(
        page("Sunfield Masala Oats", text="Nutritional information per 100 g"),
        oats(),
        SUNFIELD,
        POLICY,
    )
    assert result.matched is True


def test_an_unknown_scanned_size_skips_the_size_check() -> None:
    result = same_product(
        page("Sunfield Masala Oats 1 kg"), oats(qty=None, unit=None), SUNFIELD, POLICY
    )
    assert result.matched is True
