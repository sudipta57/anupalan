# Anupalan backend

FastAPI + Celery, one codebase, two entrypoints. Compliance engine for packaged commodities in
India — see the repo root [`README.md`](../README.md) and [`CLAUDE.md`](../CLAUDE.md) for what
this project is. This file is only about running and testing what lives in `backend/`.

**Read before touching anything here:**

- [`../CLAUDE.md`](../CLAUDE.md) — non-negotiables, layout, conventions. Loaded automatically by
  Claude Code every session; humans should read it once too.
- [`../docs/04-backend-implementation-plan.md`](../docs/04-backend-implementation-plan.md) — the
  backend work-package sequence (B0–B23) and one handoff card per package. Check it before
  starting anything.
- [`../docs/01-architecture.md`](../docs/01-architecture.md) §5, §8, §9 — the pipeline, data
  model and the settled technology decisions.
- [`../docs/02-trd.md`](../docs/02-trd.md) — every requirement's acceptance test.

---

## 1. Setup

There is no local infrastructure to stand up. Postgres is **Neon**, Redis is **Redis Cloud**,
object storage is **Cloudflare R2** — all managed services, provisioned once per
[`../infra/README.md`](../infra/README.md).

```bash
cd backend
python3.12 -m venv .venv                     # Python 3.12 required (pyproject.toml)
source .venv/bin/activate                    # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cp .env.example .env                         # paste the real Neon / Redis Cloud / R2 values
```

`.env` (not `.env.local` or any other name — `app/config.py` reads exactly `.env`) needs, at
minimum, `DATABASE_URL`, `DATABASE_URL_DIRECT`, `REDIS_URL`, and the `S3_*` block. Both database
URLs use the `postgresql+psycopg://` scheme (psycopg 3, not psycopg2) — copying a URL straight
out of the Neon console usually gives you plain `postgresql://`, which will fail with
`ModuleNotFoundError: No module named 'psycopg2'`.

Confirm connectivity before writing any code:

```bash
make -C .. check
```

This calls `app.health.check_health()` directly — the same path `GET /health` uses — and prints
the JSON. `db`/`redis` show `error` rather than crashing if a URL is unset or unreachable; the API
itself always answers 200 with `status: degraded` in that case, by design (it's a report, not a
gate).

---

## 2. Running

```bash
uvicorn app.main:app --reload              # API on :8000 — docs at /docs, health at /health
celery -A app.worker worker -l info        # worker, in a second shell
```

Or via the root `Makefile` (`make api`, `make worker` — note the Makefile assumes a Unix-style
venv layout, `.venv/bin/`; on Windows call the two commands above directly, since Windows venvs
put executables in `.venv\Scripts\`).

```
GET /health  ->  {"status":"ok","db":"ok","redis":"ok","rulepack":"LM-2011-v1.0"}
```

---

## 3. Testing

```bash
pytest                              # everything
pytest tests/test_rules.py -v       # one suite, verbose
pytest --update-golden              # rewrite a golden fixture — see below; this run FAILS on purpose
ruff check .
mypy app/services                   # --strict is scoped to services/ (pyproject.toml)
```

**Do not edit a test to make it pass.** Tests are the specification here — `CLAUDE.md` §6. If one
looks wrong, say so and stop.

**Golden files.** `tests/fixtures/findings/*.json` pin committed pipeline output. A diff in one
must be a deliberate, reviewed change, never a silent update — see
[`tests/fixtures/README.md`](tests/fixtures/README.md) for the exact procedure. `--update-golden`
rewrites and then fails the run it rewrote, so a rewrite can never be mistaken for a pass; review
the diff, then re-run without the flag.

**Coverage floor.** `services/rules` and `services/vision` carry an 80% floor (`CLAUDE.md` §5) —
these are the two places a bug is silent.

```bash
pip install pytest-cov   # not yet in pyproject.toml — ask before adding it for real
pytest --cov=app.services.rules --cov-report=term-missing
```

---

## 4. What exists right now

Kept brief on purpose — the authoritative, continuously-updated version of this table is
[`../docs/04-backend-implementation-plan.md`](../docs/04-backend-implementation-plan.md) §0.
Update that file, not this section, when a package lands.

| Area | State |
|---|---|
| `app/config.py`, `app/db.py`, `app/main.py`, `app/worker.py`, `app/health.py` | Scaffolded and working. `GET /health` is real; no router is registered yet. |
| `app/services/rules/` | **Implemented (B0–B3).** Rule pack validation with line-level errors, checksumming, the pure `evaluate()` interpreter over all seven rule kinds, findings assembly. 14 baseline cases green. |
| `app/services/{vision,extraction,reporting,bis,llm}/` | Not started. |
| `app/models/`, `app/repositories/`, `alembic/versions/` | Not started — no migration exists yet. |
| `app/routers/*.py` | Docstrings only; zero routes registered. |

---

## 5. Layout

```
backend/
├── app/
│   ├── main.py            FastAPI entrypoint — CORS, error envelope, /health
│   ├── worker.py           Celery entrypoint — imports app/services/, never its own logic
│   ├── config.py           all settings; PX_PER_MM and RULEPACK_PATH live here, nowhere else
│   ├── db.py               Neon engine + session scope
│   ├── routers/            one module per resource group; no pipeline logic lives here
│   ├── services/           the pipeline — vision, extraction, rules, reporting, bis, llm
│   ├── models/             SQLAlchemy
│   ├── schemas/             Pydantic
│   └── repositories/       org-scoped data access — the only way a router touches the DB
├── alembic/                migrations, run against DATABASE_URL_DIRECT
├── tests/
│   ├── conftest.py         fixture loaders + the golden-file / --update-golden contract
│   └── fixtures/           committed profiles, OCR dumps, golden findings, broken rule packs
└── pyproject.toml
```

Two rules that don't show up in a file tree: the Celery worker is not a separate project — it
imports `app/services/` so pipeline code is written once — and rule packs live in
`../rulepacks/`, never inside `app/`, because they're data with legal consequences, not code.
