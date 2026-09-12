# Decision log

Append-only. One dated line per architectural change, newest last. CLAUDE.md §10 and
CONTRIBUTING.md §2: **a decision lands in the same PR as the change it describes.**

This file answers "why is it like this?" six months later, when the person asking is you. It is
not a changelog — record the *choice* and what it cost, not the diff.

Read alongside [`01-architecture.md`](01-architecture.md) §9, which holds the standing technology
decisions and the alternatives already rejected. **Check §9 before re-arguing a settled
decision.** If a decision here reverses one in §9, update §9 in the same PR.

---

## Format

One entry per decision. Keep it to the five lines below; if it needs more, it needs a section in
`01-architecture.md` and a pointer from here.

```
### YYYY-MM-DD — <decision in one line, in the past tense>
**Context:** what forced a choice.
**Decision:** what was chosen.
**Alternatives:** what was rejected, and why.
**Consequences:** what this now costs or constrains, including what it makes harder.
**PR:** #<number> · **Requirement:** <FR-xx / NFR-xx, or n/a>
```

### Example entry (template — delete nothing, append below)

```
### 2026-10-03 — Rectification fixed at 20 px/mm rather than computed per image
**Context:** Marker size varies (40 mm tag, ID-1 card), so the warp could target either a fixed
scale or a per-image one derived from the marker.
**Decision:** Warp every image to a fixed PX_PER_MM = 20, read from config.
**Alternatives:** Per-image scale from the marker — rejected because every downstream
measurement would then need its own scale factor carried alongside it, and a single missed
conversion is a silently wrong millimetre in a legal report.
**Consequences:** One conversion, in one place. Very large packs may exceed a comfortable warp
size at 20 px/mm; revisit if that appears. PX_PER_MM must never be written at a call site.
**PR:** #12 · **Requirement:** FR-21
```

---

## Decisions

<!-- Append below. Newest last. Nothing recorded yet: the baseline is 01-architecture.md §9. -->

### 2026-09-12 — Repository scaffolded; baseline decisions are those in `01-architecture.md` §9
**Context:** Work on P0/P2 needed a buildable repository with CI and conventions in place.
**Decision:** Scaffolded the layout of CLAUDE.md §2 — FastAPI + Celery backend, Expo mobile app,
`rulepacks/` as data, `infra/` compose for Postgres+pgvector, Redis and MinIO — with no feature
logic. The standing technology decisions are the table in `01-architecture.md` §9 and are not
restated here.
**Alternatives:** n/a — no architectural choice was made or reversed.
**Consequences:** The licence is still unchosen; `LICENSE` is a placeholder and the repository
therefore grants no rights to anyone until it is replaced. Resolve before going public.
**PR:** n/a (initial commit) · **Requirement:** n/a

### 2026-09-12 — Infrastructure moved from self-hosted containers to managed services
**Context:** The scaffold shipped a `docker-compose.yml` running Postgres+pgvector, Redis and
MinIO locally, plus a Dockerfile for the API and worker. That requires every developer to run a
container toolchain, and makes the pilot VM stateful — the one machine holding data you cannot
lose.
**Decision:** No containers anywhere. Postgres on **Neon** (serverless, pgvector as an
extension), Redis on **Redis Cloud** (TLS), object storage on **Cloudflare R2** (S3 API).
`infra/docker-compose.yml` and `backend/Dockerfile` deleted; `infra/` now holds the provisioning
runbook. API and worker run as two processes under a supervisor.
**Alternatives:** Keeping Compose for local development and using managed services only in
production — rejected because two infrastructure definitions drift, and the drift is discovered
in production. Self-hosting everything on one VM — rejected because it makes the VM stateful for
no saving that matters at pilot scale.
**Consequences:** No offline development, and the development database is shared until there is a
Neon branch per developer. Two new failure modes to design around, both in `01-architecture.md`
§11: Neon scale-to-zero cold starts charged against NFR-01, and a hard dependency on network
reachability. Two traps are now load-bearing in code and recorded in `CLAUDE.md` §8 —
`prepare_threshold=None` for Neon's pgbouncer endpoint, and explicit `broker_use_ssl` for Celery
over `rediss://`. Migrations must use `DATABASE_URL_DIRECT`. Storage settings stay named `S3_*`
rather than `R2_*` so an on-premise MinIO deployment remains an endpoint change; the provider is
recorded in `01-architecture.md` §9, not in the variable names. NFR-05's cost model needs
re-costing against managed pricing.
**PR:** n/a (scaffolding) · **Requirement:** n/a

### 2026-09-12 — A rule that does not apply produces no finding, rather than a fifth verdict
**Context:** `03-implementation-plan.md` §P2.4 case 8 expects an importer rule on a domestic pack
to be "skipped, not FAIL", and case 10 expects a rule with a 2027 effective date evaluated in
2026 to be "NOT_APPLICABLE". Read literally that is a fifth verdict, which contradicts
`CLAUDE.md` §3.4 and `01-architecture.md` §6: verdicts are four-valued.
**Decision:** `evaluate()` returns findings only for rules that apply. A rule whose `when`
predicate is false, or whose `effective_from` is after `as_of`, is absent from the result.
`findings.assemble()` takes the pack, so it recovers the difference: the response carries
`not_applicable_rule_ids` and a `not_applicable` count alongside the four verdict counts.
**Alternatives:** Adding `NOT_APPLICABLE` to the `Verdict` union — rejected because §3.4 is a
non-negotiable and the four values are already load-bearing in the mobile findings viewer
(FR-05 groups by exactly four buckets) and in the E3 confusion matrix. Returning the rule with a
`PASS` — rejected outright: a pack that never checked a rule must not report it as satisfied.
**Consequences:** `assemble()` needs the pack, so the rendering and summarising step is no longer
usable on findings alone; that is now its documented signature. A caller that reads
`evaluate()`'s output directly sees only applicable rules and must not infer that a missing rule
was a pass. Reporting (B11) must print the not-applicable list, or a reader will wonder which
rules were checked.
**PR:** n/a (B0–B3) · **Requirement:** FR-25

### 2026-09-12 — Rule pack validation is hand-written against a line-tracking YAML loader
**Context:** FR-26 requires an invalid pack to be rejected with a **line-level** error. A schema
validator (`jsonschema`) works on the parsed structure and carries no source positions, so a YAML
loader that records line numbers is needed regardless of whether a schema language is used.
**Decision:** A `yaml.SafeLoader` subclass records `__line__` on every mapping (stripped before
the data reaches the evaluator), and `services/rules/schema.py` validates the rule shapes
directly. No new dependency.
**Alternatives:** `jsonschema` with the schema as data in `rulepacks/_schema.json` — rejected for
now because it would be the hand-written line-tracking work *plus* a dependency *plus* a mapping
from JSON-pointer error paths back to lines. Revisit if third parties start authoring packs, when
a declarative schema they can read becomes worth the machinery.
**Consequences:** Adding a rule *kind* means editing `VALID_KINDS` and a dispatch branch, which
is a code change — acceptable, since a new kind needs evaluator support anyway. Adding a new
*option* to an existing kind stays a pure pack change: rule bodies are passed through to the
evaluator unvalidated beyond their required keys.
**PR:** n/a (B1) · **Requirement:** FR-26

### 2026-09-12 — PDF rendering split into `render_html` and `render_pdf`
**Context:** `03-implementation-plan.md` §P2.6 specifies WeasyPrint for PDF output. WeasyPrint
rasterises through the GTK3 native stack (pango, cairo, gdk-pixbuf), which pip cannot install and
which is absent on a stock Windows workstation — where development is currently happening. Taken
naively that blocks all work on reports, not just PDF output.
**Decision:** Keep WeasyPrint. `services/reporting/pdf.py` exposes `render_html(data) -> str`,
which is pure and needs no native libraries, and `render_pdf(data) -> bytes`, which imports
WeasyPrint lazily inside the function and hands it that HTML. Every content assertion in
`tests/test_reporting.py` runs against the HTML; only `test_pdf_actually_rasterises` needs the
native stack and it skips with a reason where it is missing. CI installs the apt packages so the
rasterisation path is exercised on every push.
**Alternatives:** Swapping to a pure-Python PDF library (reportlab, fpdf2) — rejected because it
reverses a documented choice for a local-environment reason, and because an HTML/CSS template is
far cheaper to iterate on than a drawing API for a document this layout-heavy. Requiring every
developer to install MSYS2/GTK before touching reports — rejected as an unnecessary barrier given
the split costs nothing.
**Consequences:** PDF output is not verified on a Windows developer machine; CI is the gate for
it. `render_html` is also independently useful — the layout can be opened in a browser during
development, and an HTML report is a plausible future delivery format. A second renderer must
never be added that bypasses `ReportData`.
**PR:** n/a (B11) · **Requirement:** FR-27

### 2026-09-12 — Metric accuracy is bounded by a *relative* scale error, not an absolute one
**Context:** FR-21 states "a printed test chart with known 10.00 mm bars measures 10.00 ± 0.25 mm".
Implementing B5 against synthetic ground truth showed the dominant error is not a fixed
millimetre budget: at 0° tilt, with no perspective at all, a coplanar object still read long.
The cause is ArUco's corner localisation — roughly one pixel on a 200 px marker, i.e. **0.5%** —
which propagates as a proportional scale error to everything in the frame.
**Decision:** Read FR-21's ±0.25 mm as the 2.5% relative figure it is at 10 mm, and test it that
way: a known 10 mm bar, coplanar with but independent of the marker. Measured 0.00–0.15 mm error
across 0–25° tilt. Re-detecting the marker itself is explicitly *not* the test — the marker
defined the scale, so it is guaranteed to come back right and proves nothing.
**Alternatives:** Loosening the tolerance to an absolute ±0.5 mm so a 40 mm object passes —
rejected as fitting the test to the code; it would also have hidden the fact that error scales
with feature size.
**Consequences:** Good news for the product: a 2 mm numeral inherits ~0.01 mm of scale error,
far below the 0.25 mm default measurement uncertainty already in the rule pack, so glyph
metrology is not scale-limited. It also gives the capture screen a real reason to tell users to
move closer — a marker filling more pixels tightens the error proportionally. E1 must still be
run on real photographs; synthetic images cannot exercise lens distortion or non-flat paper.
**PR:** n/a (B5) · **Requirement:** FR-21

### 2026-09-12 — Unmeasurable quality signals report None, never a reassuring default
**Context:** ``quality()`` returns the FR-01 capture gates, including curvature, which
`01-architecture.md` §12.2 uses to downgrade metric rules to NOT_ASSESSABLE on curved packs. But
four coplanar marker corners always fit a homography exactly, so a marker carries **no**
information about whether the package is curved.
**Decision:** ``curvature`` is ``None`` until it is measured from the rectified text region
(B7), and ``tilt_deg`` is ``None`` when no marker was found. ``None`` means "unknown"; it never
means "fine".
**Alternatives:** Returning ``0.0`` for curvature — rejected because it asserts flatness nobody
measured, and §12.2's safeguard only works if the figure can be trusted.
**Consequences:** Callers must handle ``None`` explicitly rather than comparing against a
threshold. That is the point: an unhandled ``None`` is a visible bug, where a fabricated ``0.0``
is a silent wrong answer in a legal report.
**PR:** n/a (B5) · **Requirement:** FR-01, FR-21

### 2026-09-12 — Security helpers fail closed; PaddleOCR is an optional extra
**Context:** Two findings while building B4 and B6. First, ``strip_exif`` was written with a
broad ``except`` that returned the original bytes on failure — and an invalid encoder argument
made it fail on every call, so it silently returned **unstripped** images while appearing to
work. Second, PaddleOCR pulls paddlepaddle plus native wheels and downloads model weights on
first run, which CI must never do.
**Decision:** ``strip_exif`` now raises ``StorageError`` if a payload is an image it cannot
re-encode; only non-images pass through. A regression test pins the fail-closed behaviour.
PaddleOCR moves to a ``[ocr]`` optional extra; ``services/vision/ocr.py`` resolves engines
lazily, so the pipeline imports, type-checks and tests without it, with the stub adapter — which
FR-22 requires to exist regardless — standing in.
**Alternatives:** Logging the EXIF failure and continuing — rejected: a security function that
fails open is worse than one that is absent, because it is believed. Making paddleocr a core
dependency — rejected on CI cost and because it would make the interface's second implementation
theoretical.
**Consequences:** A malformed image now fails the upload path rather than being stored
unstripped; that is the intended trade. ``app/services/vision/adapters/paddle.py`` sits at ~43%
coverage locally since its body needs the real engine — the same shape as WeasyPrint's PDF path,
and it needs a CI job with the extra installed before any pilot.
**PR:** n/a (B4, B6) · **Requirement:** FR-20, FR-22, SR

### 2026-09-12 — Numeral height is decided by cap height, not by every component in the span
**Context:** The first end-to-end run of the pipeline failed a compliant label. Rule 9's Table-I
compares the *smallest* numeral against the threshold, and metrology was marking every connected
component in a numeric declaration as a numeral. In "Net Qty: 250 g" that includes the two dots
of the colon, so a label whose digits measure 3.5 mm was reported as a 0.75 mm FAIL.
**Decision:** Where a component cannot be matched to a known character — which is common, since
components split and merge — it counts as a numeral only if it reaches the **cap height** of its
text line. Components far below cap height are classified as marks (`Measurement.is_mark`) and
are excluded from the numeral *and* the letter height rules: a full stop is not a small letter
either. A cluster of one cannot set its own cap height, or an isolated mark becomes trivially
cap-height; it is measured against the tallest glyph in the region instead.
**Alternatives:** Cropping tighter to the value rather than the whole OCR word — rejected for now
because OCR gives word-level boxes and sub-word cropping would have to estimate character
advance, putting an approximation inside the measurement path. Taking the median height of the
line, as the P0 spike sketched — rejected because Rule 9(3)'s width proviso needs per-glyph
numbers.
**Consequences:** Measurement is now conservative in the right direction: an unidentifiable
component is not treated as a numeral, so the failure mode is NOT_ASSESSABLE rather than a false
FAIL (TRD §7, E3). It also means the reported height is the smallest cap-height glyph in the
declaration, which can read a few percent under the true cap height when a word mixes ascenders
and digits — within the pack's 0.25 mm uncertainty band, so it lands BORDERLINE rather than FAIL
in a marginal case. Revisit with tighter cropping when OCR gives character-level boxes.
**PR:** n/a (B7, B10) · **Requirement:** FR-23

### 2026-09-12 — Format rules evaluate the raw label text, not the normalised value
**Context:** Also found by the first end-to-end run. Extraction normalises "250 gms" to "250 g"
so downstream comparisons are uniform, and deliberately preserves `value_raw` so the rule that
objects to the variant can see it. The evaluator was reading the normalised value, so
`LM-QTY-UNIT-SYMBOL` — which exists for no other purpose than to fail a package printing "gms" —
passed every label it was written to catch.
**Decision:** `_eval_format` reads `value_raw`, falling back to the normalised value only when
raw is empty. A format rule asks how the label *wrote* something; the normalised form has by
definition already had the defect corrected out of it.
**Alternatives:** Not normalising destructively — already the case, and not the problem. Moving
unit checking into extraction — rejected: it is a rule with a citation and an effective date, so
it belongs in the pack.
**Consequences:** `observed` on a format finding now quotes what the label actually said, which
is what a report needs to show. Any future format rule must be written against raw text.
**PR:** n/a (B10) · **Requirement:** FR-24, FR-25

### 2026-09-12 — The pipeline persists through a port, so it predates the data layer
**Context:** B10's dependencies include B12, the data layer, whose schema is ask-first
(CLAUDE.md §7). Waiting would have left the ten-stage pipeline unwritten and untested until a
schema review completed.
**Decision:** `services/pipeline.py` declares `ScanStore` as a Protocol — load, mark, save — and
takes storage, OCR, the rule pack and the LLM as arguments. B12 supplies the database adapter.
**Alternatives:** Writing the schema first — rejected, it needs review. Having the pipeline use
the ORM directly — rejected outright: org scoping is enforced in `repositories/`, and a pipeline
that could reach past it would be a second door into another org's evidence.
**Consequences:** The pipeline is complete, golden-file-pinned and runs with no database, which
is what makes the end-to-end test deterministic. B12 must implement the port rather than inventing
its own call shape. The Celery task in `app/tasks/scan.py` imports a repository that does not
exist yet, so the worker cannot run end to end until B12 lands — the pipeline and its tests can.
**PR:** n/a (B10) · **Requirement:** P2.3, NFR-04
