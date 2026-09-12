"""The online ingredient cross-check — docs/08-ingredient-crosscheck-plan.md, FR-31.

Reads the ingredient list off a scan's stored OCR text, finds the product's page on the brand's
registered website, reads the list published there, and compares the two.

**This is a consistency signal, not a compliance verdict** (plan §2.1). Nothing in this package
produces a ``rules.types.Finding`` or calls ``rules.evaluate``. Its outcomes are
``CONSISTENT | DIFFERENCES_FOUND | UNCLEAR | NOT_VERIFIABLE`` and never PASS or FAIL: the package
label is the legal declaration, and a website that disagrees with it is a prompt to look, not an
accusation.

Modules, in the order a check runs them:

* ``data``      — the reviewed vocabulary and source registry in ``ingredients/``
* ``locate``    — find the list's block in a text
* ``split``     — block to items, for a label (OCR words) or a page (text)
* ``identify``  — resolve the brand; decide whether a page is this product      (pure)
* ``discover``  — candidate pages from the registered site's sitemap
* ``fetch``     — the guarded fetcher: the only code here that touches the network
* ``html_text`` — page bytes to text
* ``compare``   — the part that decides                                          (pure)
* ``check``     — the orchestrator, behind persistence ports

No module re-exports another's names from here, so importing the comparator never imports the
fetcher.
"""
