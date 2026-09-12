# Anupalan

**अनुपालन** — *compliance*. A compliance engine for packaged commodities in India.

Photograph a product package with a printed scale marker in frame. Anupalan flattens the
image to a known millimetres-per-pixel scale, reads the text, extracts the mandatory
declarations, **measures glyph heights in millimetres**, and evaluates a versioned rule pack
to produce a per-rule verdict that cites its legal source. The same product profile then
drives a BIS applicability check.

Font size in millimetres is the check nobody else automates, and it is the reason the marker
exists: without a known physical reference in frame, "is this numeral at least 2 mm tall?"
is unanswerable.

---

## ⚠️ Advisory tool — not a certification

Anupalan produces a **pre-audit opinion, not a certification**. Its output carries no legal
force and does not substitute for a Legal Metrology inspection, a BIS certification, or
professional legal advice.

The rule pack in [`rulepacks/`](rulepacks/) is an **engineering transcription** of published
sources, **pending clause-by-clause legal review** by a Legal Metrology practitioner. It has
not been reviewed or signed off. Treat every verdict as advisory until that review lands —
it is tracked as a release blocker, not a nice-to-have
(see [02-trd.md](docs/02-trd.md) §6 and [03-implementation-plan.md](docs/03-implementation-plan.md) §10).

Verdicts are deliberately four-valued — `PASS` / `FAIL` / `BORDERLINE` / `NOT_ASSESSABLE` —
because accusing a compliant label is the failure mode that matters most.

---

## The two problem statements

Built against two Smart India Hackathon 2026 problem statements from the
**Department of Consumer Affairs**, Ministry of Consumer Affairs, Food & Public Distribution:

| PS | Title | Module |
|---|---|---|
| **SIH26034** | Scan product labels and check them against the Legal Metrology (Packaged Commodities) Rules, 2011 | **Anupalan Scan** |
| **SIH26107** | An AI assistant for Indian Standards and BIS certification services | **Anupalan Sahayak** |

They combine into one system because they share the same input and the same missing
abstraction: a *product profile* extracted from a pack. One scan answers both *"is this label
legal?"* and *"does this product need the ISI mark?"* — see
[01-architecture.md](docs/01-architecture.md) §2.

Two user modes over one backend: **enforcement** (Legal Metrology officers) and **industry**
(brands, packaging agencies, marketplace sellers). Rule evaluation is identical in both.

---

## Repository layout

Authoritative definition in [CLAUDE.md](CLAUDE.md) §2.

```
anupalan/
├── CLAUDE.md          # repo contract: layout, non-negotiables, conventions, gotchas
├── docs/              # architecture, TRD, implementation plan, decisions, eval results
├── rulepacks/         # versioned YAML rule packs — the legal logic, as data
├── mobile/            # React Native (Expo dev build), Android
├── backend/           # FastAPI + Celery — one codebase, two entrypoints
├── infra/             # managed-service runbook (Neon, Redis Cloud, R2)
└── .github/           # CI, PR template, dependabot
```

Three layout rules that are not negotiable:

- **No second backend runtime.** No Node/Express service. The reasoning is in
  [01-architecture.md](docs/01-architecture.md) §9.
- **The Celery worker is not a separate project.** It imports `app/services/`, so pipeline
  code is written once.
- **Rule packs live in `rulepacks/`, never in `backend/app/`.** They are data, versioned
  independently of code.

---

## Infrastructure

**No containers.** The stateful pieces are managed services, provisioned once:

| Concern | Service | Notes |
|---|---|---|
| Database | **Neon** — serverless Postgres 16 + pgvector | two connection strings: pooled for the app, direct for migrations |
| Queue / cache | **Redis Cloud** | `rediss://` over TLS |
| Object storage | **Cloudflare R2** | S3 API, private bucket, presigned access only |

The provisioning runbook — including why Neon needs two URLs and the two traps that will
otherwise cost you a day — is [infra/README.md](infra/README.md). The application itself is two
processes from one codebase, so the machine running it holds no state.

## Quickstart — backend

Requires **Python 3.12** and accounts on the three services above. No Docker.

> This machine's bare `python` may be a different version. Create the venv with an explicit
> 3.12 interpreter — `uv python install 3.12` provides one if you do not have it.

```bash
# 1. backend venv and dependencies
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. configuration — copy the example and paste your connection strings.
#    Never commit the result; .env is gitignored.
cp .env.example .env

# 3. confirm the managed services answer before starting anything
make -C .. check
# -> {"status":"ok","db":"ok","redis":"ok","rulepack":"LM-2011-v1.0"}

# 4. run it
uvicorn app.main:app --reload            # API on :8000
celery -A app.worker worker -l info      # worker, in a second shell

# 5. check it over HTTP
curl localhost:8000/health
# -> {"status":"ok","db":"ok","redis":"ok","rulepack":"LM-2011-v1.0"}
```

`/health` answers **200 even when a dependency is down**, reporting `status: degraded` and naming
the failed component — it is a report, not a gate. A `db` or `redis` of `"error"` means that URL
is unset or unreachable.

Tests, lint and types:

```bash
pytest                          # all tests
ruff check .                    # lint
mypy app/services               # strict types on the services layer
```

There are **no migrations yet** — Alembic is initialised and wired to config, but the data
layer is P2.2 work. `make migrate` runs `alembic upgrade head` once migrations exist, against
Neon's **direct** endpoint (`DATABASE_URL_DIRECT`) rather than the pooled one.

---

## Quickstart — mobile

Requires **Node 20+** and an Android device or emulator. No Docker.

```bash
cd mobile
npm install
npm run lint
```

**Expo Go will not work.** `react-native-vision-camera` frame processors — the live marker,
blur, glare and tilt gates that make capture reliable — do not run in Expo Go. You need an
EAS **dev client** build, and you want it on day one of mobile work:

```bash
npx eas build --profile development --platform android   # produces a dev-client APK
npx expo start --dev-client
```

Details and the fallback path in [mobile/README.md](mobile/README.md).

---

## Where to read next

Start with **[docs/00-README.md](docs/00-README.md)** — the documentation index. It says which
doc to open for which kind of change, and carries the three things to keep straight.

Working in this repo with Claude Code? [CLAUDE.md](CLAUDE.md) is loaded every session and is
the contract. Humans should read it once too.

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) — conventional commits, one PR per TRD
requirement id, and the rule about not editing tests to make them pass.

---

## Status

Scaffolding only. P0 (the measurement spike — the one phase that can invalidate the concept)
is the immediate next action; see [03-implementation-plan.md](docs/03-implementation-plan.md).

No vision, OCR, metrology, rules-evaluation, extraction, reporting or BIS logic is
implemented yet. Placeholder modules name the TRD requirement they will implement.

## Licence

**Not yet chosen.** See [LICENSE](LICENSE) — it is a placeholder, and until it is replaced
this code carries no grant of rights to anyone. Pick one before the repository goes public.
