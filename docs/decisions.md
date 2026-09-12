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

### 2026-09-12 — `scans.district` and `products.brand` are recorded columns, not derived values
**Context:** FR-30 groups violations by district (Mode A) and by brand (Mode B). The schema had
neither column: `scans` carries coordinates and `products` carries a name.
**Decision:** Migration 0003 adds `scans.district` (VARCHAR 100) and `products.brand` (VARCHAR 200),
both nullable, each with an org-led index. Both dashboards group a NULL under `null` — rendered as
*unknown* — rather than excluding the row.
**Alternatives:** Resolving a district from `geo_lat`/`geo_lon` — rejected: the resolution is only
as good as the boundary file behind it, and attributing an inspection to the wrong officer's
jurisdiction is a worse failure than admitting the district is unknown. Reading a brand off
`products.name` — rejected: "Tata Salt 1 kg" and "Tata Salt 500 g" are two products of one brand,
and a packaging agency's account covers many brands, so the axis would merge nothing and split
everything. Storing either in `scans.device_meta` JSON — rejected: unindexed and dialect-specific
to query, against FR-30's 1 s budget on 50,000 findings.
**Consequences:** Both fields are optional at capture, so the dashboards degrade to an `unknown`
bucket rather than to an error. Excluding NULLs was considered and rejected: buckets that do not
sum to the headline total are how a dashboard under-reports without anyone noticing.
**PR:** n/a (B17) · **Requirement:** FR-30

### 2026-09-12 — Dashboard aggregates count only the current evaluation revision
**Context:** `findings` is append-only, so a scan corrected through `confirm-fields` keeps the
findings of every earlier revision. Summing the table counts that scan once per revision and keeps
reporting a violation that was withdrawn.
**Decision:** Every aggregate in `repositories/aggregates.py` is restricted to the findings of each
scan's **highest** revision, recovered by `MAX(revision)` per scan — the same definition of
"current" that `FindingRepository.current` uses.
**Alternatives:** A `is_current` flag on `findings` — rejected: a flag can be wrong, can be missed
on one write path, and needs a backfill; the ordering cannot be wrong. Deleting superseded findings
— rejected outright, it is what append-only forbids.
**Consequences:** Every dashboard query carries a subquery over `scan_evaluations`. Measured at
0.14 s for 50,000 findings, well inside FR-30's 1 s.
**PR:** n/a (B17) · **Requirement:** FR-30

### 2026-09-12 — The BIS applicability lists are data in `bis/`, a new top-level directory
**Context:** FR-29's applicability must be a deterministic table lookup, not retrieval. That table
had nowhere to live: `rulepacks/` is Legal Metrology rule text gated behind legal review
(`CLAUDE.md` §7), and a Python dict would put IS numbers and QCO categories where CLAUDE.md §3.2
says thresholds must never go.
**Decision:** A new top-level `bis/` directory holding `qco-crs-v1.yaml`, loaded through
`settings.BIS_LISTS_PATH`, validated and checksummed over its raw bytes the way a rule pack is. Its
version label is stamped on every applicability answer, alongside the id of the row that decided it.
**Alternatives:** Inside `rulepacks/` — rejected: it is not rule text and would drag BIS list edits
through a legal-review gate written for Legal Metrology clauses. A seeded `bis_applicability` table
— rejected: a schema change, and it would make a deterministic lookup depend on a database being
seeded rather than on a file somebody reviewed.
**Consequences:** One directory added to the `CLAUDE.md` §2 layout. A QCO amendment is a reviewed
data edit and needs no deploy, which is the same property NFR-06 gives rule packs. The lists carry
their own `as_of`, which becomes the freshness stamp on the answer.
**PR:** n/a (B20) · **Requirement:** FR-29

### 2026-09-12 — Sahayak's citations are post-validated, not requested
**Context:** FR-28 requires every claim to map to a retrieved chunk id. Asking a model for
citations produces citations; it does not produce *true* ones, and an answer that carries a
fabricated chunk id is more dangerous than one with no citation at all, because it looks sourced.
**Decision:** `services/bis/answer.py` validates after generation: every cited id must be one of
the chunks actually retrieved, and every number in the answer must appear in a cited chunk or in
the question. A failure of either is a refusal — the answer is withheld and the retrieved passages
are handed over instead. Requests for the technical content of a standard are refused *before*
retrieval runs.
**Alternatives:** Trusting the schema-constrained response — rejected: a schema constrains shape,
not truth. Stripping bad citations and publishing the rest — rejected: the sentence that cited a
fabricated source is the sentence that needed one.
**Consequences:** Five named refusal reasons rather than one flag, so refusals are countable —
`priced_standard_content` in particular is the IP boundary working, and the backend plan's release
gate asks for 10/10 on it. `confidence` reports mean reranker score across cited chunks and is null
without a reranker; it is a retrieval signal and never a probability that the answer is correct.
**PR:** n/a (B20) · **Requirement:** FR-28

### 2026-09-12 — The embedder and reranker runtimes stay out of `pyproject.toml`
**Context:** B19 needs BGE-M3 embeddings and a cross-encoder reranker. Both are heavy, both
download model weights on first use, and CI must never do that. The backend plan §4 lists them as
an outstanding dependency ask, and `CLAUDE.md` §7 makes adding one an ask rather than a decision.
**Decision:** `Embedder` and `Reranker` protocols with two adapters each — a lazily-imported
production adapter whose package is not declared, and a deterministic stand-in (`hashing`,
`overlap`) selected by config. The missing runtime raises a message naming the outstanding ask.
The `hashing` embedder refuses to be selected when `ENV=production`, checked against `ENV` rather
than trusting the setting, the way OTP echo is.
**Alternatives:** Declaring an optional `[bis]` extra now, as `[ocr]` was — rejected until the ask
is answered, since pinning model revisions is part of that ask and an unpinned revision silently
changes what the corpus was indexed with.
**Consequences:** Retrieval runs lexical-only until the runtimes are installed, which is a narrower
assistant rather than a broken one. `routers/deps.py` probes each once per process and falls back.
**PR:** n/a (B19) · **Requirement:** FR-28
### 2026-09-12 — Mobile mocks the backend at a transport seam rather than with MSW
**Context:** `03-implementation-plan.md` §P3.6 suggests mocking the API with MSW generated from the
OpenAPI schema so the app never waits on the backend. The backend is being built in parallel, so
the app needs dummy data for every screen from Stage 1.
**Decision:** One interface, `src/api/transport.ts`, with two implementations — fixtures and HTTP —
chosen by `EXPO_PUBLIC_API_MODE`. Hooks, screens and types are identical in both. The HTTP
transport was written first so the fixtures had to satisfy a real contract.
**Alternatives:** MSW — rejected because it needs polyfills under Hermes and has a history of
friction in React Native, and because it buys network-level interception the app does not need: the
seam is one function call wide. Hand-written stubs inside each hook — rejected because they are the
thing that never gets deleted.
**Consequences:** Cutover at Stage 13 is an env var plus deleting `src/api/mock/`, with no change
above the transport. The cost is that the mock is not exercised over real HTTP, so serialisation
mistakes — casing, date formats — will surface at cutover rather than before it. The mock's failure
modes are reachable from a dev panel in Settings, which is what keeps the degradation paths in
`01-architecture.md` §11 demonstrable.
**PR:** n/a (Stage 1) · **Requirement:** n/a

### 2026-09-12 — Session state lives in zustand, read synchronously, and composes the navigation
**Context:** Mode is an org-level attribute (`01-architecture.md` §3) and the two shells differ in
their tab bars, so navigation has to know the org's mode before the first paint. CLAUDE.md §5 says
server data belongs in TanStack Query, and `user`/`org` come from the server.
**Decision:** Tokens plus the user and org live in a zustand store that reads MMKV **synchronously**
in its initialiser — no `persist` middleware. Navigation composes from `tabsForMode(mode)`, and the
auth boundary is `Stack.Protected`. Settings moved off the tab bar to a root route behind a header
gear. Refresh-on-401 lives in the transport, single-flight, behind `src/api/auth-bridge.ts`.
**Alternatives:** The session as a TanStack query — rejected because TRD §5 has no "who am I"
endpoint, so it would be a query with nothing to fetch. zustand's `persist` — rejected because it
resolves `getItem` through `Promise.resolve`, so hydration lands after the first render and every
cold start flashes the login screen at a signed-in user. Redirecting from a mounted screen instead
of `Protected` — rejected because the screen mounts and fetches first. Settings as a fifth tab —
rejected because Android truncates labels at five.
**Consequences:** Two MMKV instances, so signing out cannot take preferences with it. The refresh
token sits in unencrypted MMKV until `expo-secure-store` is approved — recorded as flag 11 in
`04-frontend-plan.md`. One subscription in `AppProviders` empties the query cache whenever the org
id changes, which is the only thing stopping cached org-scoped data from crossing accounts on a
shared phone. Three contract gaps now need agreeing with the backend, all in `04-frontend-plan.md`:
no refresh endpoint, no session endpoint, and snake_case in TRD §5 against camelCase in the client.
**PR:** n/a (Stage 2) · **Requirement:** n/a

### 2026-09-12 — The printable marker is generated from OpenCV's codebook, at 15 px/mm
**Context:** FR-02 needs a scale reference of an exactly known physical size, and every millimetre
in every report is derived from it. Two things can go wrong silently: the tag's **bit pattern**
(the ArUco predefined dictionaries are fixed codebooks, not algorithms, so a hand-drawn tag is
simply not in the dictionary) and the **print scale** (a printer set to "fit to page" rescales
every downstream millimetre by a constant factor).
**Decision:** `mobile/scripts/make-marker-sheet.py` reads the tag from
`cv2.aruco.DICT_4X4_50` — the same library the backend's detector uses — and renders an A4 page at
exactly **15 px/mm**, which makes the 40 mm tag exactly 600 px, six cells of 100. The script fails
rather than writing a bad sheet if anything is printed inside the 5 mm quiet zone, if the footer
collides with the body, or if a detector round trip does not find exactly one marker, id 0, at
40 mm. The sheet carries its own 100 mm ruler and an ID-1 outline, so the print scale and the
user's card can both be checked against the paper itself.
**Alternatives:** Hardcoding a bit pattern from memory or from a web image — rejected outright; it
would not be in the dictionary and nothing in the app would say so. Rendering at 300 dpi — rejected
because 40 mm is then 472.44 px and the six cells do not divide evenly. Shipping the marker as an
in-app download — deferred: it needs `expo-asset` and a Metro `assetExts` change, and printing from
a laptop is the actual workflow (flag 13).
**Consequences:** Regenerating the sheet needs `opencv-contrib-python-headless` and `Pillow`, which
are script-time tools and in no manifest — the same arrangement as `make-sample-label.py`. The PDF
is a repo artefact, not bundled into the app; only the preview PNG ships. The sheet's constants are
now duplicated in spirit with the backend's `make_chart.py` (P0.1, unwritten): both must use
DICT_4X4_50 id 0 at 40.0 mm, and a disagreement would produce wrong measurements that no test on
either side would catch (flag 14). A verified-once ruler check is stored with the reference, so the
store never holds an unverified one.
**PR:** n/a (Stage 3) · **Requirement:** FR-02

### 2026-09-12 — Capture gates are a pure policy behind an evaluator seam, simulated until the plugin lands
**Context:** FR-01's four gates decide when the shutter is enabled, and the shutter rule is the
product: a blurred or angled frame yields a glyph height that is confidently wrong, which is worse
than one that is missing. The native ArUco frame processor that would supply real metrics is the
riskiest piece of the mobile work, and `03-implementation-plan.md` §P3.3 explicitly says not to let
it block the rest of the app.
**Decision:** `evaluateGates(metrics)` is pure and holds the whole policy, including the thresholds.
`GateEvaluator` is a one-method interface supplying `FrameMetrics`; today a simulation, later the
frame processor, with nothing above the seam changing. Tilt is **three-valued** — `pass | fail |
unknown` — because it is the angle to the marker's plane and there is no angle without a marker.
`useGates` takes no `active` flag: mounting the live view is the activation.
**Alternatives:** Computing gates inside the camera screen — rejected because the policy would then
be untestable without hardware, and hardware is exactly what CI does not have. Treating a missing
marker as a tilt *failure* — rejected because the instruction it produces ("hold flatter") sends the
user to fix the wrong thing. An `active` flag on the hook — rejected because the window between the
flag flipping and the effect running leaves the previous session's metrics in state, and the worst
case is a shutter enabled by a stale all-green report.
**Consequences:** The gate policy is fully tested with no device, including every threshold
boundary. What is **not** tested anywhere is the camera itself — preview, permissions,
`capturePhoto`, the disk write — so FR-01 is code-complete and not done until the device checklist
in `04-frontend-plan.md` Stage 4 has been walked (flag 15). Captures are written to the document
directory, not the cache, because FR-04 requires them to survive a force-close and the system
deletes caches under storage pressure. An abandoned capture stays on disk until Stage 6's queue
adopts it; losing an inspector's photograph is the worse of the two failures.
**PR:** n/a (Stage 4) · **Requirement:** FR-01

### 2026-09-12 — A scan's scale reference is frozen in the capture draft, and `qtyBasis` is derived

**Context:** FR-03's form sits between capture and scan creation, and two of its inputs can be got
wrong in ways no test downstream would notice. The saved scale reference is a *device setting* and
Settings is two taps from the form, so reading it at submit time lets the reference change between
the photograph and the record. Separately, `ProductProfile` carries both `netQuantity.unit` and
`qtyBasis`, which are not independent: Table-I is keyed on the declared quantity and only weight and
volume have one.
**Decision:** The capture draft (`src/store/draft.ts`) freezes the reference when the draft opens,
and `scan-context.tsx` reads it from there, never from the marker store. `qtyBasis` is **derived**
from the normalised unit in `units.ts` and never asked. The display-panel area becomes mandatory
exactly when the derived basis is Table-II. Mode B's "no location" is enforced by `geoForScan`
returning null whatever point it is handed, not by a screen-level conditional.
**Alternatives:** Reading the live marker store at submit — rejected: shoot against the 40 mm tag,
switch to the ID-1 card, submit, and every millimetre is wrong by a factor of 2.14 while the image
genuinely contains a marker and nothing looks wrong. Asking the operator for `qtyBasis` — rejected
because the form could then be told `kg` and `length_area_or_number` in one submission and the rules
engine would read the wrong table in silence. Guarding location in the screen only — rejected
because the permission may already be granted from a prior Mode A session on the same phone, so the
bug would be invisible: nothing prompts and nothing fails.
**Consequences:** The draft is in-memory only; Stage 6's queue owns durable scan state, so a process
death costs the typed context but never a photograph (`listCaptures()` still finds the files). Three
fields not in TRD §5 — `capturedAt`, `geo`, `district` — now ride on `POST /scans` and must be agreed
with the backend (flag 16). Unit normalisation is operator-typing only: reusing `normaliseUnit` on
OCR-extracted text would erase a whole class of label defect (flag 17). FR-03 is code-complete, not
done, until the Stage 5 device checklist has been walked.
**PR:** n/a (Stage 5) · **Requirement:** FR-03

### 2026-09-12 — The offline queue is a status column on the scan row, not an outbox table

**Context:** FR-04 requires a scan taken with no network to survive a force-close and upload later.
The stage brief called for "scans, assets and an outbox". It also has a subtler requirement hiding in
it: Stage 5's capture draft lived in memory, so a force-close between the shutter and the context form
lost the scale reference those photographs were measured against — and that is unrecoverable, because
the photographs themselves do not say what they were measured against.
**Decision:** Two tables, `scans` and `scan_assets`, and the scan's own `status` is the outbox — a row
that is `queued` and due is work to do. A row is written at the **first shutter press** (`captured`),
carrying the frozen reference, which retired the in-memory draft store entirely. The idempotency key
is minted there too, once per scan rather than per attempt. Every decision — legal transitions,
backoff, which scan is next — lives in a pure `transitions.ts`; the SQL holds none. `transition()`
throws on an illegal move. The runner works one scan at a time and re-requests upload targets on each
pass. `recoverInterrupted()` returns anything left `uploading` to `queued` on launch.
**Alternatives:** A table of pending operations alongside the status column — rejected as two answers
to one question: the day they disagree, the queue either skips an inspection or uploads one twice.
Keeping the in-memory draft alongside the row — rejected for the same reason, and because the volatile
half held the reference. Resuming a half-finished upload instead of restarting the pass — rejected
because it needs presigned URLs that have expired by the time the retry runs; the per-scan idempotency
key makes restarting both simpler and safer. Adding `expo-network` to check connectivity before trying
— rejected as a dependency that buys little: the only honest test of a connection is a request, and a
failed request is already a first-class path with a backoff behind it.
**Consequences:** `captured` now has a meaning in the state machine rather than being a dead enum
value, and FR-03's three mandatory fields became structurally unavoidable — `completeContext` is the
only path out of `captured`. Deleting a scan deliberately does **not** delete its photographs: a row
can be rebuilt from a photograph, never the reverse. A retry of `POST /scans` must return the existing
scan plus fresh upload URLs, which TRD §5 does not specify (flag 18). `Transport` grew an `upload`
method so a raw `PUT` to object storage never carries our `Authorization` header. FR-04 is
code-complete, not done, until the airplane-mode checklist has been walked on a device.
**PR:** n/a (Stage 6) · **Requirement:** FR-04

### 2026-09-12 — An unconfirmed field makes every verdict on the scan provisional, and an unknown stage is shown as unknown

**Context:** FR-06 asks for two things that look like presentation and are not. A progress screen needs
to report a pipeline stage, and `Scan` had no field for one. A low-confidence field needs a
confirmation sheet — but the reason is not politeness: `services/rules/evaluate()` is deterministic and
citable, so whatever value it is handed it will defend. Fed an MRP of `249.00` misread as `219.00`, it
produces a confident FAIL with a gazette citation against a pack that complies, which CLAUDE.md §3.4
names as the failure mode that kills the product.
**Decision:** `verdictsAreProvisional(result)` is the choke point: while any extraction is below 0.75
and not yet `source === 'human'`, the scan screen labels its summary provisional and makes the sheet
the primary action. A field confirmed by a human is never re-asked. `PipelineStage` was added to the
domain as `PipelineStage | null`, carrying the architecture's own S2–S10 names, and null renders as "the
server has not said" — `pipelineProgress` returns null rather than 0 for it. Crops are computed as an
image transform in `crop.ts`, shared with Stage 8's overlay, not produced as files. Degradation copy
lives in named functions, where `no_marker` and `reduced_extraction` are *degraded but final* and only
an unanswered field is provisional. The queue runner now polls `processing` rows to completion.
**Alternatives:** Inferring the stage from elapsed time — rejected: a bar that advances on a timer looks
identical whether the worker is progressing or wedged on OCR, and the wedged case is the only one the
screen is needed for. Cropping with `expo-image-manipulator` — rejected: a JPEG per field, written
asynchronously and cleaned up later, to show pixels a transform already shows synchronously; it would
also behave differently on a bundled fixture and a presigned URL. Down-rating the LLM fields in the
`llm-unavailable` scenario instead of omitting them — rejected because they would then appear in the
confirmation sheet as misreads, when they were never read at all. Letting the sheet treat an unedited
value as "nothing to do" — rejected: sending it is what records `source=human`, and skipping it would
leave the scan permanently provisional.
**Consequences:** `Scan` gained a field TRD §5 does not define (flag 19). `src/api/asset-source.ts` now
mediates asset URIs so no screen imports a fixture, and its `fixture://` branch is the only thing to
delete at Stage 13. The measurement-correction path has no recompute, which is an asymmetry worth
settling before Stage 8 invites a user to question a millimetre (flag 20). Stage 6's queue gained its
missing half: before this, a scan handed to the server stayed `processing` locally forever. FR-06 is
code-complete, not done, until the Stage 7 device checklist has been walked.
**PR:** n/a (Stage 7) · **Requirement:** FR-06

### 2026-09-12 — One inverted transform serves both the outlines and the taps, and a hash of a derived image is not evidence

**Context:** FR-05 wants a rectified label with tappable bounding boxes that stay aligned through pinch
and zoom, a grouped list that keeps the four verdicts apart, and a citation readable without leaving
the screen. Two of those three fail quietly rather than loudly. A box drawn two hundred pixels from the
text it names is still a box; a tap that resolves to the wrong finding still opens a plausible card. And
Mode A's evidence panel wants an image hash, for which the only hash the fixtures had was the rectified
image's.
**Decision:** `features/findings/viewport.ts` names three coordinate spaces — image pixels, canvas
(image × fit), viewport — and owns every conversion between them. The overlay places a rectangle with
`boxOnCanvas`; a tap is resolved by `viewportToImage` composed with `hitTest`, which is the same
transform inverted, and the round-trip is pinned over every region of the fixture label at 20 px/mm.
`hitTest` picks the **smallest** box containing the point, because regions nest and the smaller box is
always the more specific claim; an exact tie goes to the first candidate, and the caller hands it
`findingsInDisplayOrder`, so a tap on a box shared by a PASS and a FAIL opens the FAIL. `groupFindings`
returns one entry per verdict always, and the module deliberately exports no helper that merges FAIL
with BORDERLINE. `scaleBarLength` returns null when `pxPerMm` is null, so no ruler is drawn over an
image of unknown scale. `rawImageHash` reads only the `raw` asset and returns null otherwise.
`editingLocked` is Mode A plus `reportIssuedAt !== null`; remediation is gated on Mode B.
**Alternatives:** Driving the transform with Reanimated shared values on the UI thread — rejected: the
clamping and the focal-point correction would have had to exist as worklets *and* as plain functions for
`focusOn` and the tap, which is the duplicated-arithmetic bug this stage is organised to prevent. Every
gesture is `.runOnJS(true)` instead, and the overlay is memoised so a drag restyles one view rather than
thirteen rectangles. A ref mirroring the transform so gesture callbacks could read it mid-pan — written,
then rejected when the compiler's `react-hooks/refs` rule objected; functional state updates are both
accepted and more correct, since the updater always receives the live value. Resolving taps with
`onPress` on each SVG `Rect` — rejected: the answer would then depend on paint order, which depends on
the order the server serialised its rows. Letting a box near an edge be centred by allowing the label to
be panned past the pane — rejected: "you cannot lose the image" is worth more than "focus always
centres", and the box still arrives fully visible. Showing the rectified image's SHA-256 in the evidence
panel — rejected outright: it verifies a computation rather than a photograph, and would look exactly as
reassuring while verifying nothing.
**Consequences:** `FindingsResult` gained `findingsSha256` and `Scan` gained `reportIssuedAt`, neither
in TRD §5 (flags 21 and 22); the second is what Stage 9 will set. The hero fixture gained a `raw` asset
whose URI resolves to nothing, because the raw frame is not bundled and nothing displays it. A box near
the edge of a label focuses off-centre, which is correct and is documented on `focusOn` so it is not
filed as a bug. Pinch smoothness is now a device question rather than a settled one. FR-05 is
code-complete, not done, until the Stage 8 device checklist has been walked.
**PR:** n/a (Stage 8) · **Requirement:** FR-05

### 2026-09-12 — A listing check cannot receive a measurement, by signature
**Context:** FR-10 runs the rules engine over marketplace listing text. A listing is text: no
photograph, no marker, no homography, no millimetre. Every metric and geometry rule is
unanswerable, and a PASS there would tell a seller their font size is compliant on the strength of
the words "500 g" in a product description.
**Decision:** `services/listings.check_listing` takes **no measurements parameter**. It calls
`evaluate()` with an empty sequence, which is the documented no-marker case. A test asserts the
signature as well as the verdicts across a 50-row run.
**Alternatives:** Passing an empty list at each call site and trusting review — rejected: that is a
rule that holds until someone adds a keyword argument in a hurry. A runtime assertion over the
findings — kept as the test, not as production code: the structural guarantee makes it
unreachable, and an assertion that cannot fire is an assertion that rots.
**Consequences:** `physical_rule_ids()` walks nested `then`/`rules` bodies, because a metric rule
inside a `conditional` is still a metric rule and a top-level `kind` check would miss it. The
endpoint's response carries `"scale": "none"` so a client cannot render these verdicts as though
they came from a measured photograph. Regex-only extraction on this path: the LLM layer exists to
repair OCR noise, and a listing has none.
**PR:** n/a (B21) · **Requirement:** FR-10

### 2026-09-12 — The bulk listing check is gated on PRODUCT_READ, not PRODUCT_WRITE
**Context:** FR-10 is the flagship Mode B feature and needed a permission. `PRODUCT_WRITE` is held
by inspector and admin; `analyst` — the desk role an industry org actually staffs — has only
`PRODUCT_READ`.
**Decision:** `PRODUCT_READ`. The check persists nothing, creates nothing, and reads only text the
caller supplied in the request body.
**Alternatives:** A new `LISTING_CHECK` permission — the most honest modelling, and rejected here
because the role matrix in `tests/test_auth.py` is deliberately written out rather than derived,
and extending it is a change to the auth specification that should be made on its own and reviewed
as one, not folded into a feature. `PRODUCT_WRITE` — rejected: it locks the flagship Mode B feature
away from the role that exists to run it, for a call that leaves no trace.
**Consequences:** A viewer can run a bulk check. That is a compute cost, which B23's rate limits
bound, rather than an access-control concern — there is no data of anyone else's to reach. Revisit
if an org asks to restrict it, at which point the new permission is the right change.
**PR:** n/a (B21) · **Requirement:** FR-10

### 2026-09-12 — Rate limiting fails open, and the in-memory backend is refused in production
**Context:** NFR-01 and architecture §10 want limits per org and per IP. Two failure modes had to
be chosen deliberately: what happens when the limiter's own store is unreachable, and what happens
when the cheap backend reaches production.
**Decision:** An unreachable Redis **admits** the request and logs a warning. The in-memory backend
**raises** when `ENV` is production, checked against `ENV` rather than trusting the setting.
**Alternatives:** Failing closed on a backend outage — rejected: a rate limiter that takes the API
down when Redis blinks has converted a partial outage into a total one, and the actual abuse risk
here is an inspector's phone retrying an upload, which a hard fail does not protect against.
Letting the memory backend run in production — rejected: N workers each admit the full ceiling, so
the configured limit is silently multiplied by the worker count and nobody finds out until load.
**Consequences:** Fixed window, not a sliding log: it admits up to twice the limit across a
boundary, which is the right trade for stopping a runaway client rather than metering billing. An
unauthenticated flood is charged to its address and never to the org id it claimed, or anyone could
exhaust a tenant's quota by sending their id. `conftest.py` disables the limiter for every suite
except `test_hardening.py`, because the whole test run comes from one client address.
**PR:** n/a (B23) · **Requirement:** NFR-01

### 2026-09-12 — E1's truth file names a region per line, not just a height
**Context:** E1 compares a measured cap height against a caliper-measured one. Something has to
decide which measured glyph belongs to which truth height.
**Decision:** `truth.csv` carries the row's region in the rectified plane (`x_mm`, `y_mm`, `w_mm`,
`h_mm`) and the script measures inside it. Required, not optional.
**Alternatives:** Assigning each measurement to the nearest truth value — rejected, and this is the
important one: it flatters the result exactly where accuracy matters. A 0.8 mm line measured at
0.95 mm would be scored against 1.0 mm and recorded as a 0.05 mm error instead of a 0.15 mm one,
and P0's decision gate is read off that number.
**Consequences:** Building the E1 corpus costs one more column, which a generated chart knows by
construction and a real label needs a ruler once. Captures the script cannot measure — no marker,
unreadable file — are reported with a count and a reason rather than dropped from the denominator.
**PR:** n/a (B22) · **Requirement:** FR-23
