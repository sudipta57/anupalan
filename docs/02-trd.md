# Anupalan — Technical Requirements Document (TRD)

**Doc version:** v1.0 · Companion to `01-architecture.md`
**Scope:** v1 (SIH submission + pilot-ready MVP). Anything marked `[v2]` is explicitly out of scope.

Requirement IDs: `FR-xx` functional, `NFR-xx` non-functional, `DR-xx` data, `SR-xx` security.
Every requirement has an acceptance test. If it has no test, it is not a requirement.

---

## 1. Glossary

| Term | Meaning |
|---|---|
| PDP | Principal Display Panel — the face of the package the declarations must appear on |
| Declaration | A mandatory piece of information under LMPC Rules 2011 Rule 6 |
| Rule pack | Versioned YAML file encoding the rules the engine evaluates |
| px/mm | Pixels per millimetre in the rectified image; fixed at 20 |
| Marker | Printed ArUco tag of known physical size used as the scale reference |
| Finding | One rule's verdict for one scan |
| QCO | Quality Control Order — makes an Indian Standard mandatory for a product |
| CRS | Compulsory Registration Scheme — the electronics/IT route (registration, no factory audit) |

---

## 2. Functional requirements — Mobile (React Native, Android)

**FR-01 Guided capture.** The camera screen must run a live frame processor that evaluates four gates and displays each as pass/fail: (a) ArUco marker detected with 4 corners in frame, (b) blur — variance of Laplacian ≥ 120, (c) glare — fraction of pixels ≥ 250 luminance below 2%, (d) tilt — angle between marker plane normal and camera axis ≤ 25°.
*Accept:* shutter is disabled while any gate fails; each failing gate shows a specific instruction ("move closer", "reduce glare", "hold flatter"); all four green enables capture.

**FR-02 Marker onboarding.** First run offers: print the marker PDF (A4, 40 mm tag with a 5 mm quiet zone) or use an ID-1 card (85.60 × 53.98 mm) as fallback. The selected reference and its declared size are stored with the scan.
*Accept:* scan payload contains `marker_type` and `marker_mm`; a scan cannot be submitted without them.

**FR-03 Product context form.** Before or after capture, user supplies: product name, category (searchable list), pack type (`rigid|flexible|glass|can|other`), surface (`printed|embossed`), imported (`yes|no`), and declared net quantity if visible. Three fields are pre-filled from OCR after processing and confirmed by the user.
*Accept:* net quantity value+unit, imported flag and surface type are present on every completed scan, since all three change which rules apply.

**FR-04 Offline queue.** Scans captured without connectivity persist to SQLite with their images on disk and upload automatically on reconnect, surviving app restart and force-close.
*Accept:* airplane mode → capture 3 scans → force-close app → restore network → reopen → all 3 upload and complete.

**FR-05 Findings viewer.** Results render as the rectified image with tappable bounding boxes, plus a grouped list (Failures, Borderline, Not assessable, Passed). Tapping a finding highlights its box and shows: what was required, what was observed, and the rule citation verbatim.
*Accept:* every FAIL and BORDERLINE finding has a bounding box that highlights on tap; citation text is visible without leaving the screen.

**FR-06 Low-confidence confirmation.** Any extracted field below confidence 0.75 is shown in a confirmation sheet with its image crop before the verdict is finalised.
*Accept:* a deliberately blurred MRP triggers the sheet; the user's correction is recorded with `source=human` and the verdict recomputes.

**FR-07 Sahayak chat.** A chat screen answering BIS/standards questions, English and Hindi. Answers show inline source chips; tapping opens the source. Two entry points: free chat, and "Check BIS requirement for this product" from a scan.
*Accept:* an answer with no supporting source returns an explicit "not found in official sources" response with a link to the relevant BIS page, never a fabricated one.

**FR-08 Report export & share.** Generate and share PDF and DOCX from a completed scan.
*Accept:* both files download and open; PDF contains the annotated image, findings table and both hashes.

**FR-09 History & search.** List and filter past scans by date, product, verdict, and (Mode A) location.
*Accept:* filtering 200 seeded scans by `verdict=FAIL` returns only scans with ≥1 FAIL, within 500 ms.

**FR-10 `[Mode B]` Bulk listing check.** Paste or upload a CSV of marketplace listing URLs or listing text; the system runs presence/format rules on listing fields (metric rules are marked NOT_ASSESSABLE, since a listing has no physical scale).
*Accept:* a 50-row CSV produces 50 result rows with a summary count; no metric rule ever returns PASS or FAIL from listing text alone.

**FR-11 Ingredient cross-check view.** From a completed scan, request an online ingredient check (FR-31) and show the ingredients that match, those only on the label, those only online, any order or percentage notes, the source page with the date it was read, and the disclaimer that the label is the legal declaration.
*Accept:* all four outcomes and every reason code render from fixtures; nothing on the screen uses PASS/FAIL wording for this check; tapping a label item highlights its box on the image.

---

## 3. Functional requirements — Backend

**FR-20 Scan intake.** `POST /v1/scans` creates a scan and returns presigned upload URLs. `POST /v1/scans/{id}/submit` enqueues processing.
*Accept:* submit returns 202 with `status=queued` inside 300 ms.

**FR-21 Rectification.** Worker detects the marker, computes homography, warps to 20 px/mm, and persists the rectified asset with its `px_per_mm`.
*Accept:* a printed test chart with known 10.00 mm bars measures 10.00 ± 0.25 mm across 20 captures at varied angles ≤ 25° and distances 10–40 cm.

**FR-22 OCR.** PaddleOCR behind an `OCREngine` interface (`detect_and_recognise(image) -> list[Word]`, where `Word` = text, polygon, confidence, language). At least one alternate implementation must exist to prove the interface holds.
*Accept:* swapping the engine via config changes no calling code.

**FR-23 Glyph metrology.** For a given text span, return numeral cap-height in mm, per-glyph width/height ratio, and an uncertainty value derived from blur, tilt and px/mm.
*Accept:* on the ground-truth set (§7), measured height is within ±0.3 mm of caliper-measured truth for ≥ 90% of samples.

**FR-24 Field extraction.** Extract these field codes: `manufacturer_name`, `manufacturer_address`, `packer_name`, `importer_name`, `importer_address`, `country_of_origin`, `common_name`, `net_quantity`, `mrp`, `mfg_month_year`, `consumer_care_name`, `consumer_care_phone`, `consumer_care_email`, `unit_sale_price`, `best_before`. Regex first, LLM schema-constrained second, human third. Every value stores `source` and the character span it came from.
*Accept:* on the ground-truth set, field-level F1 ≥ 0.85 for `net_quantity`, `mrp`, `mfg_month_year`; ≥ 0.75 for address fields.

**FR-25 Rule evaluation.** Pure function: `evaluate(profile, extractions, measurements, rulepack) -> list[Finding]`. No I/O, no model calls, no clock reads (effective-date filtering takes `as_of` as an argument).
*Accept:* same inputs produce byte-identical findings across 1000 runs; the function is unit-testable with no DB.

**FR-26 Rule pack loading.** Rule packs load from YAML at boot and via `POST /v1/admin/rulepacks`, validated against a JSON schema, checksummed, and stored. Findings always record the pack version used.
*Accept:* an invalid rule pack is rejected with a line-level error and the previous pack stays active.

**FR-27 Report generation.** PDF (annotated image + findings table + metadata + hashes + advisory disclaimer) and DOCX (same content, editable) and JSON.
*Accept:* DOCX opens in Word and LibreOffice with the findings table editable as a real table, not an image.

**FR-28 Sahayak retrieval.** Hybrid BM25 + dense retrieval with RRF fusion, cross-encoder rerank on top 30, generation with mandatory citation of retrieved chunk ids.
*Accept:* on the 60-question eval set (§7), ≥ 90% of answers carry at least one correct citation and 0 answers cite a chunk that does not contain the claim (checked by an LLM judge plus manual spot-check of 20).

**FR-29 BIS applicability from a scan.** Given a product profile, return `{qco_applicable: yes|no|unclear, scheme: ISI|CRS|FMCS|none, candidate_is_numbers: [...], next_steps: [...], sources: [...]}`.
*Accept:* for 20 known products (10 under QCO, 10 not), applicability is correct for ≥ 17; "unclear" counts as wrong for a known-QCO product but is acceptable for ambiguous categories.

**FR-30 Dashboards.** Aggregate endpoints: violations by rule, by category, by district `[Mode A]`, by brand `[Mode B]`, over time.
*Accept:* endpoints return in under 1 s on 50,000 seeded findings.

**FR-31 Online ingredient cross-check.** For a completed scan, read the ingredient list from the stored OCR text, find the product's page on a registered official domain for its brand (`ingredients/sources-v1.yaml`), read the list published there, and compare the two. The outcome is one of `CONSISTENT | DIFFERENCES_FOUND | UNCLEAR | NOT_VERIFIABLE` with reason codes — never PASS/FAIL and never a finding, because a website is not the legal declaration (`08-ingredient-crosscheck-plan.md` §2.1). Pages are fetched only through the guarded fetcher, and every page read is snapshotted with its SHA-256.
*Accept:* no request reaches a host outside the registry or a non-public address (`tests/test_web_fetch_guard.py`); an unconfirmed low-confidence label item never yields `DIFFERENCES_FOUND`; every `NOT_VERIFIABLE` carries a reason. On the E5 set (≥ 30 products with hand-verified lists) the false `DIFFERENCES_FOUND` rate is reported, with its target set after the first run.

---

## 4. Non-functional requirements

| ID | Requirement | Acceptance |
|---|---|---|
| NFR-01 | Scan p50 ≤ 10 s, p95 ≤ 20 s, capture to findings | Load test, 50 concurrent scans |
| NFR-02 | App cold start ≤ 3 s on a 4 GB RAM Android 12 device | Measured on a real mid-range phone, not an emulator |
| NFR-03 | Sahayak first token ≤ 2.5 s, complete answer ≤ 8 s | Measured over 4G |
| NFR-04 | Worker survives a pod restart mid-job without losing the scan | Kill worker during processing; job retries and completes |
| NFR-05 | Infra cost ≤ ₹8,000/month at 10,000 scans/month | Costed spreadsheet, reviewed |
| NFR-06 | Rule pack change requires no code deploy | Upload a modified pack; behaviour changes on the next scan |
| NFR-07 | All API responses follow one error envelope `{error:{code,message,details}}` | Contract test across all endpoints |
| NFR-08 | Hindi and English UI strings; extraction handles Devanagari labels | 20 Devanagari labels processed end to end |

---

## 5. API contract (v1, abbreviated)

```
POST   /v1/auth/otp/request            {phone}                    -> {request_id}
POST   /v1/auth/otp/verify             {request_id, code}         -> {access, refresh, user, org}

POST   /v1/products                    {name, category_code, ...}  -> {product}
GET    /v1/products?q=&category=                                   -> {items, next_cursor}

POST   /v1/scans                       {product_id?, profile, marker_type, marker_mm, asset_count}
                                                                   -> {scan_id, uploads:[{asset_id, url, headers}]}
POST   /v1/scans/{id}/submit           {}                          -> 202 {status:"queued"}
GET    /v1/scans/{id}                                              -> {scan, assets, status}
GET    /v1/scans/{id}/findings                                     -> {rulepack_version, summary:{pass,fail,borderline,na},
                                                                       findings:[{rule_id, verdict, observed, required,
                                                                                  citation, bbox, confidence}]}
POST   /v1/scans/{id}/confirm-fields   {fields:[{code,value}]}     -> {findings}   # recomputes
POST   /v1/scans/{id}/report           {formats:["pdf","docx"]}    -> {report_id, urls}

POST   /v1/sahayak/ask                 {question, scan_id?, lang}  -> {answer, citations:[{doc_id,title,url,section}],
                                                                       confidence, as_of}
POST   /v1/bis/applicability           {profile}                   -> {qco_applicable, scheme, candidate_is_numbers,
                                                                       next_steps, sources}

GET    /v1/dashboard/violations?group_by=rule|category|district|month
POST   /v1/admin/rulepacks             {yaml}                      -> {code, version, checksum}
```

Conventions: cursor pagination, `Idempotency-Key` honoured on all POSTs that create, ISO-8601 UTC timestamps, all money as integer paise, all lengths in millimetres as floats.

---

## 6. Rule pack v1 — required coverage

The v1 pack must implement at minimum the following. Citations are to the Legal Metrology (Packaged Commodities) Rules, 2011 as amended.

**Presence rules (Rule 6(1)):** manufacturer/packer name and complete address; importer name and address for imported packages; common or generic name of the commodity; net quantity; month and year of manufacture/packing/import; MRP; consumer care details (name, phone or email, address).

**Format rules:**
- MRP must be expressed inclusive of all taxes (Rule 6(1)(e) / Rule 18 wording).
- Net quantity must use standard unit symbols — `g, kg, ml, l, L, cm, m, N` — not `gms`, `Gm`, `ltr`.
- Month and year must be a resolvable month-year.
- Consumer care must carry at least one reachable channel (phone or email).

**Metric rules (Rule 9):**
- Numeral height for the net quantity declaration, from **Table-I** where quantity is by weight/volume: up to 200 g/ml → 1 mm (2 mm if blown/formed/moulded/embossed/perforated); above 200 up to 500 g/ml → 2 mm (4 mm); above 500 g/ml → 4 mm (6 mm).
- Numeral height from **Table-II** where quantity is by length/area/number, keyed on PDP area: up to 100 cm² → 1 mm (2 mm); above 100 up to 500 cm² → 2 mm (4 mm); above 500 up to 2500 cm² → 4 mm (6 mm); above 2500 cm² → 6 mm (6 mm).
- Letter height ≥ 1 mm, or ≥ 2 mm when blown/formed/moulded/embossed/perforated.
- Glyph width ≥ ⅓ of its height, excluding numeral `1` and letters `i`, `I`, `l`.

**Conditional rules:**
- Importer declarations apply only when `is_imported = true`.
- Country-of-origin searchable/sortable filter applies only to e-commerce listings of imported products, with an **effective date of 1 July 2027** per the Second Amendment Rules, 2026. Encode the date; do not fail listings before it.

**Placement rules (partial in v1):** all declarations must appear on the PDP; the area around the quantity declaration must be free of other printed information. v1 checks the second one geometrically with a conservative margin and marks it BORDERLINE when the margin is close.

> **Legal review gate:** the pack in `rulepacks/` is engineering's transcription from public sources. Before any paid customer uses it, a legal metrology practitioner must review it clause by clause and sign off. Track that as a release blocker, not a nice-to-have.

---

## 7. Evaluation sets (build these before you build features)

**E1 — Metrology ground truth.** 60 printed labels with digits at known heights (0.8, 1.0, 1.5, 2.0, 2.5, 4.0, 6.0 mm), photographed 5× each at varied angle, distance and lighting = 300 images. Truth measured with a vernier caliper or generated from a PDF at exact point size. *Metric:* mean absolute error in mm, and the percentage inside ±0.3 mm.

**E2 — Extraction ground truth.** 200 real product labels from local shops in Kalyani/Kolkata, hand-annotated for all 15 field codes. Split 140 train / 60 test. *Metric:* per-field precision, recall, F1.

**E3 — Rule verdict set.** 100 labels labelled by a human reviewer against each rule. *Metric:* per-rule confusion matrix. **The number that matters is the false-FAIL rate** — accusing a compliant label is the failure that kills trust. Target ≤ 2%.

**E4 — Sahayak QA set.** 60 questions across QCO applicability, scheme choice, process, fees, hallmarking, labs — each with a known correct answer and source. *Metric:* citation accuracy, answer accuracy, refusal correctness on 10 deliberately unanswerable questions (e.g. "what is the tensile limit in IS 1786?", which must be refused as priced content).

E1 and E3 are what let you answer "how accurate is it?" with a number instead of a shrug. That answer is usually the difference between a good demo and a winning one.

---

## 8. Out of scope for v1

FSSAI food-label rules; multi-panel auto-stitching; curved-surface unwrapping; artwork file (AI/PDF) ingestion for pre-press checking; marketplace API integrations; iOS; on-device inference; automatic correction of artwork; payments and subscription billing; e-commerce listing scraping at scale.

`[v2]` candidates ranked by commercial value: artwork PDF ingestion (pre-press is where brands actually spend), FSSAI pack, Shopify app, marketplace bulk API.

---

## 9. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| mm measurement is not accurate enough to be credible | Kills the core differentiator | E1 built in week 1, before any UI work; if MAE > 0.5 mm, pivot the pitch to presence/format checks and present measurement as assisted-measure with human confirmation |
| Rule transcription is legally wrong | Wrong verdicts, liability | Legal review gate; advisory framing on every report; four-valued verdicts |
| BIS standard texts unavailable | Sahayak looks thin | Scope to public corpus from day one and present the IP boundary as a deliberate design choice |
| OCR fails on Indian packaging (glossy, multilingual, low contrast) | Extraction F1 collapses | Capture gates reject bad frames; fine-tune recognition on E2 train split if needed |
| Two-module scope is too large for the build window | Half-finished demo | Sahayak v1 is retrieval + citations only; ship the applicability endpoint before the free chat |
| Judges ask "why not just Google Vision?" | Weak answer looks naive | Have the cost-per-scan, data-residency and polygon-access answer ready with numbers |
