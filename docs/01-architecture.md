# Anupalan — Architecture Document

**Problem statements:** SIH26034 (Legal Metrology packaged-commodity compliance scanning) + SIH26107 (AI assistant for Indian Standards & BIS services)
**Organisation:** Department of Consumer Affairs (DoCA), Ministry of Consumer Affairs, Food & Public Distribution
**Doc version:** v1.1 · Owner: Sudipta · Status: baseline, update after each architectural change
**Changed in v1.1 (12 Sep 2026):** infrastructure moved from self-hosted containers to managed services — Neon, Redis Cloud, Cloudflare R2. §9, §11 and §13 revised. See `decisions.md`.

> Working name only. "Anupalan" (अनुपालन) = compliance. Two modules: **Anupalan Scan** (label compliance) and **Anupalan Sahayak** (BIS assistant). Rename freely.

---

## 1. One-paragraph summary

Anupalan is a mobile-first compliance engine for packaged commodities in India. A user photographs a product package with a printed scale marker in frame. The system rectifies the image to a metric plane, runs OCR, extracts the mandatory declarations required by the Legal Metrology (Packaged Commodities) Rules, 2011, **measures glyph heights in millimetres**, and evaluates a versioned, declarative rule pack to produce a per-rule PASS / FAIL / BORDERLINE / NOT_ASSESSABLE finding, each citing the specific sub-rule. The same extracted product profile is then passed to a retrieval-grounded BIS assistant that answers whether the product falls under a Quality Control Order or the Compulsory Registration Scheme, which Indian Standard applies, and what the certification route is — with citations to public BIS/gazette sources. Output is a signed PDF + editable DOCX report stored in a searchable repository, with dashboards for enforcement officials and brand teams.

---

## 2. Why these two statements combine into one system

They share the same input and the same missing abstraction.

| Shared component | Used by SIH26034 | Used by SIH26107 |
|---|---|---|
| Image → OCR → text | Label declaration extraction | Product identification from pack |
| Product profile (category, quantity, importer, material) | Determines which declarations apply | Determines which QCO/IS applies |
| Citation-backed rule/answer engine | Rule citation in findings | Clause citation in answers |
| Report + repository + RBAC | Inspection reports | Certification guidance reports |

A product scanned once answers both *"is this label legal?"* and *"does this product need the ISI mark?"*. That is the joint pitch: **one scan, full market-entry compliance verdict.**

---

## 3. Actors and modes

The same engine ships in two app shells over one backend.

**Mode A — Enforcement (Legal Metrology Officer / DoCA).** Field inspection, geo-tagged and timestamped evidence, hash-chained audit trail, violation summary, inspection history, district/state dashboards. This is what the SIH problem statement literally asks for.

**Mode B — Industry (D2C brand, packaging agency, marketplace seller).** Pre-print artwork check, bulk listing check, correction suggestions, BIS applicability check. This is the revenue path.

Mode is an org-level attribute. Mode A adds evidence-integrity features and locks editing; Mode B adds remediation suggestions and bulk import. Rule evaluation is identical in both — this matters, because a brand's whole reason to pay is that the tool runs the *same* check an inspector would.

---

## 4. High-level component diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  React Native (Android) — Expo dev build                             │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────┐ ┌────────────────┐  │
│  │ Capture     │ │ Findings     │ │ Sahayak    │ │ Offline queue  │  │
│  │ (VisionCam  │ │ viewer       │ │ chat       │ │ (SQLite+MMKV)  │  │
│  │  + marker   │ │ (overlay on  │ │            │ │                │  │
│  │  guidance)  │ │  image)      │ │            │ │                │  │
│  └─────────────┘ └──────────────┘ └────────────┘ └────────────────┘  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTPS / JSON, JWT
┌───────────────────────────────▼──────────────────────────────────────┐
│  FastAPI (Python 3.12) — api gateway                                 │
│  auth · orgs · scans · findings · reports · sahayak · admin          │
└──────┬──────────────────┬────────────────────┬───────────────┬───────┘
       │                  │                    │               │
┌──────▼──────┐  ┌────────▼────────┐  ┌────────▼───────┐ ┌─────▼──────┐
│ Vision      │  │ Rules engine    │  │ Sahayak (RAG)  │ │ Reporting  │
│ pipeline    │  │ (deterministic) │  │                │ │ PDF/DOCX   │
│ worker      │  │ rulepack v1.y   │  │ retrieve→cite  │ │            │
│ (Celery)    │  │                 │  │ →answer        │ │            │
└──────┬──────┘  └────────┬────────┘  └────────┬───────┘ └─────┬──────┘
       │                  │                    │               │
┌──────▼──────────────────▼────────────────────▼───────────────▼───────┐
│ Neon: PG16 + pgvector  │ Redis Cloud (queue) │ R2 (images, PDFs)     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 5. The vision pipeline (the technically hard part)

Ten stages. Stages 3–5 are the differentiator; everything else is standard.

**S1 — Guided capture (on device).** The camera overlay requires an **ArUco 4×4_50 marker** (printed from the app at a known 40 mm size, or the app-issued PVC card) to be visible in frame. Real-time frame processor checks: marker detected, all four corners inside frame, blur variance above threshold, glare below threshold, viewing angle under 25°. The shutter stays disabled until all pass. Rejecting bad input at capture time is worth more than any post-processing.

**S2 — Upload.** Image + capture metadata (device, timestamp, GPS if Mode A, marker size declared) → presigned R2 PUT → job enqueued.

**S3 — Metric rectification.** Detect marker corners → compute homography → warp to a canonical plane at a fixed **20 px/mm**. From here, every pixel measurement converts to millimetres by dividing by 20. This is the whole reason the marker exists: without a known physical reference, "font size in mm" is unanswerable, and font size is the check nobody else automates.

**S4 — OCR.** PaddleOCR (PP-OCRv4) for detection + recognition, English and Devanagari. Returns word-level polygons + text + confidence. Note: OCR polygons are *not* glyph heights — they include ascenders, descenders and padding, and are unreliable for measurement.

**Every photograph of a scan is read, not just the first.** Declarations are spread across panels, and the panel carrying the marker is rarely the panel carrying the address. Words from all photographs merge into one text for extraction; each keeps its own `ocr_results` row, stamped with its `asset_id`, because polygons from two photographs are in two coordinate spaces. Exactly one photograph is the *metric* one — whichever carries the marker — and it alone is rectified, measured, and used for evidence boxes.

**Orientation is recovered before recognition is trusted.** A pack photographed on its side is recognised as fragments, and nothing downstream can undo that: the extraction layer faithfully reports `INDUSTRIES PVT.LID` and a rule then judges the pack on it. The trigger is a direct measurement rather than a proxy — words are wider than tall in both scripts, so the share of taller-than-wide boxes says whether the page is sideways (measured on a real scan: **100%** as shot, **0%** upright, where word count and mean confidence were both useless as signals). Above the threshold, the page is read again at 90°/270°/180° and the readings are **merged**, not scored against each other: a folded pack has two halves facing opposite ways, and picking a winner loses one of them. On that scan the merge took 50 words at 0.865 to 243 at 0.891, and recovered the MRP, both dates and the manufacturer's address. An upright photograph returns on the first pass and pays nothing. Every word is reported in the coordinates of the image as handed in — a polygon left in a rotated frame is a real rectangle in the wrong place, and the evidence crop would show the wrong words.

**S5 — Glyph metrology.** For each declaration of interest, crop the rectified region → adaptive binarisation → connected components → filter components to digits/letters using the OCR character map → compute **cap-height** of numerals (digit glyphs have uniform cap height, which is why the rule is written about numerals) and per-glyph width/height ratio. Convert px → mm. Emit a measurement with an uncertainty band (±0.25 mm baseline, widened by blur and angle scores).

**S6 — Field extraction.** Hybrid, in this order:
1. Deterministic regex/heuristics first: MRP patterns, net-quantity patterns with unit normalisation, date patterns, pincode, phone, email.
2. LLM structuring second, over **every** field rather than only the ones regex missed, constrained to a strict JSON schema, with the raw OCR text as the only context. Where both layers produce a value for a field, **the model's reading wins** — a pattern matches a shape, not a meaning, and cannot tell that it matched the wrong thing (observed on a real pack: `mrp` → `"02"`, `best_before` → `"Date:"`, both turned into PASS by a presence rule). What bounds the model is the evidence rule, not its position in the order: a value absent from the OCR text is refused, so an override is always a different reading of text that is genuinely there, and the pattern's value is what stands when the model's is refused. Two costs are accepted deliberately — extraction is no longer reproducible run to run, and an overridden field carries 0.70, below the confirmation threshold, so it reaches a verdict only after a human confirms it. The LLM **never** decides compliance — it only proposes field values, each with the source text span.
3. Plausibility screening over both layers: a value that could not be a value of its field at all has its confidence capped below the confirmation threshold. It lowers confidence and nothing else — the value, its span and its evidence box are kept, and no verdict is touched. This is what stops `mrp = "02"` and `best_before = "Date:"` being recorded at 0.95 and satisfying a presence rule without anyone being asked. The checks carry no legal content — a date with no digit in it, an email with no `@` — because rules and limits live in the rule pack and nowhere else. They are deliberately conservative and asymmetric: a false flag costs one tap, a missed one costs a wrong verdict in a report carrying a citation. They also deliberately do **not** guess at content — `INDUSTRIES PVT.LID` is plausible as a name and is not flagged, because that damage belongs to recognition and is fixed at S4.
4. Human-in-the-loop last, and it is a **gate, not a review**: if any field is below the confidence threshold the pipeline stops here, sets the scan to `needs_confirmation` and does **not** call `evaluate()`. No verdict is issued over a value nobody has checked. A rule asked about a doubtful field answers with exactly the confidence it answers anything, and Rule 6(1) only asks whether a declaration is *present* — so an unchecked `mrp = "02"` earns a PASS and the report files it. Computing the verdict and labelling it provisional was the earlier shape and put that PASS in front of a reader.

An evaluation row **is** written at this point, carrying the pack version, its checksum and the `as_of` date, with no findings attached. That is what makes the later confirmation judge the label under the rules in force when it was photographed rather than whatever is active by then (§3.6) — a row with nothing in it, rather than no row. `confirm-fields` evaluates once nothing is still outstanding, and only then does the scan reach `complete` or `no_marker`. Which of the two is decided by whether a rectified asset exists, that asset being written if and only if a marker was found and yielded a homography.

**S7 — Rule evaluation.** Deterministic interpreter over the rule pack (see §6). No model calls. Same input → same output, always.

**S8 — Findings assembly.** Each finding = rule_id, verdict, observed value, required value, citation, evidence bounding box, confidence.

**S9 — BIS applicability handoff.** The product profile goes to Sahayak, which returns QCO/CRS applicability, candidate IS numbers and the certification route.

**S10 — Report + persist.** PDF (report layout with annotated image) + DOCX (editable, per the PS requirement) + JSON. SHA-256 over the image and the findings blob, stored in an append-only audit table.

**Target latency:** under 10 s p50, under 20 s p95, for a single label on a mid-range Android phone over 4G.

---

## 6. Rules engine design

The rule pack is **data, not code** — a versioned YAML file, loaded at boot, hot-swappable, with every rule carrying its legal citation.

Why this is non-negotiable:
- Rule 6(10A) changed twice in 2026 (G.S.R. 128(E) of 13 Feb 2026, then the Second Amendment Rules of 27 Apr 2026 pushing the effective date to 1 Jul 2027). A system with rules in `if` statements needs a redeploy and a regression risk every time the gazette moves.
- Every finding must cite a rule. If the rule is a row in a data file, the citation is a field on that row and cannot drift from the logic.
- Reports become defensible: "checked against rule pack LM-2011 v1.4, effective 2026-07-01".

Rule kinds supported in v1:
- `presence` — the field must exist (manufacturer name/address, net quantity, MRP, month+year, consumer care)
- `format` — the field must match a pattern or normalised shape (MRP inclusive-of-all-taxes wording, unit symbols, date format)
- `metric` — a measured value must clear a threshold from a lookup table (numeral height by Table-I/Table-II, width ≥ ⅓ height)
- `conditional` — applies only when a predicate on the product profile holds (importer details only for imported packages; country-of-origin filter only for e-commerce listings of imported goods)
- `composite` — an AND/OR over other rules

Verdicts are four-valued, deliberately:
`PASS` · `FAIL` · `BORDERLINE` (measurement within uncertainty band of the threshold) · `NOT_ASSESSABLE` (field or panel not visible in this image).
Collapsing BORDERLINE into FAIL would produce confident wrong accusations, which is the fastest way to lose both an enforcement pilot and a paying brand.

---

## 7. Sahayak (BIS assistant) design

**The hard constraint that shapes everything:** full texts of Indian Standards are copyrighted and sold by BIS. You cannot ingest IS documents into a corpus and serve their content. Any team that plans a "chatbot over all Indian Standards" will hit this at demo time.

So the corpus is built only from public, non-priced material:
- Quality Control Orders as published in the Gazette of India (PDF)
- The BIS list of products under mandatory certification (ISI mark scheme)
- The Electronics & IT Goods (Compulsory Registration) Order product list (CRS)
- BIS scheme guides, FAQ pages, hallmarking pages, fee schedules
- The BIS **catalogue metadata**: IS number, title, scope abstract, ICS code, publication year, amendment status
- Recognised laboratory directory

What Sahayak answers: does a QCO cover this product, which IS number applies, ISI vs CRS vs FMCS, the application process, fees, which labs, hallmarking questions.
What Sahayak refuses: the technical content of a standard — test limits, clause text, tolerance tables. It says so plainly and points to the BIS purchase route. **Frame this refusal as a feature in the pitch**; it demonstrates you understand the IP boundary the ministry lives inside.

Applicability is a **table lookup**, not retrieval (B20). The QCO/CRS lists live in `bis/qco-crs-v1.yaml` — data at the repository root, versioned and checksummed the way `rulepacks/` is, for the same reason: "does this product need the ISI mark" is answered by a published list, a brand plans a launch around the answer, and no category, IS number or scheme name may sit in a `.py` file where it changes only on a deploy. Retrieval is used for the explanation and the next steps around that answer, never for the answer. The lists carry catalogue metadata only — IS number, title and scheme — and no standard's content.

Retrieval design: hybrid BM25 + dense (pgvector, multilingual-e5 or BGE-M3 for Hindi/English), reciprocal-rank fusion, then a cross-encoder rerank on the top 30. Generation is citation-required: every sentence in the answer maps to a retrieved chunk id, and if no chunk supports a claim, the assistant declines rather than fills in. Answers carry a freshness stamp because QCOs are amended constantly.

---

## 8. Data model (core tables)

```
orgs(id, name, mode[enforcement|industry], state, created_at)
users(id, org_id, role[admin|inspector|analyst|viewer], phone, email, full_name, is_active, ...)
products(id, org_id, name, brand, category_code, gtin, is_imported, pack_type, surface,
         net_qty_value, net_qty_unit)
scans(id, org_id, product_id, user_id, status, captured_at, geo_lat, geo_lon, geo_accuracy_m,
      district, device_meta, marker_type, marker_mm, profile, error)
scan_assets(id, scan_id, org_id, kind[raw|rectified|annotated], s3_key, sha256, content_type,
            size_bytes, width_px, height_px, px_per_mm)
ocr_results(id, scan_id, org_id, asset_id, engine, version, raw_json, mean_conf)
extractions(id, scan_id, org_id, field_code, value_raw, value_norm, source[regex|llm|human],
            confidence, bbox, span_start, span_end, superseded_by)
measurements(id, scan_id, org_id, field_code, glyph, height_mm, width_mm, uncertainty_mm,
             clear_space_mm, is_numeral, is_mark, method)
scan_evaluations(id, scan_id, org_id, revision, source, rulepack_version, rulepack_checksum,
                 as_of, findings_sha256, reduced_extraction)
findings(id, evaluation_id, scan_id, org_id, rule_id, rulepack_version, verdict, severity,
         observed, required, citation, message, band, bbox, confidence)
rulepacks(id, code, version, effective_from, checksum, body, published_by, published_at, is_active)
reports(id, scan_id, org_id, evaluation_id, pdf_key, docx_key, json_key, sha256, generated_at)
otp_requests(id, phone, code_hash, expires_at, consumed_at, attempts, request_ip)
refresh_tokens(id, user_id, org_id, family_id, token_hash, expires_at, revoked_at, replaced_by)
idempotency_keys(id, org_id, key, endpoint, request_fingerprint, entity_id, response_json)
bis_queries(id, org_id, scan_id NULL, user_id, question, answer, citations_json, model, as_of)
bis_documents(id, source_type, title, url, published_at, sha256)
bis_chunks(id, document_id, text, embedding vector(1024), section_ref)
audit_log(id BIGSERIAL, org_id, actor_id, action, entity, entity_id, payload, prev_hash, hash, created_at)
```

`findings` is append-only and always stamped with `rulepack_version`. A report regenerated a year later must reproduce the verdict that was issued under the rules in force at scan time.

Five properties of this schema carry requirements that would otherwise depend on everyone remembering them:

- **`org_id` is on every org-owned table, including the ones that hang off a scan.** They could have reached their org by joining `scans`, but scoping that needs a join is scoping that can be written without one. The denormalised copy is kept honest by a composite foreign key — `(scan_id, org_id)` references `scans (id, org_id)`, which carries a matching `UNIQUE` — so a mis-scoped row is a database error, not a code-review question. The only org-owned table without `org_id` is `otp_requests`: a code is issued against a phone number before anyone knows which org, or whether any, it belongs to.
- **`scan_evaluations` groups findings into revisions.** Each row records which pack, which checksum and which `as_of` produced one complete verdict set, plus the canonical hash of that set. The current verdicts for a scan are its highest revision's. This is what lets `confirm-fields` (FR-06) recompute under the *original* pack version without mutating a row, and what lets a redelivered Celery task recognise an identical result and record nothing new (NFR-04).
- **`scans.profile` is frozen at submit** rather than re-read from `products` at evaluation time. A brand correcting its catalogue next month must not retroactively change a verdict already issued.
- **`rulepacks.body` holds the YAML itself**, so a report regenerated next year reproduces its verdict from the database alone rather than needing the right git revision checked out.
- **The `verdict` CHECK constraint lists exactly four values.** There is no `NOT_APPLICABLE`: a rule that does not apply produces no row at all (`decisions.md`, 2026-09-12), and the not-applicable list is recovered from the pack.

- **`idempotency_keys` records what a creating POST produced**, fingerprinted by request body. The mobile app retries on a flaky connection and, with FR-04's offline queue, may retry a scan submitted days earlier — so a request arriving twice is the normal case. A replayed key returns the original response verbatim, presigned URLs included; a replayed key with a *different* body is a 409, because silently returning the earlier scan would answer a question the caller did not ask.

- **`scans.district` and `products.brand` are recorded, never derived** (B17, migration 0003). FR-30 groups violations by district in Mode A and by brand in Mode B, and neither could be faked from what was already there. A district resolved from `geo_lat`/`geo_lon` against a boundary file of unknown vintage attributes an inspection to the wrong jurisdiction; a brand read off `products.name` splits `Tata Salt 1 kg` and `Tata Salt 500 g` into two brands and merges nothing. Both are nullable and both dashboards group a NULL under *unknown* rather than dropping the row, so the buckets always sum to the headline total.

Four of these tables — `scan_evaluations`, `otp_requests`, `refresh_tokens` (B12) and `idempotency_keys` (B14) — were added as reviewed deviations from the original model; `geo_point` became three columns to avoid a PostGIS dependency. Enumerated columns are `VARCHAR` + `CHECK` rather than native Postgres `ENUM`, so extending a value is a one-line migration and the same models build a SQLite schema for the org-isolation suite that CI runs without any datastore.

---

## 9. Technology decisions, with the alternative that was rejected

| Decision | Choice | Rejected alternative | Reason |
|---|---|---|---|
| Backend language | **FastAPI (Python)** | Express/Node | OCR, OpenCV homography, connected-component metrology, embeddings and reranking are all Python-native. Node would force a Python sidecar, giving two services and two deploy stories for zero gain. |
| Extra Node service | **None in v1** | Express BFF | A BFF is justified when you have many clients or heavy websocket work. One Android app does not justify a second runtime. Revisit only if a web dashboard needs SSR. |
| Async work | **Celery + Redis** | FastAPI BackgroundTasks | Scans take seconds and can fail; you need retries, visibility and a dead-letter path. BackgroundTasks dies with the process. |
| DB | **Postgres 16 + pgvector** | Postgres + a separate vector DB | Corpus is tens of thousands of chunks, not millions. One database to back up, one to deploy. |
| DB hosting | **Neon** (managed, serverless) | Self-hosted Postgres in a container on the app VM | No database to patch, back up or lose. Branching gives a throwaway database per PR, which the org-isolation suite wants. Costs: the pooled endpoint is pgbouncer in transaction mode, so migrations must use the direct endpoint and psycopg's prepared-statement threshold must be disabled; and scale-to-zero adds a cold start of up to a few seconds on the first query, which is charged against NFR-01. pgvector is available as an extension, so the §8 data model is unchanged. |
| Object storage | **Cloudflare R2** | MinIO in a container; AWS S3 | Zero egress fees, which matters because reports and annotated images are read far more than written. S3-compatible API, so the settings are named `S3_*` and an on-premise MinIO swap is an endpoint change, not a code change. R2 has no regions (`region=auto`) and no per-object ACLs, so access is presigned-only — which §10 required anyway. |
| Redis hosting | **Redis Cloud** (managed, TLS) | Redis in a container alongside the app | The broker is the one component whose loss strands in-flight scans; managed persistence and failover are worth more than the saved rupees. TLS is not optional: the URL is `rediss://` and Celery must be told explicitly via `broker_use_ssl`. |
| Local development | **No containers — the managed services are shared** | Docker Compose mirroring production locally | One less toolchain to install, and every developer provisions in minutes. Costs: you cannot work offline, and a shared development database means a destructive migration hits everyone — so use a Neon branch per developer once there is more than one. |
| OCR | **PaddleOCR PP-OCRv4**, self-hosted | Google Vision / Textract | Data residency — a government deployment may need to run wholly on-premise, and that capability is part of the pitch. Also needed: raw word polygons, which managed APIs expose inconsistently. **Not** a cost decision: cloud OCR runs about ₹0.10–0.15 per image, negligible against ₹49–99 pricing, so do not argue this one on cost. Keep a cloud-OCR adapter behind the interface as a fallback. |
| Scale reference | **ArUco marker (primary), ID-1 card 85.60×53.98 mm (fallback), user-entered pack dimension (last resort)** | Phone AR depth / assume DPI | Depth APIs are unreliable on cheap Android and add a hard dependency. Without a physical reference, mm measurement is guesswork, and guessed millimetres in a legal report are worse than no measurement. |
| LLM role | **Extraction + explanation only** | LLM decides compliance | Verdicts must be deterministic, reproducible and citable. An LLM verdict cannot be defended in an enforcement context and cannot be regression-tested. |
| LLM vendor | **Unspecified — `LLMProvider` interface, vendor only in `config.yaml`.** Budget tier for extraction and explanations, mid tier for Sahayak, with a working open-weight adapter | Committing to one provider in code | Extraction costs roughly ₹0.04/scan on a budget model, so vendor choice is not a cost question — it is a deployment question. A government buyer may require fully on-premise operation, so the open-weight path must stay working. Pick per call site on measured schema-failure rate and citation accuracy against E2/E4, not on leaderboards. |
| Mobile | **React Native + Expo dev build**, react-native-vision-camera | Bare RN; Flutter | Team velocity. Vision-camera frame processors work under Expo dev builds; Expo Go does not, so plan for a dev build from day one. |
| Rules | **Declarative YAML rule pack, versioned** | Hardcoded checks | Gazette amendments; citation integrity; report reproducibility. |
| BIS corpus | **Public QCO/CRS/FAQ/metadata only** | Full IS standard texts | Standards are priced and copyrighted. |

---

## 10. Security, privacy, integrity

- Auth: phone OTP + JWT access/refresh; org-scoped RBAC (`admin`, `inspector`, `analyst`, `viewer`); row-level org isolation enforced in the repository layer, tested. Access tokens are stateless HS256 and short-lived, so verifying one costs no database round trip; they cannot be revoked before expiry, which is why revocation acts on the refresh family instead. Refresh tokens are opaque, stored as a peppered hash, and rotated — presenting a retired one revokes its whole family. OTP codes are single-use, short-lived, attempt-capped and rate-limited per phone *and* per IP; six digits carries only 10^6 of entropy, so those four properties are the defence and the hash is not. `org_id` is minted into the token from the user's row and read back from the verified token; a request body carrying an `org_id` is a 400, never an override.
- Storage: presigned URLs only, private buckets, per-org key prefix, server-side encryption.
- Evidence integrity (Mode A): SHA-256 of the raw image recorded at upload; `audit_log` is hash-chained (`hash = H(prev_hash || row)`); reports embed both hashes. Anyone can verify a report was not altered after issue. Because the API never proxies image bytes — it signs an upload URL and the client uploads straight to object storage — the raw hash is **declared by the client at create time and verified by the worker** against the stored object before any processing; a mismatch fails the scan rather than attaching a hash the evidence does not have. The chain is per-org, starting from a fixed genesis value, and `GET /v1/admin/audit/verify` reports the **first broken link** with its entry id and whether the row was edited (`hash_mismatch`) or removed (`broken_link`) — everything before that point is still provably intact. The canonical row rendering the hash covers is versioned and must never be edited in place, since changing it would invalidate every chain already written.
- Location and device data: collected only in Mode A, disclosed in-app, retention configurable per org.
- DPDP Act 2023 posture: the data is about products, not people, which is a genuine advantage over most health/fintech entries. The only personal data is user accounts and inspector location. Say this explicitly to judges.
- Rate limiting per org **and** per IP (B23, `services/ratelimit.py`): 120 req/min per address, 600 per org, fixed window, Redis-backed so the limit is the limit across every instance. Both axes are needed — per-IP alone lets one org flood from many addresses, per-org alone lets one address sweep many orgs. An unauthenticated flood is charged to its address and never to the org id it claimed, or anyone could exhaust a tenant's quota by sending their id. `/health` is exempt, because a load balancer throttled into declaring the service dead turns a rate limit into an outage. The limiter **fails open** if its own store is unreachable, and refuses the in-memory backend when `ENV` is production, where N workers would each admit the full ceiling.
- Upload size and MIME allow-list, both enforced when the presigned URL is **issued** rather than after the bytes arrive; EXIF stripped from anything served, fail-closed — if metadata cannot be removed, the bytes are not returned.

---

## 11. Failure modes and how the system degrades

| Failure | Behaviour |
|---|---|
| No marker detected | Capture blocked with a specific instruction; a "no-measurement mode" is offered which runs presence/format rules only and marks all metric rules NOT_ASSESSABLE |
| OCR confidence low on a field | Field surfaced for one-tap human confirmation; never silently guessed |
| Measurement within uncertainty band | BORDERLINE verdict with the band printed, not FAIL |
| LLM unavailable | Presence/format/metric rules still run; extraction falls back to regex-only; report is issued flagged "reduced extraction" |
| Sahayak finds no supporting source | Declines, returns the closest official page link |
| Offline | Scans queue locally, upload and process on reconnect; queue survives app restart |
| Database suspended (Neon scale-to-zero) | First query pays a cold start; `pool_pre_ping` and `pool_recycle` reconnect transparently. A scan in flight retries rather than failing |
| Database or broker unreachable | `GET /health` answers 200 with `status: degraded` and names the failed component. The API reports rather than failing closed, so a probe can distinguish a dead process from a dead dependency |
| Rate limiter's store unreachable | Requests are admitted and a warning is logged. A limiter that takes the API down when Redis blinks has converted a partial outage into a total one |
| Corpus ingested but not embedded | Sahayak retrieval runs lexical-only. A narrower assistant, not a broken one |
| Embedding or reranking runtime absent | Probed once per process; retrieval falls back to the fused order and logs it |

---

## 12. Known limitations (state these before a judge finds them)

1. A single photo covers one panel. Multi-panel packs need multiple captures stitched into one scan; v1 supports multiple assets per scan but does not auto-detect that a panel is missing.
2. Curved surfaces (bottles, pouches) distort glyph geometry. Planar homography under-measures on strong curvature; v1 detects high curvature and downgrades metric rules to NOT_ASSESSABLE rather than reporting a wrong millimetre value.
3. Embossed/blown text on glass and plastic is low-contrast and often fails OCR. The rules have a separate (higher) threshold for it; v1 asks the user to tag the pack as embossed.
4. The rule pack encodes the general rules. Schedule-specific and commodity-specific exemptions are partially covered in v1 and must be expanded with a legal metrology consultant before any commercial release.
5. Verdicts are advisory. The product is a pre-audit, not a certification. This must appear on every report.

---

## 13. Deployment

**No containers.** Stateful infrastructure is managed — Postgres on **Neon**, Redis on **Redis Cloud**, object storage on **Cloudflare R2** — and the application is two processes from one codebase:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000   # API
celery -A app.worker worker -l info                # worker
```

Hackathon/pilot: both processes on a single 2 vCPU / 4 GB VM under systemd, with `caddy` in front for TLS. The VM is now stateless — nothing on it needs backing up, and replacing it is a redeploy rather than a restore. A PaaS that builds from source (buildpack/nixpacks) is the alternative and needs no VM at all. Android build distributed via the EAS internal channel, later the Play Store.

Production path: API and worker as separate services behind a load balancer, workers autoscaled on queue depth. Neon, Redis Cloud and R2 all scale without a migration, which is most of the reason for choosing them. Model serving stays on CPU until scan volume justifies a GPU node.

Provisioning runbook, including the two Neon connection strings and why they differ: `infra/README.md`.
