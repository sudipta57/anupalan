# Anupalan — API reference

**Doc version:** v1.0 · **Written:** 12 Sep 2026 · **API version:** `v1`
**Companions:** [`02-trd.md`](02-trd.md) §5 is the contract this implements;
[`01-architecture.md`](01-architecture.md) §10 is the security model behind it.

The machine-readable schema is the source of truth and is generated from the code:

```bash
make openapi          # writes backend/openapi.json
# or, with the API running:
curl http://localhost:8000/openapi.json
```

`mobile/` generates its client from that file (`npm run gen:api`). **Do not hand-maintain types on
both sides** (`CLAUDE.md` §2). This document exists for the things a schema cannot say: why an
endpoint behaves the way it does, and which failures are deliberate.

---

## 1. Conventions

| | |
|---|---|
| Base path | `/v1` |
| Auth | `Authorization: Bearer <access token>` on everything except `/health` and the two OTP endpoints |
| Errors | One envelope, always: `{"error": {"code", "message", "details"}}` (NFR-07) |
| Timestamps | ISO-8601, UTC |
| Money | Integer paise |
| Lengths | Float millimetres |
| Idempotency | `Idempotency-Key` honoured on every creating POST |
| Pagination | Cursor, via `next_cursor` |

### The rules that shape every response

**`org_id` is never accepted in a request body.** It comes from the verified token and nowhere
else. A body carrying one is a **400** with `code: org_id_not_accepted` — not a silent drop, which
would be equally safe and would also hide both a broken client and someone probing for exactly
this.

**Cross-org access is a 404, never a 403.** Another org's scan, finding, report or product is
indistinguishable from one that does not exist. A 403 would confirm the row exists, which tells an
attacker with a guessed id precisely what they wanted to know. A 403 *is* returned when your own
role is insufficient — inside your own org, that reveals nothing and is the only way to learn what
to ask an admin for.

**Verdicts are four-valued** — `PASS | FAIL | BORDERLINE | NOT_ASSESSABLE` — and BORDERLINE is
never folded into FAIL. A rule that does not apply produces **no finding at all**; its id appears
in `not_applicable_rule_ids` instead. "Does not apply to you" and "we could not measure it" are
different outcomes and the API keeps them apart.

**Every verdict names its rule pack.** `rulepack_version` is on every finding and every findings
response. A report regenerated next year must reproduce the verdict issued under the rules in force
at scan time.

---

## 2. Errors

```json
{ "error": { "code": "rate_limited", "message": "too many requests for this ip. Retry in 43 seconds.", "details": { "scope": "ip", "limit": 120 } } }
```

| Status | `code` | Meaning |
|---|---|---|
| 400 | `org_id_not_accepted` | The body carried an `org_id` |
| 401 | `http_401` | Missing, malformed or invalid token. Carries `WWW-Authenticate: Bearer`. The message never says *which* — that would tell an attacker which half of an attempt worked |
| 403 | `permission_denied` | Your role lacks the permission. `details` names the permission and the role |
| 404 | `http_404` | Not found, **or** another org's row |
| 409 | `http_409` | Idempotency key replayed with a different body; or a scan that has not been evaluated yet |
| 413 | `http_413` | Upload over the ceiling |
| 422 | `validation_error` | Schema validation failed. `details` carries per-field errors |
| 429 | `rate_limited` | See §6. Carries `Retry-After` |
| 500 | `internal_error` | Never a stack trace |

---

## 3. Endpoints

### Auth

```
POST /v1/auth/otp/request    {phone}               -> {request_id, code?}
POST /v1/auth/otp/verify     {request_id, code}    -> {access, refresh, user, org}
POST /v1/auth/refresh        {refresh}             -> {access, refresh}
```

`code` is echoed in the response **only** when `OTP_ECHO_IN_RESPONSE` is on and `ENV` is not
production — the check is against `ENV`, not against the flag alone, because a setting that can be
switched on in production by editing an environment variable is an authentication system with a
published key.

Refresh tokens rotate. A reused refresh token invalidates the whole family: reuse means the token
leaked, and the only safe response is to assume the attacker has it too.

### Scans

```
POST /v1/scans                      -> {scan_id, status, uploads:[{asset_id, url, headers}]}
POST /v1/scans/{id}/submit          -> 202 {status: "queued"}
GET  /v1/scans/{id}                 -> {scan, assets}
GET  /v1/scans/{id}/findings        -> {rulepack_version, summary, findings, not_applicable_rule_ids}
POST /v1/scans/{id}/confirm-fields  -> {findings}        # recomputes
POST /v1/scans/{id}/applicability   -> {qco_applicable, scheme, ...}
```

**The API never proxies image bytes.** `POST /v1/scans` signs upload URLs; the client uploads
straight to object storage. `submit` enqueues and returns inside 300 ms (FR-20) — it flips a status
and puts a message on a queue, and a handler that opened an image could not keep to that.

`marker_type` and `marker_mm` are **required** (FR-02). The 422 comes from the schema, before any
handler runs: a scan that could not be measured cannot be created at all.

`confirm-fields` recomputes against **the pack the scan was originally evaluated under and the
original `as_of`** — not the active pack and not today. Nothing is mutated: the superseded
extraction keeps its row, the previous findings keep theirs, and the result is a new evaluation
revision.

### Products and listings

```
POST /v1/products/listings/check    {csv, profile?}   -> {rulepack_version, scale, summary, rows}
```

Mode B bulk check (FR-10). Up to 500 rows. The response carries `"scale": "none"` because **a
listing has no physical scale**: every metric and geometry rule in every row is `NOT_ASSESSABLE`,
and the field exists so a client cannot render these verdicts as though they came from a measured
photograph. A `url` column is recorded as provenance and is **never fetched** — an endpoint that
requested caller-supplied URLs would be a server-side request forgery with a CSV interface.

### Sahayak and BIS

```
POST /v1/sahayak/ask         {question, scan_id?, lang}  -> {answer, citations, confidence, as_of, refused, refusal_reason, sources}
POST /v1/bis/applicability   {profile}                   -> {qco_applicable, scheme, candidate_is_numbers, next_steps, sources, ...}
```

`/bis/applicability` is a **deterministic table lookup** against the published QCO/CRS lists in
`bis/` — no model is called and no retrieval happens. `/sahayak/ask` is retrieval plus a
citation-checked generation.

`refused: true` is a normal, successful (200) response with a named `refusal_reason`:

| Reason | Meaning |
|---|---|
| `priced_standard_content` | Asked for the technical content of an Indian Standard. Refused and pointed at the BIS purchase route — **this is a feature** (`CLAUDE.md` §3.5) |
| `no_supporting_source` | Nothing in the official corpus covers it. The official pages are returned instead of a guess |
| `fabricated_citation` | The model cited a chunk that does not exist. The answer is withheld |
| `unsupported_claim` | The answer stated a figure no cited source contains |
| `assistant_unavailable` | No model, or the call failed. The retrieved passages are still returned |

`confidence` is a **retrieval** signal — the mean reranker score across the cited chunks — and is
`null` when no reranker ran. It says how well the sources matched the question and nothing about
whether the answer is true.

### Dashboards

```
GET /v1/dashboard/violations?group_by=rule|category|district|brand|month&since=&until=&limit=
```

`group_by` is an enum; anything outside it is a 422 before a handler runs. Counts are the verdicts
that **currently stand** — a scan corrected through `confirm-fields` is counted once, at its latest
revision. A `key` of `null` means the dimension was not recorded, never that the group is empty, so
buckets always sum to the headline total. The window filters on `captured_at`, the inspection date,
not on when the row arrived.

### Admin

```
GET  /v1/admin/audit          -> {entries}
GET  /v1/admin/audit/verify   -> {ok, entries_checked, first_break, breaks}
POST /v1/admin/rulepacks      {yaml}   # FR-26 — not implemented yet
```

Verification reports the **first broken link**, not a boolean: "the audit log is corrupt" is not
something an investigator can act on, whereas "entry 4,117 of 9,220 no longer matches its contents"
bounds the problem and says where to look. There is no repair endpoint and there will not be one —
a chain that can be rebuilt through the API proves nothing.

### Meta

```
GET /health -> {status, db, redis, rulepack}
```

Returns 200 with `status: "degraded"` when a dependency is down, so a load balancer can tell
"reachable but impaired" from "gone". Never rate limited.

---

## 4. Roles

Permissions are named for the action, never the endpoint, so an endpoint that moves or splits does
not change who may call it.

| | viewer | analyst | inspector | admin |
|---|:--:|:--:|:--:|:--:|
| Read scans, findings, reports, products, dashboards | ● | ● | ● | ● |
| Bulk listing check | ● | ● | ● | ● |
| Ask Sahayak, generate reports | | ● | ● | ● |
| Create/submit scans, confirm fields, write products | | | ● | ● |
| Publish rule packs, verify the audit chain, manage users | | | | ● |

**No role can edit a verdict, including admin.** Findings are append-only and produced by the
evaluator; a correction goes through `confirm-fields`, which changes an *input* and recomputes.

---

## 5. Rate limits

Two axes, both enforced (B23). Per-IP alone lets one org flood from many addresses; per-org alone
lets one address sweep many orgs.

| Bucket | Default | Key |
|---|---|---|
| Per IP | 120 / minute | client address |
| Per org | 600 / minute | `org_id` from the verified token |

Every response carries `X-RateLimit-Limit` and `X-RateLimit-Remaining`; a 429 adds `Retry-After`.
`details.scope` says which bucket refused, because "you are sending too fast" and "your
organisation is" are different problems with different fixes.

`/health`, `/docs`, `/openapi.json` and `/redoc` are exempt: a load balancer polling health must
not be throttled into declaring the service dead.

An unauthenticated flood is charged to its **address**, never to the org id it claimed — otherwise
anyone could exhaust a tenant's quota by sending their id. If the limiter's backing store is
unreachable it **fails open** and logs: a rate limiter that takes the API down when Redis blinks
has converted a partial outage into a total one.

---

## 6. Security

Read [`01-architecture.md`](01-architecture.md) §10 for the model. The operational surface:

- **Object storage is presigned-only.** Buckets are private, there are no per-object ACLs, and
  every URL expires (default 900 s). EXIF is stripped from anything served — a scan photograph
  carries GPS, a device serial and a timestamp, and an annotated image served to a brand must not
  carry the inspector's location. Stripping is fail-closed: if it cannot be done, the bytes are not
  returned.
- **`sha256` is recorded on the bytes as received**, before EXIF stripping and before
  rectification. A hash taken after processing proves nothing about what the camera produced.
- **The audit log is hash-chained per org** and has no update path in the repository layer.
- **Every query is org-scoped in the repository base class**, which cannot be constructed over a
  table that has no `org_id`.

### Dependency audit

```bash
make audit          # installed versions + pip-audit
```

`pip-audit` is **not** a declared dependency — adding one is ask-first (`CLAUDE.md` §7) and a
security scanner does not belong in a deployed image. Install it in the dev venv when you run the
audit:

```bash
backend/.venv/bin/pip install pip-audit
```

Run it before each release and record the date and outcome in [`eval-results.md`](eval-results.md)
alongside the other release numbers.

---

## 7. Advisory disclaimer

Every report and every findings screen carries it, and it cannot be configured off
(`CLAUDE.md` §3.8):

> Advisory pre-audit output. Not a certification, not legal advice, and carries no legal force.
> The rule pack is an engineering transcription pending legal review.
