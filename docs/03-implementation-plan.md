# Anupalan — Implementation Plan

**Doc version:** v1.0 · Companion to `01-architecture.md` and `02-trd.md`
**Today:** 12 Sep 2026 · **SIH idea submission deadline:** 30 Sep 2026

Format note: each phase lists numbered steps, the exact command or pseudocode, and a test with expected output. Hand phases to Claude Code one at a time; do not hand it the whole document.

---

## 0. Timeline

| Phase | Window | Goal | Done when |
|---|---|---|---|
| P0 Spike | Sep 12–18 | Prove millimetre measurement works | E1 MAE reported with a number |
| P1 Submission | Sep 19–30 | SIH idea + deck + 90-second demo video | Submitted before deadline |
| P2 Core backend | Oct 1–21 | Pipeline + rules + reports end to end | 50 real labels processed |
| P3 Mobile | Oct 15–Nov 7 | Full Android app on the real backend | Installable APK, offline queue works |
| P4 Sahayak | Nov 1–21 | BIS corpus + retrieval + applicability | E4 numbers reported |
| P5 Hardening | Nov 22–Dec 10 | Eval, dashboards, security, docs | All §11 gates green |
| P6 Pilot | Dec 2026 → | 5 brands + 1 agency using it weekly | 10 paying or committed users |

P2 and P3 overlap deliberately: mobile builds against a mocked API contract from day one.

---

## P0 — Measurement spike (Sep 12–18)

**This is the only phase that can kill the project, so it runs first.** Everything else is known engineering.

1. **Generate the marker and the test chart.**
   ```bash
   mkdir -p anupalan/spike && cd anupalan/spike
   python -m venv .venv && source .venv/bin/activate
   pip install opencv-contrib-python numpy reportlab pillow
   ```
   Write `make_chart.py` producing an A4 PDF with: one ArUco 4×4_50 tag, id 0, at exactly 40.0 mm, plus digit strings `0123456789` rendered at cap-heights 0.8, 1.0, 1.5, 2.0, 2.5, 4.0, 6.0 mm, each labelled. Print at 100% scale, no fit-to-page. Verify the printed tag with a ruler; if it is not 40 mm, the printer scaled it and every downstream number is wrong.

2. **Write `measure.py`.**
   ```
   detect_marker(img)          -> corners (4x2 float32) or None
   rectify(img, corners, mm)   -> warped image at PX_PER_MM = 20
       target = [[0,0],[mm*20,0],[mm*20,mm*20],[0,mm*20]] shifted to keep the page in frame
       H = cv2.getPerspectiveTransform(corners, target)
       return cv2.warpPerspective(img, H, out_size)
   measure_glyphs(warped, roi) -> list of {height_mm, width_mm}
       gray -> cv2.adaptiveThreshold(..., BINARY_INV, 35, 10)
       n, labels, stats, _ = cv2.connectedComponentsWithStats(bin)
       for each component: drop if area < 12 px or height < 4 px (noise)
       cluster components by baseline (y of bottom edge, tolerance 3 px)
       for each cluster: height_mm = median(component heights) / 20
       return per-cluster measurements
   quality(img) -> {blur: variance_of_laplacian, glare: frac(pixels>250), tilt: angle_from_homography}
   ```

3. **Shoot E1.** 60 chart captures: 3 distances (10, 25, 40 cm) × 3 angles (0°, 15°, 25°) × 2 lighting × varied phones. Store as `spike/e1/<phone>_<dist>_<angle>_<light>.jpg` with a `truth.csv` of expected heights.

4. **Report the number.**
   ```bash
   python evaluate_e1.py --dir spike/e1 --truth spike/e1/truth.csv
   ```
   Expected output shape:
   ```
   samples: 420 glyph rows across 60 images
   MAE: 0.18 mm   |  within ±0.3mm: 92.4%  |  within ±0.5mm: 98.1%
   worst case: 0.71 mm  (angle=25, dist=40, light=dim)
   by truth height:  0.8mm MAE 0.24 | 1.0mm 0.19 | 2.0mm 0.14 | 4.0mm 0.11 | 6.0mm 0.09
   ```

**Decision gate.** MAE ≤ 0.3 mm and ≥ 90% within ±0.3 mm → proceed as planned; this becomes your headline slide. MAE 0.3–0.5 mm → proceed, but tighten capture gates (max 15° tilt, max 30 cm) and widen the BORDERLINE band. MAE > 0.5 mm → do not claim automated font checking. Reposition to presence/format checking plus assisted measurement where the user taps the two ends of a glyph. Decide this in week one, not in the demo.

---

## P1 — SIH submission (Sep 19–30)

1. **Write the idea submission.** Structure: problem framing in one paragraph, the joint-scan insight (§2 of the architecture doc), architecture diagram, the P0 measurement number, tech stack, feasibility, impact, and a named dual-use story (enforcement + industry).
2. **Record a 90-second demo.** A real label, a real measurement, one real FAIL with a citation. A working 30% beats a mocked 100%; judges have seen every fake demo.
3. **Pre-write answers to the five questions you will be asked:** why not Google Vision; how accurate; what stops Amazon building it; what about standards copyright; what happens when the rules change. Two sentences each, memorised.
4. **Have one real user quote.** Walk into five shops or one packaging agency in Kalyani this week, show the spike, and write down what they say. One sentence from a real brand owner is worth more than any slide.

---

## P2 — Core backend (Oct 1–21)

### P2.1 Scaffold
Repo layout is defined in `CLAUDE.md` §2 and is the single source of truth. In short: one root folder, `mobile/` for the React Native app, `backend/` for FastAPI plus the Celery worker (one codebase, two entrypoints — the worker imports `app/services/`, so pipeline code is written once), `rulepacks/` for the YAML packs, `docs/`, `infra/`.

There is no local infrastructure to stand up. Postgres is **Neon**, Redis is **Redis Cloud**, object storage is **Cloudflare R2**; provision them once per `infra/README.md` and paste the connection strings into `backend/.env`. Note the two Neon URLs — pooled for the app, direct for Alembic.

```bash
cd backend
cp .env.example .env          # paste the Neon, Redis Cloud and R2 values
make -C .. check              # confirms db + redis answer before you start anything
alembic upgrade head          # uses DATABASE_URL_DIRECT, Neon's non-pooled endpoint
uvicorn app.main:app --reload
celery -A app.worker worker -l info
```
Expected: `GET /health` → `{"status":"ok","db":"ok","redis":"ok","rulepack":"LM-2011-v1.0"}`

A component reading `error` there means its URL is unset or unreachable — the API still answers 200 with `status: degraded`, by design.

### P2.2 Data layer
Migrations for every table in architecture §8. Enforce org scoping in a base repository class so no query can forget it.
*Test:* `test_org_isolation` — user in org A requests a scan from org B → 404 (not 403; do not leak existence).

### P2.3 Vision pipeline as a Celery task
```
@task(bind=True, max_retries=3)
def process_scan(scan_id):
    scan = load(scan_id)
    for asset in scan.raw_assets:
        img = download(asset)
        q = quality(img)
        corners = detect_marker(img)
        if corners is None: mark(scan, "no_marker"); return
        warped, px_per_mm = rectify(img, corners, scan.marker_mm)
        store(warped, kind="rectified")
        words = ocr.detect_and_recognise(warped)
        store_ocr(scan, words)
    extractions = extract_fields(words, scan.profile)       # regex -> llm -> flag low conf
    measurements = measure_fields(warped, extractions, q)   # only for fields needing mm
    findings = evaluate(scan.profile, extractions, measurements,
                        rulepack=active_pack(), as_of=scan.captured_at)
    persist(findings); mark(scan, "complete")
```
*Test:* golden-file test — one fixture image in, a committed `findings.json` out, byte-identical. Any change to that file must be a deliberate, reviewed diff.

### P2.4 Rules engine
Implement the interpreter for `presence | format | metric | conditional | composite` against `rulepacks/lm-2011-v1.yaml`. Keep it a pure function (TRD FR-25).

*Test cases with expected output:*

| # | Input | Expected |
|---|---|---|
| 1 | net_qty present, 250 g, numeral height 2.4 mm, printed | `LM-9-2-TABLE1` → PASS (required 2.0) |
| 2 | same, height 1.9 mm | FAIL, observed 1.9, required 2.0 |
| 3 | same, height 2.05 mm, uncertainty 0.25 | BORDERLINE, band "1.80–2.30" |
| 4 | same, no marker → no measurement | NOT_ASSESSABLE |
| 5 | 250 g, embossed, height 3.5 mm | FAIL (required 4.0 for embossed) |
| 6 | mrp absent | `LM-6-1-E` FAIL, citation Rule 6(1)(e) |
| 7 | mrp "₹250" without inclusive-of-taxes wording | `LM-MRP-FORMAT` FAIL |
| 8 | is_imported=false, importer fields absent | `LM-6-1-IMPORTER` skipped, not FAIL |
| 9 | is_imported=true, importer address absent | FAIL |
| 10 | e-commerce listing, imported, no COO filter, as_of=2026-10-01 | `LM-6-10A` NOT_APPLICABLE (effective 2027-07-01) |
| 11 | same, as_of=2027-08-01 | FAIL |
| 12 | net qty by number, PDP 300 cm², height 1.8 mm | `LM-9-2-TABLE2` FAIL (required 2.0) |
| 13 | glyph height 4.0 mm, width 1.1 mm | `LM-9-3-WIDTH` FAIL (required ≥1.33) |
| 14 | glyph is numeral "1", width 0.6 mm, height 4.0 | PASS (excluded) |

### P2.5 Extraction
Regex layer first, with a normalisation table for units (`gms|Gms|gm → g`, `ltr|Ltr → l`). LLM layer second, one call, strict JSON schema, temperature 0, with the OCR text as sole context and a required `source_span` per field.
*Test:* on 20 fixture OCR dumps, regex-only recall for `net_quantity` ≥ 0.8; with the LLM layer ≥ 0.95; no field is ever returned without a `source_span` that exists in the input.

### P2.6 Reporting
PDF via WeasyPrint (HTML template) and DOCX via python-docx, from one shared data structure so they cannot drift.
*Test:* generate both from the same scan; assert the findings table has identical row count and identical verdict strings in both; assert the DOCX table is a real `w:tbl`.

---

## P3 — Mobile (Oct 15–Nov 7)

1. From the repo root: `npx create-expo-app mobile -t` → add `expo-dev-client`, `react-native-vision-camera`, `react-native-mmkv`, `expo-sqlite`, `@tanstack/react-query`, `zustand`, `react-hook-form`, `react-native-svg`.
2. Build the dev client immediately (`eas build --profile development --platform android`). Vision-camera frame processors do not run in Expo Go — discovering this in week three costs days.
3. Marker detection on device: a small native frame processor plugin wrapping OpenCV ArUco. If that stalls, ship the interim version that uploads a frame every 500 ms for server-side gate checks, and swap later. Do not let the plugin block the rest of the app.
4. Screens in order: Capture → Context form → Processing → Findings → Report → History → Sahayak.
5. Offline queue with a state machine per scan: `captured → queued → uploading → processing → complete | failed`, persisted in SQLite, retried with backoff.
6. Mock the API with MSW from the OpenAPI schema so mobile never waits on backend.

*Tests:* FR-01 gate behaviour on a real device; FR-04 airplane-mode sequence exactly as written in the TRD; findings overlay boxes align with the rectified image at all zoom levels.

---

## P4 — Sahayak (Nov 1–21)

1. **Build the corpus.** Scripted ingestion, each source with a `source_type`, `url`, `published_at`, `sha256`: gazette QCO PDFs, BIS mandatory-certification product list, CRS product list, BIS scheme guides and FAQs, hallmarking pages, lab directory, catalogue metadata (IS number, title, scope, ICS, year, amendments). **Do not ingest priced standard texts.** Put that rule in the ingestion code as an explicit blocklist with a comment, so nobody adds it later by accident.
2. Chunk at 400–600 tokens with section-reference metadata; embed with BGE-M3 (multilingual, handles Hindi); store in pgvector with an HNSW index.
3. Retrieval: BM25 (Postgres FTS) + dense, RRF fusion, cross-encoder rerank top 30 → top 6 to the generator.
4. Generation with a citation-required prompt: every claim maps to a chunk id; unsupported → refuse. Post-validate that each cited chunk id exists and that the answer contains no numeric claim absent from the cited chunks.
5. `POST /v1/bis/applicability`: classify the product profile to a category, look it up against the QCO/CRS tables (a real table, not retrieval — applicability is a lookup and must be deterministic), then use retrieval only for the explanation and next steps.

*Test:* E4 run reporting citation accuracy, answer accuracy, and refusal correctness on the 10 unanswerable questions. Expected output shape:
```
E4: 60 questions
answer accuracy 87%  | citation accuracy 93%  | hallucinated citations 0
refusals: 10/10 correct on priced-standard content
```

---

## P5 — Hardening (Nov 22–Dec 10)

1. Run E1/E2/E3/E4 end to end; commit the numbers to `docs/eval-results.md` with a date. Re-run before every demo.
2. Dashboards (FR-30) with the aggregate queries indexed.
3. Security pass: org isolation tests, presigned URL expiry, rate limits, EXIF stripping, hash-chain verification endpoint, dependency audit.
4. Load test to NFR-01.
5. Write the technical documentation the problem statement explicitly asks for: architecture, deployment framework, API reference, rule pack authoring guide.
6. Legal review gate on the rule pack. Book this in November; a practitioner's calendar is not a week-of thing.

---

## P6 — Pilot (Dec onward)

Target in order: 1 packaging design agency (reaches many brands at once), 3 local D2C brands, 1 Amazon/Flipkart account-management agency. Instrument scans per week per org, FAIL rate found, and the one metric that predicts payment: **repeat use in week 3 without you prompting them.**

---

## 7. Claude Code handoff pattern

`CLAUDE.md` at the repo root is loaded automatically every session and carries the non-negotiables, layout, commands and conventions. Do not repeat that content in a task; reference it.

For each phase, hand over one task in this shape:

```
CONTEXT: read docs/01-architecture.md §5 and docs/02-trd.md FR-23.
TASK: implement backend/app/services/vision/metrology.py
CONSTRAINTS:
  - pure functions, no I/O, no global state
  - PX_PER_MM constant imported from config, never hardcoded at a call site
  - every public function fully type-annotated, numpy arrays typed as npt.NDArray[np.uint8]
  - no new dependencies without asking
SIGNATURE:
  def measure_text_span(warped: NDArray, bbox: BBox, quality: Quality) -> Measurement
TESTS TO PASS: tests/test_metrology.py (14 cases, already written — do not edit the tests)
DONE WHEN: pytest tests/test_metrology.py passes and mypy is clean
```

Write the tests before handing over the implementation. With a spec this precise, the tests *are* the spec, and an agent that can edit its own tests will eventually make them pass the wrong way.

---

## 8. Repo conventions

- Python: ruff + mypy strict on `services/`, pytest, 80% coverage floor on `services/rules` and `services/vision` (the two places a bug is silent).
- TS: eslint + prettier, no `any` in `src/api` or `src/domain`.
- Commits: conventional commits. One PR per TRD requirement id, titled with it.
- Every architectural change updates `01-architecture.md` in the same PR, with a dated line in `docs/decisions.md`. A doc that lags the code by two weeks is worse than no doc.

---

## 9. What to build first if the timeline compresses

Ranked by demo value per hour, if you lose a fortnight:

1. Marker rectification + numeral height measurement (P0) — the only thing nobody else will have
2. Presence rules for the seven Rule 6(1) declarations — the visible core of the PS
3. PDF report with citations — makes it look like a product, not a script
4. Findings overlay on the image — the screenshot that goes in the deck
5. BIS applicability lookup — proves the two statements really are one system
6. Sahayak free chat — the most impressive-sounding and the most droppable

Drop from the bottom, never from the top.

---

## 10. Release gates before any external user

- [ ] E1, E2, E3, E4 numbers committed and dated
- [ ] False-FAIL rate ≤ 2% on E3
- [ ] Legal metrology practitioner has signed off the rule pack
- [ ] Advisory disclaimer on every report and every findings screen
- [ ] Org isolation test suite green
- [ ] Rule pack version stamped on every finding and report
- [ ] Hash-chain verification endpoint working and documented
