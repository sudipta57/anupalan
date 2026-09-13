# 06 — Wiring the app to the API

The mobile app (stages 0–12 complete) and the backend (B0–B16 complete) were built in parallel
against `02-trd.md` §5. This document is the diff between them: every place the two halves do not
yet meet, what each side expects, and which side should move.

> **Status, 2026-09-12 (second pass).** The first version of this document was written against a
> branch two commits behind `main` and undercounted what the backend already had: B17–B23 had
> landed, so Sahayak, BIS applicability, the dashboards and the bulk listing check all existed. The
> tables below are now correct against `main`, and **every gap this document raised has been closed**
> — see §8, which records what was built and what is deliberately left. The `mobile/` side has not
> been touched yet; that is the next piece of work.

It exists because the cutover was sequenced as **close the backend gaps first, then wire once**
(2026-09-12). Wiring the app against the contract as it stands today would mean writing adapter
code for shapes that are about to change, and — in two places recorded below — shipping a screen
that looks correct and is not.

**How to read it.** §1 is the coverage table: of the app's fifteen API calls, eight have a server.
§2 is environment setup that blocks everything regardless of contract. §3 is the gap register, in
three tiers: gaps that make the app *wrong*, gaps that leave a screen with nothing to call, and
differences the app absorbs on its own side with no backend change. §4 carries one ready-to-paste
handoff card per backend work package, in the CLAUDE.md §11 shape. §5 is what the app side does.
§6 is the order.

Flag numbers in parentheses refer to `05-frontend-plan.md` §9, which is where these were first
recorded as assumptions. Three of those flags are **answered** by this audit and marked so.

---

## 1. Where the two halves stand

Fifteen calls: fourteen in `mobile/src/api/endpoints.ts`, plus the refresh that
`live-transport.ts` issues on a 401.

| # | App call | Method and path | Server? | State |
|---|---|---|---|---|
| 1 | `requestOtp` | `POST /v1/auth/otp/request` | ✅ | response names differ — app adapts (§3.3) |
| 2 | `verifyOtp` | `POST /v1/auth/otp/verify` | ✅ | request body keys are **refused**, not ignored (§3.3) |
| 3 | refresh | `POST /v1/auth/refresh` | ✅ | body field is `refresh`; a mismatch signs the user out (§3.3) |
| 4 | `createScan` | `POST /v1/scans` | ✅ | per-asset `sha256` required (§3.1 G1 — app computes it); `district` **now accepted** |
| 5 | `submitScan` | `POST /v1/scans/{id}/submit` | ✅ | — |
| 6 | `getScan` | `GET /v1/scans/{id}` | ✅ | **fixed** — `org_id`, `user_id`, `profile`, `geo`, `district` added |
| 7 | `getFindings` | `GET /v1/scans/{id}/findings` | ✅ | **fixed** — `extractions`, `measurements`, `findings_sha256` added |
| 8 | `confirmFields` | `POST /v1/scans/{id}/confirm-fields` | ✅ | same response, same fix |
| 9 | `listScans` | `GET /v1/scans` | ✅ | **built** (§8 W4) |
| 10 | `listProducts` | `GET /v1/products` | ✅ | **built** (§8 W5) |
| 11 | `createReport` | `POST /v1/scans/{id}/report` | ✅ | **built** (§8 W6), synchronous |
| 12 | `getReport` | `GET /v1/reports/{id}` | ✅ | **built** (§8 W6) |
| 13 | `askSahayak` | `POST /v1/sahayak/ask` | ✅ | existed on `main` (B20) |
| 14 | `bisApplicability` | `POST /v1/bis/applicability` | ✅ | existed on `main` (B20) |
| 14b | `bisApplicabilityForScan` | `POST /v1/scans/{id}/applicability` | ✅ | **now called** — see §3.4 |
| 15 | `checkListings` | `POST /v1/listings/check` | ⚠️ | exists at **`POST /v1/products/listings/check`**, and takes `{csv}` rather than `{rows[]}` — the app adapts, see §8 |

**All fifteen now have a server.** Twenty `/v1` paths are registered in total; the extras are
`GET /v1/auth/me`, `GET /v1/dashboard/violations`, `GET /v1/admin/audit` and
`GET /v1/admin/audit/verify`. `POST /v1/scans/{id}/applicability` used to be on that list of
endpoints nobody called; it is now what the scan's BIS screen runs on (§3.4).

Three endpoints exist that the app does not call: `GET /v1/auth/me` (**answers flag 9** — it is
there, and it is a better session restore than trusting the local cache, so the app should adopt
it), `GET /v1/admin/audit` and `GET /v1/admin/audit/verify`.

---

## 2. Before anything can run

None of this is a contract question. All of it blocks the first request.

1. **`backend/.venv` is stale.** `python -c "import app.main"` fails with
   `ModuleNotFoundError: No module named 'pgvector'`. The venv holds the B0–B3 packages and none of
   B4–B12's. Fix: `cd backend && .venv/bin/pip install -e ".[dev]"`. Until this is done there is no
   `openapi.json`, so `npm run gen:api` has nothing to fetch and the app cannot be generated from
   the schema at all.
2. **`backend/.env` is missing `SECRET_KEY`.** It defaults to `""`, and `services/auth` raises
   rather than falling back, so **no token can be issued and sign-in cannot succeed**.
3. **`backend/.env` is missing every `S3_*` key.** `POST /v1/scans` presigns an upload per asset, so
   with no bucket configured **the capture path cannot start**. Present keys are `APP_NAME`,
   `ENV`, `DEBUG`, `LOG_LEVEL`, `API_V1_PREFIX`, `CORS_ORIGINS`, `DATABASE_URL`,
   `DATABASE_URL_DIRECT`, `DB_POOL_RECYCLE`, `DB_CONNECT_TIMEOUT`, `REDIS_URL`, `PX_PER_MM`.
4. **`OTP_ECHO_IN_RESPONSE` is unset.** There is no SMS gateway configured, so with the echo off
   there is no way to receive a code on a device. It must be on for local and staging, and it must
   stay off in production — `OtpRequestOut.code` is populated only when it is set.
5. **The phone cannot reach `localhost`.** Either `adb reverse tcp:8000 tcp:8000` over USB, or the
   development machine's LAN address in `EXPO_PUBLIC_API_URL`. Already documented in
   `mobile/.env.example`. CORS is not a factor: a React Native app sends no `Origin`.

Values for 2 and 3 are credentials and are not recorded in any file in this repository, including
`.env.example`.

---

## 3. The gap register

### 3.1 Gaps that make the app wrong

These are not missing features. In each case the app has code that runs, produces a plausible
screen, and is incorrect.

#### G1 — `POST /v1/scans` requires a SHA-256 per asset; the app computes none

*App:* `CreateScanBody.assetCount: number`, which is what TRD §5 specifies.
*Server:* `ScanCreateIn.assets: list[AssetIn]`, each carrying `content_type`, `size_bytes`,
`sha256` (required, `^[0-9a-f]{64}$`) and `kind`. The refinement is deliberate and documented in
`backend/app/schemas/scans.py`: a count cannot produce presigned URLs, because the content type is
part of the signature, and the size ceiling is enforced when the capability is *issued* rather than
after the bytes have arrived. The worker then verifies the stored object against the declared hash
and fails the scan on a mismatch, which is what keeps `scan_assets.sha256` NOT NULL on a path where
the API never sees the bytes.

*Why it matters:* there is no honest stub. A fabricated hash fails the scan; making the field
optional would turn a checkable claim into a record of whatever arrived.

*Resolution (decided 2026-09-12):* **the app computes it**, with `expo-crypto` — approved for this.
`size_bytes` and `content_type` come from `expo-file-system` with no new dependency. The backend
does not change. This is the app's work, listed in §5.

#### G2 — the findings response omits `extractions`, which silently opens the report gate

*App:* `FindingsResult` carries `extractions: Extraction[]` and `measurements: Measurement[]`.
`features/processing/confidence.ts` reads `result.extractions.some(needsConfirmation)` to decide
whether verdicts are provisional; `features/reports/eligibility.ts` uses that same predicate to
**refuse to generate a report** while any extracted field is below the 0.75 confidence threshold,
and `fieldsNeedingConfirmation` is what populates FR-06's confirmation sheet.

*Server:* `FindingsOut` has `summary`, `findings`, `not_applicable_rule_ids`, `rulepack_version`,
`revision`, `evaluated_at`, `as_of` and `reduced_extraction`. The extractions and measurements are
computed — `_domain_extractions` and `_domain_measurements` in `app/routers/scans.py` — used for the
recompute, and not returned.

*Why it matters, and why this one is first:* with no extractions the client has two options and both
are wrong. Defaulting to `[]` makes `.some()` return false, so **the report gate opens for every
scan** and the app will issue a PDF over a 0.41-confidence MRP without saying so — the exact failure
Stage 9 was organised against, reintroduced silently. Leaving the field absent crashes the screen.
FR-06's sheet is empty either way, so the one mechanism that lets a human correct a bad read becomes
unreachable.

*Also absent from the same response:*
- `findings_sha256` (flag 21) — Mode A's evidence panel shows it *before* anyone asks for a PDF,
  because that is the moment an inspector decides whether to issue one. It must hash the same blob
  the report embeds, or the two surfaces disagree for no reason a reader could diagnose.
- `remediation` per finding — Mode B's "what to change on the artwork". `services/reporting/explain.py`
  exists (B11); this is where its output reaches the screen.
- per-finding `rulepack_version`. It is on the envelope, which satisfies CLAUDE.md §3.6. The app's
  `Finding` type carries it per row; the app can fill that from the envelope, so **no change asked**.

*Resolution:* backend adds `extractions`, `measurements`, `findings_sha256` and `remediation`. Card
W1.

#### G3 — `district` does not exist anywhere in the backend

*App:* `Scan.district: string | null` and `ScanListItem.district`, sent on create (flag 16), shown
on every history row, and one of the four history filters — Mode A only, because Mode B collects no
location at all (`01-architecture.md` §10).
*Server:* absent from `ScanCreateIn`, absent from `ScanOut`, and **absent from the `scans` table**,
which has `geo_lat`, `geo_lon` and `geo_accuracy_m` only.

*Why it matters:* it cannot be sent, stored or returned, so the filter has nothing to filter and the
row has nothing to show. FR-30's "violations by district" also has no column to group by — the
dashboard requirement and the history filter are blocked by the same missing field.

*Resolution:* a `district` column, a create-body field, and the response field. This is a schema
change, which CLAUDE.md §7 says needs agreement — and it is far cheaper now than after the table has
rows. Card W3.

#### G4 — `GET /v1/scans/{id}` omits five fields the screens read

| Field | App uses it for | Where it is now |
|---|---|---|
| `profile` | the scan screen and the report filename | already a JSON column on `scans`, just not in `ScanOut` |
| `org_id` | cross-org assertions in the app's own tests | on the row |
| `user_id` | attribution on an inspection | on the row |
| `report_issued_at` | **Mode A's editing lock** after a report is issued (flag 22) | needs the reports work, W6 |
| `issues` | the §11 degradation banners | derivable — see below |

`issues` the app can derive and will: `no_marker` from the scan status, `reduced_extraction` from the
findings envelope's existing flag, `low_confidence_fields` from G2's extractions once they arrive.
**No backend change asked for `issues`.** `pipeline_stage` (flag 19) stays absent and the progress
screen already renders that honestly as "the server has not said" — worth adding if the worker can
publish it, but not blocking.

*Resolution:* add `profile`, `org_id`, `user_id` now; `report_issued_at` with W6. Card W2.

#### G5 — the status and marker vocabularies differ, and one difference strands a queued scan

*Status.* Server: `created | queued | processing | complete | failed | no_marker`. App:
`captured | queued | uploading | processing | complete | failed`, where `captured` and `uploading`
are local-only states of the offline queue and never come from the server.

The mismatch that matters is **`no_marker`**. `features/queue/runner.ts` moves a local row out of
`processing` only on `complete` or `failed`, so a no-marker scan would sit in the queue forever and
the pending badge would never clear. Per `01-architecture.md` §11 a no-marker run is *degraded but
final* — it has real findings, with every metric rule NOT_ASSESSABLE — so the app will map it to
`complete` plus the `no_marker` issue, which is what the degradation UI was built for. `created` maps
to `queued`. **No backend change asked**, but the mapping is recorded here so it is not later read as
the app losing a status.

*Marker type.* Server: `aruco_4x4_50 | id1_card | user_declared`. App:
`aruco_40mm | id1_card | user_dimension`. The server's names are better — `aruco_4x4_50` names the
ArUco dictionary, which is the thing that must match `make-marker-sheet.py` and `make_chart.py`
(flag 14), and the 40 mm belongs in `marker_mm` where it already is. **The app renames to match.**
No backend change asked.

### 3.2 Gaps that leave a screen with nothing to call

#### G6 — there is no `GET /v1/scans`, and TRD §5 never defined one (flag 5)

FR-09 is a numbered requirement with an acceptance criterion — *filter 200 seeded scans by
`verdict=FAIL` within 500 ms* — and the contract has no endpoint for it. Both history tabs, the four
filters and the search box have nothing to talk to.

The app needs a page of `ScanListItem`: `id`, `orgId`, `productId` (flag 24), `productName`,
`status`, `capturedAt`, `district`, `thumbnailUri`, and a four-count verdict `summary`. The summary
is the interesting part — it is an aggregate over the current evaluation's findings, not a
projection, and the 500 ms criterion is about that query rather than about the rendering. Filters:
`verdict` (exactly one, never a set — see the note below), `productId`, `q`, `district`, `from`,
`to`, `cursor`, `limit`.

**One constraint is not negotiable.** `verdict=FAIL` must mean *this scan has at least one finding
whose verdict is FAIL*, and nothing else. It must never be widened to "has a problem" by including
BORDERLINE. A filter that did would hand CLAUDE.md §3.4's failure mode to an inspector through the
search box: they ask for failures, they are shown a compliant pack whose measurement merely sat
inside the uncertainty band, and the list looks longer and more useful while being wrong. The app's
side of this is `features/history/filters.ts`, where the predicate reads exactly one count and there
is deliberately no helper that accepts a set. Card W4.

#### G7 — `GET /v1/products` is a docstring (TRD §5 defines it)

Needed by the product picker on the context form (FR-03) and by the history product filter (FR-09).
The app reads `Page<Product>` with `q` and `category`. Card W5.

Separately, and **not** blocking: `ProductProfile` has no brand and no SKU, while the Mode B history
row asks to filter by both (flag 25). Those become real in FR-10's listing check; the product model
should gain them there rather than having them invented for a filter.

#### G8 — reports: the service exists, the endpoints do not

`services/reporting/` is complete (B11 — one data structure to PDF, DOCX and JSON, with the DOCX
table a real `w:tbl`). `routers/reports.py` is a docstring. The app needs both halves of an
asynchronous generation (flag 23): `POST /v1/scans/{id}/report {formats}` returning a report with
`status: "pending"`, and `GET /v1/reports/{id}` returning the same shape until it leaves that state,
because rendering an annotated PDF is S10 of the pipeline and not something a request can wait on.

The report carries `files[]` with a presigned read URL per format, `image_sha256`, `findings_sha256`,
`rulepack_version`, `requested_at`, `generated_at | null` and `error | null`. `formats` is kept
alongside `files` on purpose: a report that comes back ready with one of two requested documents must
be visible as a short delivery rather than looking like the user only asked for one. Issuing a report
is also what sets G4's `report_issued_at`. Card W6.

### 3.3 Differences the app absorbs — no backend change asked

Recorded so nobody fixes them twice.

**`needs_confirmation` is a seventh scan status, and the app has a word for it (2026-09-13).** The
backend stops before evaluation when a field is below FR-06's threshold, so `GET /v1/scans/{id}`
can return `needs_confirmation` and `GET /v1/scans/{id}/findings` then answers **200 with an empty
`findings` array** and a populated `extractions` array. An empty findings list is a real answer
here, not an error: the scan was read and deliberately not judged. The 409 on that endpoint still
means what it always meant — no evaluation row at all, i.e. not yet processed.

The app maps it to a domain status of the same name rather than folding it into `processing` or
`complete`. Folding into `processing` would leave the offline queue polling for a change only the
confirmation sheet can make; folding into `complete` would claim verdicts that do not exist. It
counts as `needsAttention` (the user's turn) but not as `isPending` (the queue's work), and the
scan and findings screens both route to the confirmation sheet instead of rendering a verdict list.


**Casing (flag 10, now decided).** The backend is snake_case throughout; the app is camelCase
throughout. The app will convert at the transport seam with **explicit per-endpoint adapters**, not a
generic deep key transform. The reason is specific: a blind converter would rewrite
`profile.is_imported` and `profile.net_qty_in_g_or_ml`, whose names are the **rule pack's** contract
and not the API's — renaming one breaks a pack — and it would rewrite the presigned `headers` map,
where `x-amz-*` must survive byte for byte. If the backend would rather emit camelCase aliases on its
response models, say so and the adapters get thinner; they do not go away, because §3.1's structural
work has to live somewhere.

**`extra="forbid"` makes every request-body name mismatch fatal, not cosmetic.** Worth stating
plainly, because it is the reason casing cannot be left to drift:

- `OtpVerifyIn` wants `{request_id, code}`; the app sends `{requestId, code}` → **422**, so sign-in
  fails at the first call rather than degrading.
- `RefreshIn` wants `{refresh}`; the app sends `{refreshToken}` → **422**. `live-transport.ts` treats
  any non-ok refresh as the server rejecting the token and calls `onExpired()`, so the user is
  **signed out every time an access token expires**. A 422 and a 401 mean opposite things here and
  only one of them should end a session.
- `OtpRequestOut` returns `{request_id, expires_at, code?}`; the app expects
  `{requestId, expiresInSeconds}`. That is a semantic difference as well as a naming one — an
  absolute instant against a duration — and the app will convert rather than ask for a second field.

**The fifth summary bucket.** The server's `FindingsSummary` has five counts —
`pass`, `fail`, `borderline`, `na`, `not_applicable` — plus `not_applicable_rule_ids`. The app's has
four, because there are four verdicts. This **answers flag 6**: the backend omits inapplicable rules
from the findings list and reports them separately, which is exactly what the fixtures assumed and is
the right call, since a fifth verdict would contradict a non-negotiable. The app maps `na` to
`notAssessable` and currently **discards** `not_applicable_rule_ids`. That is a real loss — "does not
apply to you" is a useful thing for a brand to read on the findings screen — and it is the app's
gap to close, not the backend's.

**Refresh exists (answers flag 8).** `POST /v1/auth/refresh` is implemented with rotation, which is
what Stage 2 assumed. Only the body field name differs, as above.

---

### 3.4 BIS applicability runs off the scan, and the chat is grounded in it

Two changes, 2026-09-13, both on the path behind **Check BIS requirement**.

**The lookup no longer needs a `productId`.** `app/scan/[id]/bis.tsx` used to return its not-found
state whenever `scan.productId` was null, without calling the backend at all. That is every scan
taken in the field — a photographed label is not matched to a catalogue product — so the screen
reported "no applicability record" for a record nobody had asked for. It now calls
`POST /v1/scans/{id}/applicability`, which reads the profile the scan was **frozen** with and needs
no product row. That endpoint also stamps the answer with the scan's `captured_at` rather than
today, so a scan re-opened next year reproduces the verdict issued under the lists in force when the
package was photographed — the same reason findings carry `rulepack_version` (CLAUDE.md §3.6).

The app's `useBisApplicability(productId, …)` hook is unchanged and still serves the catalogue path;
`useBisApplicabilityForScan(scanId, profile)` is the new one, cached under its own key because the
capture date is part of the answer.

**`scan_id` on `POST /v1/sahayak/ask` now grounds the generation.** It used to do two things — prove
the scan belongs to the caller's org, and record the link on `bis_queries`. It now also loads that
scan's frozen profile into the prompt, so a question about "this product" reaches the model with the
product attached instead of the model inferring it from whatever the question spelled out. This is
additive: the request body is unchanged, and an ask without `scan_id` behaves exactly as before.

Three boundaries hold, and they are the reason this is safe:

- **Retrieval is untouched.** The question still reaches `retrieve()` exactly as typed. The profile
  steers how an answer is worded, never which sources it may cite, so retrieval stays reproducible
  from the question alone.
- **The product is context, never a source.** `services/bis/answer` still requires every claim to
  name a retrieved passage, so a user's own typed-in category cannot become the authority for a
  certification requirement. `test_the_product_block_buys_no_authority_over_the_rules` pins it.
- **The lookup still decides applicability.** The chat sits *under* the verdict on the screen, and
  nothing in it produces a `qco_applicable`.

One subtlety that would otherwise have been a silent, undiagnosable refusal: the answer validator
rejects any number in the answer that appears in no cited passage and was not in the question. A
declared net quantity repeated back — "for a 36 g pack" — is exactly that, so the product block is
counted as provenance for **numbers only**
(`test_a_quantity_the_user_declared_is_not_a_fabricated_figure`).

---

## 4. Handoff cards

In the CLAUDE.md §11 shape. W1–W6 are what the first cutover needs; Sahayak, BIS applicability and
the listing check are B18–B21 and are out of its scope.

### W1 — Findings response: extractions, measurements, hash, remediation

```
CONTEXT:     docs/06-wiring-contract.md §3.1 G2; docs/02-trd.md FR-05, FR-06;
             docs/01-architecture.md §10; mobile/src/features/processing/confidence.ts and
             mobile/src/features/reports/eligibility.ts are the two readers.
TASK:        backend/app/schemas/findings.py, backend/app/routers/scans.py
CONSTRAINTS:
  - FindingsOut gains extractions[] and measurements[]. Both are already built in the router
    (_domain_extractions, _domain_measurements) and thrown away; this is a response change,
    not new computation.
  - an extraction carries at least: field_code, value_raw, value_norm, source
    (regex|llm|human), confidence, bbox. The client decides what needs human confirmation by
    reading confidence < 0.75 AND source != human, so BOTH fields must be accurate on every
    row — a default confidence of 1.0 would silently disable FR-06.
  - superseded rows stay excluded, as they are today.
  - FindingsOut gains findings_sha256: the hash of the SAME blob the report embeds. If the
    report hashes a different serialisation, the evidence panel and the PDF will disagree and
    neither will be diagnosable.
  - FindingOut gains remediation: str | None, Mode B's "what to change". Null is fine.
  - no new verdict value, and the summary keeps its five buckets.
TESTS:       tests/test_findings.py — a scan with one 0.41-confidence extraction returns that
             extraction with source != 'human'; findings_sha256 is byte-identical to the hash
             the reporting service embeds for the same evaluation; a confirm-fields recompute
             returns the corrected row with source='human'.
DONE WHEN:   pytest tests/test_findings.py tests/test_confirm_fields.py
```

### W2 — Scan response: the fields the screens read

```
CONTEXT:     docs/06-wiring-contract.md §3.1 G4 and G5; docs/02-trd.md FR-05.
TASK:        backend/app/schemas/scans.py (ScanOut), backend/app/routers/scans.py (get_scan)
CONSTRAINTS:
  - ScanOut gains profile (the stored JSON, verbatim — the rule pack addresses these names,
    so do not rename the keys), org_id and user_id.
  - report_issued_at comes with W6; leave it out until then rather than shipping a null that
    means "no reports endpoint exists".
  - do NOT add an `issues` array. The client derives it from status + reduced_extraction +
    extraction confidence, and a second source of truth for the same thing would drift.
  - status and marker_type keep the server's vocabularies. The client maps no_marker to
    complete-plus-an-issue and renames the marker values. Both mappings are recorded in
    docs/06-wiring-contract.md §3.1 G5; if either vocabulary changes, that section is the
    place it has to change with it.
TESTS:       tests/test_scan_intake.py — GET returns the profile exactly as stored, including
             is_imported and net_qty_in_g_or_ml; another org's scan is still 404.
DONE WHEN:   pytest tests/test_scan_intake.py tests/test_org_isolation.py
```

### W3 — `district` on a scan

```
CONTEXT:     docs/06-wiring-contract.md §3.1 G3; docs/01-architecture.md §10 (Mode B collects
             no location); docs/02-trd.md FR-09, FR-30.
TASK:        backend/app/models/scan.py, an alembic revision, schemas/scans.py, routers/scans.py
CONSTRAINTS:
  - a nullable district column on scans, indexed — it is a filter key and a dashboard group-by.
  - ScanCreateIn gains district: str | None. It comes from the client, which is the only party
    that knows it; the server must not reverse-geocode geo_lat/geo_lon into one, because Mode B
    sends no geo at all and an inferred district would then be silently absent for half the
    users.
  - null is the correct and expected value for every Mode B scan. Do not default it.
  - this is a schema change: per CLAUDE.md §7 it needs agreement before the migration is
    written, and `alembic revision --autogenerate` must come back empty afterwards.
TESTS:       tests/test_migration.py — autogenerate diff is empty after upgrade head.
             tests/test_scan_intake.py — a scan created without a district reads back null.
DONE WHEN:   pytest tests/test_migration.py && alembic upgrade head on the direct endpoint
```

### W4 — `GET /v1/scans`: the history list

```
CONTEXT:     docs/06-wiring-contract.md §3.2 G6; docs/02-trd.md FR-09 (accept: filtering 200
             seeded scans by verdict=FAIL returns only scans with >=1 FAIL, within 500 ms);
             mobile/src/features/history/filters.ts is the client predicate.
TASK:        backend/app/routers/scans.py (list endpoint), schemas/scans.py, repositories/scans.py
SIGNATURE:   GET /v1/scans?verdict=&product_id=&district=&from=&to=&q=&cursor=&limit=
             -> {items: [ScanListOut], next_cursor: str | None}
             ScanListOut: scan_id, product_id | None, product_name, status, captured_at,
                          district | None, thumbnail_url | None,
                          summary {pass, fail, borderline, na}
CONSTRAINTS:
  - verdict takes EXACTLY ONE of PASS|FAIL|BORDERLINE|NOT_ASSESSABLE and means "this scan has
    at least one finding with that verdict". Never widen it to a set or to "has a problem":
    folding BORDERLINE into FAIL here is CLAUDE.md §3.4's failure mode delivered through a
    filter, and it would look like a better feature. One verdict per question.
  - the summary counts the CURRENT evaluation's findings only — the highest revision — or a
    confirm-fields recompute would double every count.
  - cursor pagination, consistent with the rest of §5. Order by captured_at desc.
  - org-scoped through repositories/ like everything else; another org's scans are absent, not
    forbidden.
  - from/to are inclusive calendar dates. The client sends local dates, so `to` must cover the
    whole of that day.
  - q is free text over the product name (flag 25).
  - 500 ms on 200 scans is a query-shape requirement: index what the summary aggregates over
    rather than counting rows in Python.
TESTS:       tests/test_scan_list.py (new) — 200 seeded scans, at least one of which has a
             BORDERLINE and NO failures: verdict=FAIL must not return it, and verdict=BORDERLINE
             must. That one fixture is the whole point of the suite; without it a merged filter
             passes every other test. Plus: cursor paging returns each scan once; another org's
             scans never appear.
DONE WHEN:   pytest tests/test_scan_list.py tests/test_org_isolation.py
```

### W5 — `GET /v1/products`

```
CONTEXT:     docs/06-wiring-contract.md §3.2 G7; docs/02-trd.md §5, FR-03.
TASK:        backend/app/routers/products.py, schemas/products.py (new), register in main.py
SIGNATURE:   GET /v1/products?q=&category=&cursor= -> {items: [...], next_cursor}
             POST /v1/products {name, category_code, ...} -> {product}
CONSTRAINTS:
  - the product profile is what decides which rules apply AND which QCO applies
    (01-architecture.md §2), so the profile fields here must stay the same names as
    ProfileIn — the rule pack addresses them.
  - org-scoped. A catalogue is per-org.
  - brand and sku are deliberately NOT added here; see §3.2 G7 and flag 25.
TESTS:       tests/test_products.py (new) — q matches on name; another org's products absent.
DONE WHEN:   pytest tests/test_products.py
```

### W6 — Reports: generate and poll

```
CONTEXT:     docs/06-wiring-contract.md §3.2 G8; docs/02-trd.md FR-08, FR-27;
             docs/01-architecture.md §10; flags 22 and 23.
TASK:        backend/app/routers/reports.py, schemas/reports.py (new), a Celery task,
             register in main.py
SIGNATURE:   POST /v1/scans/{id}/report {formats:["pdf","docx"]} -> 202 ReportOut(status="pending")
             GET  /v1/reports/{report_id}                        -> ReportOut
             ReportOut: report_id, scan_id, status(pending|ready|failed), rulepack_version,
                        formats[], files[{format, url, size_bytes}], image_sha256,
                        findings_sha256, requested_at, generated_at|None, error|None
CONSTRAINTS:
  - generation is asynchronous. Rendering an annotated PDF is pipeline stage S10; the POST
    enqueues and returns, and the client polls GET until status leaves pending.
  - formats is returned alongside files, not instead of it. A ready report delivering one of
    two requested documents must be visible as a short delivery rather than reading as though
    the user only asked for one.
  - every report embeds BOTH hashes and the rulepack_version, and carries the advisory
    disclaimer (CLAUDE.md §3.8). findings_sha256 must equal W1's.
  - issuing a report sets scans.report_issued_at, and ScanOut then returns it — that single
    field is what locks editing in Mode A after issue, so findings cannot be corrected out from
    under a PDF already in circulation.
  - files[].url is a time-limited presigned GET. Buckets stay private.
  - the report is generated from the STORED findings of the evaluation being reported, never
    re-evaluated at report time (CLAUDE.md §3.6).
TESTS:       tests/test_reports.py (new) — a pending report polls to ready; the PDF and DOCX
             have identical row counts and verdict strings; both hashes match the findings
             response; report_issued_at is set on the scan; a scan from another org is 404.
DONE WHEN:   pytest tests/test_reports.py
```

---

## 5. What the app side does

No backend involvement, and none of it starts until the cards above land — the sequencing decision
was to wire once.

1. **Per-asset hashing for `POST /v1/scans` (G1).** `expo-crypto` — **approved 2026-09-12**, the
   first dependency added since Stage 11's `expo-web-browser`. Read the file's bytes through
   `expo-file-system`, `Crypto.digest('SHA-256', bytes)`, hex-encode. `size_bytes` and
   `content_type` come from the same `File` handle. `CreateScanBody` changes from `assetCount` to an
   `assets[]` list; `features/queue/runner.ts` changes in one place, because it already pairs upload
   targets to assets by position. It is a native module, so the EAS dev client needs rebuilding —
   which is why it installs at cutover, with everything else that needs a rebuild, rather than now.
2. **An explicit adapter per endpoint**, in `src/api/`, converting names and the two vocabularies of
   §3.1 G5, and deriving `Scan.issues`. Pure functions, unit-tested, with `profile` and the presigned
   `headers` map passing through untouched.
3. **Adopt `GET /v1/auth/me`** for session restore instead of trusting the local cache (flag 9), so a
   role or org change takes effect on next launch.
4. **Stop discarding `not_applicable_rule_ids`** (§3.3) — the findings screen should be able to say
   "this rule does not apply to you", which is distinct from "we could not measure it".
5. **Fix the refresh body name** so a 422 cannot end a session (§3.3).
6. Then delete `src/api/mock/`, `src/api/dev.ts`, the `metro.config.js` resolver branch and the four
   dev panels in Settings, per Stage 13's *Done when*.

Unchanged by all of this: every screen, every hook, every feature module. The seam held — the
wiring is `src/api/` plus one hashing helper.

---

## 6. Order of work

**W1 first, and not for effort reasons.** It is the only gap on this list that makes the shipped app
assert something false, and the falsehood is a report issued over unverified readings. Everything
else is a screen that is visibly empty, which is a known state rather than a wrong one.

| Order | Card | Unblocks |
|---|---|---|
| 1 | W1 findings response | FR-06's confirmation sheet; Stage 9's report gate; the evidence panel |
| 2 | W2 scan response | the scan and findings screens end to end |
| 3 | W3 district (schema — needs agreement first) | W4's filter, and FR-30 later |
| 4 | W4 `GET /v1/scans` | both history tabs, all four filters, the search box |
| 5 | W5 `GET /v1/products` | the context form's picker; the product filter |
| 6 | W6 reports | Stage 9's screen; Mode A's editing lock |

After W1–W6 the capture path runs end to end against the real backend and nine of the app's fifteen
calls are live. Sahayak, BIS applicability and the bulk listing check stay on fixtures until
B18–B21, which is why the mock layer is deleted only at the end and not with the first card.

Two things gate the first request regardless of any card: §2.1 and §2.2.

---

## 7. Decisions taken, 2026-09-12

| Decision | Alternative rejected |
|---|---|
| The app computes each asset's SHA-256, with `expo-crypto` approved for it | Making `sha256` optional at create and having the worker compute it from the stored object — rejected: it turns a claim the server can check into a record of whatever arrived, and a corrupted upload stops being detectable |
| Close the backend gaps first, then wire once | Wiring the eight live endpoints now behind adapters and revisiting — rejected: the adapters would be written against shapes that are about to change, and G2 cannot be adapted around safely at all |
| The app converts casing, with explicit per-endpoint adapters | A generic deep key transform — rejected: it would rewrite the rule pack's own field names inside `profile`, and the `x-amz-*` presigned headers |
| `no_marker` maps to `complete` plus a `no_marker` issue | Adding `no_marker` to the app's status union — rejected: §11 calls it degraded *but final*, and the queue's terminal check would need a third terminal state in every branch that has one |


---

## 8. What was built, 2026-09-12

All six work packages landed on `main`'s code. **682 tests pass** (64 new), `ruff` and
`mypy app/services` are clean. No migration was written and no dependency was added.

### W1 — the findings response · `schemas/findings.py`, `routers/scans.py`

`GET /v1/scans/{id}/findings` and the confirm-fields response now carry:

- **`extractions[]`** — `extraction_id`, `field_code`, `value_raw`, `value_norm`, `source`,
  `confidence`, `bbox`, `source_span`. Superseded rows excluded.
- **`measurements[]`** — `measurement_id`, `field_code`, `glyph`, `height_mm`, `width_mm`,
  `uncertainty_mm`, `clear_space_mm`, `is_numeral`, `is_mark`, `method`.
- **`findings_sha256`** — the **stored** digest from `scan_evaluations`, not recomputed. It already
  existed as a column; only the response was missing it. That is what makes the evidence panel and
  a report quote the same hash by construction rather than by two code paths agreeing.
- **`finding_id`** on each finding — nullable, because the bulk listing check shares this shape and
  judges text that was never a scan, so it has no evidence row to point at.

The query that produces the extractions is now written once and feeds both the evaluator's value
type and the response, so the set a verdict was computed from and the set the client is shown cannot
drift apart under a concurrent correction.

**The test that matters** is `test_a_low_confidence_extraction_keeps_its_real_confidence`. An
implementation that omitted the field or defaulted it to 1.0 passes everything else in the suite and
turns the client's report gate into a no-op.

### W2 — the scan response · `schemas/scans.py`, `routers/scans.py`

`ScanOut` gained `org_id`, `user_id`, `profile`, `geo` and `district`; `ScanCreateIn` gained
`district`, which the column has been waiting for since B17 — it could be written by the pipeline
and never by a client, which is to say never.

`profile` is returned through a **non-strict** `ProfileOut`: a request with an unknown field is a
client bug worth a 422, but a *stored* profile carrying a key this version does not know is our own
older data, and refusing to render it would turn a future schema addition into an outage on every
scan recorded before it. `geo` is one nested object rather than three nullable columns, and a
latitude without a longitude reports as no position rather than half of one.

**Not added: `issues`.** The client derives it from the status, `reduced_extraction` and the
extraction confidences. A second source of truth for the same three facts would drift.

### W3 — `district`

No migration needed: the column and its index arrived with B17's dashboard work. Only the API
surface was missing, and that is W2.

### W4 — `GET /v1/scans` · `routers/scans.py`, `routers/pagination.py` (new)

Filters: `verdict`, `product_id`, `district`, `from`, `to`, `tz_offset_minutes`, `q`, `cursor`,
`limit`. Returns `{items, next_cursor}` with four verdict counts and a presigned thumbnail per row.

Three things worth knowing:

- **The verdict filter reads one verdict.** It is an `IN` against a grouped sub-select over the
  *current* evaluation only. A mutation test confirmed the guard works: widening `FAIL` to also
  match `BORDERLINE` fails three tests, including one whose entire purpose is a seeded scan that is
  borderline **without** failing. Without that row in the fixture the two implementations are
  indistinguishable, and the wrong one returns a longer, more useful-looking list.
- **Filter, page, then aggregate.** Counting findings per row before paging is correct and does not
  scale; this counts only the page's scans. FR-09's 500 ms is a query-shape requirement.
- **Keyset cursors, not offsets.** `LIMIT/OFFSET` silently repeats and skips rows when something is
  inserted while a user is paging, which in an evidence archive is not a cosmetic problem. Cursors
  are opaque base64 and a malformed one is a 422, never a silent fall back to page one.
- **`tz_offset_minutes`** exists because `from` and `to` are the *user's* calendar days. An inspector
  in India filtering for "today" means the day that began at 00:00 IST; comparing that against UTC
  midnight files every scan before 05:30 under yesterday, and the user concludes one was lost.

### W5 — `GET /v1/products` · `routers/products.py`

Alphabetical, searchable over name **and brand**, filterable by category, cursor-paged. Returns what
a catalogue actually holds — deliberately no `qty_basis` and no `channel`, because neither is a
property of a product: the channel is where *this* check is happening, and the basis follows from
the unit. `POST /v1/products` is still not implemented; no client creates catalogue entries yet.

**Flag 25 is partly answered:** `Product.brand` exists (B17 added it). `sku` still does not.

### W6 — reports · `routers/reports.py` (new), registered in `main.py`

`POST /v1/scans/{id}/report` renders and stores; `GET /v1/reports/{id}` re-presigns. Both hashes
travel with the report, the raw image's hash rather than the rectified one, and the response names
the **evaluation** it states — so a later correction makes a new revision and does not change what
an already-issued document meant. That property has its own test.

**Generation is synchronous, and that is an interim.** The client polls until `status` leaves
`pending`, which is the right shape for work that belongs to the worker as pipeline stage S10 — but
a `pending` state needs a column to live in, and `reports` has neither `status` nor `error`. Adding
them is a migration, which CLAUDE.md §7 says needs agreement first. A polling client is correct
either way: it finds the report `ready` on its first read.

**This is the one open decision left on the backend.** Moving to async needs `reports.status`,
`reports.error`, and a Celery task — roughly an hour, plus a migration to approve.

### Still open

| Item | Why it is open |
|---|---|
| Async report generation | Needs two columns on `reports` — a migration, so it needs sign-off |
| `POST /v1/products` | In TRD §5; no client needs it yet |
| `remediation` on a finding | Mode B's "what to change". Not a column and not in the rule pack; needs one or the other, so it needs a decision |
| `pipeline_stage` on a scan | Flag 19. The progress screen already renders its absence honestly |
| Listing check path and body | Lives at `/v1/products/listings/check` and takes `{csv}`. Left as the backend has it; the app adapts |


---

## 9. The app side, 2026-09-12

Both halves are now wired. **670 mobile tests** (25 new) and **691 backend tests** (9 new) pass; one
mobile failure predates this work and is flag 33. Lint, types and formatting are clean on both sides.

### `src/api/adapters/` — the wire→domain layer

One module per resource, each holding the server's shape and the mapping to the app's **beside each
other**, so the two cannot drift unnoticed. Every endpoint function now returns a domain type; the
wire types are not exported past this folder.

Explicit code rather than a recursive key transformer, and the reason is specific rather than
stylistic: a generic converter would rewrite `profile.is_imported` and `profile.net_qty_in_g_or_ml`,
whose names are the **rule pack's** contract rather than the API's, and the presigned `headers` map,
where `x-amz-*` must survive byte for byte or every upload fails its signature.

Three mappings are decisions, not renames, and each is written down where it happens:

- **`no_marker` → `complete` plus an issue.** Architecture §11 calls such a run degraded *but final*.
  Left as its own terminal state it would strand the offline queue, which leaves `processing` only on
  `complete` or `failed` — the row would sit there for ever and the pending badge would never clear.
- **`aruco_4x4_50` ⇄ `aruco_40mm`.** The server's name is better and stays on the wire: it names the
  ArUco dictionary the printed sheet and the backend's chart generator must agree on (flag 14), while
  the 40 mm lives in `markerMm`, where an ID-1 card is a different number.
- **An answer's outcome comes from `refusal_reason`, never from whether a citation arrived.** A
  not-found answer *does* carry a link — the official page to go and read — so counting citations
  would classify it as answered and publish prose no source supports.

### Client-side hashing — `src/features/capture/hash.ts`

`expo-crypto` added (approved 2026-09-12; first dependency since Stage 11). The queue reads each
photograph's bytes and digests them natively before `POST /v1/scans`, and the worker checks the
stored object against the declaration. Hashing on the device is what makes it a **checkable claim**:
a hash computed by the server after the upload would verify the upload against itself.

### The refresh bug this found

`live-transport.ts` was sending `{refreshToken}` where the server's `RefreshIn` wants `{refresh}`,
and every request schema sets `extra="forbid"` — so that body was a **422**. The transport read any
non-ok refresh as a rejected token and ended the session, which means users would have been signed
out every time an access token expired, for as long as they used the app. Two fixes: the correct
field name, and **only a 401 now ends a session**. `backend/tests/test_mobile_contract.py` pins the
spelling of every request body from the server's side.

### The mock now speaks the server's shapes

`src/api/mock/to-wire.ts` renders the fixtures outward at the last moment. Keeping the mock returning
finished domain objects would have bypassed the adapters entirely: mock mode would exercise a
different code path from live mode, and every test that runs against fixtures would leave the mapping
untested. The fixtures themselves stay in the app's vocabulary, which is what the tests read.

`__tests__/adapters.test.ts` round-trips domain → wire → domain, which catches a field renamed on one
side only, plus directed cases for the three decisions above.

### Two tests changed, and why

Both asserted behaviour the fixture layer had invented and the real server does not have:

- A **freshly created** scan was expected to carry `no_marker` in its `issues`. The server reports it
  through the scan's *status*, and only once the scan has been looked at — a queued scan does not
  know yet. Now read off a finished scan.
- A scan was expected to carry `reduced_extraction`. The server reports that on the **findings**,
  because it is a fact about one evaluation rather than about the run. `issuesFor(scan, result)` in
  `features/processing/degradation.ts` merges the two where both are to hand, which is what the
  screens now call.

### Still open on the app side

| Item | Note |
|---|---|
| Device walkthrough | Nothing here has run on hardware. The hashing path in particular is untested on a real 4 MB JPEG. |
| `__tests__/i18n.test.ts` | Fails, predates this work, untouched per CLAUDE.md §6 — flag 33 needs a decision. |
| Mock layer | Kept, not deleted. It now mirrors the wire faithfully and 6 test files depend on it; deleting it is a separate call. |
| `reportIssuedAt` | Still null: the server does not publish it, so Mode A's editing lock never engages. |
| A listing `url` row | The server records a URL as provenance and never fetches it, so such rows come back with no verdicts. Correct, and the results table already shows a row with no result as neither passing nor failing. |
