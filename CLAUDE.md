# CLAUDE.md

Instructions for Claude Code working in this repository. Read this before touching anything.

---

## 1. What this project is

**Anupalan** — a compliance engine for packaged commodities in India. Built against two Smart India Hackathon 2026 problem statements from the Department of Consumer Affairs:

- **SIH26034** — scan product labels and check them against the Legal Metrology (Packaged Commodities) Rules, 2011
- **SIH26107** — an AI assistant for Indian Standards and BIS certification services

A user photographs a package with a printed scale marker in frame. The system flattens the image to a known millimetres-per-pixel scale, reads the text, extracts the mandatory declarations, **measures glyph heights in millimetres**, and evaluates a versioned rule pack to produce per-rule verdicts, each citing its legal source. The same product profile then drives a BIS applicability check.

Two user modes over one backend: **enforcement** (Legal Metrology officers) and **industry** (brands, packaging agencies, marketplace sellers).

---

## 2. Repository layout

Everything lives under one root folder. Two application folders: `mobile/` for the React Native app, `backend/` for the API and worker.

```
anupalan/                         # root
├── CLAUDE.md                     # this file
├── README.md
├── docs/                         # architecture, TRD, implementation plan, decisions
├── rulepacks/                    # versioned YAML rule packs — the legal logic
│
├── mobile/                       # FRONTEND — React Native (Expo dev build), Android
│   ├── app/                      # expo-router screens
│   ├── src/
│   │   ├── api/                  # generated client + hooks (TanStack Query)
│   │   ├── domain/               # types shared with backend schemas
│   │   ├── features/             # capture, findings, sahayak, history, reports
│   │   ├── components/
│   │   ├── db/                   # SQLite offline queue
│   │   └── native/               # vision-camera frame processor plugin
│   ├── assets/
│   └── __tests__/
│
├── backend/                      # BACKEND — FastAPI + Celery, one codebase, two entrypoints
│   ├── app/
│   │   ├── main.py               # FastAPI entrypoint
│   │   ├── worker.py             # Celery entrypoint
│   │   ├── config.py
│   │   ├── routers/              # auth, products, scans, reports, sahayak, admin, dashboard
│   │   ├── services/
│   │   │   ├── vision/           # marker, rectify, ocr, metrology
│   │   │   ├── extraction/       # regex layer, llm layer, normalisation
│   │   │   ├── rules/            # rule pack loader + deterministic evaluator
│   │   │   ├── reporting/        # pdf, docx, json
│   │   │   ├── bis/              # corpus ingest, retrieval, applicability
│   │   │   └── llm/              # provider interface + adapters
│   │   ├── models/               # SQLAlchemy
│   │   ├── schemas/              # Pydantic
│   │   └── repositories/         # org-scoped data access
│   ├── alembic/
│   ├── tests/
│   │   └── fixtures/             # golden images + expected findings JSON
│   └── pyproject.toml
│
└── infra/                        # managed-service runbook, Caddyfile, deploy scripts
```

Rules for this layout:
- **Never create a second backend runtime.** No Node/Express service. The decision and its reasoning are in `docs/01-architecture.md` §9.
- The Celery worker is **not** a separate project. It imports from `app/services/` so pipeline code is written once.
- Anything shared between `mobile/` and `backend/` flows one way: backend publishes an OpenAPI schema, mobile generates its client from it. Never hand-maintain duplicate types.
- Rule packs live in `rulepacks/`, never inside `backend/app/`. They are data, versioned independently of code.

---

## 3. Non-negotiables

These are the design decisions the whole project rests on. Do not work around them. If a task seems to require breaking one, stop and ask.

1. **The LLM never decides compliance.** It extracts field values and writes explanations. Every PASS/FAIL comes from `services/rules/evaluate()`, a pure deterministic function over a rule pack. Verdicts must be reproducible, citable and regression-testable.

2. **Thresholds live in the rule pack, never in code.** No millimetre value, no table row, no effective date hardcoded in a `.py` file. If you need a number, read it from the loaded pack.

3. **Millimetres require the marker.** Every metric measurement derives from the marker homography. No marker means metric rules return `NOT_ASSESSABLE`. Never estimate, infer or guess a physical size.

4. **Verdicts are four-valued:** `PASS | FAIL | BORDERLINE | NOT_ASSESSABLE`. Never collapse BORDERLINE into FAIL. Accusing a compliant label is the failure mode that kills the product.

5. **Never ingest priced Indian Standards texts** into the BIS corpus. Full IS documents are copyrighted and sold by BIS. The corpus is public material only: Quality Control Orders, the mandatory-certification and CRS product lists, BIS scheme guides and FAQs, hallmarking pages, lab directory, catalogue metadata. `services/bis/ingest.py` carries an explicit blocklist — keep it and keep the comment explaining why.

6. **Every finding carries `rulepack_version`.** A report regenerated next year must reproduce the verdict issued under the rules in force at scan time.

7. **Every query is org-scoped.** Go through `repositories/`, which enforces it. Cross-org access returns 404, not 403 — do not leak existence.

8. **Every report and findings screen carries the advisory disclaimer.** This is a pre-audit tool, not a certification.

---

## 4. Commands

```bash
# backend
# Nothing to start locally: Postgres (Neon), Redis (Redis Cloud) and object storage
# (Cloudflare R2) are managed services. Runbook and provisioning: infra/README.md.
cd backend
cp .env.example .env                          # paste the real connection strings
make -C .. check                              # confirms db + redis answer before you start
alembic upgrade head                          # runs against Neon's DIRECT endpoint
uvicorn app.main:app --reload                 # API on :8000
celery -A app.worker worker -l info           # worker
pytest                                        # all tests
pytest tests/test_rules.py -v                 # one suite
ruff check . && mypy app/services             # lint + types
alembic revision --autogenerate -m "message"  # new migration

# mobile
cd mobile
npm install
eas build --profile development --platform android   # dev client — required, see §8
npx expo start --dev-client
npm run test
npm run lint
npm run gen:api                               # regenerate client from backend OpenAPI

# evaluation
cd backend
python -m scripts.eval_e1 --dir ../eval/e1    # measurement accuracy
python -m scripts.eval_e3 --dir ../eval/e3    # rule verdicts, false-FAIL rate
python -m scripts.eval_e4 --set ../eval/e4    # sahayak citations
```

`GET /health` should return `{"status":"ok","db":"ok","redis":"ok","rulepack":"LM-2011-v1.0"}`.

---

## 5. Code conventions

**Python**
- 3.12, full type annotations on every public function. numpy arrays typed as `npt.NDArray[np.uint8]`.
- `ruff` + `mypy --strict` on `app/services/`. No `# type: ignore` without a comment explaining it.
- `services/rules/` and `services/vision/` hold an 80% coverage floor — these are where a bug is silent.
- `services/rules/evaluate()` is pure: no I/O, no model calls, no `datetime.now()`. Effective-date filtering takes `as_of` as an argument.
- Money as integer paise. Lengths as float millimetres. Never mix units in a variable name — `height_mm`, not `height`.

**TypeScript**
- No `any` in `src/api/` or `src/domain/`.
- eslint + prettier, enforced in CI.
- Server state via TanStack Query. Local UI state via zustand. Do not put server data in zustand.

**Both**
- Conventional commits. One PR per TRD requirement id, titled with it (e.g. `feat(vision): FR-23 glyph metrology`).
- Errors follow one envelope: `{"error": {"code", "message", "details"}}`.

---

## 6. Testing rules

- **Do not edit tests to make them pass.** Tests are written before implementation and are the specification. If a test looks wrong, say so and stop — do not change it.
- Golden-file tests in `backend/tests/fixtures/` pin the pipeline output. A diff in a golden file must be a deliberate, reviewed change, never a silent update.
- The rules engine has 14 baseline cases documented in `docs/03-implementation-plan.md` §P2.4. Every new rule adds at least one PASS case, one FAIL case and one BORDERLINE case.
- Org isolation has its own suite. It runs on every PR.
- Before any demo, re-run the E1/E3/E4 evaluations and commit the numbers to `docs/eval-results.md` with a date.

---

## 7. Ask before doing

Stop and ask rather than deciding alone:
- Adding any dependency
- Changing the database schema or writing a migration
- Changing an API contract that `mobile/` consumes
- Adding or replacing a managed service, or repointing `DATABASE_URL` / `REDIS_URL` / the S3 endpoint at a different provider
- Changing anything in `rulepacks/` — rule text has legal consequences and needs review
- Anything that touches a §3 non-negotiable

Free to decide alone: internal refactors behind a stable interface, test additions, error-message wording, logging, performance work that does not change output.

---

## 8. Gotchas that have already cost time

- **Expo Go will not run vision-camera frame processors.** You need an EAS dev build. Build it on day one of mobile work.
- **`PX_PER_MM` is imported from config.** Never write `20` at a call site.
- **Neon's pooled endpoint is pgbouncer, and psycopg 3 uses prepared statements.** `app/db.py`
  sets `prepare_threshold=None` for exactly this reason. Remove it and you get
  `prepared statement "_pg3_0" does not exist` under load but never in testing. Migrations use
  `DATABASE_URL_DIRECT`, the non-pooled endpoint, because pgbouncer cannot run DDL reliably in a
  transaction.
- **Celery does not infer TLS from a `rediss://` URL.** `broker_use_ssl` must be set, which
  `app/worker.py` does off the URL scheme. A plaintext `redis://` against a TLS endpoint fails at
  connect time, not at startup.
- **OCR bounding boxes are not glyph heights.** They include ascenders, descenders and padding. Glyph measurement goes through connected components on the rectified image, never through OCR polygons.
- **The marker must print at exactly 100% scale.** If the printer scales the page, every millimetre downstream is wrong and the bug looks like a code bug for days. Verify printed markers with a ruler.
- **Planar homography under-measures on curved packs.** Detect high curvature and downgrade metric rules to `NOT_ASSESSABLE` rather than reporting a confident wrong number.
- **The LLM extraction layer must return a `source_span`** for every field, and that span must exist in the input OCR text. Validate it; do not trust it.

---

## 9. LLM usage in this codebase

Three call sites, all behind `services/llm/provider.py`. No vendor name appears anywhere outside `config.yaml` and the adapter files.

| Call site | Purpose | Tier |
|---|---|---|
| `extraction.llm_layer` | Map OCR text to field codes, strict JSON schema, temperature 0 | Budget |
| `reporting.explain` | Turn a finding into plain-language guidance | Budget |
| `bis.answer` | Write a cited answer from retrieved chunks | Mid |

An open-weight adapter must stay working. A government deployment may need to run entirely on-premise, and that capability is part of the pitch. Never write code that assumes a specific provider's features.

Non-LLM models in use, all self-hosted: PaddleOCR PP-OCRv4 (text detection + recognition), BGE-M3 (embeddings), a cross-encoder reranker.

---

## 10. Documentation duties

| File | When to read | When to update |
|---|---|---|
| `docs/01-architecture.md` | Before changing the pipeline, data model or a technology choice. §9 lists rejected alternatives — check it before re-arguing a settled decision. | Same PR as any architectural change |
| `docs/02-trd.md` | Before implementing a feature — every FR/NFR has an acceptance test | When a requirement changes |
| `docs/03-implementation-plan.md` | At the start of each phase | When phase scope changes |
| `docs/04-frontend-plan.md` | Before any mobile work — the fourteen frontend stages and their status | In the same change that completes a stage |
| `docs/decisions.md` | When a decision looks odd | Append a dated line on every architectural change |
| `docs/eval-results.md` | Before any demo | After every evaluation run |
| `rulepacks/lm-2011-v1.yaml` | Before touching rule logic | Only with review — see §7 |

A doc that lags the code by two weeks is worse than no doc. Architecture changes and their doc updates ship in the same PR.

---

## 11. Task handoff format

Work is handed over one task at a time in this shape. If a task arrives without these parts, ask for the missing ones before starting.

```
CONTEXT:     which docs and sections to read first
TASK:        the single file or module to produce
CONSTRAINTS: purity, dependencies, naming, what not to touch
SIGNATURE:   exact function or class signatures
TESTS:       the test file to pass — already written, do not edit
DONE WHEN:   the command that must pass (pytest path, mypy clean, etc.)
```

## 12. Definition of done

A task is done when: the named tests pass, `ruff` and `mypy` are clean (or `lint` for mobile), no new dependency was added without asking, the relevant doc is updated in the same change, and the diff contains nothing the task did not ask for.
