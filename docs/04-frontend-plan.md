# Anupalan — Frontend Build Order

**Doc version:** v1.3 · Companion to `02-trd.md` (the requirements) and `03-implementation-plan.md` §P3 (the phase this sits inside)
**Scope:** the Android app, end to end, built against dummy data until the backend is ready
**Owner:** frontend half of a two-person team; the backend is being built in parallel

> **This is a living file.** Update the stage's status and its *What shipped* note **in the same
> change that completes it**. A plan that lags the code is worse than no plan (CLAUDE.md §10).
> When a stage changes the phase's scope, update `03-implementation-plan.md` §P3 too.

**Status legend:** ✅ done · 🔨 in progress · ⬜ not started

---

## 1. Progress at a glance

| # | Stage | Requirements | Status |
|---|---|---|---|
| 0 | Shell, design system, i18n | NFR-07, NFR-08 | ✅ |
| 1 | Domain types and the dummy-data engine | — | ✅ |
| 2 | Auth and mode-aware navigation | — (TRD has no SR-xx entries; see flag 12) | ✅ |
| 3 | Marker onboarding | FR-02 | ⬜ |
| 4 | Guided capture and the four gates | FR-01 | ⬜ |
| 5 | Product context form | FR-03 | ⬜ |
| 6 | Offline queue | FR-04 | ⬜ |
| 7 | Processing and low-confidence confirmation | FR-06 | ⬜ |
| 8 | Findings viewer | FR-05 | ⬜ |
| 9 | Report export and share | FR-08 | ⬜ |
| 10 | History and search | FR-09 | ⬜ |
| 11 | Sahayak chat and BIS applicability | FR-07 | ⬜ |
| 12 | Bulk listing check | FR-10 | ⬜ |
| 13 | Hardening and the live-backend cutover | NFR-02, NFR-07, NFR-08 | ⬜ |

---

## 2. Working constraints

These were decided at the start of frontend work and apply to every stage below.

| Decision | Consequence |
|---|---|
| **Dummy data everywhere until the backend lands** | One transport seam, not fakery per screen. See §3. |
| **Both modes, screen by screen** | Every screen gets its Mode A (enforcement) and Mode B (industry) variant as it is built. Costs roughly 40% more screen work, landing on stages 5, 8, 9, 10 and all of 12. |
| **Simulated capture gates behind an interface** | The native ArUco frame processor is deferred; the screen is real and the plugin drops in later with no screen changes (`03-implementation-plan.md` §P3.3 sanctions this). |
| **i18n wired from the first string** | English complete, Hindi filled for the strings a Hindi-speaking inspector reads every scan, English fallback for the rest. |
| **Testing on a physical Android device** | Stages 4, 6 and 13 cannot be validated on an emulator. |
| **No web target** | MMKV has no web implementation. The `web` script was removed rather than left to mislead. |

**Approved dependencies.** Anything beyond these comes back for approval first (CLAUDE.md §7).

| Package | Needed for | Stage |
|---|---|---|
| `expo-location` | Mode A geo-tagged evidence on scans | 5 |
| `expo-file-system` | Queued capture images on disk | 6 |
| `expo-sharing` | FR-08 share PDF and DOCX | 9 |
| `expo-localization` | NFR-08 device locale | 0 ✅ |
| `expo-image-manipulator` | FR-06 image crop in the confirmation sheet | 7 |
| `@testing-library/react-native` (dev) | Screen tests, so "tests first" is possible | 0 ✅ |

---

## 3. The dummy-data engine

One module decides where data comes from. Everything above it is production code from the first
commit, so the cutover at Stage 13 is "delete the fixtures, flip the flag" — no screen rewrites.

```
screens → hooks (TanStack Query) → transport.ts ─┬─ mock: fixtures            ← today
                                                 └─ live: fetch + JWT         ← EXPO_PUBLIC_API_MODE=live
```

Rules for the fixtures, all of which exist to stop the demo drifting from reality:

- **Typed against `src/domain`**, so a fixture that drifts from the real shape fails `tsc` rather
  than failing silently in front of a judge.
- **Real rule ids and citations**, lifted from `rulepacks/lm-2011-v1.yaml` — `LM-9-2-TABLE1`,
  `LM-6-1-E-MRP`, `LM-6-10A-COO-FILTER` and the rest, with their gazette citations verbatim.
- **Every finding stamped `LM-2011-v1.0`** (CLAUDE.md §3.6).
- **The scan lifecycle advances with the clock**, not with a timer: status is a function of
  time elapsed since submit (`queued → processing → complete`). The Processing screen has
  something real to poll, and there are no timers to leak or clean up on re-mount.
- **220 seeded scans**, so FR-09's "200 scans under 500 ms" can be measured rather than assumed.
- **A dev panel forces the failure modes**: no marker, low-confidence field, LLM unavailable,
  error envelope, offline. These are acceptance criteria, not edge cases.

---

## 4. Phase A — Foundations

Blocks everything else.

### Stage 0 · Shell, design system, i18n ✅

**Requirements:** NFR-07 (error envelope), NFR-08 (Hindi and English)

Replace the Expo starter screens with the real navigation shell and the primitives every later
screen composes from.

**What shipped**

- `src/theme/` — palette, 4pt spacing, type scale, light and dark. The brand is teal-blue
  **deliberately not green**, because verdict colours are semantic and must own their hues: a
  green chrome element would read as a passing verdict. No webfont — NFR-02's 3-second cold-start
  budget is not worth spending on a font download.
- `src/components/` — Button, Card, Chip, Field, Banner, EmptyState, Skeleton, SegmentedControl,
  Text, Screen, plus `VerdictBadge` and `AdvisoryDisclaimer`. Tab icons are hand-drawn in
  `react-native-svg` rather than adding an icon package; the scan icon is a viewfinder framing a
  marker square.
- `src/i18n/` — typed keys, English complete, Hindi filled for navigation, verdicts and the
  disclaimer, English fallback for the rest. Device locale seeds first run; Settings switches live.
- `src/api/` — `ApiError` and the error envelope, plus a QueryClient that does not retry 4xx
  (cross-org access returns 404 by design; retrying it is pointless).
- `src/providers/` — root error boundary that keeps the app alive and offers a retry.
- `app/(tabs)/` — Scan, History, Sahayak, Settings. Stage 2 makes these mode-aware.
- `test-utils/render.tsx` and 20 tests.

**Removed:** the Expo starter chrome — `animated-icon`, `app-tabs`, `themed-text/view`,
`hint-row`, `web-badge`, `collapsible`, `external-link`, `src/constants/`, `src/hooks/`,
`global.css`, `scripts/reset-project.js`, and the `web` npm script.

**Gotchas found, so nobody pays for them twice**

- **RNTL 14 made `render()` and `unmount()` async.** Missing an `await` gives
  "`render` function has not been called", which reads like a config problem and is not.
- **MMKV 4 changed API** — `MMKV` is a type, not a constructor. Use `createMMKV()`, and the
  deleter is `remove()`, not `delete()`.
- **Expo's own starter `use-color-scheme.web.ts` fails the lint rules its own config ships**
  (setState in an effect). Replaced with `useSyncExternalStore`.

**Done when:** app boots to the real shell on a device, switches language live, lint/tsc/tests green.
**Verified:** lint 0 errors · tsc clean · 20 tests pass · `expo export --platform android` produces a 4.2 MB Hermes bundle.

### Stage 1 · Domain types and the dummy-data engine ✅

**Requirements:** — (chore; enables every stage after it)

**What shipped**

- `src/domain/` — split by concern: `common`, `verdict`, `org`, `product`, `scan`, `finding`,
  `report`, `sahayak`. All fifteen field codes, the four-valued verdict, `ScanListItem` for the
  history row. Deliberately **no `isFailure()` helper** — a helper like that is exactly how
  BORDERLINE quietly becomes FAIL three screens away.
- `src/api/transport.ts` — the seam. `live-transport.ts` is written already, so the mock is
  built against a real contract rather than the other way round.
- `src/api/types.ts` — the §5 contract, hand-maintained until `gen:api` replaces it.
- `src/api/endpoints.ts`, `keys.ts`, `hooks.ts` — one typed function and one hook per endpoint.
  `useScan` polls while status is `queued`/`processing` and stops on its own.
- `src/api/mock/` — routing, the scenario switch, and fixtures: two orgs (one per mode), four
  products chosen to hit different rule branches, the hero scan, 220 seeded scans, Sahayak
  answers covering all three outcomes, BIS applicability.
- **`scripts/make-sample-label.py`** — draws `assets/fixtures/rectified-label.png` at exactly
  20 px/mm *and* emits `label.ts` with the boxes and measured cap heights, in one run. The net
  quantity numerals really are 4.60 mm on that image; the fine print really is 0.90 mm. Nothing
  is hand-authored, so the overlay cannot drift from the picture.
- Dev scenario panel in Settings (`__DEV__` only) for the six failure modes.
- 25 new tests, 45 total.

**Two guards worth knowing about**

- Every bounding box is asserted to lie inside the image. A box running off the edge would look
  like a Stage 8 rendering bug rather than a bad fixture.
- The Table-I PASS is asserted to be arithmetically true: observed ≥ required, and observed
  equals the cap height actually drawn.

**Done when:** every hook returns typed dummy data, and `EXPO_PUBLIC_API_MODE=live` compiles with
no change above the transport.
**Verified:** lint 0 · tsc clean · 45 tests pass · prettier clean · `expo export` bundles, with
the sample label byte-identical in the output.

### Stage 2 · Auth and mode-aware navigation ✅

**Requirements:** none in the TRD — `02-trd.md` §1 declares `SR-xx` security ids and then defines
none, so the behaviour below is drawn from `01-architecture.md` §3 and §14 (flag 12).

| Mode | Tabs |
|---|---|
| A — enforcement | Scan · Inspections · Sahayak |
| B — industry | Scan · Bulk · History · Sahayak |

**What shipped**

- `src/store/session.ts` — tokens, user and org, read **synchronously** from MMKV in the store's
  initialiser. No zustand `persist`: its hydration lands one microtask after the first render, so
  every cold start would flash the login screen at a user who is already signed in. Synchronous
  reads are why MMKV was chosen in Stage 0, and this is where that pays off.
- `src/lib/storage.ts` — **two** MMKV instances. Signing out clears the session instance wholesale;
  preferences survive it, because a user who signs out has not asked to be put back into English.
- `app/(auth)/phone.tsx` and `otp.tsx` — two screens, one per endpoint. Phone numbers normalise to
  E.164 before the request, so `98000 00001`, `098000-00001` and `+91 9800000001` are one person.
- **Refresh on 401 in `src/api/live-transport.ts`**, single-flight, invisible above the transport.
  `src/api/auth-bridge.ts` is the three-callback seam that lets the transport reach the session
  without `store → api → transport → store`.
- `src/features/navigation/tabs.ts` — a pure `tabsForMode(mode)`. The layout renders from it with
  `Tabs.Protected`, so the other mode's route is **absent from the navigator**, not merely hidden.
- Settings moved out of the tab bar to `app/settings.tsx`, behind a header gear, and gained an
  account card with role, org, mode and sign-out.
- Dev panel gained a fixture-account switch that runs the **real** OTP request and verify rather
  than writing a session into the store, so the switch exercises the path that ships.
- 58 new tests, 103 total.

**The three things worth knowing**

- **Mode A has no History tab because Inspections *is* its history** — the same FR-09 list plus the
  district filter, geo-tag and evidence chain. Two routes over one dataset would leave the one
  called "History" quietly missing the evidence panel.
- **The query cache is emptied on org id change, not on sign-out.** There are three ways to end up
  looking at another org's data and only one is a sign-out button; the other two are a rejected
  refresh token and a second account signing in on a shared phone. Asserted in
  `__tests__/auth-cache.test.ts`, because this is the class of bug that works in testing precisely
  because nobody switches accounts.
- **Refresh-on-401 cannot be checked by using the app** — in `mock` mode the transport is the mock,
  so the path is dead until Stage 13. `__tests__/auth-refresh.test.ts` covers it against a stubbed
  `fetch`, including that many simultaneous 401s share one refresh, and that a refresh which could
  not *reach* the server does not sign the user out. Conflating those two logs an inspector out for
  driving through a tunnel.

**Also:** `npm run types:routes` now regenerates `.expo/types/router.d.ts` without starting Metro,
so typed routes are a real gate in CI. They were stale enough to still list the deleted `/explore`,
which only went unnoticed because nothing before this stage navigated anywhere.

**Done when:** logging in as an enforcement org and an industry org produces visibly different
navigation from the same build.
**Verified:** lint 0 · tsc clean · 103 tests pass · prettier clean · `expo export --platform
android` bundles. The mode difference is asserted in `__tests__/mode-navigation.test.ts`; the
on-device check is tapping the two fixture accounts in Settings and watching the tab bar change.

---

## 5. Phase B — The capture path

Needs the EAS dev client on a real phone.

### Stage 3 · Marker onboarding ⬜

**Requirements:** FR-02

- First-run choice: print the A4 marker sheet (40 mm ArUco tag, 5 mm quiet zone) or use an ID-1
  card at 85.60 × 53.98 mm.
- The printable sheet ships as an asset, with the print-at-100% warning and a ruler-check step.
  A printer that scales the page makes every downstream millimetre wrong, and it looks like a
  code bug for days (CLAUDE.md §8).
- `markerType` and `markerMm` persisted and attached to every scan.

**Done when:** the scan payload contains `marker_type` and `marker_mm`, and a scan cannot be
submitted without both.

### Stage 4 · Guided capture and the four gates ⬜

**Requirements:** FR-01

- vision-camera preview, permission flow, marker alignment overlay.
- A `GateEvaluator` interface with a simulated implementation behind it, plus a dev toggle to
  force each pass/fail state. The native ArUco frame processor drops in later unchanged.
- Four gate chips, each with its own instruction when red. Thresholds: blur ≥ 120 variance of
  Laplacian, glare < 2% of pixels at ≥ 250 luminance, tilt ≤ 25°.
- Shutter disabled while any gate fails. Capture writes the image to disk and opens a local scan.

> **Prerequisite:** Expo Go cannot run frame processors. The EAS dev client build must be on the
> device before this stage starts.

**Done when:** the shutter is disabled while any gate fails, each failing gate shows its specific
instruction, and all four green enables capture.

### Stage 5 · Product context form ⬜

**Requirements:** FR-03

- react-hook-form: product name, searchable category, pack type (rigid / flexible / glass / can /
  other), surface (printed / embossed), imported yes-no, declared net quantity with unit.
- Unit entry rejects the variants the rules reject — `gms`, `Gm`, `ltr` — normalising to `g`,
  `kg`, `ml`, `l`.
- The OCR-prefill path for three fields, confirmed by the user after processing.

| Mode | Difference |
|---|---|
| A | Geo-tagged and timestamped at capture via expo-location, disclosed in-app |
| B | No location collected; pre-print artwork context rather than field inspection |

**Done when:** net quantity value and unit, the imported flag and surface type are present on
every completed scan — all three change which rules apply.

### Stage 6 · Offline queue ⬜

**Requirements:** FR-04

- expo-sqlite schema for scans, assets and an outbox; images on disk via expo-file-system.
- A persisted state machine per scan: `captured → queued → uploading → processing → complete | failed`,
  retried with backoff, resumed on launch.
- Queue UI: a pending badge and a per-item state list with manual retry.

**Done when:** airplane mode → capture 3 scans → force-close the app → restore network → reopen →
all 3 upload and complete. Run exactly that, on a real device.

---

## 6. Phase C — The results path

This is the demo.

### Stage 7 · Processing and low-confidence confirmation ⬜

**Requirements:** FR-06

- Pipeline progress against the real stage names, polling scan status.
- Degradation handled as designed (`01-architecture.md` §11): no marker offers a no-measurement
  mode running presence and format rules only, with metric rules marked `NOT_ASSESSABLE`; LLM
  unavailable shows a "reduced extraction" flag rather than failing.
- Any field below 0.75 confidence surfaces in a confirmation sheet with a crop of that region.

**Done when:** the deliberately blurred MRP fixture triggers the sheet, the correction is
recorded with `source=human`, and the verdict recomputes.

### Stage 8 · Findings viewer ⬜

**Requirements:** FR-05

- The rectified image with tappable bounding boxes in react-native-svg, staying aligned through
  pinch and zoom.
- Four groups — Failures, Borderline, Not assessable, Passed — visually distinct, never merged.
  A BORDERLINE prints its uncertainty band ("2.05 mm, band 1.80–2.30"), not a bare verdict.
- Tapping a finding shows required, observed and the citation verbatim, without leaving the screen.
- The advisory disclaimer and the rule pack version (CLAUDE.md §3.8, §3.6).

| Mode | Difference |
|---|---|
| A | Evidence panel: image hash, findings hash, capture time and location. Editing locked after issue |
| B | A remediation suggestion per failing finding — what to change on the artwork |

**Done when:** every FAIL and BORDERLINE has a bounding box that highlights on tap, and the
citation text is visible without leaving the screen.

### Stage 9 · Report export and share ⬜

**Requirements:** FR-08

- Request PDF and DOCX, poll for completion, hand off to the system share sheet.
- A preview carrying the disclaimer, both hashes and the rule pack version.
- Mock mode ships real sample PDF and DOCX files so the share path is genuinely exercised.

**Done when:** both files share out of the app and open in an external viewer.

### Stage 10 · History and search ⬜

**Requirements:** FR-09

- Virtualised list over the 220 seeded scans; filters for date range, product and verdict.
- Verdict filters keep all four values distinct — "failures only" must not quietly include
  BORDERLINE.

| Mode | Difference |
|---|---|
| A | District and state filters; inspection-history framing |
| B | Filter by brand and SKU; no location filter, since none is collected |

**Done when:** filtering 200 seeded scans by `verdict=FAIL` returns only scans with at least one
FAIL, within 500 ms. Measure it and record the number.

---

## 7. Phase D — Assistant, bulk, hardening

Droppable from the bottom if the timeline compresses.

### Stage 11 · Sahayak chat and BIS applicability ⬜

**Requirements:** FR-07

- Chat in English and Hindi, with inline source chips that open the cited page.
- Two entry points: free chat, and "Check BIS requirement for this product" from a completed
  scan, rendering QCO applicability, scheme, candidate IS numbers, next steps and sources.
- Two refusals designed as features: no supporting source returns an explicit "not found in
  official sources" with a link to the relevant BIS page; a request for the technical content of
  a standard is declined and pointed at the BIS purchase route (CLAUDE.md §3.5).
- Answers carry a freshness stamp — QCOs are amended constantly.

**Done when:** the unanswerable fixture returns the explicit not-found response with an official
link, and never a fabricated citation.

### Stage 12 · Bulk listing check ⬜

**Requirements:** FR-10 · Mode B only

- Paste listing text or pick a CSV of marketplace URLs; up to 50 rows.
- Presence and format rules only. Every metric rule shows `NOT_ASSESSABLE` with the reason stated
  plainly: a listing has no physical scale, so there is nothing to measure.
- Results table with summary counts, and an export.

**Done when:** a 50-row CSV produces 50 result rows with a summary count, and no metric rule ever
returns PASS or FAIL from listing text alone.

### Stage 13 · Hardening and the live-backend cutover ⬜

**Requirements:** NFR-02, NFR-07, NFR-08

- Cold start measured on a real 4 GB Android 12 phone, not an emulator. Target 3 seconds.
- Loading, empty and error states on every screen; the full `01-architecture.md` §11 degradation
  table walked through deliberately.
- Hindi completion pass and a layout check at Devanagari string lengths.
- Cutover: point `gen:api` at the live OpenAPI schema, regenerate types, fix what the compiler
  flags, delete the fixtures folder and the mock branch of the transport.
- Accessibility pass: labels, hit targets, focus order, contrast in both themes.

**Done when:** cold start is measured and reported, the app runs against the real backend with no
screen changes, and the mock transport is gone from the release build.

---

## 8. Sequencing

Stages 0 and 1 block everything. After that the capture path and the results path are
independent — the results path only needs fixtures, so it can be built before a single real
endpoint exists.

| Lane | Stages |
|---|---|
| Blocking | 0 ✅ · 1 |
| Capture path | 2 · 3 · 4 · 5 · 6 |
| Results path | 7 · 8 · 9 · 10 |
| Last | 11 · 12 · 13 |
| In parallel, start early | EAS dev client build · marker sheet printed and ruler-checked |

**If the timeline compresses, drop from the bottom.** Stages 4, 8 and 9 — gated capture, the
findings overlay and the report — are the demo. Everything after Stage 10 is valuable and
droppable; nothing before it is.

---

## 9. Flags and open questions

1. **Both modes costs roughly 40% more screen work**, landing on stages 5, 8, 9, 10 plus stage 12
   entirely. Do not read the stage count as the effort.
2. **Mode A's evidence panel cannot be truly verified yet.** The hash chain is computed
   server-side, so the panel renders dummy hashes until the backend lands. The UI is real; the
   integrity claim is not testable from the app alone.
3. **Dashboards are not in this plan.** `01-architecture.md` §3 mentions district and state
   dashboards for enforcement, but `02-trd.md` §2 has no mobile requirement for them — FR-30 is a
   set of backend endpoints. Decide before Stage 10 whether they belong on the phone.
4. **A fixture transport instead of MSW.** `03-implementation-plan.md` §P3.6 suggests mocking with
   MSW from the OpenAPI schema. MSW in React Native needs polyfills and has a history of friction
   with Hermes; a transport seam gives the same "app code is identical in both modes" property
   with no dependency and no native risk. Deliberate deviation — record it in `decisions.md` when
   Stage 1 lands.
5. **TRD §5 has no scan-list endpoint, but FR-09 needs one.** The contract defines
   `GET /v1/scans/{id}` and nothing that lists or filters scans. Stage 1 assumes
   `GET /v1/scans?verdict=&district=&from=&to=&cursor=` returning a page of compact rows with a
   verdict summary. **Agree this with the backend before Stage 10** — it is an API contract
   change and CLAUDE.md §7 says to ask.
6. **How does the backend represent a rule that does not apply?** CLAUDE.md §3.4 says verdicts
   are four-valued, but `03-implementation-plan.md` §P2.4 cases 8 and 10 describe a rule being
   "skipped" or `NOT_APPLICABLE`. The fixtures **omit inapplicable rules from the findings list**
   rather than inventing a fifth verdict, because inventing one would contradict a
   non-negotiable. Confirm the backend does the same.
7. **`react-native-nitro-modules` is an auto-installed peer** of MMKV and vision-camera, not
   declared in `package.json`. If the EAS dev-client build fails on autolinking, check this first.
8. **TRD §5 has no refresh endpoint**, although `auth/otp/verify` returns a refresh token and
   `01-architecture.md` §197 specifies access/refresh JWTs. Stage 2 assumes
   `POST /v1/auth/refresh {refreshToken} -> {accessToken, refreshToken}`, returning **401** when the
   refresh token is rejected — the status the client uses to decide a session is over rather than
   merely unreachable. **Agree before Stage 13.**
9. **TRD §5 has no session endpoint.** `user` and `org` arrive exactly once, in the verify response,
   so the app cannot revalidate who it is after a restart and caches them locally. A `GET /v1/auth/me`
   would let the org and role be refreshed as server state instead — worth having if a user's role
   can change while they are signed in.
10. **TRD §5 sketches snake_case field names** (`{request_id}`, `{access, refresh}`) while the
    client types are camelCase throughout. One of the two has to give, and FastAPI can alias on the
    way out. **This affects every endpoint, so settle it early** — it is cheap now and a
    find-and-replace across the app later.
11. **The refresh token is in unencrypted MMKV.** A rooted device, or one with ADB backup enabled,
    can read it off disk. The right home is the Android Keystore via `expo-secure-store`, which is a
    new dependency and needs approval (CLAUDE.md §7). `src/lib/storage.ts` keeps it behind one
    interface so the swap is a one-file change.
12. **`02-trd.md` declares `SR-xx` security requirement ids in §1 and defines none.** Auth therefore
    has no acceptance tests in the TRD, and Stage 2 was built from `01-architecture.md` §3 and §14
    instead. Worth adding them: org isolation and session handling are the requirements most likely
    to be assumed rather than checked.

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-09-12 | Created. Fourteen stages defined; Stage 0 completed and recorded. |
| 2026-09-12 | Stage 1 completed. Two API contract gaps recorded as flags 5 and 6. |
| 2026-09-12 | Stage 2 completed. Settings moved off the tab bar; flags 8–12 added, three of them API contract gaps. Stage 1's MSW deviation and Stage 2's session design recorded in `decisions.md`. |
