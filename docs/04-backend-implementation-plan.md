# Anupalan — Backend Implementation Plan

**Doc version:** v1.0 · **Written:** 12 Sep 2026
**Scope:** `backend/` only — FastAPI API, Celery worker, `rulepacks/` consumption, eval scripts.
**Companions:** `01-architecture.md` (§5 pipeline, §8 data model, §9 settled decisions), `02-trd.md` (every FR/NFR below is defined there with its acceptance test), `03-implementation-plan.md` (whole-project phases and dates).

This document does not restate `CLAUDE.md`. Every task below inherits its non-negotiables (§3), layout (§2), conventions (§5), testing rules (§6) and ask-first list (§7).

**How to use it:** §2 is the sequence. §3 is one handoff card per work package, in the `CLAUDE.md` §11 shape. Hand over **one card at a time**. Write the test file named on the card *before* the implementation, then hand the card over with the tests already committed.

---

## 0. Where the backend stands today (12 Sep 2026)

Audited against the working tree, not against the plan.

| Area | State |
|---|---|
| `app/config.py` | **Done.** All settings, `PX_PER_MM`, `RULEPACK_PATH`, Neon/Redis/R2 blocks, `alembic_url`, `redis_is_tls`. |
| `app/db.py` | **Done.** Engine, `Base`, `session_scope`, `ping`. `prepare_threshold=None` + pre-ping in place. Every model is registered on `Base` (B12). |
| `app/main.py` | **Done.** CORS, the NFR-07 error envelope, five exception handlers, `/health`, the rate-limit middleware (B23) and every feature router. The envelope carries an error's headers, so a 401 is a well-formed 401 and a 429 carries `Retry-After`. |
| `app/worker.py` | **Done.** Celery app, TLS off the URL scheme, `task_acks_late`, `include=["app.tasks.scan"]`. |
| `app/health.py` | **Done.** db + redis + rulepack, 200-with-`degraded` semantics. |
| `app/routers/*.py` | **`auth.py` (B13), `scans.py` (B14, B15), `admin.py` (B16), `dashboard.py` (B17), `sahayak.py` (B20), `products.py` (B21 bulk listing)**, plus `deps.py` (session, principal, `requires`, `found`, `Idempotency-Key`, enqueuer, storage, LLM, BIS searchers). `reports.py` is a docstring only; `products.py`'s CRUD half is still P2.2. |
| `app/models/` | **Implemented (B12, B14, B17).** 19 tables across nine modules. Postgres-only types declared `with_variant`, so the same models build a SQLite schema for CI. B17 added `scans.district` and `products.brand`. |
| `app/schemas/` | **`base.py`, `auth.py` (B13), `scans.py`, `findings.py` (B14, B15).** `StrictModel` forbids unknown fields and refuses a body-supplied `org_id` with a 400. Literal unions are asserted against the models' CHECK tuples at import, so the contract and the database cannot drift. |
| `app/repositories/` | **Implemented (B12, B14, B16, B17).** `OrgScopedRepository` cannot be constructed over a table without `org_id`; `scans.py` carries the concrete repositories and `ScanStoreAdapter`; plus `idempotency.py`, `rulepacks.py` (resolve a pack by the version a scan was judged under), `audit.py` (append and read, no update path) and `aggregates.py` (FR-30, dimension as an enum, current revision only). |
| `app/services/auth/` | **Implemented (B13).** `tokens.py` (HS256 on the stdlib, no JWT dependency), `otp.py`, `rbac.py`. |
| `app/services/audit.py` | **Implemented (B16).** Per-org hash chain, versioned canonicalisation, verification reporting the first broken link and whether the row was edited or removed. |
| `app/services/rules/` | **Done (B0–B3).** `schema.py` validates with line-level errors, `loader.py` checksums and activates, `evaluate.py` interprets all seven rule kinds, `findings.py` assembles. 14 baseline cases green, 88% coverage. |
| `app/services/reporting/` | **Done (B11).** `model.py` is the one structure PDF/DOCX/JSON all render from; `pdf.py` splits `render_html` (pure) from `render_pdf` (needs GTK3). Disclaimer and both hashes in every format. `explain.py` is the LLM guidance call site — it returns a `str`, so it structurally cannot express a verdict. |
| `app/services/vision/` | **Implemented (B5, B6).** `marker.py` + `rectify.py` warp to `PX_PER_MM`; `ocr.py` is the FR-22 interface with stub and PaddleOCR adapters. Metrology (B7) not started. |
| `app/services/storage.py` | **Implemented (B4).** Org-prefixed keys, presign-time limits, sha256 on receipt, fail-closed EXIF stripping. |
| `app/services/extraction/` | **Implemented (B9).** Regex, then LLM for the residue, then human confirmation; every span verified against the real text. |
| `app/services/llm/` | **Implemented (B8).** Vendor-neutral `LLMProvider`; a failure is a return value, never an exception. |
| `app/services/pipeline.py` | **Done (B10).** All ten stages; `ScanStoreAdapter` (B12) implements the `ScanStore` port, and `app/tasks/scan.py` wires it into the worker. Golden-file pinned. |
| `app/services/listings.py` | **Implemented (B21).** CSV in, a verdict per row out. `check_listing` has no measurements parameter, so a metric verdict cannot reach this path by any argument a caller could pass. |
| `app/services/ratelimit.py` | **Implemented (B23).** Per-IP and per-org fixed windows; Redis, in-memory and null backends; fails open on a backend outage and refuses the in-memory backend in production. |
| `scripts/` | **Implemented (B22, B23).** `eval_e1`, `eval_e3`, `eval_e4` and `loadtest`, plus `common.py` for the commit/pack provenance header every run prints. Not an installed package — `pyproject.toml` ships only `app*`. |
| `app/services/bis/` | **Implemented (B18, B19, B20).** `ingest.py` (blocklist + comment, 8 source types, chunking with section refs, sha256 dedupe), `embedding.py` (`Embedder` protocol, lazy BGE-M3 + `hashing` stand-in, resumable `embed_pending`), `retrieve.py` (Postgres FTS + pgvector searchers, exact RRF, rerank 30→6), `applicability.py` (deterministic lookup over `bis/qco-crs-v1.yaml`), `answer.py` (citation-required generation with post-validation and five named refusals). |
| `alembic/` | **Three migrations.** `0001_initial_schema.py` creates the `vector` extension, 18 tables, the HNSW index while `bis_chunks` is empty, and five dashboard indexes; `0002_idempotency_keys.py` adds `idempotency_keys` (B14). `0003_dashboard_dimensions.py` adds `scans.district` and `products.brand` with their org-led indexes (B17) — **written and reviewed, not yet applied to Neon**; `tests/test_migration.py` fails until `alembic upgrade head` is run. |
| `tests/` | 617 tests across 28 suites. New since B20: `test_bulk_listing.py` (21), `test_eval_harness.py` (17), `test_hardening.py` (19). Before those: `test_dashboard.py` (19, including the 50,000-finding gate), `test_bis_ingest.py` (26), `test_retrieval.py` (20, one opt-in Postgres round-trip), `test_applicability.py` (18), `test_bis_answer.py` (34), `test_sahayak_api.py` (11). `mypy` is clean over the whole of `app/`. Skips: PDF rasterisation needs GTK3. The Postgres retrieval round-trip and `test_migration.py` skip without database credentials, and both run for a developer who has them. |
| `bis/` | **New (B20).** `qco-crs-v1.yaml` — the QCO/CRS applicability lists, versioned and checksummed data at the repository root, on the same terms as `rulepacks/`. See `docs/decisions.md`, 2026-09-12. |
| CI | ruff + mypy (strict on services) + pytest, no datastores. Green. |

So: the frame is built and the conventions are enforced. Everything below is the first line of feature code.

---

## 1. Fixed points this plan is built on

Three constraints shape the ordering more than anything else. They are not re-arguable here — see `01-architecture.md` §9.

1. **`evaluate()` is pure and is the product.** It takes profile + extractions + measurements + pack + `as_of`, and returns findings. Because it touches nothing, it can be built and fully tested *before* vision, OCR, extraction, storage or the database exist. It is therefore built **first**, not last.
2. **Millimetres come only from the marker.** B5 (rectify) gates B7 (metrology) gates every `metric` rule. Nothing downstream may invent a length.
3. **One codebase, two entrypoints.** Nothing in `routers/` may hold pipeline logic; the worker imports `app.services.*`. A service function that cannot be called from both is in the wrong place.

---

## 2. Sequence

Work packages are `B0`–`B23`. Dependencies are hard: do not start a package whose predecessors are not green.

### 2.1 The three tracks

```
track A — verdict engine (no infrastructure needed, start immediately)
  B1 rulepack schema+checksum ──> B2 evaluate() ──> B3 findings assembly
                                          │
track B — pipeline (needs images, not the DB)                 │
  B4 storage adapter ─┐                                       │
  B5 marker+rectify ──┼──> B7 metrology ──┐                   │
  B6 OCR interface ───┘                   ├──> B10 process_scan ──> B11 reporting
  B8 llm provider ──> B9 extraction ──────┘          │
                                                     │
track C — platform (needs Neon)                      │
  B12 data layer + org scoping ──> B13 auth ──> B14 scan API ──┘
                                        ├──> B15 findings/confirm API
                                        ├──> B16 audit chain
                                        └──> B17 dashboards

track D — sahayak (independent of A/B, needs B12 for the pgvector tables)
  B18 corpus ingest ──> B19 retrieval ──> B20 answer + applicability
```

### 2.2 Ordered table

| # | Package | TRD | Depends on | Window | Gate to clear it |
|---|---|---|---|---|---|
| ✅ B0 | Test scaffolding + fixture contract | — | — | done | `pytest` green with the new conftest fixtures |
| ✅ B1 | Rule pack: validation, checksum, `RulePack` API | FR-26 | — | done | invalid pack rejected with a line number; previous pack stays active |
| **✅ B2** | **`evaluate()` — the rules interpreter** | **FR-25** | B1 | **done** | **all 14 baseline cases pass; 1000-run byte-identity; no DB import in the module** |
| ✅ B3 | Findings assembly + summary + `rulepack_version` stamping | FR-25 | B2 | done | every finding carries pack version, citation, bbox slot |
| ✅ B4 | Object storage adapter (R2/S3), presign, sha256, EXIF strip | FR-20, SR | — | done | presigned PUT/GET round-trips against the real bucket |
| ✅ B5 | Marker detection + rectification to `PX_PER_MM` | FR-21 | P0 spike | done (synthetic; E1 still owed) | 10.00 mm bars measure 10.00 ± 0.25 mm on 20 captures |
| ✅ B6 | `OCREngine` interface + PaddleOCR adapter + second adapter | FR-22 | — | done | engine swap by config changes no calling code |
| ✅ B7 | Glyph metrology + uncertainty + curvature downgrade | FR-23 | B5 | done (synthetic; E1 still owed) | ≥90% within ±0.3 mm on the E1 set |
| ✅ B8 | `LLMProvider` interface + two adapters (wire, stub) | §9 | — | done | vendor name appears only in config + adapter |
| ✅ B9 | Extraction: regex layer, normalisation, LLM layer, span validation | FR-24 | B8 | done | regex recall ≥0.8, +LLM ≥0.95 on 20 fixtures; every value has a verified `source_span` |
| ✅ B10 | `process_scan` Celery task, status machine, retries | P2.3, NFR-04 | B4–B9, B12 | done | golden-file test byte-identical; re-running a completed scan records nothing new |
| ✅ B11 | Reporting: one data structure → PDF, DOCX, JSON | FR-27 | B3 | done | identical row count and verdict strings in both; DOCX table is a real `w:tbl` |
| ✅ B12 | Data layer: models, migrations, org-scoped repositories | DR, SR | — | done | `test_org_isolation` green (41); `alembic upgrade head` applied to Neon, autogenerate diff empty |
| ✅ B13 | Auth: OTP, JWT access/refresh, RBAC dependency | SR | B12 | done | role matrix exhaustive; token carries `org_id`, a body-supplied one is a 400 |
| ✅ B14 | Scan intake API: create, submit, get | FR-20 | B12, B13, B4 | done | 202 `queued`; a replayed `Idempotency-Key` returns the original scan, a changed body is a 409 |
| ✅ B15 | Findings API + `confirm-fields` recompute | FR-05, FR-06 | B3, B14 | done | correction recorded `source=human`; recompute uses the scan's **original** pack, pinned by a test that forces the active pack to differ |
| ✅ B16 | Audit log hash chain + verification endpoint | SR | B12 | done | tampering one row breaks verification at that row and not before it; chain survives a restart |
| ✅ B17 | Dashboard aggregates + indexes | FR-30 | B12 | done | 50,000 seeded findings in 0.14 s on every dimension; `group_by` outside the enum is a 422 |
| ✅ B18 | BIS corpus ingest + **blocklist** | P4.1 | B12 | done | blocklist non-empty and commented; a priced IS text is refused by URL, by contents, and by the catalogue-metadata size cap |
| ✅ B19 | Hybrid retrieval: BM25 + dense + RRF + rerank | FR-28 | B18 | done (top-6 recall still owed — B22) | RRF ordering exact to the arithmetic; empty stays empty |
| ✅ B20 | Sahayak answer (citation-required) + applicability **lookup** | FR-28, FR-29 | B19 | done | applicability is a table lookup; 10/10 refusals correct; 20/20 on FR-29's known products |
| ✅ B21 | Bulk listing check (Mode B) | FR-10 | B2, B14 | done | no metric rule returns PASS/FAIL from listing text — enforced by the signature, not by care |
| ✅ B22 | Eval harness: `scripts.eval_e1/e3/e4` | §7 | B7, B2, B20 | done (corpora still owed) | each prints the exact output shape in `03-implementation-plan.md` |
| 🟡 B23 | Hardening: rate limits, load test, security pass, docs | NFR-01, SR | all | code done; numbers owed | §5 gates all green — three need corpora or a deployment |
| ✅ B24 | API surface for the mobile client: findings `extractions`, `ScanOut` fields, `GET /v1/scans`, `GET /v1/products`, reports | FR-05, FR-06, FR-08, FR-09, FR-27 | B14–B16 | done | all 15 client calls have a server; 682 tests green; the verdict filter proved by mutation against a borderline-only fixture |

**Why B2 comes before everything.** It is the only module whose correctness is legally load-bearing, it needs zero infrastructure, and its 14 cases are already written in `03-implementation-plan.md` §P2.4. If the backend gets one week, it gets B1 + B2 + B3 + B11 and a fixture-fed demo — a citable PDF verdict with no camera involved at all.

### 2.3 Parallelism

Two people: one takes track A then B (the pipeline), one takes track C (platform) then D. They meet at B10, the only package that needs both. One person: A → C → B → D, and accept that B10 slips to the end of October.

---

## 3. Handoff cards

Each card is ready to paste into a Claude Code session. `CONTEXT` assumes `CLAUDE.md` is already loaded.

---

### B0 — Test scaffolding and the fixture contract

```
CONTEXT:     docs/02-trd.md §7; CLAUDE.md §6.
TASK:        backend/tests/conftest.py (extend), backend/tests/fixtures/README.md
CONSTRAINTS: no network in unit tests; no DB in any test under tests/unit/.
             Fixtures are committed data — images stay small (<300 KB each).
PRODUCE:
  - fixture loaders: load_profile(name), load_ocr_dump(name), load_expected_findings(name)
  - a `golden` marker + a --update-golden flag that is OFF by default and prints a warning
  - tests/fixtures/README.md stating: a golden diff is a reviewed change, never a silent update
DONE WHEN:   pytest green; `pytest --update-golden` rewrites nothing unless explicitly passed.
```

Do this first. Every later card names a fixture, and a fixture format invented twice is a day lost.

---

### B1 — Rule pack validation, checksum, and the pack API

```
CONTEXT:     docs/02-trd.md FR-26; rulepacks/lm-2011-v1.yaml; app/services/rules/loader.py.
TASK:        backend/app/services/rules/schema.py  (JSON schema for a pack)
             backend/app/services/rules/loader.py  (extend — do not rewrite)
CONSTRAINTS:
  - pure: no DB write here; persisting the pack row is B12's job
  - the schema is data too — put it in rulepacks/_schema.json, not in a Python literal
  - validation errors must carry the YAML line number
  - checksum is sha256 over the raw file bytes, not over the parsed dict
SIGNATURE:
  def validate_pack(raw: bytes, *, path: Path | None = None) -> None      # raises RulePackError
  def load_pack(path: Path) -> RulePack                                    # existing, now validating
  RulePack.checksum: str
  RulePack.rules: tuple[Rule, ...]       # parsed, typed; not raw dicts
  RulePack.table(name: str) -> Table
DEPENDENCY:  needs `jsonschema`. ASK before adding.
TESTS:       tests/test_rulepack_loader.py — valid pack loads; missing citation rejected;
             unknown `kind` rejected; float version rejected; checksum stable across reloads;
             an invalid pack leaves active_pack() returning the previous one.
DONE WHEN:   pytest tests/test_rulepack_loader.py && mypy app/services clean.
```

The schema must force every rule to carry `id`, `kind`, `citation`, `severity`, `message`. A rule without a citation is unusable in a report, so the schema — not a code review — is what has to stop it.

---

### B2 — `evaluate()`, the rules interpreter ★ critical path

```
CONTEXT:     docs/01-architecture.md §6; docs/02-trd.md FR-25 and §6;
             docs/03-implementation-plan.md §P2.4.
TASK:        backend/app/services/rules/evaluate.py
             backend/app/services/rules/types.py   (Profile, Extraction, Measurement, Finding, Verdict)
CONSTRAINTS:
  - PURE. No I/O, no DB, no model call, no datetime.now(), no logging of inputs.
    Effective-date filtering takes `as_of` as an argument.
  - No threshold, table row, unit symbol or date literal in this file. All of it is read from
    the pack. A grep for a bare float in evaluate.py should return nothing.
  - Four-valued verdicts. BORDERLINE is never collapsed into FAIL.
  - A metric rule with no measurement is NOT_ASSESSABLE. Never a guess, never a PASS.
  - A conditional rule whose `when` is false, or whose effective_from is after as_of, produces
    NO FINDING AT ALL — it is never a FAIL and never a PASS. Verdicts stay four-valued
    (CLAUDE.md §3.4); assemble() recovers the difference from the pack. See docs/decisions.md,
    2026-09-12.
  - Rule kinds to support: presence | any_of | format | metric | conditional | composite | geometry
SIGNATURE:
  def evaluate(
      profile: Profile,
      extractions: Sequence[Extraction],
      measurements: Sequence[Measurement],
      *,
      rulepack: RulePack,
      as_of: date,
  ) -> list[Finding]
TESTS:       tests/test_rules.py — the 14 cases in 03-implementation-plan.md §P2.4, verbatim,
             plus one determinism test (1000 runs, identical serialisation) and one import test
             (assert no sqlalchemy/celery/httpx import reachable from the module).
             ALREADY WRITTEN — DO NOT EDIT.
DONE WHEN:   pytest tests/test_rules.py -v passes, mypy app/services clean,
             coverage on app/services/rules ≥ 80%.
```

Three details the 14 cases pin down that are easy to get subtly wrong:

- **Borderline band.** The pack says `if |observed - required| <= uncertainty then BORDERLINE`. Case 3 (observed 2.05, required 2.0, uncertainty 0.25) is BORDERLINE even though `observed > required` — so the band is symmetric and is checked **before** the comparator, not after a PASS.
- **Table lookup.** `max_qty_g_or_ml: null` is the open-ended top row; rows are ordered and the first row whose bound is not exceeded wins. `500` belongs to the `≤500` row, not to the one above it.
- **Effective dates.** Cases 10 and 11 differ only in `as_of`. A rule with `effective_from` in the future yields `NOT_APPLICABLE`, which must be distinguishable in the output from `NOT_ASSESSABLE` — they mean opposite things to the person reading the report.

---

### B3 — Findings assembly

```
CONTEXT:     docs/01-architecture.md §5 S8; docs/02-trd.md §5 (findings response shape).
TASK:        backend/app/services/rules/findings.py
CONSTRAINTS: pure; every Finding carries rulepack_version (CLAUDE.md §3.6); message templates
             are rendered from the pack's `message` with {observed}/{required}/{qty}/{unit}/
             {surface}/{pdp}; a missing template variable raises — never an empty placeholder
             in a legal report.
SIGNATURE:
  def assemble(findings: Sequence[Finding], pack: RulePack) -> FindingsReport
  FindingsReport = {rulepack_version, summary: {pass, fail, borderline, na, not_applicable},
                    findings: [...]}
TESTS:       tests/test_findings.py — summary counts; template rendering; unknown placeholder raises.
DONE WHEN:   pytest tests/test_findings.py, mypy clean.
```

---

### B4 — Object storage adapter

```
CONTEXT:     docs/01-architecture.md §9 (R2 row), §10; infra/README.md §3; app/config.py S3_* block.
TASK:        backend/app/services/storage.py
CONSTRAINTS:
  - speak S3, never R2-specific APIs — an on-premise MinIO swap must be an endpoint change
  - no per-object ACL calls (R2 rejects them); access is presigned-only
  - key layout: {org_id}/{scan_id}/{kind}/{asset_id}.{ext} — the org prefix is mandatory
  - strip EXIF from anything that will be served; record sha256 of the bytes as received,
    BEFORE any processing (evidence integrity, §10)
  - MIME allow-list and max upload size enforced at presign time, not after upload
SIGNATURE:
  def presign_put(key: str, content_type: str, size_limit: int) -> PresignedUpload
  def presign_get(key: str, expires_in: int | None = None) -> str
  def put_bytes(key: str, data: bytes, content_type: str) -> StoredObject   # sha256 on the way in
  def get_bytes(key: str) -> bytes
DEPENDENCY:  needs `boto3`. ASK before adding.
TESTS:       tests/test_storage.py with a stubbed client — key layout, expiry, allow-list
             rejection, sha256 stability. One opt-in integration test against the real bucket,
             skipped without credentials.
DONE WHEN:   pytest tests/test_storage.py, mypy clean.
```

---

### B5 — Marker detection and metric rectification

```
CONTEXT:     docs/01-architecture.md §5 S1–S3; docs/02-trd.md FR-21; the P0 spike's measure.py.
TASK:        backend/app/services/vision/marker.py, backend/app/services/vision/rectify.py
CONSTRAINTS:
  - pure functions over arrays, no I/O, no file reads
  - PX_PER_MM imported from app.config — CLAUDE.md §8 names the hardcoded 20 as a known time
    sink. It must not appear as a literal at any call site.
  - arrays typed npt.NDArray[np.uint8]
  - marker absent -> return None, never an estimate. The caller marks the scan "no_marker".
  - detect high curvature and report it; rectify does not silently flatten a bottle
SIGNATURE:
  def detect_marker(img: NDArray[np.uint8]) -> MarkerCorners | None
  def rectify(img: NDArray[np.uint8], corners: MarkerCorners, marker_mm: float) -> Rectified
      # Rectified = {image, px_per_mm, homography, out_size}
  def quality(img: NDArray[np.uint8], corners: MarkerCorners | None) -> Quality
      # Quality = {blur, glare, tilt_deg, curvature}
DEPENDENCY:  needs `opencv-contrib-python` (ArUco is in contrib) and `numpy`. ASK before adding.
TESTS:       tests/test_rectify.py — a synthetic marker at known warps recovers the scale;
             a 10.00 mm bar measures 10.00 ± 0.25 across the committed fixture captures;
             no marker -> None; tilt beyond 25° reported, not silently corrected.
DONE WHEN:   pytest tests/test_rectify.py, mypy app/services clean,
             coverage ≥80% on services/vision.
```

`marker_mm` is per-scan (40 mm tag vs ID-1 card, TRD FR-02) and arrives from the request. It is a function argument, never a constant.

---

### B6 — OCR behind an interface

```
CONTEXT:     docs/02-trd.md FR-22; docs/01-architecture.md §5 S4, §9 (OCR row).
TASK:        backend/app/services/vision/ocr.py  (+ adapters/paddle.py, adapters/stub.py)
CONSTRAINTS:
  - the interface is the deliverable; the adapter is replaceable. FR-22 requires a second
    working implementation to prove the interface holds — the stub adapter replays a committed
    OCR dump and is what every downstream unit test uses.
  - engine choice comes from config; no calling code changes when it is swapped
  - polygons are returned as given; they are NOT heights (CLAUDE.md §8) and nothing in this
    module may convert a polygon to a millimetre
SIGNATURE:
  class OCREngine(Protocol):
      def detect_and_recognise(self, image: NDArray[np.uint8]) -> list[Word]
  Word = {text, polygon, confidence, language}
  def get_engine(name: str | None = None) -> OCREngine
DEPENDENCY:  needs `paddleocr` + `paddlepaddle` (large, CPU wheels). ASK — and ask about pinning
             the model files and where they are cached, because CI must not download them.
TESTS:       tests/test_ocr_interface.py — the stub adapter satisfies the Protocol; get_engine
             honours config; a Devanagari dump round-trips with language tags intact (NFR-08).
DONE WHEN:   pytest tests/test_ocr_interface.py, mypy clean.
```

---

### B7 — Glyph metrology

```
CONTEXT:     docs/01-architecture.md §5 S5; docs/02-trd.md FR-23;
             docs/03-implementation-plan.md §P0.2.
TASK:        backend/app/services/vision/metrology.py
CONSTRAINTS:
  - pure, no I/O, no global state
  - measurement is connected components on the rectified image, NEVER OCR polygons (CLAUDE.md §8)
  - cap-height is measured on numerals, which is why Rule 9 is written about numerals
  - every measurement carries an uncertainty widened by blur, tilt and px/mm
  - curvature above threshold -> return no measurement, so the rule lands NOT_ASSESSABLE
    (01-architecture.md §12.2). A confident under-measurement is the worst possible output.
  - glyphs excluded from the width ratio ("1", "i", "I", "l") are read from the pack's
    exclude_glyphs, not written here
SIGNATURE:
  def measure_text_span(warped: NDArray[np.uint8], bbox: BBox, quality: Quality) -> Measurement | None
  Measurement = {field_code, glyph, height_mm, width_mm, uncertainty_mm, method}
TESTS:       tests/test_metrology.py — synthetic glyphs at exact pixel heights; noise components
             dropped; baseline clustering; uncertainty grows with blur and tilt; high curvature
             returns None. ALREADY WRITTEN — DO NOT EDIT.
DONE WHEN:   pytest tests/test_metrology.py, mypy clean, coverage ≥80% on services/vision.
```

---

### B8 — LLM provider interface

```
CONTEXT:     CLAUDE.md §9; docs/01-architecture.md §9 (LLM vendor row).
TASK:        backend/app/services/llm/provider.py (+ adapters/)
CONSTRAINTS:
  - NO vendor name outside config and the adapter files — not in a comment, not in a variable
  - an open-weight adapter must work; a government deployment may be fully on-premise
  - three call sites only: extraction.llm_layer, reporting.explain, bis.answer
  - strict JSON-schema mode and temperature are parameters of the interface, because the
    extraction call site depends on both
  - failure is a first-class return, not an exception that kills a scan: LLM down means
    regex-only extraction and a report flagged "reduced extraction" (01-architecture.md §11)
SIGNATURE:
  class LLMProvider(Protocol):
      def complete(self, *, prompt: str, schema: dict | None, temperature: float,
                   max_tokens: int, tier: Literal["budget", "mid"]) -> LLMResult
  LLMResult = {text, parsed: dict | None, usage, ok: bool, error: str | None}
DEPENDENCY:  one HTTP client (`httpx` is already a dev dep — promote it) plus the open-weight
             adapter's client. ASK.
TESTS:       tests/test_llm_provider.py — a schema violation surfaces as ok=False, never as a
             partial dict; a provider timeout returns ok=False; no vendor string appears in the
             interface module (grep assertion).
DONE WHEN:   pytest tests/test_llm_provider.py, mypy clean.
```

---

### B9 — Field extraction

```
CONTEXT:     docs/01-architecture.md §5 S6; docs/02-trd.md FR-24;
             docs/03-implementation-plan.md §P2.5.
TASK:        backend/app/services/extraction/{regex_layer,normalise,llm_layer,pipeline}.py
CONSTRAINTS:
  - order is fixed: regex -> LLM for what regex missed -> human confirmation below 0.75
  - the unit normalisation table comes from the rule pack's
    tables.unit_symbols.rejected_variants, not from a dict in Python. The pack already carries
    gms/Gms/gm/GM/ltr/Ltr/LTR/lts.
  - the LLM gets the OCR text as its ONLY context, temperature 0, strict JSON schema
  - EVERY field carries a source_span, and that span is verified to exist in the input text
    before the value is accepted (CLAUDE.md §8). Do not trust the model's span.
  - 15 field codes exactly as listed in FR-24
  - money as integer paise; lengths as float millimetres
SIGNATURE:
  def extract(words: Sequence[Word], profile: Profile, *, llm: LLMProvider | None) -> list[Extraction]
  Extraction = {field_code, value_raw, value_norm, source: Literal["regex","llm","human"],
                confidence, bbox, source_span: tuple[int, int]}
TESTS:       tests/test_extraction.py — 20 committed OCR dumps; regex-only recall for
             net_quantity ≥0.8; with the stub LLM ≥0.95; a fabricated span is rejected;
             "250 gms" normalises to value 250 unit g with the raw string preserved.
DONE WHEN:   pytest tests/test_extraction.py, mypy clean.
```

---

### B10 — `process_scan`, the pipeline task

```
CONTEXT:     docs/01-architecture.md §5 (all ten stages); docs/03-implementation-plan.md §P2.3;
             docs/02-trd.md NFR-04.
TASK:        backend/app/services/pipeline.py  (the logic)
             backend/app/tasks/scan.py         (the thin Celery binding)
             register the task module in worker.py's include=[]
CONSTRAINTS:
  - the Celery task is a five-line wrapper. All logic lives in services/ so it is testable
    without a broker and callable from the API.
  - status machine: queued -> processing -> complete | failed | no_marker
  - idempotent: re-running a completed scan must not duplicate findings
  - acks_late is already set; the task must be safe to run twice after a worker kill
  - no marker -> mark the scan no_marker, run presence/format rules only, mark every metric
    rule NOT_ASSESSABLE (01-architecture.md §11) — do not abort the scan
  - LLM unavailable -> regex-only, scan completes, report flagged "reduced extraction"
TESTS:       tests/test_pipeline_golden.py — one committed fixture image in,
             tests/fixtures/expected_findings.json out, byte-identical. A diff here is a
             reviewed change, never a silent update (CLAUDE.md §6).
             tests/test_pipeline_degraded.py — no-marker path, LLM-down path, re-run idempotency.
DONE WHEN:   both suites pass; killing the worker mid-job leaves the scan completing on retry.
```

---

### B11 — Reporting

```
CONTEXT:     docs/02-trd.md FR-27; docs/01-architecture.md §5 S10, §10; CLAUDE.md §3.8.
TASK:        backend/app/services/reporting/{model,pdf,docx,json_report,explain}.py
CONSTRAINTS:
  - PDF and DOCX render from ONE shared data structure so they cannot drift
  - the DOCX findings table must be a real w:tbl, editable in Word and LibreOffice
  - every report carries: annotated image, findings table, rulepack_version, both SHA-256
    hashes, and the advisory disclaimer (CLAUDE.md §3.8) — the disclaimer is not optional and
    cannot be configured off
  - reporting.explain is an LLM call site: it writes plain-language guidance for a finding and
    NEVER changes a verdict
DEPENDENCY:  needs `weasyprint` (PDF) and `python-docx`. ASK — weasyprint has native
             dependencies (pango/cairo) that the deploy VM must have, so raise it with infra at
             the same time.
TESTS:       tests/test_reporting.py — the same scan to both formats: identical row count,
             identical verdict strings; the DOCX table is a w:tbl and not an image; the
             disclaimer string is present in all three outputs.
DONE WHEN:   pytest tests/test_reporting.py, mypy clean.
```

---

### B12 — Data layer and org scoping

```
CONTEXT:     docs/01-architecture.md §8 (every table), §10; CLAUDE.md §3.7.
TASK:        backend/app/models/*.py, backend/app/repositories/base.py,
             alembic/versions/0001_*.py
CONSTRAINTS:
  - ★ CLAUDE.md §7: schema changes and migrations are ASK-FIRST. Bring the proposed DDL for
    review before writing the migration.
  - org scoping is enforced in the repository base class, not remembered at each call site.
    A query that cannot name its org must not get past the base class.
  - cross-org access returns 404, never 403 — do not leak existence
  - findings is append-only; a correction writes a new row, it never updates one
  - migrations run on DATABASE_URL_DIRECT (pgbouncer cannot do DDL reliably in a transaction)
  - the first migration creates the pgvector extension; bis_chunks.embedding is vector(1024)
SIGNATURE:
  class OrgScopedRepository(Generic[T]):
      def __init__(self, session: Session, org_id: UUID) -> None
      def get(self, id: UUID) -> T | None      # returns None for another org's row
      def list(self, **filters: object) -> Sequence[T]
TESTS:       tests/test_org_isolation.py — a user in org A requesting org B's scan, product,
             finding, report and bis_query each get 404. Runs on every PR (CLAUDE.md §6).
DONE WHEN:   alembic upgrade head against a Neon branch, then the isolation suite green.
```

Create these indexes in the same migration, because B17 needs them and adding them later against a populated table is a lock: `findings(scan_id)`, `findings(rule_id, verdict)`, `scans(org_id, captured_at)`, `extractions(scan_id, field_code)`, and the HNSW index on `bis_chunks.embedding`.

---

### B13 — Auth and RBAC

```
CONTEXT:     docs/01-architecture.md §10; docs/02-trd.md §5 (auth endpoints).
TASK:        backend/app/routers/auth.py, backend/app/services/auth/{otp,tokens,rbac}.py
CONSTRAINTS:
  - org_id comes from the verified token and NOWHERE else. A request body carrying an org_id
    is a 400, not an override.
  - roles admin | inspector | analyst | viewer, enforced by a dependency, not by if-statements
    inside handlers
  - OTP codes hashed at rest, rate-limited per phone and per IP, single-use, short TTL
  - refresh rotation; a reused refresh token invalidates the family
DEPENDENCY:  a JWT library and a hasher. ASK.
TESTS:       tests/test_auth.py — the role matrix (each role × each endpoint); a body-supplied
             org_id is rejected; OTP replay rejected; expired refresh rejected.
DONE WHEN:   pytest tests/test_auth.py, mypy clean.
```

---

### B14 — Scan intake API

```
CONTEXT:     docs/02-trd.md FR-20, FR-02, §5; the existing docstring in app/routers/scans.py.
TASK:        backend/app/routers/scans.py (create/submit/get), backend/app/schemas/scans.py
CONSTRAINTS:
  - POST /v1/scans returns presigned upload URLs; the API never proxies image bytes
  - submit returns 202 {status:"queued"} inside 300 ms — it enqueues and returns, it does not
    touch an image
  - a scan cannot be submitted without marker_type and marker_mm (FR-02)
  - Idempotency-Key honoured on both POSTs
  - routers hold no pipeline logic; they validate, call repositories/services, shape output
TESTS:       tests/test_scans_api.py — the 202 shape and latency; missing marker_mm -> 422 in
             the NFR-07 envelope; a replayed Idempotency-Key returns the original scan, not a
             second one.
DONE WHEN:   pytest tests/test_scans_api.py; the OpenAPI schema regenerates cleanly for mobile.
```

Changing this contract after mobile has generated its client is ASK-FIRST (`CLAUDE.md` §7). Publish the OpenAPI schema the day this lands, so `mobile/` can run `npm run gen:api` and mock with MSW instead of waiting.

---

### B15 — Findings API and field confirmation

```
CONTEXT:     docs/02-trd.md FR-05, FR-06; §5 findings response shape.
TASK:        backend/app/routers/scans.py (findings + confirm-fields), schemas/findings.py
CONSTRAINTS:
  - the response always carries rulepack_version and the summary block
  - confirm-fields records the correction with source=human and RECOMPUTES by calling
    evaluate() again with the same as_of and the same pack version the scan was first
    evaluated under — not the currently active pack. A report regenerated next year must
    reproduce the original verdict (CLAUDE.md §3.6).
  - the recompute writes new finding rows; it never mutates the old ones
TESTS:       tests/test_confirm_fields.py — a correction flips a FAIL to PASS; the original
             finding row survives; the new findings carry the ORIGINAL pack version.
DONE WHEN:   pytest tests/test_confirm_fields.py.
```

---

### B16 — Audit hash chain

```
CONTEXT:     docs/01-architecture.md §10; docs/03-implementation-plan.md §10 release gates.
TASK:        backend/app/services/audit.py, backend/app/routers/admin.py (verify endpoint)
CONSTRAINTS:
  - hash = H(prev_hash || canonical_row_json); canonicalisation must be stable across Python
    versions (sorted keys, explicit separators, UTF-8)
  - append-only; no update path for this table exists in the repository layer
  - the verification endpoint reports the first broken link, not just a boolean
TESTS:       tests/test_audit_chain.py — a tampered row breaks verification at that row and not
             before it; the chain survives a process restart.
DONE WHEN:   pytest tests/test_audit_chain.py.
```

---

### B17 — Dashboards

```
CONTEXT:     docs/02-trd.md FR-30.
TASK:        backend/app/routers/dashboard.py, backend/app/repositories/aggregates.py
CONSTRAINTS: aggregation in SQL, not in Python; org-scoped like everything else;
             group_by is an enum, never interpolated into SQL.
TESTS:       tests/test_dashboard.py — 50,000 seeded findings, each endpoint under 1 s;
             a group_by value outside the enum -> 422.
DONE WHEN:   pytest tests/test_dashboard.py with the seed fixture.
```

---

### B18 — BIS corpus ingest ★ has a hard legal constraint

```
CONTEXT:     docs/01-architecture.md §7; docs/03-implementation-plan.md §P4.1; CLAUDE.md §3.5.
TASK:        backend/app/services/bis/ingest.py
CONSTRAINTS:
  - ★ NEVER ingest priced Indian Standards texts. The module carries an explicit blocklist
    WITH the comment explaining why. Keep both. This is not a style preference; it is the
    difference between a demo and a copyright problem.
  - allowed source_types only: qco_gazette | mandatory_cert_list | crs_list | scheme_guide |
    faq | hallmarking | lab_directory | catalogue_metadata
  - every document records source_type, url, published_at, sha256
  - chunks of 400–600 tokens, each with a section_ref
TESTS:       tests/test_bis_ingest.py — a document whose source looks like a priced IS text is
             REFUSED with a named error; the blocklist is non-empty; allowed types ingest;
             sha256 dedupe works on re-ingest.
DONE WHEN:   pytest tests/test_bis_ingest.py.
```

---

### B19 — Hybrid retrieval

```
CONTEXT:     docs/01-architecture.md §7; docs/02-trd.md FR-28.
TASK:        backend/app/services/bis/retrieve.py
CONSTRAINTS: BM25 via Postgres FTS (no new dependency) + dense via pgvector, RRF fusion,
             cross-encoder rerank top 30 -> top 6; embeddings are BGE-M3, self-hosted;
             retrieval is deterministic given a fixed corpus — no temperature anywhere here.
DEPENDENCY:  the embedding model runtime and the reranker. ASK — these are the heaviest
             additions in the project, and CI must not download weights.
TESTS:       tests/test_retrieval.py — RRF ordering on a fixed toy corpus is exact;
             an empty result set returns empty, never a nearest-anything chunk.
DONE WHEN:   pytest tests/test_retrieval.py.
```

---

### B20 — Sahayak answer and BIS applicability

```
CONTEXT:     docs/01-architecture.md §7; docs/02-trd.md FR-28, FR-29;
             docs/03-implementation-plan.md §P4.
TASK:        backend/app/services/bis/{answer,applicability}.py, backend/app/routers/sahayak.py
CONSTRAINTS:
  - ★ applicability is a TABLE LOOKUP against the QCO/CRS lists, not retrieval. Retrieval is
    used only for the explanation and next steps. A lookup is deterministic; retrieval is not,
    and "does this product need the ISI mark" is not a question to answer probabilistically.
  - generation is citation-required: every claim maps to a chunk id. Post-validate that each
    cited chunk id exists AND that every numeric claim in the answer appears in a cited chunk.
    Unsupported -> refuse and return the closest official page link.
  - refusing priced-standard content is a FEATURE. The refusal says so plainly and points at
    the BIS purchase route.
  - answers carry an as_of freshness stamp — QCOs are amended constantly
SIGNATURE:
  def applicability(profile: Profile) -> Applicability
      # {qco_applicable: "yes"|"no"|"unclear", scheme: "ISI"|"CRS"|"FMCS"|"none",
      #  candidate_is_numbers: [...], next_steps: [...], sources: [...]}
TESTS:       tests/test_bis_answer.py — a fabricated chunk id fails post-validation; a numeric
             claim absent from the cited chunks fails; all 10 unanswerable questions are refused.
             tests/test_applicability.py — the 20 known products from FR-29, ≥17 correct.
DONE WHEN:   both suites pass; E4 reports the output shape in 03-implementation-plan.md §P4.
```

---

### B21 — Bulk listing check (Mode B)

```
CONTEXT:     docs/02-trd.md FR-10.
TASK:        backend/app/services/listings.py, backend/app/routers/products.py (bulk endpoint)
CONSTRAINTS: a listing has no physical scale, so EVERY metric rule is NOT_ASSESSABLE on this
             path. Make it structurally impossible for a metric rule to return PASS or FAIL
             from listing text — pass an empty measurement set, and assert that in the test.
TESTS:       tests/test_bulk_listing.py — a 50-row CSV yields 50 results and a summary;
             no metric rule in any row is PASS or FAIL.
DONE WHEN:   pytest tests/test_bulk_listing.py.
```

---

### B22 — Evaluation harness

```
CONTEXT:     docs/02-trd.md §7; docs/eval-results.md (output formats); CLAUDE.md §4.
TASK:        backend/scripts/{eval_e1,eval_e3,eval_e4}.py   (new package: backend/scripts/)
CONSTRAINTS: print exactly the output shapes in 03-implementation-plan.md §P0.4 and §P4;
             read corpora from ../eval/, which is gitignored — the scripts commit numbers,
             never images; every run prints the commit sha and the rule pack version, because
             a number that cannot name its pack cannot be reproduced.
DONE WHEN:   each script runs end to end and its output pastes into docs/eval-results.md.
```

E3's headline is the **false-FAIL rate**, target ≤2%. Print it on its own line; it is the number that decides whether anyone trusts the tool.

---

### B23 — Hardening

```
CONTEXT:     docs/02-trd.md NFR-01, docs/03-implementation-plan.md §10 release gates;
             docs/01-architecture.md §10.
TASK:        rate limiting, load test, dependency audit, API reference, rule pack authoring guide
CONSTRAINTS: rate limits per org and per IP; presigned URL expiry verified; EXIF stripping
             verified on served assets; load test to NFR-01 (p50 ≤10 s, p95 ≤20 s, 50 concurrent)
             INCLUDING a Neon cold start in the measurement, since 01-architecture.md §11 charges
             that cold start against NFR-01.
DONE WHEN:   the §5 gates below are all green and the numbers are in docs/eval-results.md
             with a date.
```

---

## 4. Dependencies to request

`CLAUDE.md` §7: **every one of these needs an explicit ask before it is added.** Batch them per package rather than one at a time.

| Package | Dependency | For | Notes |
|---|---|---|---|
| B1 | `jsonschema` | rule pack validation | small, pure Python |
| ✅ B4 | `boto3`, `pillow` | R2 via the S3 API; EXIF stripping | **Added.** Pillow declared explicitly, not leaned on as a WeasyPrint transitive |
| ✅ B5, B7 | `opencv-contrib-python`, `numpy` | ArUco + homography + connected components | **Added.** ArUco is in **contrib**; the plain wheel will not do |
| ✅ B6 | `paddleocr`, `paddlepaddle` | OCR | **Added as the `[ocr]` extra, not a core dep** — CI must never download model weights. Lazy import; stub adapter stands in |
| B8 | `httpx` (promote from dev) | LLM adapters | |
| B9 | `python-dateutil`, possibly `regex` | month-year resolution, Unicode classes for Devanagari | |
| ✅ B11 | `weasyprint`, `python-docx` | PDF, DOCX | **Added.** GTK3 native stack needed only by `render_pdf`; CI installs it, Windows dev skips that one test |
| ✅ B12 | `pgvector` (Python bindings) | the vector column type | **Added.** Also gives B19 its similarity operators. Declared `with_variant`, so SQLite still builds the schema for CI |
| ✅ B13 | a JWT library, a hasher | auth | **Refused — none added.** HS256 is written against stdlib `hmac` (`services/auth/tokens.py`, with a test per attack class); OTP codes and refresh tokens use peppered HMAC-SHA256, since a six-digit code is protected by single use, a short TTL and rate limiting, not by the cost of its hash |
| ✅ B19 | `sentence-transformers` | BGE-M3 embeddings, cross-encoder rerank | **Answered — added as the `[bis]` extra, not a core dep**, on the same terms as `[ocr]`: it pulls torch and fetches weights on first use, which CI must never do. One package carries both runtimes (`BAAI/bge-m3`, `BAAI/bge-reranker-v2-m3`). The adapters still import it inside the adapter, so `services/bis/` imports and type-checks without it, and `hashing`/`overlap` remain the configured stand-ins. **Model revisions are not yet pinned** — the ask asked for that and it is still owed; both adapters resolve whatever revision the hub serves, so a corpus embedded today and a query embedded after an upstream re-release are not guaranteed to share a vector space. |
| ✅ B23 | a rate limiter, a load-test tool | NFR-01 | **Refused — none added.** The limiter is `redis` (already a dependency) plus an in-memory backend on stdlib `threading`; the load test is `scripts/loadtest.py` on `httpx`, already a dev dep. `pip-audit` stays undeclared and is installed on demand by `make audit` — a security scanner does not belong in a deployed image. |
| tests | `pytest-cov` | the 80% coverage floor | `freezegun` should not be needed — `evaluate()` takes `as_of` |

Everything else in the stack is already declared in `backend/pyproject.toml`.

---

## 5. Backend release gates

A subset of `03-implementation-plan.md` §10, restricted to what the backend owns. None of these are optional.

Status as of 12 Sep 2026, after B23. **Every gate that needs only code is green; the four that are
open need a corpus, a deployment, a migration run or a practitioner's calendar — none of them can
be closed by writing more backend.**

- [x] `pytest` green, including `test_org_isolation` and the golden-file pipeline test
- [x] `ruff check .` and `mypy app/services` clean; coverage ≥80% on `services/rules` and `services/vision`
- [ ] E1 and E3 numbers committed and dated in `docs/eval-results.md`; false-FAIL rate ≤2% — **the harness runs (B22); the corpora do not exist yet (TRD §7)**
- [x] E4 refusals 10/10 correct on priced-standard questions — `tests/test_bis_answer.py`, including the TRD's own "tensile limit in IS 1786" example
- [x] Every finding and every report stamped with `rulepack_version`
- [x] Advisory disclaimer present in PDF, DOCX and JSON outputs
- [x] Hash-chain verification endpoint working and documented (`docs/06-api-reference.md`)
- [x] No threshold, table row or effective date anywhere in a `.py` file — grepped by `tests/test_hardening.py`
- [x] BIS ingest blocklist present, tested, and its comment intact — a test reads the source and fails if the comment goes
- [x] `GET /health` returns the real active pack version, and `degraded` when a dependency is down
- [x] OpenAPI schema published (`make openapi`) — `mobile/`'s generated client still has to be built against it
- [ ] **`alembic upgrade head` against Neon** — migration 0003 is written and reviewed, not applied. `tests/test_migration.py` fails until it is
- [ ] **NFR-01 load test numbers** — `scripts/loadtest.py` is written; it needs a staging deployment with a worker
- [ ] Legal review of the rule pack booked (November) — a release blocker, not a nice-to-have

---

## 6. If the backend timeline compresses

Ranked by demo value per hour. Drop from the bottom, never from the top.

1. **B1 + B2 + B3** — the rules engine over the pack. Deterministic, citable verdicts from fixture input. Nothing else demonstrates the idea.
2. **B5 + B7** — rectification and millimetre glyph heights. The one thing no other team will have.
3. **B11** — the PDF with citations. Turns a script into a product.
4. **B12 + B14 + B15** — the data layer and API, so the phone can talk to it.
5. **B9** — extraction. Until this lands, fixtures stand in for it.
6. **B20 applicability lookup only** — proves the two problem statements are one system. Cheap, because it is a table.
7. **B19 + B20 free chat** — the most impressive-sounding and the most droppable.

Note what this ordering implies: a fixture-driven backend that produces a real, cited, correctly-measured PDF verdict is worth more in a demo than a complete API with a guessed millimetre in it.

---

## 7. Standing traps

The ones from `CLAUDE.md` §8 that will actually bite in backend code, plus two this plan adds.

- `PX_PER_MM` is imported from config. Never `20` at a call site.
- OCR bounding boxes are not glyph heights. Measurement goes through connected components on the rectified image.
- Neon's pooled endpoint is pgbouncer: keep `prepare_threshold=None`, and run migrations on `DATABASE_URL_DIRECT`.
- Celery does not infer TLS from `rediss://`; `broker_use_ssl` is set off the URL scheme in `worker.py`.
- **An unidentifiable glyph is not a numeral.** Rule 9 compares the *smallest* numeral against the threshold, so anything wrongly counted as one decides the verdict. The two dots of the colon in "Net Qty: 250 g" failed a compliant label at 0.75 mm until cap height was used to tell a digit from a mark. When in doubt, a component is neither a numeral nor a letter.
- **Format rules read `value_raw`, never `value_norm`.** Normalisation turns "250 gms" into "250 g" — exactly the defect `LM-QTY-UNIT-SYMBOL` exists to catch — so reading the normalised value makes the rule pass every label it was written for.
- **Metric error is relative, not absolute.** FR-21's ±0.25 mm is stated against a *10 mm* feature — it is a 2.5% figure. The dominant term is ArUco's corner localisation (~1 px on a 200 px marker = 0.5%), which scales with feature size, so a 40 mm object legitimately reads ~0.2 mm long. Do not treat ±0.25 mm as an absolute budget that holds at any size, and do not test it by re-detecting the marker — the marker defined the scale and is guaranteed to come back right.
- **A quality signal that cannot be measured is `None`, never `0.0`.** `quality().curvature` is `None` because four marker corners carry no curvature information. `0.0` would assert a flatness nobody measured, and architecture §12.2's NOT_ASSESSABLE safeguard depends on that number being trustworthy.
- **Recompute uses the scan's original pack version, not the active one.** The obvious implementation of `confirm-fields` is wrong in a way no test catches unless you write that test (B15).
- **"Does not apply to you" and "we could not measure it" are different outcomes.** Verdicts stay four-valued, so the first is the *absence* of a finding plus an entry in `not_applicable_rule_ids`, and the second is a `NOT_ASSESSABLE` finding that still states what would have been required. Collapsing them turns a clean report into an accusation; treating absence as a pass hides a rule that was never checked.


---

### B24 — The API surface the mobile client was written against

Added after the app and the backend were read against each other for the first time. The full gap
register, and what each change was for, is `docs/06-wiring-contract.md`.

```
CONTEXT:     docs/06-wiring-contract.md (the whole document); TRD FR-05, FR-06, FR-08, FR-09, FR-27.
TASK:        app/schemas/findings.py, app/schemas/scans.py, app/routers/scans.py,
             app/routers/products.py, app/routers/reports.py (new),
             app/routers/pagination.py (new), app/main.py
CONSTRAINTS:
  - the findings response carries extractions with their REAL confidence and source. The client
    decides what to ask a human about (FR-06) and whether a report may be issued (FR-08) from
    exactly those two fields; defaulting confidence to 1.0 disables both and fails nothing.
  - findings_sha256 is the STORED column, never recomputed. A second implementation of the same
    claim disagrees with the report the first time either changes.
  - the verdict filter matches ONE verdict. Never widen FAIL to mean "has a problem" — that is
    CLAUDE.md §3.4 delivered through a search box, and it makes the list look better.
  - keyset cursors, not offsets; a malformed cursor is 422, never a silent page one.
  - district is recorded from the client, never derived from coordinates.
  - a report names the evaluation it states, so a later correction cannot change what an
    already-issued document meant.
  - no migration without asking (CLAUDE.md §7) — which is why report generation is synchronous.
TESTS:       tests/test_findings_api.py, tests/test_scan_list.py, tests/test_products_api.py,
             tests/test_reports_api.py, plus additions to tests/test_scans_api.py and
             tests/test_bulk_listing.py. The seeded archive in test_scan_list.py must contain a
             scan that is BORDERLINE with no failure — without it, a collapsed verdict filter
             passes every test in the file.
DONE WHEN:   pytest && ruff check . && mypy app/services
```

**Left open, and why:** report generation is synchronous because a `pending` status needs
`reports.status` and `reports.error`, which is a migration and therefore needs agreement first
(CLAUDE.md §7). `remediation` on a finding is neither a column nor a field in the rule pack, so it
needs a decision about which it should be. `POST /v1/products` is in TRD §5 and no client needs it
yet.
