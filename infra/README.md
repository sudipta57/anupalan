# infra/

No containers. Postgres, Redis and object storage are **managed services**, provisioned once
through their providers' consoles rather than declared in a compose file. This folder holds the
provisioning runbook and, later, deploy scripts.

| Concern | Service | Notes |
|---|---|---|
| Database | **Neon** (serverless Postgres + pgvector) | scale-to-zero; pooled and direct endpoints |
| Queue / cache | **Redis Cloud** | `rediss://` over TLS, non-default port |
| Object storage | **Cloudflare R2** | S3 API, zero egress fees |

Nothing here holds a credential. Every value goes in `backend/.env`, which is gitignored. The
variable names and shapes are documented in [`backend/.env.example`](../backend/.env.example).

---

## 1. Neon — Postgres + pgvector

1. Create a project. Pick **Postgres 16** and the region closest to your users
   (`ap-south-1`, Mumbai, for an India deployment — latency and data residency both matter, see
   [01-architecture.md](../docs/01-architecture.md) §9).
2. Enable pgvector in the database you will use:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
   The BIS corpus stores `vector(1024)` embeddings (`bis_chunks`), so this must exist before the
   first migration that creates that table.
3. Copy **both** connection strings from the dashboard:

   | Env var | Which endpoint | Used by |
   |---|---|---|
   | `DATABASE_URL` | **Pooled** — host contains `-pooler` | the API and the worker |
   | `DATABASE_URL_DIRECT` | **Direct** — no `-pooler` | Alembic migrations only |

   Both need `?sslmode=require`, and the scheme must be `postgresql+psycopg://` for SQLAlchemy to
   pick psycopg 3.

**Why two URLs.** The pooled endpoint is pgbouncer in transaction mode. It multiplexes many
application connections onto few Postgres ones, which is what you want for a serverless database —
but it cannot run DDL reliably inside a transaction, and it cannot route server-side prepared
statements. So migrations go direct, and the application code disables psycopg's prepared-statement
threshold (`prepare_threshold=None`, set in `app/db.py`). Getting this wrong produces
`prepared statement "_pg3_0" does not exist` under load — intermittently, which is the worst kind.

**Scale-to-zero.** An idle Neon branch suspends. The first query after that pays a cold start of
roughly half a second to a few seconds. `pool_pre_ping` and `pool_recycle` handle the dropped
connections; budget for the latency against TRD NFR-01.

---

## 2. Redis Cloud — broker, result backend and cache

1. Create a database. The free tier is enough for development.
2. Copy the endpoint and password into `REDIS_URL` as
   `rediss://default:<password>@<host>:<port>/0`.

**Use `rediss://`, not `redis://`.** Redis Cloud terminates TLS on a non-default port. Celery needs
`broker_use_ssl` configured for a TLS broker, and `app/worker.py` switches it on automatically when
it sees the `rediss://` scheme — so the scheme in the URL is load-bearing, not cosmetic. A
`redis://` URL against a TLS endpoint fails at connect time with a protocol error.

Celery is configured with `task_acks_late` and `worker_prefetch_multiplier=1` so a scan survives a
worker restart mid-job (TRD NFR-04).

---

## 3. Cloudflare R2 — images, rectified assets, reports

1. Create a bucket. Keep it **private**; all access is through presigned URLs
   ([01-architecture.md](../docs/01-architecture.md) §10).
2. Create an R2 API token scoped to that bucket and copy the access key id and secret.
3. Fill in:
   - `S3_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com`
   - `S3_REGION=auto` — R2 has no regions and requires the literal string `auto`
   - `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`

R2 is addressed through the S3 API, so the settings are named `S3_*` and any S3-compatible store
works by changing the endpoint and keys. That matters because a government deployment may have to
run wholly on-premise, and the object store is the easiest piece to move.

**R2 has no ACLs.** Do not send `ACL=public-read`; it is rejected. Public access, if ever needed,
is a bucket-level custom domain — put it in `S3_PUBLIC_BASE_URL`.

No S3 client is a dependency yet. Presigned upload URLs are TRD FR-20 (P2.2), and the client
library arrives with them.

---

## 4. Verifying a fresh environment

```bash
cd backend
cp .env.example .env        # then paste the real values in
make check                  # from the repo root: confirms db and redis answer
```

`make check` starts nothing. It reads `.env` and reports what `GET /health` would report:

```
{"status":"ok","db":"ok","redis":"ok","rulepack":"LM-2011-v1.0"}
```

A component showing `error` means that service is unreachable or its URL is unset — the API still
answers 200 with `status: degraded`, because a health endpoint reports rather than fails closed.

---

## 5. Deploying

No Dockerfile. The API and the worker are two processes from one codebase:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000   # API
celery -A app.worker worker -l info                # worker
```

Run them under a process supervisor — systemd on a VM behind Caddy for TLS, or a PaaS that builds
from source with a buildpack. Deploy scripts land in this folder when the pilot needs them; see
[01-architecture.md](../docs/01-architecture.md) §13.
