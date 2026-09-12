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

### 2026-09-12 — `POST /v1/scans` takes an asset list, not an `asset_count`
**Context:** TRD §5 abbreviates the intake body as `{..., asset_count}`. Implementing B14 showed a
count cannot produce upload URLs: `presign_put` needs a **content type per asset**, because the
type is part of the signature (B4) and is what stops a client presenting one type to the
allow-list and uploading another.
**Decision:** The body carries `assets: [{content_type, size_bytes, sha256}]`. The size lets the
ceiling be enforced when the capability is issued rather than after the bytes arrive. The hash is
declared by the client and **verified by the worker** against the stored object before any
processing; a mismatch fails the scan.
**Alternatives:** Making `scan_assets.sha256` nullable and having the worker fill it in — rejected
because it weakens evidence integrity: architecture §10 wants the hash of the raw image recorded
*at upload*, and a hash the server computes later attests to what is in the bucket now, not to
what the camera produced. Having the API hash the object at submit — rejected outright, FR-20 gives
submit 300 ms and forbids it touching an image.
**Consequences:** The declared hash is a *claim* until the worker checks it, which is the honest
framing and is tested both ways. The mobile client must hash before uploading — it already holds
the bytes for the offline queue, so this costs nothing there. `services/pipeline.ScanAsset` gained
an optional `sha256`; `None` skips verification, so the golden-file test is unaffected.
**PR:** n/a (B14) · **Requirement:** FR-20, SR

### 2026-09-12 — Idempotency is a table, fingerprinted by request body
**Context:** TRD §5 requires `Idempotency-Key` on every creating POST. The mobile app retries on a
flaky connection and, with FR-04's offline queue, may retry a scan submitted days earlier — so a
request arriving twice is the normal case, not the exceptional one. Without a record of what the
first attempt produced, every retry is duplicate evidence and a dashboard that counts one
inspection twice.
**Decision:** An `idempotency_keys` table (migration 0002), org-scoped like everything else,
storing a fingerprint of the canonical request body and the original response verbatim. A retry
with the same body replays that response, presigned URLs included. A retry with a *different* body
is a **409**.
**Alternatives:** Redis with a TTL — rejected because it makes scan creation depend on Redis being
up, where today Redis being down only degrades the worker, and a flush silently reopens the
duplicate window. A column on `scans` — rejected: it carries no request fingerprint, and products
and B21's bulk endpoint would each need their own column and unique index.
**Consequences:** Records accumulate and are genuinely disposable; `purge_before` exists for a
retention policy B23 will set. Replaying the stored response rather than re-deriving it is what
keeps a retry from minting a second live upload capability for the same object.
**PR:** n/a (B14) · **Requirement:** FR-20

### 2026-09-12 — A recompute resolves its pack by version, database first then disk
**Context:** B15's `confirm-fields` must re-evaluate under the pack the scan was **originally**
judged by, not the active one (CLAUDE.md §3.6) — the backend plan lists the obvious
`active_pack()` implementation as a standing trap. Something therefore has to turn a stored
version label back into a `RulePack`.
**Decision:** `repositories/rulepacks.resolve_pack` looks in the `rulepacks` table first, then in
`rulepacks/` on disk, and **records** what it resolved from disk. The database becomes the durable
copy, and a pack file later removed from the repository stays reproducible. When neither source
has it, `confirm-fields` returns **409** rather than substituting today's rules.
**Alternatives:** Always reading from disk — rejected: it ties reproducibility to whichever git
revision is deployed. Seeding the table at startup — rejected as a migration-shaped problem
solved lazily for free.
**Consequences:** A read path that writes, which is unusual enough to be documented where it
lives. The refusal is a real outcome and is tested: a scan whose pack has vanished cannot be
recomputed, and saying so is the only honest answer.
**PR:** n/a (B15) · **Requirement:** FR-06

### 2026-09-12 — Audit verification continues from what each row claims
**Context:** B16 requires the endpoint to report the **first** broken link. The naive walk carries
the expected hash forward, so one edited row reports every subsequent row as broken too.
**Decision:** `verify` continues from the hash each row *claims*, not from the one it should have
had. A single edit therefore produces exactly one break, at the edited row, distinguishing
`hash_mismatch` (the row was edited) from `broken_link` (a row was removed or inserted).
`created_at` is set in Python and signed into the hash; the row `id` is not, because it is
assigned on flush and the chain's order comes from the links. Canonicalisation is versioned
(`CANONICAL_FORM`) and must never be edited in place.
**Alternatives:** Reporting a boolean — rejected by the card and useless in practice: "the audit
log is corrupt" bounds nothing. Including the `id` in the hash — rejected, it would force a flush
before the hash could be computed for no gain.
**Consequences:** Everything before the first break is still provably intact, which is the claim
an investigator actually needs. Concurrent appends within one org could fork the chain; the tail
read takes a row lock on Postgres, and SQLite needs none because the suite is single-threaded.
**PR:** n/a (B16) · **Requirement:** SR

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

### 2026-09-12 — `org_id` denormalised onto every scan-child table, held honest by a composite FK
**Context:** B12's brief is that org scoping is enforced in the repository base class, not
remembered at each call site: "a query that cannot name its org must not get past the base class."
The scan-child tables — assets, OCR results, extractions, measurements, evaluations, findings,
reports — could reach their org by joining `scans`, but a base class that has to join is a base
class each subclass can bypass by writing its own query.
**Decision:** Every org-owned table carries `org_id` itself, so `OrgScopedRepository.select()` is
one `WHERE` with no join, and every read, write, count and existence check inherits it. The
redundant copy is not trusted: each child table's `(scan_id, org_id)` is a composite foreign key
onto `scans (id, org_id)`, which carries a matching `UNIQUE`, so a row whose org disagrees with
its scan's cannot be inserted at all.
**Alternatives:** Joining through `scans` inside the base class — rejected because the filter then
lives in the query rather than in the class, and a subclass writing its own `select()` silently
loses it. Postgres row-level security — rejected for now: it moves the boundary into the database
where the CI suite (which runs on SQLite) could not exercise it, and it needs a per-request `SET`
that pgbouncer's transaction pooling makes fragile.
**Consequences:** Seven redundant columns and seven composite keys. `test_org_isolation` asserts
structurally that no org-owned table lacks `org_id` and no scan child lacks the composite key, so
a new table that forgets either fails the suite rather than leaking quietly. `otp_requests` is the
one deliberate exception and is listed as such: a code is issued against a phone number before
anyone knows which org it belongs to.
**PR:** n/a (B12) · **Requirement:** SR, DR

### 2026-09-12 — Findings grouped into `scan_evaluations` revisions; saving is idempotent by content
**Context:** Two requirements pull in opposite directions. `findings` is append-only, and B15's
`confirm-fields` must recompute under the pack version the scan was *originally* judged under. But
`task_acks_late` means a killed worker's message is redelivered and the pipeline runs the whole
scan again (NFR-04) — and B10 requires that re-running a completed scan does not duplicate
findings. Appending on every run doubles the verdict set; deleting the previous rows is exactly
what append-only forbids.
**Decision:** A `scan_evaluations` row records one complete run of the rules engine — its
revision, its pack version and checksum, its `as_of`, and the canonical SHA-256 of the findings it
produced. Findings point at it. The verdicts that stand for a scan are its highest revision's.
`ScanStoreAdapter.save_outcome` compares that digest against the latest evaluation and, when they
match, writes nothing: a redelivery costs a comparison. A genuinely different result appends a new
revision, leaving the old one intact.
**Alternatives:** A plain `revision` integer on `findings` with no grouping table — rejected
because `as_of` and the pack checksum would then be repeated on every row or not stored at all,
and B15 needs both. An `is_current` flag — rejected: a flag can be wrong, an ordering cannot.
Deleting and re-inserting on re-run — rejected outright, it breaks append-only.
**Consequences:** One extra table and one extra join on the findings endpoint. `findings_sha256`
is also what a report embeds (`01-architecture.md` §10), so the hash earns its place twice. The
digest covers findings, not extractions: a re-run producing identical verdicts from slightly
different extraction rows records nothing new, which is the right trade because the verdict is
what the row exists to state.
**PR:** n/a (B12) · **Requirement:** NFR-04, FR-05, FR-06

### 2026-09-12 — Database tests run on SQLite in CI, with a Neon drift test as the deploy gate
**Context:** `CLAUDE.md` §6 requires the org-isolation suite to run on **every PR**, and CI holds
no datastore credentials by design — Postgres, Redis and object storage are managed services and
the workflow has no secrets for them.
**Decision:** Postgres-only column types (`JSONB`, `vector(1024)`, `BIGSERIAL`) are declared
through `with_variant` in `app/models/base.py`, so one model file yields the real type on Neon and
a portable one on SQLite. `test_org_isolation.py`, `test_auth.py` and `test_scan_store.py` build
the schema with `create_all()` on in-memory SQLite. `test_migration.py` runs against
`DATABASE_URL_DIRECT` and skips without it: it asserts the database is at head and that
`compare_metadata` returns an empty diff, so the models and the migration cannot drift apart
unnoticed.
**Alternatives:** A Neon branch per CI run — rejected for now: it needs an API token in CI secrets
and makes every PR depend on a live external service. Skipping the isolation suite in CI —
rejected, it contradicts §6, and this is the one suite that must never be allowed to go yellow.
**Consequences:** SQLite does not check the migration, the extension or the index method, so
`alembic upgrade head` followed by `pytest tests/test_migration.py` is a release gate rather than
a CI step. Foreign keys are enabled explicitly in the fixture (`PRAGMA foreign_keys=ON`), because
SQLite ignores them by default and the composite keys are the point.
**PR:** n/a (B12) · **Requirement:** SR, DR

### 2026-09-12 — HS256 tokens written against the stdlib rather than adding a JWT dependency
**Context:** B13 needs signed access tokens and a hash for OTP codes and refresh tokens. The
dependency ask covered a JWT library and a slow hasher; only `pgvector` was approved.
**Decision:** `services/auth/tokens.py` implements HS256 on `hmac`, `hashlib` and `base64`, and
OTP codes and refresh tokens are peppered HMAC-SHA256. The module documents the four attack
classes a JWT verifier has to close and closes each explicitly: the algorithm is a module constant
never read from the token's own header, the signature is compared with `compare_digest`, `typ`
separates token kinds, and the payload is parsed only after the signature verifies.
`tests/test_auth.py` constructs each attack — `alg: none`, `alg: RS256`, a tampered `org` claim, a
foreign signing key — rather than asserting the property in the abstract.
**Alternatives:** `pyjwt` — recommended but not approved; the tests are written against behaviour
rather than implementation, so swapping it in later is a module replacement with the suite
unchanged. `argon2-cffi` for OTP codes — not approved and not needed: six digits is 10^6 of
entropy, so anyone holding the hash column can enumerate it whatever the cost function. What
protects a code is that it is single-use, short-lived, attempt-capped and rate-limited on two
axes — all enforced by columns, all tested.
**Consequences:** ~60 lines of security-critical code this project now owns and must maintain,
which is the real cost. One configured `SECRET_KEY`, never used directly: `derive_key` HMACs it
with a purpose label, so the JWT signing key and the OTP pepper are different keys. There is no
development default — unset means no token can be issued, because a default signing key that
reaches production is an auth system anyone can mint tokens for and nothing about it looks broken.
**PR:** n/a (B13) · **Requirement:** SR

### 2026-09-12 — A body-supplied `org_id` is refused, not ignored
**Context:** `org_id` comes from the verified token and nowhere else. Pydantic's default is to
drop unrecognised fields, which would make a body carrying `org_id` safe but invisible.
**Decision:** `schemas/base.StrictModel` sets `extra="forbid"` and raises `BodyOrgIdError` before
any field is parsed when a body contains `org_id`; `main.py` renders it as a 400 in the NFR-07
envelope. Every request schema inherits it.
**Alternatives:** Ignoring the field — equally safe, and rejected anyway because it conceals both
a broken client and an attacker probing for exactly this. A router-level check — rejected: it
would exist only on the endpoints somebody remembered.
**Consequences:** Every request body is now strict about unknown fields, so a client typo is a 422
rather than a silently missing value. Any future schema that legitimately needed a field named
`org_id` — there is none — would have to opt out deliberately.
**PR:** n/a (B13) · **Requirement:** SR

### 2026-09-12 — The explainer returns a string, so it cannot express a verdict
**Context:** `reporting.explain` is one of the three LLM call sites (`CLAUDE.md` §9) and it writes
guidance about a finding. The non-negotiable is that the LLM never decides compliance (§3.1), and
"we told it not to" is not an enforcement mechanism.
**Decision:** `explain(finding) -> str`. It receives a finished, frozen `ReportFinding` and
returns prose; there is no field on its return value a verdict could occupy. The prompt states the
verdict as settled fact rather than asking for one, and an answer that reaches for a legal
citation is discarded in favour of the deterministic template — the citation is the pack's, is
printed separately and verbatim, and a plausible invented one in the guidance column is the
failure that would make the document indefensible.
**Alternatives:** Returning a structured object with optional fields — rejected: any field the
model can populate is a field that can contradict the engine. Passing the whole findings report
and asking for a summary — rejected for the same reason, plus cost.
**Consequences:** Guidance is always produced. No provider, a failed call, an empty answer, or one
that cites law all fall back to a template built from the finding itself, so an unavailable LLM
changes the wording and never the report's existence (`01-architecture.md` §11). `explain_all`
defaults to adverse findings only, since explaining a dozen passes is a dozen calls for text
nobody reads.
**PR:** n/a (B11) · **Requirement:** FR-27
