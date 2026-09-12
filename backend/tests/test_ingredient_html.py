"""HTML to text for the online ingredient list — B29.

Stdlib ``html.parser`` only; no parsing dependency (plan ask 2). The text produced here is what
every online item's ``source_span`` indexes, so it has to be a deterministic function of the stored
snapshot bytes: the same snapshot read next year must give the same offsets.
"""

from __future__ import annotations

from app.services.ingredients.html_text import page_text
from app.services.ingredients.split import read_page
from tests.ingredients_support import vocabulary

PRODUCT_PAGE = b"""<!doctype html>
<html><head>
<title>Sunfield Masala Oats 500 g &amp; more | Sunfield</title>
<style>.x { color: red }</style>
<script>window.dataLayer = ["Ingredients: poison"];</script>
</head><body>
<nav><a href="/">Home</a> <a href="/oats">Oats</a></nav>
<main>
  <h1>Masala   Oats</h1>
  <p>A warm, savoury breakfast made with rolled oats and a blend of Indian spices, ready in
  three minutes. Sunfield has been milling oats in India since 1985.</p>
  <section class="ingredients">
    <h3>Ingredients</h3>
    <ul>
      <li>Rolled oats (70%)</li>
      <li>Spices &amp; condiments</li>
      <li>Salt</li>
    </ul>
  </section>
  <section><h3>Nutritional Information</h3>
  <table><tr><td>Energy</td><td>380 kcal</td></tr></table></section>
</main>
<noscript>Please enable JavaScript</noscript>
</body></html>
"""


def test_title_and_main_headings_are_captured() -> None:
    result = page_text(PRODUCT_PAGE, "text/html; charset=utf-8")
    assert result.title == "Sunfield Masala Oats 500 g & more | Sunfield"
    assert result.headings == ("Masala Oats", "Ingredients", "Nutritional Information")


def test_scripts_styles_and_noscript_never_reach_the_text() -> None:
    result = page_text(PRODUCT_PAGE, "text/html")
    assert "poison" not in result.text
    assert "color: red" not in result.text
    assert "enable JavaScript" not in result.text


def test_list_items_become_lines_and_sections_become_paragraphs() -> None:
    result = page_text(PRODUCT_PAGE, "text/html")
    assert (
        "Ingredients\n\nRolled oats (70%)\nSpices & condiments\nSalt\n\nNutritional Information"
        in result.text
    )


def test_the_online_list_reads_from_the_page() -> None:
    result = read_page(page_text(PRODUCT_PAGE, "text/html").text, vocabulary().locate)
    assert result is not None
    assert [entry.name for entry in result.items] == ["Rolled oats", "Spices & condiments", "Salt"]
    assert result.items[0].pct == 70.0


def test_the_same_bytes_give_the_same_text() -> None:
    assert page_text(PRODUCT_PAGE, "text/html") == page_text(PRODUCT_PAGE, "text/html")


def test_the_charset_comes_from_the_header() -> None:
    body = "<title>Café Oats</title><p>x</p>".encode("latin-1")
    assert page_text(body, "text/html; charset=ISO-8859-1").title == "Café Oats"


def test_the_charset_comes_from_a_meta_tag_when_the_header_has_none() -> None:
    body = '<meta charset="windows-1252"><title>Café Oats</title>'.encode("cp1252")
    assert page_text(body, "text/html").title == "Café Oats"


def test_an_unknown_charset_falls_back_rather_than_raising() -> None:
    assert page_text(b"<title>Oats</title>", "text/html; charset=no-such-codec").title == "Oats"


def test_an_empty_shell_rendered_by_javascript_is_recognised() -> None:
    shell = (
        b"<html><head><title>Sunfield</title></head><body>"
        b'<div id="root"></div><script src="/app.js"></script></body></html>'
    )
    assert page_text(shell, "text/html").looks_script_rendered is True


def test_a_real_page_with_scripts_is_not_mistaken_for_a_shell() -> None:
    assert page_text(PRODUCT_PAGE, "text/html").looks_script_rendered is False
