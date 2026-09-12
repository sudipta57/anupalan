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
