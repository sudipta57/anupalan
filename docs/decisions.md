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
`05-frontend-plan.md`. One subscription in `AppProviders` empties the query cache whenever the org
id changes, which is the only thing stopping cached org-scoped data from crossing accounts on a
shared phone. Three contract gaps now need agreeing with the backend, all in `05-frontend-plan.md`:
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
in `05-frontend-plan.md` Stage 4 has been walked (flag 15). Captures are written to the document
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
### 2026-09-12 — A provisional verdict blocks a report rather than warning on one, and the mock writes real files

**Context:** FR-08 asks for PDF and DOCX generated from a completed scan and handed to the share
sheet. Two questions sat underneath it. First: what should happen when the scan's verdicts are still
provisional? Stage 7 already makes an unconfirmed low-confidence field mark every verdict on a scan
provisional, and Stage 8's findings screen carries that as a banner. Second: what should the mock hand
to the share sheet, given that bundling a `.pdf` needs a `metro.config.js` asset extension and
approval (flag 13)?
**Decision:** `blocksReport` refuses. A findings *screen* may show provisional verdicts behind a
caveat, because the reader is holding the phone and the next scan replaces it; a PDF leaves the
device, embeds a findings hash, quotes gazette citations beside a millimetre and cannot be retracted
from an inbox, so a report over a misread MRP is CLAUDE.md §3.4's failure mode made permanent and
distributable. A **degraded-but-final** run is not blocked: `01-architecture.md` §11 issues those
flagged, and withholding one would leave an inspector with no record of an inspection they made — so
no-marker and reduced-extraction warn and travel with the document. Generation is asynchronous:
`Report` gained `status`, `formats`, `requestedAt`, `generatedAt | null` and `error | null`, and the
app polls `GET /reports/{id}`. `Transport` grew a `download`, the mirror of Stage 6's `upload`, because
a share sheet needs a file rather than an https URL. `scripts/make-sample-report.py` generates a real
PDF 1.4 with the annotated label embedded as a JPEG and a real OOXML package whose findings table is a
`<w:tbl>`, emitted as base64 and written by `File.write(…, { encoding: 'base64' })`.
**Alternatives:** Generating the report with a disabled button and a caption — rejected: a control
that looks available and is not teaches people to hunt for a way around it, and the explanation
belongs where the decision is made. Blocking degraded runs too — rejected as above; it confuses "a
question is unanswered" with "a limitation is stated". A POST that blocks until the PDF is rendered —
rejected: it ties a share button to a render that takes seconds and can fail, with nothing to show
either way. Resolving the mock's download without writing bytes — rejected: "both files open in an
external viewer" would then pass in testing and fail in front of a judge. Bundling the sample files as
assets — rejected for now: it needs a `metro.config.js` change and approval, and base64 costs 47 KB in
a folder that is deleted at Stage 13 anyway. Offering JSON in the share sheet — rejected: it is a real
report format whose home is the API, and in a share sheet it invites sending a machine artefact to a
trader who cannot read it.
**Consequences:** Two contract additions TRD §5 does not have (flag 23), and a `report-failed` mock
scenario beyond §11's table, because S10 can fail on its own and the screen must handle it. Report
files land in the cache rather than the document directory — the phone is not their archive — under a
deterministic filename, so re-sharing overwrites instead of accumulating `report(1).pdf`. The report
screen is reachable only from the findings screen, so nobody sends a document over verdicts they never
opened. FR-08 is code-complete, not done, until the Stage 9 device checklist has been walked — nothing
in a test runner can open a PDF.
**PR:** n/a (Stage 9) · **Requirement:** FR-08

### 2026-09-12 — The verdict filter is single-select, and the fixture now contains a scan that can prove it

**Context:** FR-09 filters past scans by date, product, verdict and (Mode A) location. A verdict
filter is the easiest place in the entire app to collapse BORDERLINE into FAIL, and the collapse does
not look like a bug: a "problems" filter returning `fail > 0 || borderline > 0` gives a longer list in
which every scan really does have something on it. Building the filter surfaced two further things —
that the 220-scan fixture could not distinguish the merged filter from the correct one, and that the
hero scan was internally inconsistent.
**Decision:** The filter is single-select and `matchesVerdict` is a switch that reads exactly one
field of `FindingsSummary`; the module deliberately exports no helper taking a set of verdicts, and
the mock imports the same predicate so fixture data and app cannot disagree about what "has a FAIL"
means. `buildSummary` gained a **borderline-without-failure** bucket: every borderline in the seeded
set previously sat beside a failure, so a merged filter would have returned an identical list and
passed every test written against that data. The hero scan became an enforcement inspection — it was
owned by the industry org while recorded by the enforcement inspector (a cross-org row CLAUDE.md §3.7
makes impossible) and carried a `geo` and `district` that §10 says Mode B never collects, contradicting
`geoForScan`. One `ScanList` serves both tabs, and `toQuery` drops `district` for Mode B where the
request is built rather than only hiding the control.
**Alternatives:** A multi-select verdict filter — rejected: it lets someone ask for "FAIL and
BORDERLINE" and read the answer as a count of problems, which is the forbidden collapse wearing a
filter's clothes. A headline verdict per row instead of four counts — rejected: it needs a ranking
rule, and any such rule is one step from "this scan failed" on a pack whose only mark was a
BORDERLINE. Filtering client-side over the cached pages — rejected: the cost then grows with the
archive, and the 500 ms criterion would quietly become a function of how long someone has used the
app. `Date.now()` for the date presets — rejected: impure in a render, and React's own rule forbids
it; `now` is a parameter everywhere. Answering a reversed date range with an empty list — rejected:
the user asked a clear question and an empty list answers a different one, so the range is swapped.
**Consequences:** `ScanListItem` gained a `productId` and `ListScansQuery` a `q` (flags 24 and 25).
Mode B's "filter by brand and SKU" is deferred: neither field exists on `ProductProfile`, and
inventing them for a filter is the wrong order of work — SKUs become real in Stage 12. The filter
measures **0.020 ms per pass** over all 220 seeded scans, timed in bulk because one pass lands under
the millisecond clock; what remains on a device is the list render, bounded by `getItemLayout` and
confirmed only by the checklist.
**PR:** n/a (Stage 10) · **Requirement:** FR-09

### 2026-09-12 — An uncited answer is not shown as an answer, and `unclear` is not `no`

**Context:** FR-07 is the SIH26107 half: a BIS and Indian Standards assistant, with chat in English
and Hindi, source chips that open the cited page, and a "check BIS requirement" entry point from a
completed scan. Two of its three outcomes are refusals designed as features. Building it surfaced the
one thing a client can verify about a citation and the one place the applicability answer can be
quietly inverted.

**Decision:** A citation whose URL cannot be placed on an official host (`OFFICIAL_HOSTS` — BIS,
manakonline, crsbis, eGazette, DoCA, and subdomains, `https` only) is **not rendered**, and an
`answered` response left with no showable citation is **presented as not-found with its model prose
suppressed entirely**. Separately, `qcoApplicable` maps to three stances, not two: every affirmative
row on the applicability screen — the certification route, the standards list, the plain-language
heading — is gated on `isConclusive`, and `scheme: 'none'` on an `unclear` record is treated as the
absence of a claim rather than the claim "no route applies". The fixture set gained a deliberately
fabricated citation (`ans_fabricated`, on a `.com` reseller) so the guard is proved rather than
asserted, and the freshness stamp gained an `unknown` tier for a date that will not parse or sits in
the future.

**Alternatives:** Rendering `answer.citations` directly and trusting the retrieval layer — rejected:
a fabricated source does not make an answer worse, it makes it *more convincing*, and it is the part
of a response a reader will not check. Showing the prose under a not-found heading when the downgrade
fires — rejected: that is the caveat nobody reads above the answer everybody does. Validating the URL
with `URL` — rejected: React Native's polyfill has moved between releases, and this should not be the
one thing in the app that behaves differently on Hermes than in the test runner; a regex host parser
is used instead. Upgrading an `http` citation to `https` — rejected: a link any intermediary could
have rewritten is not evidence, and promoting it hides that it arrived downgraded. Mapping
`QcoApplicable` to a boolean "needs certification" — rejected: this is CLAUDE.md §3.4's collapse
running the other way and doing more damage, since a wrong FAIL gets disputed while a wrong clearance
gets believed. Treating an unparseable `asOf` as zero days old — rejected: an answer with no
provenance in time is worse than an old one, because an old stamp can be weighed. Caching answers by
question in TanStack Query — rejected: asking the same question twice is what people do when they
doubt the first answer, and a cache hit would replay it; the transcript is local UI state and is not
persisted at all. `Date.now()` in the render for the freshness tier — rejected on the same grounds as
Stage 10's date presets, and the lint rule caught it: an answer turn is stamped `receivedAt` on
arrival and the BIS screen uses the query's `dataUpdatedAt`.

**Consequences:** `expo-web-browser` moved from installed-but-unused to used, for in-app Custom Tabs
with a `Linking` fallback — a dead source chip is the wrong thing to ship, since the chip is the app's
offer to be checked. The mock's answer routing was rewritten from word-overlap scoring, which made the
two cases a demo most needs the hardest to reach, and its `/bis/applicability` route no longer falls
back to the atta record for an unknown product — that answered a question about one product with
another's applicability. Four flags added: the host allowlist now exists on both sides and must not
drift (26, the same hazard as flag 14), the backend must genuinely emit `unclear` rather than
defaulting to `no` (27), the `required` and inconsistent-record branches have no fixture reachable
from a scan because none of the four fixture products is honestly QCO-covered (28), and `lang` assumes
the server answers in the language asked for rather than the client translating a cited answer
afterwards (29).
**PR:** n/a (Stage 11) · **Requirement:** FR-07

### 2026-09-12 — A truncated bulk check is refused, and a measured verdict on a listing is rejected client-side

**Context:** FR-10 is Mode B's bulk listing check: paste or upload up to fifty marketplace URLs or
lines of listing copy, run presence and format rules, mark every metric rule NOT_ASSESSABLE because a
listing carries no physical scale. Its acceptance criterion has two halves — a count, and a
prohibition — and the prohibition is the one the client can get wrong without anyone noticing.

**Decision:** More than fifty rows **blocks submission** and names the excess, rather than checking
the first fifty. And `features/bulk/guard.ts` checks what the server returned: any metric rule whose
verdict is PASS, FAIL **or** BORDERLINE is forced to `NOT_ASSESSABLE`, its `observed` value cleared,
the row and batch summaries recomputed, and the correction **stated in a banner** rather than applied
silently. The single list of metric rule ids moved out of the mock transport into
`features/bulk/metric-rules.ts`, and the fixture layer gained `buildViolatingCheck` plus a
`listing-metric-verdict` dev scenario that emits `PASS · 4.2 mm` on the Rule 9 family on purpose.

**Alternatives:** Truncating at fifty with a notice — rejected: the notice is read once and the table
is read for an hour, and the dropped row is the one that was non-compliant; the result has been mailed
on by the time anyone notices. Trusting the backend and rendering `findings` as they arrive — rejected:
a metric PASS with a millimetre value and a gazette citation, from a source containing no millimetres,
is the most convincing wrong output this system can produce, and the realistic cause is not a bug but
a well-meant Rule 9 path over the listing's own photograph landing three layers from anyone thinking
about CLAUDE.md §3.3. Treating BORDERLINE as the safe middle — rejected: it presupposes a measurement,
so it would have been the one verdict that sounds cautious and still gets through. Silently sanitising
without the banner — rejected: it leaves the server emitting a forbidden verdict indefinitely, and the
next surface to render it may not have a guard. Counting NOT_ASSESSABLE against a row — rejected:
every row has five by construction, so it would rank every row at the top and rank none of them.
Reusing `Finding` for a listing — rejected: `scanId`, `bbox` and `band` would be structurally present
and permanently null, which invites an empty evidence panel and a reader wondering what is missing;
`ListingFinding` carries a `notAssessableReason` instead. One CSV row per listing — rejected: the
findings would have to be flattened into a cell, and the first thing anyone does with the file is
filter on a rule id.

**Consequences:** `ListingCheck`, `ListingRowResult`, `ListingFinding`, `ListingSourceKind` and
`NotAssessableReason` added to the domain; `POST /v1/listings/check` assumed and flagged as a contract
gap (flag 30) since TRD §5 has no listing endpoint at all. `api/mock/index.ts` now imports
`METRIC_RULE_IDS` rather than holding its own literal — the same narrowing it already does for
`matchesVerdict`. `Field` gained a narrow `inputStyle` passthrough for the paste box. The metric-rule
list is now remembered in two places that must not drift, which is flag 14's hazard for the third time
and argues for a `metric: true` flag on the rule in the pack (flag 31). CSV file picking is deferred
for want of `expo-document-picker` (flag 32); paste takes CSV content and covers the realistic phone
workflow. Every CSV field is quoted unconditionally and a leading `=`, `+`, `-` or `@` is
apostrophe-guarded, because listing copy is attacker-influenced text and spreadsheets execute formulas.
**PR:** n/a (Stage 12) · **Requirement:** FR-10

### 2026-09-12 — The mock is excluded from a live bundle at resolution time, and the exclusion is measured

**Context:** Stage 13's acceptance includes "the mock transport is gone from the release build".
Before this change it was not. Three screens imported `@/api/mock` statically for the fixture OTP and
the account switcher; all three were `__DEV__`-gated at render, which keeps a panel off a user's
screen and does nothing about what is bundled. A production export contained the whole fixture graph —
220 seeded scans, the base64 sample PDF and DOCX, every gazette citation — as unreachable code that
still costs cold-start parse time against NFR-02's three-second budget and still ships a working
offline fake of a compliance tool inside the real one.

**Decision:** The fixture layer is reached only through conditional `require`s in
`src/api/transport.ts` and a new `src/api/dev.ts`, which exposes a `DevBridge | null` to the three
screens that wanted conveniences. The exclusion itself happens in a new `metro.config.js`, which
resolves anything under `src/api/mock/` to `scripts/empty-module.js` when
`EXPO_PUBLIC_API_MODE=live`. `npm run verify:bundle` exports a production bundle in live mode and
fails if any of five mock-only sentinel strings appears in it. Separately: Hindi was completed (145
strings, 586 of 586 keys) with completeness, orphan and copy-of-English regression tests; every
rendered colour pair in both themes is asserted at 4.5:1; and `src/lib/startup.ts` instruments the
JS-side cold start.

**Alternatives:** Relying on the conditional `require` alone — **rejected by measurement, not by
argument.** `EXPO_PUBLIC_API_MODE` is inlined to a literal by `babel-preset-expo`, so the branch is
statically dead in a live build, and the reasonable expectation is that the `require` goes with it.
Metro resolves `require()` targets while building the module graph, *before* dead-code elimination,
so it does not. `verify:bundle` failed on its first run and is the only reason this is known.
Deleting the fixtures folder now, as the plan's wording suggests — rejected: there is no deployed
backend, so it would leave the app with no data source in the only mode it can run in. Returning
empty stubs from `dev.ts` instead of `null` — rejected: `null` forces a caller to handle the state a
release build is actually in, and the panels then keep compiling after the folder is deleted. Using
the 3:1 large-text contrast allowance for captions — rejected: `caption` is 12 px and `mono` is 13 px,
and both carry rule ids, millimetre readings and hashes; none of that is large text. Growing `Chip`
to 44 px — rejected: it would destroy the one property a chip has, which is fitting eight of them in
a filter row; the touch area grew via `hitSlop` instead, sized to the `gap` between chips so
neighbours cannot steal each other's taps. Reporting `Date.now()` from the startup instrument when
`__BUNDLE_START_TIME__` is absent — rejected: it would report a cold start of zero, which is the kind
of number that reaches a slide.

**Consequences:** `metro.config.js` is now load-bearing for NFR-07 and must keep calling through to
the upstream resolver (flag 34). Measured effect: a production Android bundle is **4.85 MB in mock
mode and 4.76 MB in live mode**, so 92 KB of fixtures are genuinely gone. The light and dark palettes
no longer share a `textSubtle`, which is correct — one grey cannot sit 4.5:1 from both a near-white
and a near-black ground. `Field` gained nothing here; `Chip` and `SegmentedControl` gained `hitSlop`.
Two Stage 13 items remain blocked and are recorded as such rather than claimed: the cutover needs a
deployed backend publishing OpenAPI, and the cold-start figure needs the EAS build on a physical 4 GB
phone. `__tests__/i18n.test.ts` now fails because its fallback case used a real app key as a
stand-in for a missing one; it has been left untouched per CLAUDE.md §6 and needs a decision (flag 33).
**PR:** n/a (Stage 13) · **Requirement:** NFR-02, NFR-07, NFR-08

---

## 2026-09-12 — The backend gaps close before the app is wired, and the app computes its own image hashes

**Context:** Both halves are built — the app through Stage 12, the backend through B16 — and were
read against each other for the first time. Eight of the app's fifteen API calls have a server. The
audit is `06-wiring-contract.md`; what follows is the two decisions it forced and one it answered.

**Decision:** **Nothing is wired until six backend changes land** (W1–W6 in that document), rather
than wiring the eight live endpoints now behind adapters. The deciding case is a single missing
field. `GET /v1/scans/{id}/findings` does not return `extractions`, and the app's
`verdictsAreProvisional` is `result.extractions.some(needsConfirmation)` — the predicate
`blocksReport` uses to refuse a PDF while any extracted field sits below the 0.75 confidence
threshold. An adapter has two choices and both are wrong: default the field to `[]` and `.some()`
returns false, so **the report gate opens for every scan** and the app issues reports over
unverified readings with no caveat on them; leave it absent and the screen crashes. FR-06's
confirmation sheet is empty either way, so the one mechanism for correcting a bad read becomes
unreachable. The backend already computes those rows and discards them, which makes this a response
change rather than new work — and it is why it is the first card rather than the easiest.

**Decision:** **The app computes a SHA-256 per asset**, with `expo-crypto` approved for it — the
first dependency added since Stage 11. `POST /v1/scans` requires `assets[].sha256` before the upload,
and the worker verifies the stored object against it and fails the scan on a mismatch. The app had no
hashing of any kind; it only ever displayed a hash the server computed.

**Decision:** **The app converts snake_case to camelCase, with explicit per-endpoint adapters.**

**Alternatives:** *Making `sha256` optional at create and having the worker compute it from the
stored object* — rejected. It needs no dependency and no on-device hashing of a 4 MB JPEG, and it is
the cheaper path, but it converts a claim the server can check into a record of whatever arrived: a
corrupted or truncated upload stops being detectable, and `01-architecture.md` §10 wants the hash of
the bytes that were captured, not of the bytes that survived the network. *A generic deep key
transform at the transport seam* — rejected, and this one would have been a quiet disaster: it would
rewrite `profile.is_imported` and `profile.net_qty_in_g_or_ml`, whose names are the **rule pack's**
contract rather than the API's, so a pack would stop matching its own fields; and it would rewrite the
presigned `headers` map, where `x-amz-*` must survive byte for byte or every upload fails its
signature. *Adding `no_marker` to the app's `ScanStatus` union* — rejected: §11 calls a no-marker run
degraded *but final*, so it maps to `complete` plus the existing `no_marker` issue, and the
alternative would add a third terminal state to every branch that checks for one. *Asking the backend
for an `issues` array* — rejected: the app derives it from the status, `reduced_extraction` and the
extraction confidences, and a second source of truth for the same three facts would drift.

**Consequences:** `district` turns out not to exist anywhere in the backend — not in the create body,
not in the scan response, not as a column — so the Mode A history filter, the history row and FR-30's
district rollup are all blocked on one migration, which CLAUDE.md §7 says needs agreement and which is
cheaper now than after the table has rows. `extra="forbid"` on every request schema means a
mismatched key is a **422 rather than a dropped field**, which turns the casing question from
cosmetic into blocking: the app's current refresh body would 422, and `live-transport.ts` reads any
non-ok refresh as a rejected token, so users would be signed out every time an access token expired.
Three flags are answered: refresh exists (8), `GET /v1/auth/me` exists and should be adopted for
session restore (9), and the backend does omit inapplicable rules rather than inventing a fifth
verdict (6) — though the app currently discards the `not_applicable_rule_ids` it sends, which is the
app's gap to close. `expo-crypto` is native, so it installs at cutover with everything else that needs
a dev-client rebuild rather than now. Seven calls still have no server; Sahayak, BIS applicability and
the bulk listing check are B19–B21, so Stages 11 and 12 stay on fixtures and `src/api/mock/` is
deleted at the end of the sequence rather than with the first endpoint.
**PR:** n/a · **Requirement:** FR-05, FR-06, FR-08, FR-09, FR-20, NFR-07

---

## 2026-09-12 — The API surface the app was written against now exists, and one report decision is deferred

**Context:** With `main` merged, eight of the mobile client's fifteen calls had a server and four
endpoints did not exist at all. Two of the gaps were not missing features but wrong behaviour: the
findings response omitted `extractions`, which is what the client reads to decide whether a verdict
may be reported, and `ScanOut` omitted the `profile`, `district` and `org_id` its screens read.
`docs/06-wiring-contract.md` §8 records the whole of what was built.

**Decision:** Six work packages, no migration and no new dependency. The findings response now
carries `extractions`, `measurements` and the stored `findings_sha256`; `ScanOut` carries
`profile`, `geo`, `district`, `org_id` and `user_id`, and `ScanCreateIn` finally accepts the
`district` its column has been waiting for; `GET /v1/scans` and `GET /v1/products` were written with
keyset cursor pagination; and reports got both endpoints. **Report generation is synchronous for
now**, because a `pending` status needs a column and a migration needs agreement (CLAUDE.md §7).

**Alternatives:** *Recomputing `findings_sha256` in the findings handler* — rejected: it is already a
stored column written when the verdicts were issued, and a second implementation of the same claim
would disagree with the report the first time either changed. *Making `finding_id` required* —
rejected by a test failure that turned out to be right: the bulk listing check shares `FindingOut`
and judges text that was never photographed, so there is no evidence row to name, and a fabricated
id would make two very different things look alike. *An `issues` array on the scan* — rejected: the
client derives it from the status, `reduced_extraction` and the extraction confidences, and a second
source of truth for the same three facts would drift. *Offset pagination* — rejected: it repeats and
skips rows when anything is inserted mid-walk, which in an evidence archive is not cosmetic.
*Deriving `district` from `geo_lat`/`geo_lon`* — rejected: a boundary file of unknown vintage
attributing an inspection to the wrong district is worse than one that admits it does not know, and
Mode B sends no coordinates at all. *Adding `reports.status` and shipping async now* — deferred
rather than rejected; it is the right shape and it needs a migration signed off.

**Consequences:** All fifteen client calls now have a server, across twenty `/v1` paths. 682 tests
pass, 64 of them new; `ruff` and `mypy app/services` clean. The verdict filter's guard is proved
rather than asserted — a mutation that widened `FAIL` to include `BORDERLINE` fails three tests,
because the seeded archive contains one scan that is borderline **without** failing; without that
row the correct and the collapsed implementations are indistinguishable, and the wrong one looks
better. `GET /v1/scans` takes a `tz_offset_minutes`, because `from` and `to` are the user's calendar
days and UTC midnight files an Indian inspector's early-morning scans under yesterday. Three things
stay open and are listed in `06-wiring-contract.md` §8: async reports, `remediation` on a finding
(neither a column nor in the rule pack, so it needs a decision either way), and `POST /v1/products`.
The bulk listing check keeps its `/v1/products/listings/check` path and `{csv}` body; the app will
adapt rather than the backend growing a second route for one client.
**PR:** n/a · **Requirement:** FR-05, FR-06, FR-08, FR-09, FR-27, TRD §5

---

## 2026-09-12 — The app talks to the real API, through an explicit wire→domain layer

**Context:** With the backend complete, the app had to stop returning fixtures and start mapping the
server's shapes. The API is snake_case and the app is camelCase, but the differences were never only
cosmetic: the status vocabularies differ, the marker names differ, several fields the app treated as
certain are nullable on the wire, and every request schema sets `extra="forbid"` — so a mismatched
key is a 422 rather than a dropped field.

**Decision:** `src/api/adapters/`, one module per resource, each holding the wire type beside the
function that maps it. Every endpoint returns a domain type and no wire type escapes the folder. The
mock now renders its fixtures outward through `src/api/mock/to-wire.ts` rather than returning
finished domain objects. `expo-crypto` was added and the queue hashes each photograph on the device
before `POST /v1/scans`.

**Alternatives:** *A recursive snake→camel transformer at the transport seam* — rejected, and it
would have failed in a way nobody would have traced: it rewrites `profile.is_imported` and
`profile.net_qty_in_g_or_ml`, whose names are the **rule pack's** contract rather than the API's, so a
pack would stop matching its own fields; and it rewrites the presigned `headers` map, where `x-amz-*`
must survive byte for byte or every upload fails its signature. *Leaving the mock returning domain
objects* — rejected: it would bypass the adapters entirely, so mock mode would exercise a different
code path from live mode and every fixture-based test would leave the mapping untested. *Deleting the
mock at the cutover, as Stage 13 planned* — deferred: it now mirrors the wire faithfully, six test
files depend on it, and deleting it is a separate decision rather than a side effect of wiring.
*Deriving a Sahayak answer's outcome from whether citations came back* — rejected once the backend's
five refusal reasons were read: a not-found answer carries a link to the official page, so counting
citations classifies it as answered and publishes prose no source supports.

**Consequences:** A live sign-out bug was found and fixed. `live-transport.ts` sent `{refreshToken}`
where `RefreshIn` wants `{refresh}`; with `extra="forbid"` that body is a 422, and the transport
treated any failed refresh as a dead session — so users would have been signed out every time an
access token expired. The field name is corrected and **only a 401 now ends a session**;
`backend/tests/test_mobile_contract.py` pins the spelling of every request body from the server's
side, including the case that a camelCase verify body is refused. Three domain types were loosened to
what the server can actually say: `Org.state` and `Org.createdAt` are nullable (the session endpoint
publishes neither), `Measurement.uncertaintyMm` is nullable (null is "could not be established",
which is not zero), and `FindingsResult` gained `reducedExtraction` and `notApplicableRuleIds`. Two
tests were changed because they asserted behaviour the fixture layer had invented: a freshly created
scan does not carry `no_marker` (the server reports it through status, once the scan has been looked
at) and a scan does not carry `reduced_extraction` (the server reports it on the findings, because it
is a fact about one evaluation). `issuesFor(scan, result)` merges the two where both are to hand.
Nothing has run on hardware, and `expo-crypto` is native, so the EAS dev client needs rebuilding
before the device walkthrough.
**PR:** n/a · **Requirement:** FR-04, FR-06, FR-08, FR-09, NFR-07

---

## 2026-09-12 — B19's dependency ask is answered, and the LLM runs on open-weight models

**Context:** Making the device walkthrough possible meant closing the three runtime gaps the code had
deliberately left open rather than papered over. `services/vision/ocr.py` resolved a `PaddleOCREngine`
whose runtime was absent, so a scan would have uploaded and then failed at recognition.
`services/bis/embedding.py` and `retrieve.py` both raised a message naming B19's outstanding
dependency ask. And `LLM_MODEL_BUDGET`/`LLM_MODEL_MID` were empty, so all three call sites in
CLAUDE.md §9 had a base URL and a key but no model to name.

**Decision:** `sentence-transformers` is declared as a **`[bis]` extra**, on exactly the terms
`[ocr]` was — out of the core dependencies because it pulls torch and fetches weights on first use,
which CI must never do, and still imported inside the adapter so `services/bis/` imports and
type-checks without it. One package carries both runtimes the corpus needs: `BAAI/bge-m3` for the
1024-dimensional multilingual embeddings and `BAAI/bge-reranker-v2-m3` for the rerank. `[ocr]` was
installed rather than newly declared — it was already in `pyproject.toml`.

The LLM tiers are filled with the open-weight models the configured endpoint actually serves:
`openai/gpt-oss-20b` for budget (extraction, explanations) and `openai/gpt-oss-120b` for mid
(Sahayak answers). No vendor name enters a `.py` file; both are a base URL and a model name in the
environment, which is what keeps §9's open-weight path honest rather than aspirational.

*Using the `hashing` embedder to make retrieval run without the model* — rejected. It is a test
double; it would return semantically meaningless neighbours and Sahayak would cite sources that do
not answer the question, which is worse than the refusal it returns today.

**Consequences:** Both tiers were verified through `ChatCompletionsProvider` rather than raw HTTP:
extraction returns valid JSON inside its 1200-token budget, and an explanation fits
`reporting/explain.py`'s 220 even though these are reasoning models that spend tokens before they
speak. No code changed for either. **Model revisions are still unpinned** — B19's ask asked for that
and it remains owed; until it is done, a corpus embedded today and a query embedded after an upstream
re-release are not guaranteed to share a vector space. Installing `[ocr]` moved `numpy` to 2.3.5 and
`opencv-contrib-python` to 4.10.0.84, still the contrib wheel, and the suite holds at one failure,
which is `test_llm_provider.py::test_the_open_weight_path_is_the_same_adapter_not_a_second_one`: it
asserts a provider built for a local server carries no credential, and
`adapters/chat_completions.py` falls back to `settings.LLM_API_KEY` regardless of where the base URL
points. That is left for review rather than edited, per CLAUDE.md §6. Sahayak still refuses every
question — `bis_documents` is empty, there is no corpus source in `bis/` beyond the applicability
table, and nothing calls `ingest()`.
**PR:** n/a · **Requirement:** FR-22, FR-28, FR-29, CLAUDE.md §9

## 2026-09-13 — The model's reading outranks the pattern's, and every photograph is read

**Context:** Two things surfaced on the same device scan. First, a scan may carry up to ten assets and
`pipeline.py` read `record.assets[0]` — so a two-photograph capture of a sachet OCR'd the front panel
(17 words of branding) and never opened the back, where the manufacturer, address, MRP and dates were
printed. Extraction then reported them absent and the presence rules FAILed, correctly, on text that
was photographed but never read. Second, on the panel that *was* read, the regex layer matched `mrp`
to `"02"` and `best_before` to `"Date:"` — a fragment and a caption — and because Rule 6(1) checks
only that a field is present, both became PASS. A confident wrong PASS on a legal report is worse
than the FAIL it replaced.

**Decision:** Every raw asset is decoded, hash-verified and OCR'd; their words merge into one text for
extraction, because a declaration is a declaration wherever it is printed. The marker selects which
photograph is the *metric* one and it need not be the first — that one alone is rectified, measured,
and used for evidence boxes. And the LLM layer is now asked about every field rather than only the
ones no pattern matched, with its reading winning where the two disagree.

**Why the order reversed.** A pattern matches a shape, not a meaning, and cannot tell that it matched
the wrong thing: the text genuinely did match. What bounds the model is not its position in the order
but the evidence rule — `extract_with_llm` refuses any value absent from the OCR text — so an override
is always a different reading of text that is really there, and the pattern's value is what stands
when the model's is refused. The deterministic layer remains the floor, not the ceiling.

**Costs accepted deliberately.** Extraction is no longer reproducible run to run; two evaluations of
one image minutes apart already produced different `findings_sha256`. `evaluate()` is still pure and
still the only thing that issues a verdict, so §3.1 holds, but §3.6's "regenerate the same verdict"
now depends on the stored extractions rather than on re-running the pipeline. And an overridden field
carries 0.70 against the pattern's 0.95, below FR-06's 0.75, so it reaches a verdict only after a
human confirms it — more fields now route through confirmation, which is the intended trade.

**Coordinate spaces, which is where this could have gone wrong quietly.** Measurement is passed only
the metric photograph's words: glyph heights come from connected components on the rectified image,
and polygons from a second, unrectified photograph would have measured the right glyph in the wrong
place and produced a confident wrong millimetre — exactly what §3.3 exists to prevent. Evidence boxes
from non-metric photographs are dropped and their values kept, because a box from an unrectified
photograph is a real rectangle in a different space and there is no homography to bring it across.
`ocr_results` now holds one row per photograph, stamped with its `asset_id` — the grain the model's
docstring already specified, and the column already existed, so no migration.

**Alternative rejected:** letting the model override only where a pattern's value fails its own field
format check. It would have killed `"02"` and `"Date:"` while keeping determinism everywhere else,
but it makes correctness depend on having written a good enough validator per field — the same
brittleness that produced the bad matches — and it was not what was asked for.

**PR:** n/a · **Requirement:** FR-24, architecture §5 S6, CLAUDE.md §3.1, §3.3, §6

## 2026-09-13 — Orientation is recovered before recognition is trusted, and implausible values lose their confidence

**Context:** A scan of a protein sachet returned `manufacturer_name` as `NDUSTRIES PVT.LTD`,
`mrp` as `02` and `best_before` as `Date:`. None of these were extraction failures. The OCR text
genuinely contained those strings, the extraction layer reported them faithfully, and Rule 6(1) —
which asks whether a declaration is *present*, not what it says — returned **PASS** for the MRP and
the shelf life. Both were recorded at 0.95, above FR-06's threshold, so nobody was ever asked.

Two distinct causes, addressed separately.

**Recognition.** The pack was photographed lying on its side and folded across the middle. Read as
shot it gave 50 words at 0.865 confidence; rotated it gave 107 at 0.906 — and the two rotations
returned *different halves of the pack*, because the fold put them 180° apart. Clockwise recovered
the nutrition table, anticlockwise the manufacturer, address, both dates and the MRP.

**Decision:** `services/vision/orientation.py` reads a page again at other orientations when the
upright pass is not trustworthy, and **merges** the readings rather than scoring them and keeping a
winner. Merging is the whole point: a folded or multi-panel pack has no single correct orientation,
and picking the best one would have chosen clockwise here and lost every declaration the label is
judged on. On the real photograph the merge took 50 words to 243, and `138.00` — the actual MRP,
previously read as `02` — became readable.

**Why the trigger is box shape.** Word count and mean confidence were measured first and rejected:
50 words at 0.865 looks like an ordinary read, and any threshold tight enough to catch it fires on
healthy captures. Words are wider than tall in both Latin and Devanagari, so the share of
taller-than-wide boxes is a direct measurement of the thing being asked about — 100% as shot, 0%
upright, on the same photograph. `looks_thin` is kept as a second signal for the different failure
it actually describes: a page read badly rather than sideways.

**Cost.** Three extra recognition passes, but only on a page that asks for them; an upright
photograph returns on the first pass unchanged. Every word is mapped back to the coordinates of the
image as handed in, because a polygon left in a rotated frame is a real rectangle in the wrong
place, and the confirmation sheet's evidence crop would show the wrong words.

**Extraction.** Separately, `services/extraction/plausibility.py` caps the confidence of a value
that could not be a value of its field at all. It lowers confidence and nothing else: the value,
its span and its evidence box are kept, and no verdict is touched — `evaluate()` remains the only
thing that decides compliance (§3.1). A flagged field simply falls below FR-06's threshold and is
put in front of a person before a verdict rests on it.

**These are not thresholds in the §3.2 sense.** Nothing here encodes a rule, a limit or a table
row. The question is narrower and has no legal content — a date field with no digit in it, an email
with no `@`, a price that is a leading zero. Whether the value then complies stays the rule pack's
business.

**Deliberately asymmetric, and deliberately not clever.** A false flag costs one tap on the
confirmation sheet; a missed one costs a wrong verdict in a report carrying a gazette citation, so
the checks lean toward asking. They do **not** guess at content: `INDUSTRIES PVT.LID` is plausible
as a manufacturer's name and is not flagged, because nothing about the string reveals it is
truncated. Flagging it would put half of every real label on the confirmation sheet. That damage is
recognition's, and is fixed at S4 rather than papered over here.

**Alternative rejected:** scoring the orientations and keeping the best. Simpler, and wrong for the
case that motivated the work — see above.

**PR:** n/a · **Requirement:** FR-06, FR-22, FR-24, architecture §5 S4/S6, CLAUDE.md §3.1, §3.2

## 2026-09-13 — A verdict is not issued over a value nobody has checked

**Context:** FR-06 existed and was working: fields below 0.75 were surfaced for confirmation, the
screens flagged the verdicts as provisional, and report generation was blocked until they were
answered. What it did not do was stop the verdict being *computed and shown* first. So a real scan
produced `mrp = "02"` — a fragment of `138.00 (3.83/g)` — at 0.95 confidence, Rule 6(1)(e) asked
only whether an MRP was declared, found one, and returned **PASS**. The user then corrected the
value, the recompute ran correctly, and the verdict did not move, because a presence rule is
satisfied by the correct value and by junk alike. The feature looked broken while working exactly
as designed.

**Decision:** confirmation becomes a gate rather than a review. When any extraction is below the
threshold the pipeline persists its OCR, extractions and measurements, sets the scan to a new
`needs_confirmation` status, and does **not** call `evaluate()`. `confirm-fields` evaluates once
nothing is outstanding, and the scan reaches `complete` or `no_marker` only then.

**The evaluation row is still written, with no findings on it.** This is the part worth recording,
because it looks like an empty row for nothing. It carries `rulepack_version`, `rulepack_checksum`
and `as_of`, which is what makes the confirmation that follows judge the label under the rules in
force when it was photographed rather than whatever is active whenever the user gets round to it
(§3.6). Deferring evaluation without it would have meant either a new column on `scans` or quietly
re-resolving the active pack at confirmation time — the second of which is the §3.6 bug the
confirm-fields handler was already written to avoid. So: a row with nothing in it, rather than no
row, and no schema change beyond the status itself.

**`complete` vs `no_marker` after confirmation** is decided by whether a rectified asset exists.
That asset is written if and only if a marker was found *and* yielded a homography, so it is the
durable record of the fact. Re-deriving it from an empty measurement list would confuse "no marker"
with "a marker, but nothing measurable on this label".

**What this does not fix, stated plainly.** It does not change the `mrp = "02"` verdict. That PASS
came from a presence rule being satisfied by junk, and confirming earlier, later or never leaves it
a PASS. The fix for that shipped separately the same day — plausibility screening caps the
confidence of a value that could not be its field at all, which is what puts `"02"` in front of a
person in the first place. This change is about not *showing* a verdict computed from unchecked
text; that one is about catching the junk.

**Costs.** A seventh scan status and its migration (0004), a seventh value in the app's domain
`ScanStatus`, and one more state for the offline queue's machine — where it is deliberately
`needsAttention` but not `isPending`: the queue has nothing left to do, and the user has. `GET
/findings` now returns 200 with an empty findings array for such a scan, which is a contract change
`mobile/` consumes and is recorded in `06-wiring-contract.md` §3.3. One existing test,
`test_a_unit_defect_still_fails_after_correction`, now confirms two fields instead of one: it is
about what a format rule reads, and it has to reach a verdict to say anything about that.

**Alternative rejected:** evaluating as before and hiding the result behind the existing
`verdictsAreProvisional` flag. It is what the code already did, and the objection is not that the
verdict was visible — it is that it existed at all. A computed verdict over unchecked text is a
number somebody will eventually read out of the database, whatever the UI does with it.

**PR:** n/a · **Requirement:** FR-05, FR-06, architecture §5 S6, CLAUDE.md §3.4, §3.6

---

## 2026-09-13 — BIS applicability reads the scan, and Sahayak is grounded in it

**Decision:** the scan's BIS screen calls `POST /v1/scans/{id}/applicability` instead of gating on a
`productId` it never has, and `scan_id` on `POST /v1/sahayak/ask` now loads that scan's frozen
profile into the generation prompt. The screen shows the deterministic verdict with the conversation
beneath it.

**Why:** the button was a dead end. Every scan taken in the field has `product_id = null` — a
photographed label is not matched to a catalogue product — and the screen returned "no applicability
record" without making a request, for an endpoint that had never needed a product row. It reads the
frozen profile and stamps the answer with `captured_at`, so the verdict stays reproducible under the
lists in force at capture (CLAUDE.md §3.6).

The chat was the other half. It existed and worked, but `scan_id` was used only for org-scoping and
for the `bis_queries` row, so a question about "this product" reached the model with no product
attached. Grounding is what makes one tap from a scan useful.

**What did not change, deliberately:** retrieval still receives the question exactly as typed, so
which sources an answer may cite is still a function of the question alone. The product is context,
never a source — every claim must still name a retrieved passage — and applicability is still
decided by the table lookup and nothing else. A wrong "no licence needed" is a seized consignment,
so the chat sits under the verdict rather than in place of it.

**Alternative rejected:** replacing the applicability screen with the chat, which is the literal
shape of the request. It reads better and it inverts §3.1 in the BIS half of the system: the thing
that answers "does this need certification" would become a model with a citation check rather than a
reviewed list, and the answer people act on would stop being reproducible.

**Known limit, not fixed here:** the corpus is one document and one chunk, so most questions refuse
with `no_supporting_source`. That is the refusal working — an answer with no source is withheld —
but it is now the binding constraint on answer quality, and it is a `bis/` data change needing review
under CLAUDE.md §7.

**PR:** n/a · **Requirement:** FR-07, FR-28, FR-29, CLAUDE.md §3.1, §3.5, §3.6

---

## 2026-09-13 — The context form fills itself from the label, and a person still confirms it

**Decision:** after capture, the app sends one downscaled photograph to `POST /v1/prefill`, the
worker reads it with the same OCR and extraction the pipeline uses, and the context form fills
itself from the declarations that came back. The three fields that decide which rules run are
gated behind a single explicit confirmation before a scan can be created.

**Why:** FR-03 has always said "three fields are pre-filled from OCR and confirmed by the user",
and `05-frontend-plan.md` deferred it three times — at Stages 5, 7 and 8 — each time on the same
reasoning: there was no extraction to prefill *from* until processing had run, and prefilling a
form that is filled in *before* processing would mean re-opening a submitted scan. That reasoning
was right about the post-processing path and it answered the wrong question. The complaint is not
"the form is hard to correct afterwards", it is "I photographed the pack and now I am typing what
the pack says". So the read happens **before** submit, on its own cheap path, and the form the user
was going to fill is already filled when they look at it.

**What keeps it inside §3.1.** The model fills a form; it does not decide anything.

- `is_imported` is proposed in one direction only. An importer declaration on the label suggests
  *imported*; the absence of one suggests **nothing**. `is_imported=false` switches the importer
  rules off, and a pack with no importer line is exactly the pack in breach of Rule 6 — inferring
  "domestic" from silence would launder that omission into a profile field that hides it.
- `surface` is never proposed, in either half of the system. It selects a Rule 9 threshold column
  and cannot be read from a label's words. Nor are pack type, panel area, channel or category code
  — `NEVER_SUGGESTED` lists each with its reason and a test asserts the list.
- Net quantity and the imported flag, where they were machine-filled, hold submission until the
  user affirms them once. Editing the field counts as affirming it: someone who retyped the
  quantity has looked at the pack.
- Every filled field shows the text that was read and the declaration it came from, so a value can
  be checked against the pack rather than trusted.

**No new LLM call site.** Prefill calls `extraction.extract`, which is the existing
`extraction.llm_layer` site at the budget tier with its existing prompt and schema. CLAUDE.md §9's
table still lists three.

**No millimetre is produced.** Prefill reads words; it does not rectify, detect a marker or measure,
which is why it can run on a 1600 px thumbnail. §3.3 is respected by not producing the quantity
that would violate it — the scan itself is still measured by the pipeline off the full-resolution
original.

**Alternative rejected — move the context form after processing**, so it prefills from the
pipeline's own extraction and no second OCR pass exists. It is the better end state and it is a
much larger change: `create_scan` would take a partial profile, the pipeline would evaluate twice,
the confirm-fields sheet would grow profile fields, and a capture with no network could no longer
be completed at all. That last one is FR-04, so it is not a trade that can be made quietly. The
cost of the path taken is one extra OCR pass per scan on a thumbnail; recorded here so the
reuse-the-pipeline's-OCR optimisation is a known follow-on rather than a rediscovery.

**Alternative rejected — presign a scratch upload like every other image.** Three round trips
while a person waits at a form, plus a bucket lifecycle rule, for an object that is read once and
deleted. Architecture §10's "the API never sees the bytes" is about **evidence**, and this
photograph is not evidence: the scan's own images still go up presigned with their declared
SHA-256, which is the chain a report cites. The prefill copy arrives base64 in the request body,
capped, EXIF-stripped, and deleted by the worker as soon as it has been read.

**Degradation, by design:** no network, prefill disabled, broker down, Redis down, unreadable
photograph, nothing recognisable on the label — every one of them ends as a form that behaves
exactly as it did before this existed. The capture path cannot be failed by this feature, which is
the only way it could be allowed onto that path at all.

**PR:** n/a · **Requirement:** FR-03, FR-04, FR-06, FR-24, CLAUDE.md §3.1, §3.2, §3.3, §3.7, §9

---

## 2026-09-13 — The context form waits for the read instead of filling in around the user

**Decision:** the product context screen does not render its form until the label read has settled.
While it runs, `PrefillGate` shows a spinner, what is happening, and a way straight to the blank
form. The form then mounts **once**, with the suggestions seeding its defaults.

**Supersedes** the "runs beside the form, never in front of it" part of the entry above. Everything
else in that entry — the one-way imported flag, surface never proposed, the confirmation gate, no
new LLM call site, no millimetre — is unchanged.

**Why:** the first version rendered the form immediately and filled it a few seconds later. Run on
a phone, that is worse than it sounds. The screen rearranges itself under someone who has already
started typing; the fields they were mid-way through answering are suddenly answered; and the whole
proposition of the feature — *stop typing what the pack already says* — is undermined by a form
that opens asking them to type. Waiting is the honest version of the same promise: the form arrives
finished.

**The wait is the thing that needed designing, not the spinner.** Three things end it — an answer,
a failure, and `TIMEOUT_MS` — and the gate offers **"fill it in myself"** on the first tap. That
escape hatch is load-bearing, not a courtesy: without it this change would put a network call on
the capture path, which is exactly what FR-04 forbids. With it, a user with no signal taps once and
is where they were before the feature existed, and a user who knows the pack is unreadable does not
have to watch a timer to prove it.

**A structural gain, not only a UX one.** Because the form now mounts with the answer in hand, the
suggestions seed `defaultValues` instead of being written in by an effect afterwards. The "never
overwrite what the user typed" rule stops being a `getValues()` check that has to be right and
becomes true by construction — there is no window in which a field is first empty and then filled.
The apply-effect and its `applied` ref are gone.

**Skipping is final, deliberately.** A read that lands after the user has chosen to type is
discarded rather than applied. A form that fills itself under someone who just said they would do
it themselves is the original bug wearing a different hat.

**PR:** n/a · **Requirement:** FR-03, FR-04 · **Supersedes:** part of the 2026-09-13 entry above

---

## 2026-09-13 — Prefill reads every photograph, not the front panel

**Decision:** `POST /v1/prefill` takes `images: [...]` — every photograph the capture holds, in
capture order — and the worker merges their recognised words before extracting once.

**Why:** the first version read `assets[0]` on the reasoning that it is "the one framed at the
front panel, where the declarations are". Half true, and the wrong half. Rule 6's mandatory
declarations are spread deliberately across a pack's faces: net quantity and the commodity name go
on the principal display panel, while the manufacturer, the importer, the country of origin, the
consumer-care line and the month of packing are almost always on the back or a side. So reading one
photograph proposes nothing for most of the fields the form exists to stop people typing — and the
photograph most likely to carry them is the one that was being ignored.

**One extraction over merged words, not one per photograph.** It is a single LLM call rather than
N, and it lets a declaration be read in the context of the others. It also matches what the
pipeline already does with a scan's images, for the same stated reason: a declaration is a
declaration wherever on the pack it is printed.

**Merging is safe here in a way it is not in the pipeline.** Word polygons from two photographs are
in two different coordinate spaces — which is exactly why `pipeline` keeps a per-asset `ocr_pages`
beside its merged text. Prefill discards geometry entirely; a suggestion carries a value and the
text it was read from, never a box. There is nothing here for the mismatch to corrupt.

**One bad photograph does not cost the others.** A frame that will not decode is skipped and the
rest are read; the read fails only when *nothing* could be decoded. Same on the client: a capture
whose file has gone is dropped from the batch rather than abandoning the request.

**What it costs, and what was done about it.** Three photographs is not three times the network but
it is three times the OCR, and someone is now watching that wait. So the byte ceiling became a
ceiling on the *request* rather than on one image, the photograph count is capped to match
`POST /v1/scans`' asset limit, and the client's give-up timeout scales with the count — 20 s, plus
15 s per extra photograph, capped at 90 s — instead of being a flat 30 s that three photographs
would blow through while the read was still working.

**PR:** n/a · **Requirement:** FR-03, FR-24 · **Amends:** the two 2026-09-13 entries above
· **Amended by:** the entry below, which replaces the count ceiling with three

---

## 2026-09-13 — A read takes three photographs, and the client drops the rest

**Decision:** `POST /v1/prefill` accepts one to **three** images. A client holding more sends the
first three in capture order and silently drops the rest.

**Why three.** The entry above set the ceiling at ten by matching `POST /v1/scans`' asset limit,
which was the wrong thing to match. That limit is about how much *evidence* a scan may carry, and
more evidence is strictly better — a report cites what it was given. Prefill's ceiling is a budget
on a person's *patience*: they are watching a spinner that will not become a form until the read
settles, and every extra photograph is another OCR pass on that wait. More is worse. Two limits
that point in opposite directions should not share a number.

Three is what the pack itself justifies. Rule 6's mandatory declarations live on the principal
display panel (net quantity, commodity name) and on the back or a side (importer, country of
origin, consumer-care line). Three photographs cover those faces; the fourth is nearly always
another angle on a face already read, so it proposes no new declaration and still costs ~15 s.

**The client drops, the server refuses.** Both halves carry the number, and that is deliberate
rather than duplication. The server's `max_length` is the contract holding its own line — it is the
only thing that makes the shape true regardless of who is calling. The client's slice is what
ensures nobody meets it: a 422 on the capture path would take prefill down for a user who did
nothing wrong except photograph carefully, and the capture path is the one that must never break
(FR-04). A test on each side pins the number so the two cannot drift apart into exactly that 422.

**Dropping is silent.** No banner, no "two photographs were ignored". A capture of five is somebody
being thorough, and telling them their care was discarded reads as a fault in a flow that is about
to hand them a filled form. The gate does show how many are being read rather than how many were
taken, which is the honest version of the same fact and costs nothing to look at.

**What did not change:** the scan still uploads every photograph it captured. This ceiling is on
what gets *read for the form*, never on what becomes evidence — the two paths were already
separate, and this is the first thing that makes the separation visible.

**PR:** n/a · **Requirement:** FR-03, FR-04 · **Amends:** the entry above

---

## 2026-09-13 — The capture gates measure a real frame instead of a timer

**Decision:** `POST /v1/capture/gates` measures a preview frame server-side, and the capture screen
polls it every 500 ms through the existing `GateEvaluator` seam. The simulation stays for tests and
any screen with no camera.

**Why:** the chips were a pure function of elapsed time. They went green 2.4 seconds after the
screen opened, pointed at anything — a desk, a cable, a wall — and the shutter went with them. That
is not a missing feature, it is an affirmative false statement to the user, and it let marker-less
photographs into the queue; "no rectified image" on the findings screen was the downstream symptom.
`03-implementation-plan.md` §P3.3 sanctions this exact interim.

**Why not the native ArUco plugin, which is the end state:** vision-camera 5.2.3 is Nitro-based and
has removed the `VisionCameraProxy.initFrameProcessorPlugin` API that every existing ArUco example
targets; `mobile/android` is prebuild output that `expo prebuild --clean` discards, so native code
has to be packaged as a config plugin before it survives; and OpenCV for Android is a new dependency
with an EAS-build feedback loop measured in tens of minutes. None of that is impossible, and none of
it was worth doing before the chips told the truth.

**What did not change:** the thresholds. `features/capture/gates.ts` still owns the FR-01 policy and
is still pure — the endpoint returns measurements and no verdict, so there is exactly one definition
of when the shutter opens. `tilt_degrees` stays three-valued: null when there is no marker plane to
measure against, never 0.

**Alternative considered — computing blur and glare on-device** in a worklet over the frame's Y
plane, leaving only marker and tilt to the server. It is the better end state and `FramePlane.
getPixelBuffer()` makes it reachable, but it doubles the number of code paths producing
`FrameMetrics` and none of the worklet half can be tested anywhere but a physical device. Correctness
first; the latency win can come after the gates are honest.

**Known limitation, recorded rather than hidden:** the snapshot is of the preview, not the sensor,
so `blur_variance` reads lower than the photograph's would. The gate errs toward calling a frame
soft, which is the safe direction, but the 120 threshold wants re-checking on a device.

**PR:** n/a · **Requirement:** FR-01, `03-implementation-plan.md` §P3.3, CLAUDE.md §3.2, §3.3

---

## 2026-09-13 — The marker is no longer a capture gate

**Decision:** the shutter gates on sharpness, glare and angle. The marker chip is gone, and an angle
that cannot be measured — which is every frame without a marker — no longer blocks capture.

**Why:** `detect_marker` only knows ArUco DICT_4X4_50, but the app offers three scale references
(printed tag, ID-1 card, hand-measured dimension). With a real marker gate, two of those three were
choices that led to a shutter which never unlocked, and nothing on screen explained why. The
simulation had hidden this completely by going green regardless.

The second half follows from the first: tilt is the angle to the *marker's* plane, so without a
marker it is `unknown`. Leaving `unknown` blocking would have kept the marker gate in place under
the angle's name — with no chip naming it and no instruction that could be acted on.

**What did not change — and this is the part worth being precise about.** CLAUDE.md §3.3 is
untouched. It governs *measurement*, not capture: a scan with no marker still gets no homography,
still lands as `no_marker`, and every metric rule still returns NOT_ASSESSABLE. What moved is only
when the app refuses to take a picture. The pipeline is still the thing that decides a millimetre is
unknowable, and it still says so out loud. `unknown` also stays a distinct state rather than
collapsing into `pass`, for the same reason §3.4 keeps BORDERLINE: "we could not check this" and
"this is fine" are different things to show a user.

The capture screen now shows the unmeasured-angle note whenever nothing is blocking, and it names
the consequence — *"No scale reference in frame, so the angle was not checked. Size rules will be
Not assessable."* A user who wants millimetres learns that before the photograph, not after.

**Tests:** eight assertions in `capture-gates.test.ts` encoded the old policy and were rewritten to
the new one rather than deleted — the marker case now pins that a marker-less frame *is* capturable,
and a new case pins that a measured-and-bad angle still blocks, so loosening `unknown` did not
loosen `fail`.

**Reversible:** restoring the gate is adding `'marker'` back to `GATE_IDS` and its result row. The
better fix, if the marker is wanted again, is detectors for the other two references — then the gate
means something whichever one the user picked.

**PR:** n/a · **Requirement:** FR-01, FR-02, CLAUDE.md §3.3, §3.4

---

## 2026-09-13 — Prefill asks the model for a product name, and trusts the pattern's origin line

**Decision:** two changes to prefill, neither touching extraction for verdicts.

1. When extraction proposes no name, prefill asks the model one more question: what the product is
   called. `extraction.product_name` is a **fourth LLM call site** (CLAUDE.md §9, updated). The
   model answers in parts, each with a span. Every part must be found in the OCR text or the whole
   answer is dropped, and the form receives the label's own characters at those spans, not the
   model's spelling. Company-looking answers (Ltd, Pvt, Industries) are refused. It is asked only
   after a successful extraction call and only when no name came out of it.
2. `is_imported` may be proposed from the **pattern layer's** reading, which `extract` had replaced
   with the model's. An "Imported by" match is believed as before. A "Country of origin" match must
   name a country in `extraction.countries`, must not be India, and must not be contradicted by the
   model reading India.

**Context:** a real prefill of a Dabur fruit drink's back panel read 182 words and filled only the
net quantity. The panel has no common-name line, so the model found one on some runs and not
others. The carton says "Country of Origin Nepal" and "Imported & Marketed by DABUR INDIA LTD". The
pattern read the origin at 0.95, the model re-read it at 0.70, the model's answer won the merge,
and 0.70 is below the bar `is_imported` needs. An earlier docstring had called that "Nepal" a
hallucination. It was not, and the docstring now says so.

**Rejected:** loosening the extraction prompt so the model finds `common_name` more readily. That
call feeds the Rule 6 common-name rule, and a label that omits its common name would move from FAIL
to PASS. Also rejected: proposing imported whenever an origin reading is "not India". That is a
negative test any OCR misread passes (`DABURNDIAID`), which is why a positive country match is
required. A missing or mangled country proposes nothing, which is the safe direction.

**Not changed:** pack type stays manual and in `NEVER_SUGGESTED`. It is not printed on labels, and
reading it reliably would need an image model.

**Cost:** one extra budget-tier request on prefills whose label shows no common name, about 2–9 s on
the current provider. The name question is still skipped when the model's extraction wrongly files
slogan text as `common_name` ("CITY CLEAN" on one run of the same pack), because a common name read
off the label outranks the model's answer.

**Tests:** `tests/test_prefill_name_and_origin.py` (26).

**PR:** n/a · **Requirement:** FR-03, CLAUDE.md §3.1, §3.4, §8, §9
