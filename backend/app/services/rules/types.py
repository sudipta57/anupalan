"""Value types crossing the rules engine boundary (TRD FR-25).

Everything here is a frozen dataclass. The evaluator is a pure function, and a mutable input
would let two evaluations of "the same" scan disagree.

**Verdicts are four-valued** (CLAUDE.md §3.4): ``PASS | FAIL | BORDERLINE | NOT_ASSESSABLE``.
There is deliberately no fifth value for "this rule does not apply to your product". A rule whose
predicate is false produces **no finding at all** — see ``evaluate()``'s docstring for why that
is not the same thing as a silent pass, and how ``findings.assemble()`` counts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE"]
"""The four verdicts. BORDERLINE is never collapsed into FAIL (CLAUDE.md §3.4)."""

ExtractionSource = Literal["regex", "llm", "human"]

QtyBasis = Literal["weight_or_volume", "length_area_or_number"]
"""Which Rule 9 table applies: Table-I keys on quantity, Table-II keys on panel area."""

Channel = Literal["retail", "ecommerce"]

EMBOSSED_SURFACES = frozenset(
    {"embossed", "blown", "formed", "moulded", "molded", "perforated"}
)
"""Surfaces Rule 9 treats as the raised-text case, which carries the higher thresholds.

The *thresholds* for these surfaces live in the pack, never here (CLAUDE.md §3.2). This set only
records which surface words select the pack's ``embossed`` column — a vocabulary question, not a
legal-value one. The wording follows Rule 9: "blown, formed, moulded, embossed or perforated".
"""


@dataclass(frozen=True)
class BBox:
    """Evidence rectangle on the rectified image, in pixels."""

    x: float
    y: float
    width: float
    height: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class Profile:
    """The product context that decides which rules apply.

    Field names match the dotted paths the rule pack uses (``profile.is_imported``,
    ``profile.net_qty_in_g_or_ml``, ...). Renaming one here breaks a pack, so treat these as part
    of the pack contract, not as internal names.
    """

    is_imported: bool = False
    surface: str = "printed"
    qty_basis: QtyBasis = "weight_or_volume"
    channel: Channel = "retail"

    net_qty_in_g_or_ml: float | None = None
    """Net quantity normalised to grams or millilitres — the Table-I key."""

    pdp_area_cm2: float | None = None
    """Principal display panel area — the Table-II key."""

    net_qty_value: float | None = None
    net_qty_unit: str | None = None
    pack_type: str | None = None
    category_code: str | None = None
    name: str | None = None

    @property
    def is_embossed(self) -> bool:
        """True when the surface selects the pack's raised-text threshold column."""
        return self.surface.strip().lower() in EMBOSSED_SURFACES

    @property
    def surface_column(self) -> str:
        """The pack ``threshold_column`` key this profile's surface selects."""
        return "embossed" if self.is_embossed else "normal"


@dataclass(frozen=True)
class Extraction:
    """One extracted declaration (TRD FR-24).

    ``source_span`` is the character range in the OCR text the value came from. The extraction
    layer must verify it exists in the input before accepting the value (CLAUDE.md §8); by the
    time an Extraction reaches the evaluator that check has already happened.
    """

    field_code: str
    value_raw: str
    value_norm: str | None = None
    source: ExtractionSource = "regex"
    confidence: float = 1.0
    bbox: BBox | None = None
    source_span: tuple[int, int] | None = None

    @property
    def is_present(self) -> bool:
        """A field is present only when it carries a non-blank value.

        An empty string extracted with high confidence is an absent declaration, not a present
        one — the difference decides a Rule 6(1) verdict.
        """
        return bool((self.value_norm or self.value_raw or "").strip())

    @property
    def value(self) -> str:
        """The normalised value where one exists, else the raw one."""
        return (self.value_norm or self.value_raw or "").strip()


@dataclass(frozen=True)
class Measurement:
    """One physical measurement off the rectified image (TRD FR-23).

    Millimetres only ever come from the marker homography (CLAUDE.md §3.3). No Measurement may
    be constructed from an estimate, from OCR polygons, or from a curved surface the rectifier
    flagged — in those cases the vision layer emits nothing and the metric rule lands
    NOT_ASSESSABLE.

    ``uncertainty_mm`` of ``None`` means "use the pack's default", i.e.
    ``meta.measurement.default_uncertainty_mm``.
    """

    field_code: str
    glyph: str | None = None
    height_mm: float | None = None
    width_mm: float | None = None
    uncertainty_mm: float | None = None
    clear_space_mm: float | None = None
    is_numeral: bool = False
    is_mark: bool = False
    """Punctuation or a diacritic — a colon, a comma, the dot of an 'i'.

    Neither a numeral nor a letter, and excluded from both height rules. Rule 9 sets minimum
    heights for numerals and for letters; a full stop is not a small letter, and measuring one as
    though it were fails compliant labels on a fraction of a millimetre.
    """

    method: str = ""

    @property
    def width_to_height_ratio(self) -> float | None:
        """Glyph width as a fraction of its height, or None if either side is unmeasured."""
        if self.height_mm is None or self.width_mm is None or self.height_mm <= 0:
            return None
        return self.width_mm / self.height_mm


@dataclass(frozen=True)
class Finding:
    """One rule's verdict for one scan (TRD FR-25, architecture §5 S8).

    ``rulepack_version`` is mandatory and is stamped by the evaluator from the pack it evaluated
    against (CLAUDE.md §3.6) — not from whatever pack happens to be active when the finding is
    read back a year later.
    """

    rule_id: str
    rulepack_version: str
    verdict: Verdict
    citation: str
    severity: str
    message: str = ""
    observed: str | None = None
    required: str | None = None
    observed_value: float | None = None
    required_value: float | None = None
    band: str | None = None
    """The uncertainty band printed on a BORDERLINE verdict, e.g. ``1.80-2.30``."""

    field_codes: tuple[str, ...] = ()
    bbox: BBox | None = None
    confidence: float | None = None

    def sort_key(self) -> tuple[int, str]:
        """Order findings worst-first, then by rule id, so output is deterministic."""
        rank = {"FAIL": 0, "BORDERLINE": 1, "NOT_ASSESSABLE": 2, "PASS": 3}
        return (rank[self.verdict], self.rule_id)


@dataclass(frozen=True)
class FindingsReport:
    """The assembled response body (TRD §5 ``GET /v1/scans/{id}/findings``)."""

    rulepack_version: str
    summary: dict[str, int]
    findings: tuple[Finding, ...] = ()
    not_applicable_rule_ids: tuple[str, ...] = field(default=())
    """Rules in the pack that did not apply to this product, so a reader can tell
    "does not apply to you" from "we could not measure it" without a fifth verdict."""
