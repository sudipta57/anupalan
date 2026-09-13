"""Fetch public BIS pages into `bis/corpus/`, one reviewable YAML file per page.

    python -m scripts.fetch_bis                          # fetch every manifest entry
    python -m scripts.fetch_bis --only hallmarking       # entries whose title matches
    python -m scripts.fetch_bis --calibrate-404 <url>    # see what this host's soft 404 looks like

**This writes files; it does not ingest.** `scripts/ingest_bis.py` is still the only thing that puts
a document in the database, and `services/bis/ingest.screen()` is still the only thing that decides
what may enter the corpus. The ordering is the point: a fetch lands in the working tree, a human
reads the diff, and only then does it become something an answer can cite. A fetcher that wrote
straight to the database would mean nobody could say, six months from now, what text an answer had
been given from — which is the argument `ingest_bis.py` makes for hand-curated files, and it applies
to a machine-curated one just as hard.

**There is exactly one blocklist**, in `services/bis/ingest`, and this script calls it rather than
carrying a copy. Two definitions of "may this enter the corpus" will drift, and the drift that
matters is the one where the second copy is more permissive (CLAUDE.md §3.5).

Two host-specific hazards this script exists to handle, both of which have already cost time:

- **bis.gov.in serves soft 404s.** A wrong URL returns HTTP 200 with a generic page, not an error,
  so the status code proves nothing. Two such pages reached the corpus before and were caught only
  because their extracted text was byte-identical. Both guards below come from that: a title-overlap
  check, and a duplicate-hash check across the whole run.
- **The pages are mostly navigation.** A whole-page dump is menus, and menu text then gets retrieved
  and cited to a user as the source of an answer. Only the content region is kept, and a region that
  is mostly anchor text is flagged in the file's own header for review.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import yaml
from bs4 import BeautifulSoup, Tag

from app.services.bis.ingest import (
    BIS_SOURCE_TYPES,
    CATALOGUE_METADATA_MAX_CHARS,
    SourceDocument,
    screen,
)

# Where the manifest and the corpus live, relative to `backend/`. Outside `app/` because they are
# data, on the same terms as `rulepacks/` (CLAUDE.md §2).
_BIS = Path(__file__).resolve().parents[2] / "bis"
DEFAULT_MANIFEST = _BIS / "corpus-manifest.yaml"
DEFAULT_OUT = _BIS / "corpus"

# The manifest deliberately does NOT live in `corpus/`: `ingest_bis.corpus_files()` reads every
# `*.yaml` in that directory as a document, so a manifest sitting there fails the required-key
# check and takes the whole ingest run down with it.

TIMEOUT_S = 30.0
USER_AGENT = "anupalan-bis-corpus/1.0 (compliance research)"

# A whole-page dump on bis.gov.in is menus: the products-under-compulsory-certification page is
# ~95% navigation, and its real content region is a single paragraph plus five links.
STRIP_SELECTORS = (
    "nav, header, footer, aside, script, style, noscript, form",
    ".breadcrumb, .breadcrumbs, #breadcrumb",
    ".menu, .main-menu, .sub-menu, .navbar, .sidebar, .side-menu",
    ".footer, .site-footer, .footer-menu, .social, .social-links",
    ".cookie, .cookie-notice, .skip-link, .search, .language-switcher",
    "#sidebar, #footer, #header, #menu",
    # bis.gov.in specifics: the footer row carries the "Last Updated on" stamp and the visitor
    # counter, and the counter changes on every fetch — left in, it would make the text hash
    # different every run and defeat the duplicate-page guard.
    ".footer_row, .copyright_area, .topnavlist, .covidlist, .covid-leftlist, .productsCC",
    ".breadcrumb-area, .bread_crumb",
)

CONTENT_SELECTORS = (
    # bis.gov.in has no semantic `main` or `article` — it is a Bootstrap grid, and the content
    # region is this class. Found by measuring: on the compulsory-certification page it is the only
    # block over 150 chars with a link density under 45%, everything else being menus and footer.
    ".who_we_area",
    "main",
    "article",
    "#main-content",
    ".main-content",
    ".entry-content",
    ".page-content",
    ".content-area",
    ".post-content",
    "#content",
)

LINK_DENSITY_CEILING = 0.55
"""Above this, the content region is a link index rather than prose, and the document is refused.

Measured the hard way: the first run wrote a "Product Certification Fee" document whose entire text
was *"Like Us on Facebook / Follow Us on Twitter / Follow Us on LinkedIn"*, and a "Jewellers
Registration Scheme" document that was four link labels. Both were flagged and written anyway. A
flagged file still gets ingested, retrieved and quoted to a user as an official source — so the
flag has to be a refusal. A reported gap is strictly better than a citation to a menu."""

MIN_CONTENT_CHARS = 120

MAX_CONTENT_CHARS = 60_000
"""Above this the page is a data table, not prose.

The Scheme I page came back at 281,144 characters: the entire products-under-certification table,
every row an IS number. It is not the content of a standard, so the blocklist does not catch it, but
it is useless to retrieval — a chunk of it is a table fragment with no sentence in it — and it would
dominate the corpus by sheer volume. A table that matters belongs in `bis/qco-crs-v1.yaml`,
which is reviewed data, not here."""

TITLE_OVERLAP_MIN = 0.4
"""How much of a title's distinctive vocabulary must appear in the extracted text. Below this the
page is not about what the manifest labelled it, which on this host means a soft 404."""


@dataclass(slots=True)
class Skip:
    url: str
    reason: str
    detail: str = ""


@dataclass(slots=True)
class Fetched:
    document: SourceDocument
    fetched_at: datetime
    sha256: str
    note: str
    link_density: float

    @property
    def filename(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.document.title.lower()).strip("-")
        return f"{slug}.yaml"


@dataclass(slots=True)
class Report:
    documents: list[Fetched] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)


def looks_like_pdf(url: str, content_type: str, body: bytes) -> bool:
    """A PDF, however it was labelled.

    This fetcher reads HTML. Handing PDF bytes to an HTML parser yields a few hundred characters of
    binary noise, which then fails the title-overlap check and gets reported as a suspected soft
    404 — a misleading reason that sends whoever reads the report looking for a broken URL rather
    than for a missing feature. Six of the eight skips in the first run were this.
    """
    return (
        body[:5] == b"%PDF-"
        or "application/pdf" in content_type.lower()
        or urlparse(url).path.lower().endswith(".pdf")
    )


def normalise(text: str) -> str:
    """Whitespace-collapsed and case-folded. Used for hashing and overlap checks."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def force_english(url: str) -> str:
    """Pin ``lang=en`` on bis.gov.in.

    The host's language choice is sticky: a request with no ``lang`` can land on ``lang=hi`` and
    return the whole page in Hindi. That is not a Hindi corpus — it is the same document in a
    language the retrieval index was not built for, arriving under an English title.
    """
    parsed = urlparse(url)
    if "bis.gov.in" not in parsed.netloc:
        return url
    params = dict(parse_qsl(parsed.query))
    params["lang"] = "en"
    return urlunparse(parsed._replace(query=urlencode(params)))


def extract_content(soup: BeautifulSoup) -> tuple[str, float]:
    """The content region's text, and its anchor-text fraction."""
    for selector in STRIP_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    region: Tag | None = None
    for selector in CONTENT_SELECTORS:
        candidate = soup.select_one(selector)
        if candidate and len(candidate.get_text(strip=True)) >= MIN_CONTENT_CHARS:
            region = candidate
            break
    if region is None:
        region = soup.body or soup

    flat = region.get_text(" ", strip=True)
    anchor_chars = sum(len(a.get_text(" ", strip=True)) for a in region.find_all("a"))
    density = anchor_chars / len(flat) if flat else 1.0

    return re.sub(r"\n{3,}", "\n\n", region.get_text("\n", strip=True)), density


BREADCRUMB_WINDOW = 12
"""How many leading lines to search for the page heading when trimming a breadcrumb."""


def drop_breadcrumb(text: str, title: str) -> str:
    """Remove a leading ``Home / Section / Page`` trail.

    The trail survives content-region extraction because on this host it sits *inside* the content
    div rather than in a `nav`. Left in, it is the first thing a retrieved chunk says, and "Home /
    Product Certification /" is not something anyone should read back as the source of an answer.

    Anchored on the heading rather than on a separator: the trail ends with the page's own title, so
    the last line in the opening window that matches the title is where the document really starts.
    A page whose heading is not in that window is left exactly as it was.
    """
    lines = text.split("\n")

    # Preferred anchor: the trail ends with the page's own heading.
    wanted = normalise(title)
    cut = -1
    for index, line in enumerate(lines[:BREADCRUMB_WINDOW]):
        if normalise(line) == wanted:
            cut = index
    if cut > 0:
        return "\n".join(lines[cut:])

    # Fallback: the heading on the page rarely matches the manifest title exactly — "Scheme I - ISI
    # Mark Scheme" is rendered "Scheme - I (ISI Mark Scheme)" with an en-dash. So when the title
    # cannot be found, cut after the last bare separator instead, which is where any trail ends.
    if lines and normalise(lines[0]) == "home":
        last = -1
        for index, line in enumerate(lines[:BREADCRUMB_WINDOW]):
            if line.strip() == "/":
                last = index
        if last > 0:
            return "\n".join(lines[last + 1 :])

    return text


def find_published_at(soup: BeautifulSoup, text: str) -> date | None:
    """A date the page itself states, or ``None``. Never inferred — a freshness stamp nobody
    published is worse than no stamp, because the screen renders it as fact."""
    meta = soup.find("meta", attrs={"property": "article:modified_time"})
    if isinstance(meta, Tag):
        content = meta.get("content")
        if isinstance(content, str):
            try:
                return datetime.fromisoformat(content.replace("Z", "+00:00")).date()
            except ValueError:
                pass

    match = re.search(r"Last Updated on\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%B %d, %Y").replace(tzinfo=UTC).date()
        except ValueError:
            pass
    return None


def redirected_to_root(requested: str, final: str) -> bool:
    """Soft-404 guard zero, and the only decisive one.

    Measured 2026-09-13: ``https://www.bis.gov.in/this-page-does-not-exist/`` returns **HTTP 200**
    and lands on ``https://www.bis.gov.in/?lang=hi`` — the Hindi homepage, 15,485 characters of
    pure navigation. A real page keeps its path and its ``lang=en``. So a request that asked for a
    path and arrived at the root did not find what it asked for, whatever the status line says.

    Note this also catches the language flip, which ``force_english`` cannot: the redirect drops
    the pinned query string, so a soft 404 comes back in Hindi no matter what was requested.
    """
    asked = urlparse(requested).path.strip("/")
    got = urlparse(final).path.strip("/")
    return bool(asked) and not got


def title_matches_content(title: str, text: str) -> bool:
    """Soft-404 guard one: does the page talk about what we labelled it?"""
    stop = {"the", "of", "for", "and", "under", "a", "an", "to", "in", "on", "bis"}
    tokens = {t for t in re.findall(r"[a-z]{4,}", title.lower()) if t not in stop}
    if not tokens:
        return True
    flat = normalise(text)
    return sum(1 for t in tokens if t in flat) / len(tokens) >= TITLE_OVERLAP_MIN


def build(entry: dict[str, Any], html: str, final_url: str, body: bytes = b"") -> Fetched | Skip:
    url = str(entry["url"])
    source_type = str(entry["source_type"])
    title = str(entry["title"])

    if source_type not in BIS_SOURCE_TYPES:
        return Skip(url, "bad_source_type", f"{source_type!r} is not one of the eight")

    # Checked before anything reads the body: PDF bytes through an HTML parser produce hundreds of
    # thousands of characters of noise, which then trips the size ceiling and gets reported as a
    # data table. That reason is wrong and sends the reader looking for the wrong problem.
    if looks_like_pdf(final_url, "", body):
        return Skip(
            url,
            "pdf_unsupported",
            "this fetcher reads HTML; the page is a PDF and needs a text extractor first",
        )

    if redirected_to_root(url, final_url):
        return Skip(
            url,
            "soft_404_redirect",
            f"asked for a path and landed on {final_url} — this host answers a wrong URL with "
            "HTTP 200 and its homepage",
        )

    soup = BeautifulSoup(html, "html.parser")
    text, density = extract_content(soup)
    text = drop_breadcrumb(text, title)

    if len(text) < MIN_CONTENT_CHARS:
        return Skip(url, "no_content", f"content region was {len(text)} chars")

    if len(text) > MAX_CONTENT_CHARS:
        return Skip(
            url,
            "table_not_prose",
            f"{len(text)} chars exceeds the {MAX_CONTENT_CHARS} ceiling — this is a data table, "
            "and a table that matters belongs in bis/qco-crs-v1.yaml where it is reviewed",
        )

    if density > LINK_DENSITY_CEILING:
        return Skip(
            url,
            "link_index",
            f"link density {density:.0%} — the content region is a menu, not prose. A citation to "
            "this would quote a list of link labels back to the user as an official source",
        )

    if not title_matches_content(title, text):
        return Skip(
            url,
            "soft_404_suspected",
            f"none of the distinctive words in {title!r} appear in the extracted text",
        )

    document = SourceDocument(
        source_type=source_type,
        title=title,
        url=final_url,
        text=text,
        published_at=find_published_at(soup, text),
    )

    # The one blocklist, called here rather than copied. A refusal at this point is the whole
    # point of fetching into the working tree first: it never reaches a file, let alone a citation.
    refusal = screen(document)
    if refusal is not None:
        return Skip(url, f"refused:{refusal.rule_id}", refusal.why)

    if source_type == "catalogue_metadata" and len(text) > CATALOGUE_METADATA_MAX_CHARS:
        return Skip(
            url,
            "catalogue_too_long",
            f"{len(text)} chars exceeds the {CATALOGUE_METADATA_MAX_CHARS} cap — this is a "
            "standard wearing a catalogue label",
        )

    return Fetched(
        document=document,
        fetched_at=datetime.now(UTC),
        sha256=hashlib.sha256(normalise(text).encode()).hexdigest(),
        note=str(entry.get("note") or "").strip(),
        link_density=density,
    )


def run(manifest_path: Path, out_dir: Path, *, only: str | None = None) -> Report:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entries = list(manifest["sources"])
    if only:
        entries = [e for e in entries if only.lower() in str(e["title"]).lower()]

    report = Report()
    seen: dict[str, str] = {}

    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for entry in entries:
            url = force_english(str(entry["url"]))

            try:
                response = client.get(url, timeout=TIMEOUT_S)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                report.skips.append(Skip(url, "unreachable", str(exc)))
                continue

            result = build(entry, response.text, str(response.url), response.content)
            if isinstance(result, Skip):
                report.skips.append(result)
                continue

            # Soft-404 guard two: two pages whose normalised text is byte-identical means at least
            # one is this host's generic 200 page. This is exactly how the last two got in.
            if result.sha256 in seen:
                report.skips.append(
                    Skip(url, "soft_404_duplicate", f"text identical to {seen[result.sha256]!r}")
                )
                continue

            seen[result.sha256] = result.document.title
            report.documents.append(result)

    write(report, out_dir)
    return report


def write(report: Report, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    for item in report.documents:
        payload: dict[str, object] = {
            "source_type": item.document.source_type,
            "title": item.document.title,
            "url": item.document.url,
            "text": item.document.text,
        }
        if item.document.published_at:
            # The `date` object, not `.isoformat()`. A string round-trips through YAML as a string,
            # and `ingest_bis._as_date` rejects it — correctly, since a freshness stamp that is
            # really text would sort and compare wrong. yaml.safe_dump emits a bare `2026-04-15`
            # for a date, which is what the hand-curated files carry and what loads back as a date.
            payload["published_at"] = item.document.published_at

        header = (
            f"# Fetched {item.fetched_at.date().isoformat()} by scripts/fetch_bis.py "
            f"from the url below.\n"
            f"# sha256(normalised text): {item.sha256[:16]}\n"
            f"# Content region only - nav, breadcrumbs, sidebar and footer stripped. "
            f"Link density {item.link_density:.0%}.\n"
        )
        if item.note:
            header += f"# {item.note}\n"

        (out_dir / item.filename).write_text(
            header + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )


def calibrate_404(url: str) -> None:
    """Fetch a URL you know is wrong, to see this host's generic 200 page.

    Worth running once per host before trusting anything the run produced: it shows what the
    duplicate-hash guard will be matching against.
    """
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        response = client.get(force_english(url), timeout=TIMEOUT_S)

    text, density = extract_content(BeautifulSoup(response.text, "html.parser"))
    print(f"status        : {response.status_code}")
    print(f"final url     : {response.url}")
    print(f"content chars : {len(text)}")
    print(f"link density  : {density:.0%}")
    print(f"sha256        : {hashlib.sha256(normalise(text).encode()).hexdigest()[:16]}")
    print("--- first 400 chars of the content region ---")
    print(text[:400])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch public BIS pages into bis/corpus/.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", default=None, help="only entries whose title contains this")
    parser.add_argument("--calibrate-404", dest="calibrate", default=None)
    args = parser.parse_args(argv)

    if args.calibrate:
        calibrate_404(args.calibrate)
        return 0

    report = run(args.manifest, args.out, only=args.only)

    print(f"\nwrote {len(report.documents)} documents to {args.out}")
    for item in report.documents:
        flag = "  [LINK-HEAVY]" if item.link_density > LINK_DENSITY_CEILING else ""
        name = item.filename
        print(f"  {name:<54} {item.document.source_type:<19} {len(item.document.text):>6}c{flag}")

    if report.skips:
        print(f"\nskipped {len(report.skips)}:")
        for skip in report.skips:
            print(f"  {skip.reason:<22} {skip.url}")
            if skip.detail:
                print(f"  {'':<22} {skip.detail}")

    # A skip is a reported gap and a useful outcome, so it is not a failure exit. Nothing was
    # ingested either way — `scripts/ingest_bis.py` is still a separate, deliberate step.
    return 0


if __name__ == "__main__":
    sys.exit(main())
