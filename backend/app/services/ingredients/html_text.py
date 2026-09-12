"""Page bytes to text — B29.

Stdlib ``html.parser`` only; no parsing dependency (plan ask 2). The text produced here is what
every online item's ``source_span`` indexes, so it must be a deterministic function of the stored
snapshot: the same bytes read next year give the same text and the same offsets.

Block elements become paragraph breaks and list items become line breaks, which is what lets the
splitter read an HTML ``<ul>`` of ingredients one item per line. Script, style, template and
``noscript`` content never reaches the text. There is no JavaScript execution: a page that only
renders its content with JavaScript is recognised as such, and reported, rather than half-read.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from html.parser import HTMLParser

MIN_VISIBLE_CHARS = 200
"""Below this much visible text, a page that loads scripts is taken to be an empty shell a script
fills in. An engineering heuristic for choosing a reason code, never a comparison threshold."""

_BLOCK = frozenset(
    {
        "address", "article", "aside", "blockquote", "details", "dialog", "div", "dl", "dt", "dd",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "hr", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody",
        "tfoot", "thead", "ul",
    }
)  # fmt: skip
_LINE = frozenset({"li", "br", "tr", "option"})
_CELL = frozenset({"td", "th"})
_SKIP = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "object", "canvas"})
_HEADINGS = frozenset({"h1", "h2", "h3"})

_WHITESPACE = re.compile(r"\s+")
_EXTRA_BREAKS = re.compile(r"\n{3,}")
_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?([^\s;\"']+)", re.IGNORECASE)
_META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class PageText:
    """What a page says, as far as the cross-check is concerned."""

    text: str
    title: str = ""
    headings: tuple[str, ...] = ()
    script_count: int = 0

    @property
    def looks_script_rendered(self) -> bool:
        return self.script_count > 0 and len(self.text) < MIN_VISIBLE_CHARS


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.pending_breaks = 0
        self.skip_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.heading_parts: list[str] | None = None
        self.headings: list[str] = []
        self.script_count = 0

    def _break(self, level: int) -> None:
        self.pending_breaks = max(self.pending_breaks, level)

    def _space(self) -> None:
        if self.parts and self.pending_breaks == 0 and not self.parts[-1].endswith(" "):
            self.parts.append(" ")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.script_count += 1
        if tag in _SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = True
            return
        if tag in _BLOCK:
            self._break(2)
        elif tag in _LINE:
            self._break(1)
        elif tag in _CELL:
            self._space()
        if tag in _HEADINGS:
            self.heading_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            return
        if tag in _BLOCK:
            self._break(2)
        elif tag in _LINE:
            self._break(1)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.in_title = False
            return
        if tag in _HEADINGS and self.heading_parts is not None:
            heading = " ".join("".join(self.heading_parts).split())
            if heading:
                self.headings.append(heading)
            self.heading_parts = None
        if tag in _BLOCK:
            self._break(2)
        elif tag in _LINE:
            self._break(1)

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.heading_parts is not None:
            self.heading_parts.append(data)

        collapsed = _WHITESPACE.sub(" ", data)
        if not collapsed.strip():
            if collapsed:
                self._space()
            return
        if self.pending_breaks and self.parts:
            self.parts.append("\n" * self.pending_breaks)
        self.pending_breaks = 0
        self.parts.append(collapsed)


def _decode(body: bytes, content_type: str | None) -> str:
    candidates: list[str] = []
    if content_type:
        header = _HEADER_CHARSET.search(content_type)
        if header is not None:
            candidates.append(header.group(1))
    meta = _META_CHARSET.search(body[:4096])
    if meta is not None:
        candidates.append(meta.group(1).decode("ascii", errors="ignore"))
    candidates.append("utf-8")

    for name in candidates:
        try:
            codecs.lookup(name)
        except LookupError:
            continue
        return body.decode(name, errors="replace")
    return body.decode("utf-8", errors="replace")


def page_text(body: bytes, content_type: str | None) -> PageText:
    """Extract the visible text, title and main headings from a page's bytes."""
    extractor = _Extractor()
    extractor.feed(_decode(body, content_type))
    extractor.close()

    lines = (" ".join(line.split()) for line in "".join(extractor.parts).split("\n"))
    text = _EXTRA_BREAKS.sub("\n\n", "\n".join(lines)).strip()

    return PageText(
        text=text,
        title=" ".join("".join(extractor.title_parts).split()),
        headings=tuple(extractor.headings),
        script_count=extractor.script_count,
    )


__all__ = ["MIN_VISIBLE_CHARS", "PageText", "page_text"]
