# Anupalan — Online Ingredient Cross-check: Plan

**Status:** 13 Sep 2026. Asks 1, 2, 4, 5 and 6 approved; 3, 7 and 8 deferred as recommended.
**B25–B30 are implemented** (services and tests; no persistence or API). B31–B33 not started. The
source registry ships empty pending curation, so every check is `brand_not_registered` until a person
adds verified brand domains.
**Proposed requirements:** FR-11 (mobile), FR-31 (backend). Neither is in `02-trd.md` yet.
**Work packages:** B25–B33, following on from `04-backend-implementation-plan.md`.

---

## 1. The feature in one paragraph

After a scan completes, the user taps **Check ingredients online**. The worker reads the
ingredient list off the scan's stored OCR text, finds the product's page on the manufacturer's
official website, reads the ingredient list published there, and compares the two. The result
lists what matches, what appears only on the label, what appears only online, and any differences
in order or declared percentage. Every online claim links to the page it came from, with the fetch
date and a hash of the page as it was read.

---

## 2. Two framing decisions, settled before any code

### 2.1 This is a consistency signal, not a compliance verdict

Ingredient lists are required by food and cosmetics labelling law — for food, the FSS (Labelling
and Display) Regulations, 2020 — not by the Legal Metrology (Packaged Commodities) Rules, 2011. No
rule in `rulepacks/lm-2011-v1.yaml` covers them. And a label that differs from a website is not in
itself a violation: the label is the legal declaration, and a website can lag a reformulation,
describe another region's variant, or simply be wrong.

So the check:

- produces its **own outcome type**, not a `rules.types.Finding`, and never writes to `findings`,
  `scan_evaluations`, the FR-30 dashboards or the E3 confusion matrix;
- uses its own four outcomes — `CONSISTENT | DIFFERENCES_FOUND | UNCLEAR | NOT_VERIFIABLE` — and
  never the words PASS or FAIL. This is CLAUDE.md §3.4's principle applied: a website mismatch
  rendered as FAIL is an accusation this system cannot support;
- carries the advisory disclaimer (§3.8) plus one line of its own: *"The package label is the
  legal declaration. A manufacturer's website may describe a different batch, region or
  formulation."*

### 2.2 "The manufacturer's website" needs a trust anchor

A web search for a product name returns marketplaces, resellers, recipe blogs and look-alike
domains. None of those is the manufacturer, and treating a result as authoritative because it
ranked well is how a check ends up comparing a label against a stranger's typo.

| Option | Verdict |
|---|---|
| **Curated registry: brand → official domains**, reviewed data in `ingredients/sources-v1.yaml` | **Recommended.** Deterministic, auditable, and a wrong entry is a reviewed diff |
| Search the open web and guess the official domain | Rejected: spoofable, and marketplace pages outrank brand pages |
| Marketplace pages (Amazon, BigBasket, …) | Rejected for v1: seller-entered text, and scraping them breaks their terms of service |
| Open Food Facts by GTIN | Deferred (ask 8): crowdsourced rather than the manufacturer, ODbL attribution; usable only as a labelled secondary source |

A brand missing from the registry is `NOT_VERIFIABLE` with reason `brand_not_registered`. Never a
guess.

---

## 3. Constraints that shape the design

| Rule | Consequence here |
|---|---|
| §3.1 LLM never decides | `compare()` is a pure function. v1 uses **no LLM at all**: splitting the list and the same-product check are both deterministic (§5, §6). An LLM splitter for noisy OCR is optional and behind ask 7 |
| §3.2 no thresholds in code | Tolerances, heading words, synonym tables and name-match ratios live in `ingredients/vocabulary-v1.yaml`, versioned and checksummed like a rule pack |
| §3.6 reproducible | Each check stamps vocabulary and registry version + checksum and, for every page, its URL, fetch time, content sha256 and a stored snapshot. A check is a dated observation of a website and is never recomputed in place |
| §3.7 org-scoped | New tables carry `org_id` and the composite scan FK; cross-org is 404 |
| §8 `source_span` | Every label item carries a span into the OCR text and a bbox; every online item a span into the snapshot's text. Both verified, not trusted |
| `listings.py`'s SSRF stance | Only registry domains are fetched, through a guarded fetcher (§7). No caller-supplied URL is ever requested |
| NFR-01 scan latency | Not a stage of `process_scan`. A separate on-demand Celery task after the scan completes — the scan never waits on the web |
| §2 no second runtime | No headless browser. Pages that need JavaScript to show ingredients are `NOT_VERIFIABLE`, reason `page_requires_javascript` |

---

## 4. Architecture

```
mobile: scan/[id] ── POST /v1/scans/{id}/ingredient-checks ──► 202 {check_id}
                                                                   │
                         Celery task ingredients.check ◄───────────┘
                           │
   S1 label list      stored ocr_results.raw_json ─► locate block ─► split ─► items + spans + bbox
   S2 identity        scan.profile (name, net qty) + products (brand, gtin)
   S3 discover        registry domains ─► robots.txt ─► sitemap(s) ─► rank URLs by slug tokens ─► top K
   S4 fetch           guarded GET ─► snapshot to R2 ({org}/{scan}/ingredients/{sha}.html) + sha256
   S5 online list     html ─► text ─► locate block ─► split ─► items + spans
   S6 same product?   deterministic: brand alias + name-token coverage ≥ policy
   S7 compare         compare(label, online, policy) — pure
   S8 persist         ingredient_checks + ingredient_sources, audit_log entry
                           │
mobile polls ── GET /v1/scans/{id}/ingredient-checks/latest ──► result
```

S1 reads `ocr_results.raw_json`, which already stores the engine's word list so extraction can be
re-run without re-running OCR. Nothing in the scan pipeline changes.

**Discovery via sitemap, not a search API.** Most brand sites publish `sitemap.xml`, usually named
in `robots.txt`. Scoring its URLs by slug-token overlap with the product name is deterministic,
free, vendor-less, and keeps the on-premise story intact (CLAUDE.md §9). A search-API adapter sits
behind a `PageDiscoverer` protocol as a fallback for sites with no sitemap — that is ask 3, and
not needed for v1.

### Module layout

```
ingredients/                         # NEW top-level data dir (ask 1), same terms as bis/
├── sources-v1.yaml                  # brand → official domains, aliases; reviewed
└── vocabulary-v1.yaml               # heading words (en/hi), stop headings, INS/E-number synonyms,
                                     # ambiguous pairs, tolerances, name-match ratio

backend/app/services/ingredients/
├── types.py        # IngredientItem, IngredientList, ItemDiff, Comparison, Outcome, ReasonCode
├── data.py         # load + validate + checksum both YAML files (mirrors rules/loader.py)
├── locate.py       # find the ingredient block in a text (label OCR or page text)
├── split.py        # block → items: commas, nested parentheses, percentages; deterministic
├── normalise.py    # NFKC, casefold, strip %, INS/E-number/synonym canonicalisation
├── compare.py      # compare(label, online, policy) -> Comparison            ★ pure
├── identify.py     # same_product(page_text, identity, policy) -> MatchResult ★ pure
├── discover.py     # PageDiscoverer protocol; SitemapDiscoverer; stub
├── fetch.py        # guarded fetch (§7)
├── html_text.py    # HTML → text with stdlib html.parser, script/style dropped
└── check.py        # run_check(...) orchestrator behind CheckStore / ObjectStorage ports, like pipeline.py

backend/app/tasks/ingredients.py     # thin Celery wrapper
backend/app/models/ingredient_check.py
backend/app/repositories/ingredient_checks.py
backend/app/routers/scans.py         # endpoints added (§9)
```

---

## 5. The comparator — the part that decides

`compare(label: IngredientList, online: IngredientList, *, policy: ComparisonPolicy) -> Comparison`.
No I/O, no clock, no model.

**Normalisation**, every step data-driven and unit-tested:

1. NFKC, casefold, collapse whitespace, strip trailing punctuation.
2. Lift a declared percentage into its own field: `Wheat flour (atta) (62%)` → name `wheat flour`,
   pct `62.0`, children `[atta]`.
3. Canonicalise through the vocabulary: `INS 330`, `E330`, `citric acid`, `acidity regulator (330)`
   → `ins:330`. Plain synonyms (`sugar` / `sucrose`) map only where the vocabulary lists them.
   Pairs the vocabulary marks **ambiguous** (e.g. `vegetable oil` / `palm oil`) never count as a
   match *or* a mismatch — they make the result UNCLEAR.
4. A class name carrying its INS number in brackets is matched on the number.

**Item-level diff:** `matched`, `only_on_label`, `only_online`, `ambiguous`, `pct_differs` (outside
`policy.pct_tolerance`), `order_differs` (relative order of matched items changes).

**Outcome** — evaluated in this order, first match wins:

| Outcome | When |
|---|---|
| `NOT_VERIFIABLE` | S1–S6 could not produce both lists. Always carries a `reason_code`: `label_block_not_found`, `brand_not_registered`, `no_candidate_page`, `fetch_blocked`, `page_requires_javascript`, `online_block_not_found`, `no_page_matched_product` |
| `UNCLEAR` | any label item below the FR-06 confidence threshold and not human-confirmed; or more than one variant page matched with different lists (`ambiguous_variant`); or the only differences are `ambiguous` pairs, `order_differs`, or a percentage inside the uncertainty band |
| `DIFFERENCES_FOUND` | a confident item on one side is absent from the other, or a declared percentage differs by more than tolerance |
| `CONSISTENT` | same items after normalisation, same order, percentages within tolerance |

The confidence rule mirrors FR-06: an OCR misread of `palm oil` as `pal oil` must reach the
confirmation sheet, not become a "difference". The confirm-fields flow gains ingredient items, and
confirming them re-runs `compare()` over the stored lists without refetching.

---

## 6. Same-product check

`same_product(page_text, identity, policy)` passes only when:

- the page contains the brand or one of its registry aliases, **and**
- at least `policy.name_token_coverage` of the product-name tokens (vocabulary stop words removed)
  appear in the page title or `<h1>`, **and**
- if the page names pack sizes, the scanned net quantity is among them or the page declares one
  list for all sizes. No size named → this clause is skipped, not failed.

Of the K fetched candidates, passing pages with the same list collapse into one source; passing
pages with *different* lists → `UNCLEAR / ambiguous_variant`, listing each.

---

## 7. Guarded fetch

`fetch(url, *, allowed_domains, limits) -> FetchResult`. Every line below has a test.

- `https` only, port 443 only.
- Host must equal a registry domain for this brand or be a subdomain of one.
- DNS resolved first; loopback, private, link-local (including `169.254.169.254`), CGNAT,
  multicast and reserved addresses refused, IPv4 and IPv6. The connection goes to the address that
  was validated, so a DNS-rebinding answer between check and connect cannot redirect it.
- Redirects followed manually, at most `limits.max_redirects`; every hop re-runs every check above.
- Streamed with a byte cap — aborted past `WEB_FETCH_MAX_BYTES`. Total timeout.
- `Content-Type` allow-list: `text/html`, `application/xhtml+xml`, and XML for sitemaps.
- No cookies, no `Authorization`, an honest User-Agent naming the product and a contact URL.
- `robots.txt` honoured (`urllib.robotparser`, stdlib); disallowed → `fetch_blocked`.
- Per-domain concurrency of 1; per-org daily cap on checks (config).
- **CI never opens a socket.** The suite patches the transport, and a guard test fails if a real
  connection is attempted.

---

## 8. Data model — migration 0004 (ask 4)

**`ingredient_checks`** — append-only; newest `created_at` per scan is current.
`id, org_id, scan_id (composite FK → scans(id, org_id)), requested_by, status
(queued|running|complete|failed), outcome, reason_code, label_items JSON, online_items JSON,
comparison JSON, vocabulary_version, vocabulary_checksum, sources_version, sources_checksum, error,
created_at, completed_at`

**`ingredient_sources`**
`id, org_id, check_id FK, url, final_url, domain, http_status, fetched_at, content_sha256,
snapshot_key, matched_product bool, reject_reason`

Both are added to the structural assertions in `test_org_isolation.py`. A completed check appends
to the audit hash chain (B16).

---

## 9. API — additive contract change (ask 5)

| Method | Path | Notes |
|---|---|---|
| POST | `/v1/scans/{scan_id}/ingredient-checks` | `Idempotency-Key` required. 202 `{check_id, status}`. 409 if the scan is not `complete`/`no_marker`. 429 past the per-org daily cap. Same role gate as `confirm-fields` |
| GET | `/v1/scans/{scan_id}/ingredient-checks/latest` | 404 if none. Outcome, reason, the three item groups, order/percentage notes, sources `[{url, fetched_at, content_sha256}]`, versions, disclaimer |
| GET | `/v1/scans/{scan_id}/ingredient-checks/{check_id}` | A specific historical check |

NFR-07 envelope throughout; cross-org is 404. OpenAPI regenerated, then `npm run gen:api`.

---

## 10. Mobile — proposed FR-11

- `mobile/src/features/ingredients/` — `groups.ts` (pure: result → matched / only-on-label /
  only-online / notes; never merges groups), `outcome-copy.ts` (wording for all four outcomes and
  every reason code; no PASS/FAIL vocabulary), `eligibility.ts` (shown only on a completed scan).
- `mobile/app/scan/[id]/ingredients.tsx` — status while polling, the three groups, a source chip
  that opens the page in the system browser, "Website read on <date>", the disclaimer. Tapping a
  label item highlights its bbox via `features/findings/viewport.ts`.
- An entry card on `scan/[id]/index.tsx`.
- Mock-transport fixtures for all four outcomes first, per the Stage 1 decision. New stage in
  `05-frontend-plan.md`; endpoints added to `06-wiring-contract.md`.

---

## 11. Configuration (`app/config.py`)

`INGREDIENTS_SOURCES_PATH`, `INGREDIENTS_VOCABULARY_PATH`, `INGREDIENTS_DISCOVERER`
(`sitemap` | `stub`), `INGREDIENTS_MAX_CANDIDATE_PAGES` (K), `INGREDIENTS_CHECKS_PER_ORG_PER_DAY`,
`WEB_FETCH_TIMEOUT_SECONDS`, `WEB_FETCH_MAX_BYTES`, `WEB_FETCH_MAX_REDIRECTS`,
`WEB_FETCH_USER_AGENT`.

Engineering limits only. Every comparison threshold is in the vocabulary file.

---

## 12. Tests — written before the code (CLAUDE.md §6)

| Suite | Pins |
|---|---|
| `test_ingredient_compare.py` | identical → CONSISTENT; INS/E-number/name equivalence; ambiguous pair → UNCLEAR; order swap → UNCLEAR; missing / extra item → DIFFERENCES_FOUND; % inside / at / outside tolerance; an unconfirmed low-confidence item blocks DIFFERENCES_FOUND; nested parentheses; Devanagari list; determinism |
| `test_ingredient_locate_split.py` | `Ingredients:` / `INGREDIENTS` / `सामग्री` headings; block ends at the next stop heading (nutrition, allergen, mfd by); OCR line breaks mid-item; every item span verified against its source text |
| `test_ingredient_identify.py` | brand alias; name-token coverage just below / at threshold; pack-size mismatch; two variants → ambiguous |
| `test_web_fetch_guard.py` | http refused; non-registry host; `127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`, `::1`, `fc00::/7`; redirect to a private address; DNS rebinding; oversize body; wrong content type; robots disallow; redirect cap; no socket opened |
| `test_ingredient_data.py` | vocabulary and registry validate with line-level errors; checksum over raw bytes; version must be a string |
| `test_ingredient_check.py` | orchestrator over stub discoverer + fixture HTML: every reason code reachable; snapshot stored with correct sha256 |
| `test_ingredient_api.py` | 202 + idempotent replay; 409 on an unfinished scan; 429 cap; cross-org GET/POST → 404; response carries disclaimer and versions |
| `test_org_isolation.py` | extended structurally for the two new tables |

**Evaluation (B33):** an E5 set of ≥ 30 real products with hand-verified label and website lists.
Report the outcome confusion matrix and, above all, the **false DIFFERENCES_FOUND rate** — the
number that matters here for the same reason E3's false-FAIL rate does. Committed to
`docs/eval-results.md`.

---

## 13. Work packages

| # | Package | Depends on | Gated by ask |
|---|---|---|---|
| B25 | `ingredients/` data files, `data.py` loader, `types.py` | — | 1 |
| B26 | `normalise.py` + `compare.py` ★ pure, 80% coverage floor | B25 | — |
| B27 | `locate.py` + `split.py` over OCR words and plain text | B25 | — |
| B28 | `identify.py` ★ pure | B25 | — |
| B29 | `fetch.py` guard, `html_text.py`, `discover.py` (sitemap + stub) | — | 2 |
| B30 | `check.py` orchestrator behind ports | B26–B29 | — |
| B31 | model, migration 0004, repository, isolation tests | B30 | 4 |
| B32 | Celery task, endpoints, daily cap, confirm-fields extension | B31 | 5 |
| B33 | mobile stage (FR-11) + E5 evaluation | B32 (mobile starts on fixtures once §9 is agreed) | — |

B26–B29 run in parallel once B25 lands. B30 is written against ports, as B10 was, so it never
waits on the schema review. One PR per package, titled with its requirement
(`feat(ingredients): FR-31 ingredient comparator`). A full CLAUDE.md §11 handoff card is written
as each package is picked up; the first:

```
CONTEXT:     this doc §2, §3, §5; CLAUDE.md §3; services/rules/loader.py (checksum pattern)
TASK:        backend/app/services/ingredients/{types,data,normalise,compare}.py
             + ingredients/vocabulary-v1.yaml
CONSTRAINTS: compare() pure — no I/O, no clock, no model; no tolerance or synonym in a .py file;
             no new dependency; must not import services/rules or produce a Finding
SIGNATURE:   compare(label: IngredientList, online: IngredientList, *,
                     policy: ComparisonPolicy) -> Comparison
             load_vocabulary(path: Path) -> Vocabulary     # .version, .checksum, .policy
TESTS:       tests/test_ingredient_compare.py, tests/test_ingredient_data.py — written first, then frozen
DONE WHEN:   pytest tests/test_ingredient_compare.py tests/test_ingredient_data.py
             && ruff check . && mypy app/services
```

---

## 14. Asks — CLAUDE.md §7

| # | Ask | Blocks | Recommendation |
|---|---|---|---|
| 1 | New top-level data directory `ingredients/` (a CLAUDE.md §2 layout change) | B25 | Yes. Not LM rule text, not BIS catalogue data — neither existing directory fits |
| 2 | Promote `httpx` from dev to core (already the outstanding B8 ask). **No** HTML-parser dependency — stdlib `html.parser` | B29 | Yes |
| 3 | A web-search managed service as a fallback discoverer | nothing in v1 | Defer. Sitemap first; decide on E5's `no_candidate_page` rate |
| 4 | Migration 0004: `ingredient_checks`, `ingredient_sources` | B31 | Yes, as §8 |
| 5 | Additive API: the three endpoints in §9 | B32 | Yes; no existing contract changes |
| 6 | Outcome vocabulary kept separate from the four verdicts; the check is never a Finding | all | Yes — §2.1 |
| 7 | A fourth LLM call site (`ingredients.split`, budget tier, span-validated) for noisy OCR | nothing in v1 | Defer until E5 shows how often deterministic splitting fails on real labels |
| 8 | Open Food Facts by GTIN as a labelled secondary source | nothing in v1 | Defer |

Also needed, outside §7: who curates `sources-v1.yaml`, and which first 20–30 brands it covers.
Those brands should be the E5 set.

---

## 15. Known limitations — state them before a judge does

1. Many Indian brand sites publish no ingredient list, or render it client-side. Expect a high
   `NOT_VERIFIABLE` rate, and say so up front.
2. One photograph covers one panel (architecture §12.1). Ingredients are usually on the back, so
   the scan must include that panel or the result is `label_block_not_found`.
3. Coverage is bounded by the registry. An unregistered brand is never guessed.
4. A website is not the legal declaration; a difference is a prompt to look, not a finding.
5. Synonym coverage bounds Devanagari-only lists and regional names. Gaps surface as UNCLEAR,
   not as false differences.

---

## 16. Documentation updated in the same PRs

`02-trd.md` (FR-11, FR-31) · `01-architecture.md` (§4 component; §9 rows for sitemap discovery vs
search API and for no headless browser; §11 failure modes; §12 limitations) ·
`04-backend-implementation-plan.md` (B25–B33) · `05-frontend-plan.md` (new stage) ·
`06-wiring-contract.md` · `decisions.md` (one entry per settled ask) · `CLAUDE.md` §2
(`ingredients/`), and §9 only if ask 7 is approved.
