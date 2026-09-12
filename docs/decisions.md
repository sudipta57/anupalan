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
