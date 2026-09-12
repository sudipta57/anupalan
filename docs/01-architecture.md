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

**S5 — Glyph metrology.** For each declaration of interest, crop the rectified region → adaptive binarisation → connected components → filter components to digits/letters using the OCR character map → compute **cap-height** of numerals (digit glyphs have uniform cap height, which is why the rule is written about numerals) and per-glyph width/height ratio. Convert px → mm. Emit a measurement with an uncertainty band (±0.25 mm baseline, widened by blur and angle scores).

**S6 — Field extraction.** Hybrid, in this order:
1. Deterministic regex/heuristics first: MRP patterns, net-quantity patterns with unit normalisation, date patterns, pincode, phone, email.
2. LLM structuring second, only for what regex missed, constrained to a strict JSON schema, with the raw OCR text as the only context. The LLM **never** decides compliance — it only proposes field values, each with the source text span.
3. Human-in-the-loop third: any field below the confidence threshold is surfaced for one-tap confirmation before the verdict is issued.

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

Retrieval design: hybrid BM25 + dense (pgvector, multilingual-e5 or BGE-M3 for Hindi/English), reciprocal-rank fusion, then a cross-encoder rerank on the top 30. Generation is citation-required: every sentence in the answer maps to a retrieved chunk id, and if no chunk supports a claim, the assistant declines rather than fills in. Answers carry a freshness stamp because QCOs are amended constantly.

---

## 8. Data model (core tables)

```
orgs(id, name, mode[enforcement|industry], state, created_at)
users(id, org_id, role[admin|inspector|analyst|viewer], phone, email, ...)
products(id, org_id, name, category_code, gtin, is_imported, pack_type, net_qty_value, net_qty_unit)
scans(id, org_id, product_id, user_id, status, captured_at, geo_point, device_meta, marker_type, marker_mm)
scan_assets(id, scan_id, kind[raw|rectified|annotated], s3_key, sha256, width_px, height_px, px_per_mm)
ocr_results(id, scan_id, engine, version, raw_json, mean_conf)
extractions(id, scan_id, field_code, value_raw, value_norm, source[regex|llm|human], confidence, bbox)
measurements(id, scan_id, field_code, glyph, height_mm, width_mm, uncertainty_mm, method)
findings(id, scan_id, rule_id, rulepack_version, verdict, observed, required, citation, bbox, confidence)
rulepacks(id, code, version, effective_from, checksum, published_by, published_at)
reports(id, scan_id, pdf_key, docx_key, json_key, sha256, generated_at)
bis_queries(id, org_id, scan_id NULL, question, answer, citations_json, model, created_at)
bis_documents(id, source_type, title, url, published_at, sha256)
bis_chunks(id, document_id, text, embedding vector(1024), section_ref)
audit_log(id, org_id, actor_id, action, entity, entity_id, prev_hash, hash, created_at)
```

`findings` is append-only and always stamped with `rulepack_version`. A report regenerated a year later must reproduce the verdict that was issued under the rules in force at scan time.

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

- Auth: phone OTP + JWT access/refresh; org-scoped RBAC (`admin`, `inspector`, `analyst`, `viewer`); row-level org isolation enforced in the repository layer, tested.
- Storage: presigned URLs only, private buckets, per-org key prefix, server-side encryption.
- Evidence integrity (Mode A): SHA-256 of the raw image recorded at upload; `audit_log` is hash-chained (`hash = H(prev_hash || row)`); reports embed both hashes. Anyone can verify a report was not altered after issue.
- Location and device data: collected only in Mode A, disclosed in-app, retention configurable per org.
- DPDP Act 2023 posture: the data is about products, not people, which is a genuine advantage over most health/fintech entries. The only personal data is user accounts and inspector location. Say this explicitly to judges.
- Rate limiting per org and per IP; upload size and MIME allow-list; EXIF stripped from anything served publicly.

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
