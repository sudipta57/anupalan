# Anupalan — developer entrypoints.
# Commands mirror CLAUDE.md §4. If you change one here, change it there.
#
# There is nothing to start locally: Postgres (Neon), Redis (Redis Cloud) and object storage
# (Cloudflare R2) are managed services. Provisioning runbook in infra/README.md.

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND    := backend
VENV       := $(BACKEND)/.venv
PY         := $(VENV)/bin/python
PIP        := $(VENV)/bin/pip
UVICORN    := $(VENV)/bin/uvicorn
CELERY     := $(VENV)/bin/celery
PYTEST     := $(VENV)/bin/pytest
RUFF       := $(VENV)/bin/ruff
MYPY       := $(VENV)/bin/mypy
ALEMBIC    := $(VENV)/bin/alembic

# The repo targets Python 3.12 (CLAUDE.md §5). Bare `python` may be something else.
PYTHON312  ?= python3.12

.PHONY: help dev api worker test lint migrate check venv install audit openapi eval-e1 eval-e3 eval-e4 loadtest mobile-install mobile-lint mobile-test clean

help:  ## Show this help
	@echo "Anupalan — make targets"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo

# ---------------------------------------------------------------- environment

$(VENV):
	$(PYTHON312) -m venv $(VENV)

venv: $(VENV)  ## Create backend/.venv with Python 3.12

install: venv  ## Install backend deps (editable, with dev extras)
	$(PIP) install --upgrade pip
	$(PIP) install -e "$(BACKEND)[dev]"

check:  ## Probe the managed services — same code path as GET /health
	@cd $(BACKEND) && ../$(PY) -c \
		"from app.health import check_health; print(check_health().model_dump_json())"

# ---------------------------------------------------------------- backend

dev: api  ## Alias for `api` — the everyday target

api:  ## Run the FastAPI app with reload
	@echo "--> API on http://localhost:8000  (docs at /docs, health at /health)"
	@echo "--> run 'make worker' in a second shell for the Celery worker"
	cd $(BACKEND) && ../$(UVICORN) app.main:app --reload

worker:  ## Run the Celery worker
	cd $(BACKEND) && ../$(CELERY) -A app.worker worker -l info

test:  ## Run the backend test suite
	cd $(BACKEND) && ../$(PYTEST)

lint:  ## ruff + mypy (strict on app/services), then mobile eslint
	cd $(BACKEND) && ../$(RUFF) check .
	cd $(BACKEND) && ../$(MYPY) app/services
	cd mobile && npm run lint

migrate:  ## Apply migrations via Neon's direct endpoint (DATABASE_URL_DIRECT)
	cd $(BACKEND) && ../$(ALEMBIC) upgrade head

openapi:  ## Write the OpenAPI schema to backend/openapi.json (mobile runs gen:api off this)
	cd $(BACKEND) && ../$(PY) -c 		"import json,pathlib; from app.main import app; 		 pathlib.Path('openapi.json').write_text(json.dumps(app.openapi(), indent=2), encoding='utf-8'); 		 print('wrote backend/openapi.json')"

audit:  ## Dependency audit (B23). pip-audit is dev-only and installed on demand.
	@echo "--> installed versions"
	$(PIP) list --format=columns
	@echo
	@echo "--> known vulnerabilities (pip-audit)"
	@$(PY) -m pip_audit --strict 2>/dev/null 		|| echo "pip-audit is not installed. Run: $(PIP) install pip-audit   (dev-only; see docs/06-api-reference.md §Security)"

# ---------------------------------------------------------------- evaluation (B22)
# Corpora live under eval/, which is gitignored. The scripts commit numbers, never images.

eval-e1:  ## E1 — metrology accuracy
	cd $(BACKEND) && ../$(PY) -m scripts.eval_e1 --dir ../eval/e1

eval-e3:  ## E3 — rule verdicts and the false-FAIL rate
	cd $(BACKEND) && ../$(PY) -m scripts.eval_e3 --dir ../eval/e3

eval-e4:  ## E4 — sahayak citations and refusals
	cd $(BACKEND) && ../$(PY) -m scripts.eval_e4 --set ../eval/e4

loadtest:  ## NFR-01 load test. Needs BASE_URL, IMAGE and PHONE; run it against staging.
	cd $(BACKEND) && ../$(PY) -m scripts.loadtest 		--base-url "$(BASE_URL)" --image "$(IMAGE)" --phone "$(PHONE)"

# ---------------------------------------------------------------- mobile

mobile-install:  ## npm install in mobile/
	cd mobile && npm install

mobile-lint:  ## eslint in mobile/
	cd mobile && npm run lint

mobile-test:  ## jest in mobile/
	cd mobile && npm test

# ---------------------------------------------------------------- housekeeping

clean:  ## Remove Python caches and build artefacts (keeps .venv)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
	rm -rf $(BACKEND)/build $(BACKEND)/dist $(BACKEND)/*.egg-info
