# Anupalan — Frontend Build Order

**Doc version:** v1.7 · Companion to `02-trd.md` (the requirements) and `03-implementation-plan.md` §P3 (the phase this sits inside)
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
| 3 | Marker onboarding | FR-02 | ✅ |
| 4 | Guided capture and the four gates | FR-01 | ✅ (device check pending) |
| 5 | Product context form | FR-03 | ✅ (device check pending) |
| 6 | Offline queue | FR-04 | ✅ (device check pending) |
| 7 | Processing and low-confidence confirmation | FR-06 | ✅ (device check pending) |
| 8 | Findings viewer | FR-05 | ✅ (device check pending) |
| 9 | Report export and share | FR-08 | ✅ (device check pending) |
| 10 | History and search | FR-09 | ✅ (device check pending) |
| 11 | Sahayak chat and BIS applicability | FR-07 | ✅ (device check pending) |
| 12 | Bulk listing check | FR-10 | ✅ (device check pending) |
| 13 | Hardening and the live-backend cutover | NFR-02, NFR-07, NFR-08 | ✅ wired (device check pending) |
| 13 | Hardening and the live-backend cutover | NFR-02, NFR-07, NFR-08 | 🔨 (cutover blocked on the backend; cold start on a device) |

---

## 2. Working constraints

These were decided at the start of frontend work and apply to every stage below.

| Decision | Consequence |
|---|---|
| **Dummy data everywhere until the backend lands** | One transport seam, not fakery per screen. See §3. |
| **Both modes, screen by screen** | Every screen gets its Mode A (enforcement) and Mode B (industry) variant as it is built. Costs roughly 40% more screen work, landing on stages 5, 8, 9, 10 and all of 12. |
| ~~**Simulated capture gates behind an interface**~~ **Server-measured capture gates** | Closed 2026-09-13. The simulation was reporting all-green on any subject; the gates now measure a real preview frame via `POST /v1/capture/gates`. The native ArUco plugin remains the end state and still drops in behind the same interface (`03-implementation-plan.md` §P3.3). |
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
| `expo-web-browser` | FR-07 source chips opening a cited page in-app | 11 ✅ |
| `expo-crypto` | SHA-256 per asset, which `POST /v1/scans` requires before the upload (`06-wiring-contract.md` §3.1 G1) | 13 ✅ **installed 2026-09-12.** Native, so the EAS dev client needs rebuilding before the device walkthrough |

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

### Stage 3 · Marker onboarding ✅

**Requirements:** FR-02

**What shipped**

- **`scripts/make-marker-sheet.py`** — generates `assets/marker/anupalan-marker-a4.pdf`, the
  printable A4 sheet. The tag is read from **OpenCV's own 4×4_50 codebook**, never hand-drawn, so
  the pattern on paper and the pattern the backend's detector looks for cannot diverge.
- `src/features/capture/markers.ts` — the three references and their sizes: 40.00 mm tag,
  85.60 mm ID-1 long edge, or a user-measured dimension bounded to 20–200 mm.
- `src/store/marker.ts` — the device's verified choice, in the **preferences** MMKV instance, so
  signing out does not discard the fact that you printed and measured a marker.
- `app/marker.tsx` — the setup flow, reachable from the Scan tab and from Settings.
- The Scan tab **will not offer a scan** until a reference is set up; it offers setup instead.
- 22 new tests, 125 total.

**The sheet is paper, so the checks are on the paper**

- Rendered at exactly **15 px/mm**, which makes the 40 mm tag exactly 600 px — six cells of 100.
  At 300 dpi it would be 472.44 px and the cells would not divide evenly, which is how a tag ends
  up a fraction of a millimetre off its declared size.
- It carries **its own 100 mm ruler**. If 100 mm does not measure 100 mm, the print was scaled and
  nothing else on the page can be trusted. That is the only place a "fit to page" can be caught.
- It carries an **ID-1 outline**, so a user can confirm their card really is 85.60 × 53.98 mm
  rather than some odd loyalty card.
- The generator asserts three things and fails rather than writing a bad sheet: nothing is printed
  inside the 5 mm quiet zone, the footer does not collide with the body, and **the detector finds
  exactly one marker, id 0, at 40 mm**. That last one is a round trip through the same library the
  backend will use.

**The invariant**

`markerFieldsForScan(reference)` is the single choke point: it returns `{ markerType, markerMm }`
or throws `MarkerNotSetError`. The UI prevents it ever throwing; it exists for the case where a
future screen forgets, because a scan submitted without a declared reference fails *silently* —
every metric rule NOT_ASSESSABLE, no error anywhere.

**Verification is a step, not advice.** The store only ever holds a reference the user has
confirmed measuring, which is why the invariant needs to check only that one exists.

**Done when:** the scan payload contains `marker_type` and `marker_mm`, and a scan cannot be
submitted without both.
**Verified:** lint 0 · tsc clean · 125 tests pass · prettier clean · `expo export` bundles with the
preview byte-identical. The sheet was rasterised at 381 dpi and OpenCV detected id 0 with all four
sides measuring 40.0000 mm. Payload `1011 0101 0011 0010`.
**Note:** the scan payload itself is assembled in Stage 4, where there is a scan to assemble. What
landed here is the reference, its persistence, and the guard the assembly must go through.

### Stage 4 · Guided capture and the four gates ✅ (device check pending)

**Requirements:** FR-01

**What shipped**

- `src/features/capture/gates.ts` — the four gates and their thresholds, pure. `evaluateGates` is
  a function of its metrics and nothing else.
- `src/features/capture/gate-evaluator.ts` — the seam. Server-measured today via
  `createServerGateEvaluator`; the simulation remains for tests and any screen without a camera;
  the native ArUco frame
  processor emits the same `FrameMetrics` later and **nothing above this file changes**
  (`03-implementation-plan.md` §P3.3 sanctions the ordering).
- `src/features/capture/gate-copy.ts` — one instruction per gate, exhaustive by type.
- `app/capture.tsx` — permission flow, preview, alignment overlay, four gate chips, shutter.
- `src/features/capture/capture-storage.ts` — captures written to the **document** directory.
- Dev panel gained the five gate simulations, one per failure mode.
- 29 new tests, 154 total.

**Three decisions worth knowing**

- **Tilt is three-valued.** It is the angle to the *marker's* plane, so with no marker in frame
  there is no angle. Reporting "fail" would tell the user to hold the phone flatter when the actual
  problem is that the reference is out of shot. It blocks capture exactly as a failure does; what
  differs is what the user is told. Same instinct as CLAUDE.md §3.3.
- **Mounting the live view is the activation.** `useGates` takes no `active` flag, because a
  toggled hook has a window between the flag flipping and the effect running where the previous
  session's metrics are still in state — and the worst case of that window is a shutter enabled by
  a stale all-green report.
- **Glare is strictly below 2%.** FR-01 says "below 2%", not "at most". It never decides a real
  frame, but the requirement is the specification.

**What the tests pin, and what they cannot**

Every threshold, every boundary (blur passes *at* 120, glare fails *at* 0.02, tilt passes *at* 25°),
that each simulated failure blocks its own gate and no other, and that all four instructions are
distinct. What no test here can reach: that the preview renders, that the permission prompt appears,
that `capturePhoto` returns, and that a file lands on disk. **Those need the device.**

**Done when:** the shutter is disabled while any gate fails, each failing gate shows its specific
instruction, and all four green enables capture.
**Verified:** lint 0 · tsc clean · 154 tests pass · prettier clean · `expo export --platform
android` bundles at 4.4 MB with vision-camera imported.
**Not verified:** anything requiring the camera. Needs the EAS dev client on a physical device —
see the device checklist below.

**Device checklist for this stage**

1. Scan tab → Start a scan. The permission prompt appears; grant it.
2. The preview renders and the gate chips settle to green over about two seconds (`converging`).
3. The shutter is visibly disabled until all four are green, and refuses to fire before then.
4. Settings → Simulated frame checks → each mode. Each shows its own instruction and re-disables
   the shutter.
5. Capture a photo. The thumbnail appears and the count increments.
6. "Discard last" removes it.
7. Deny the permission and reopen: the blocked-permission message appears rather than a black
   preview.

**Deferred, deliberately:** the stage brief said capture "opens a local scan". A scan record needs a
`profile`, which is Stage 5's context form, so what landed here is the photograph on disk plus
`listCaptures()` for Stage 6's queue to adopt. A capture abandoned by leaving the screen stays on
disk rather than being deleted — losing an inspector's photograph is the worse of the two failures —
and the queue owns that lifecycle from Stage 6.

### Stage 5 · Product context form ✅ (device check pending)

**Requirements:** FR-03

**What shipped**

- `src/features/scan-context/units.ts` — what a typed unit *means*. `gms`, `Gm`, `ltr`, `litre`,
  `cc`, `pcs` and the rest map onto prescribed symbols; `packet` maps onto nothing and is refused.
  An exact `L` survives as `L`, because the Second Schedule prescribes both `l` and `L` and
  lowercasing everything would narrow a declaration the law allows.
- **`qtyBasis` is derived from the unit, not asked.** Table-I is keyed on the declared quantity,
  which only exists for weight and volume; everything else is keyed on display-panel area. Asking
  twice creates a form that can be told `kg` and `length_area_or_number` in one submission, and the
  rules engine would then read the wrong table in silence. One question, one answer.
- The display-panel area is **conditionally mandatory**: required exactly when the unit puts the
  product in Table-II, because those height rules have no row to read without it. Missing it returns
  null from `buildProfile` rather than a profile whose metric rules would come back
  `NOT_ASSESSABLE` for a reason nobody typed.
- `src/features/scan-context/profile.ts` — `buildProfile` is total (null, never a `NaN` quantity),
  and `assertRuleRelevantFields` is the FR-03 choke point, the same shape as `markerFieldsForScan`.
- `src/features/scan-context/categories.ts` — 26 coded categories, searchable by the name people
  actually use (`atta`, `dal`, `charger`), including every code the fixture products use. The code
  is the contract; the label is translated.
- `src/store/draft.ts` — **the draft freezes the scale reference.** The saved reference is a device
  setting and Settings is two taps from this form: shoot against the 40 mm tag, switch to the ID-1
  card, submit, and the scan claims 85.6 mm. Every millimetre is then wrong by a factor of 2.14, the
  image genuinely contains a marker, and nothing downstream looks wrong. The draft carries what was
  in frame, and the form reads it from there rather than from the marker store.
- `src/features/scan-context/geo.ts` — `geoForScan` returns null for Mode B **whatever point it is
  handed**. Not a screen-level `if`: the location permission can already be granted from a previous
  Mode A session on the same phone, and the fixture account switch makes that sequence two taps
  long, so nothing would prompt and nothing would fail. A test hands it a coordinate and asserts the
  null.
- `app/scan-context.tsx` — the form, and its confirmation panel, which reads the three
  rule-changing fields back in the rules engine's terms. That is the only moment an operator can
  catch `180 g` typed as `180 kg` before a report is built on it.
- Capture's "Add product details" is live, the Scan tab offers an open draft before starting a new
  one, and `useWatch` replaces `watch()` so React Compiler still compiles the screen.

| Mode | Difference | Shipped as |
|---|---|---|
| A | Geo-tagged and timestamped at capture via expo-location, disclosed in-app | Disclosure card, then a fix on an explicit tap — never on mount. District field for the reporting rollups. |
| B | No location collected; pre-print artwork context rather than field inspection | No location UI at all, `geoForScan` null by construction, and the channel defaults to an online listing so Rule 6(10A) starts on. |

**Deferred, deliberately:** the OCR-prefill path. It needs extracted fields to prefill *from*, which
is Stage 7's confirmation sheet — prefilling before there is an extraction to prefill from would be
a mock talking to a mock. The form is already the shape that receives it.

> **Closed, 2026-09-13.** The form was already the shape that receives it, and that turned out to be
> the whole of the work. What was wrong in the three deferrals below was the assumed *source*: they
> all read "prefill" as "prefill from the pipeline's extraction", which only exists after
> processing, which is why each one deferred to the next stage. The read that fills this form
> happens **before** submit, over its own endpoint, on one downscaled photograph — so nothing here
> waits on Stage 7 or on an edit path. See `docs/decisions.md`, 2026-09-13.

**Done when:** net quantity value and unit, the imported flag and surface type are present on
every completed scan — all three change which rules apply.
**Verified:** lint 0 · tsc clean · 212 tests pass (58 new) · prettier clean · `expo export
--platform android` bundles at 4.6 MB. No new dependency: `react-hook-form` and `expo-location`
were both already approved and installed, and the installed dev client already carries
`ACCESS_FINE_LOCATION`, so no rebuild was needed.
**Not verified:** the location fix, the permission dialog, and Devanagari layout in the segmented
controls. Those need the device — see the checklist below.

**Device checklist for this stage**

1. Capture a photograph, then "Add product details". The form opens with the photo count and the
   reference it was shot against.
2. Type `gms` as the unit: the form says it is not a prescribed symbol and that it is recording `g`.
3. Type `packet`: the field goes red and lists the prescribed symbols.
4. Type `kg`: the note says Table I applies, and no display-panel area is asked for.
5. Type `N`: Table II, and the display-panel area appears as a required field with its reason.
6. Leave the area blank and submit: the scan is refused, not created without it.
7. Search the category field for `atta`, `dal` and `charger`. Each finds its category.
8. As the inspector: the location card appears, no dialog fires until you tap Attach, and the fix
   shows coordinates and an accuracy figure.
9. Deny location and continue: the scan is still created, without a coordinate.
10. Switch to the brand analyst and reopen the form: **no location card at all**, and the channel
    defaults to an online listing.
11. Submit as the analyst, then confirm the created panel shows no coordinate.
12. Switch to हिन्दी and walk the form: the segmented controls hold their labels without clipping.
13. Capture against the printed marker, then change the reference in Settings, then submit: the
    created scan must still report the reference the photographs were shot against.

### Stage 6 · Offline queue ✅ (device check pending)

**Requirements:** FR-04

**What shipped**

- `src/db/schema.ts` — two tables and **no outbox table.** There is exactly one pipeline per scan, so
  the scan's own `status` *is* the outbox: a row that is `queued` and due is work to do. A table of
  pending operations alongside a status column is two answers to one question, and the day they
  disagree the queue either skips an inspection or uploads one twice. Deliberate deviation from the
  stage brief, recorded in `decisions.md`.
- **A scan row exists from the first shutter press**, at `captured`, carrying the scale reference that
  was in frame. This replaced Stage 5's in-memory draft outright — the draft was a second source of
  truth for the same thing, and it was volatile: a force-close between the shutter and the context
  form lost the reference those photographs were measured against, which is unrecoverable. `captured`
  was in the documented state machine and now has a meaning.
- `src/features/queue/transitions.ts` — every decision, pure and tested: the legal-move table
  (`transition()` **throws** rather than clamping, so a `complete` scan cannot be walked back into
  `uploading`), the backoff (5 s doubling to a 5-minute cap, no jitter — one client, so a
  deterministic schedule is one that can be asserted), and `pickNext`, which works **one scan at a
  time** and refuses to start a second while one is `uploading`.
- `recoverInterrupted()` on launch. A process death mid-upload leaves a row claimed by nobody, and
  `pickNext` will not start a second while one is `uploading` — so without this, one force-close
  stalls every scan behind it, silently, which is exactly the failure FR-04's acceptance test is
  built to catch and exactly the one that reads as "the queue just stopped working".
- **The idempotency key is minted at capture and stored on the row**, not per attempt. That is what
  makes "start the pass over" a safe retry strategy: resuming a half-finished upload would need
  presigned URLs that have since expired, whereas re-requesting them with the same key gets fresh
  URLs for the same scan. Assets already up are skipped, so starting over does not redo the bytes.
- `Transport` grew an `upload` method, honoured by both implementations. It is not a JSON API call —
  a raw `PUT` of file bytes to object storage at a URL the API handed out — and routing it through
  `request` would mean an `Authorization` header leaking to a third-party host. The mock honours the
  **scenario switch**, so forcing Offline mid-queue exercises the real retry path.
- `app/queue.tsx` — per-item state in words, photographs uploaded out of total, attempt count, a
  countdown to the next attempt (a bare "waiting" is indistinguishable from "stuck", which is the
  whole question the user is asking), the error text on a failure, and manual retry. Status colours
  are deliberately **not** the verdict palette: an inspector must not learn to read the red that
  means "non-compliant pack" as the red that means "you lost signal".
- Submitting the context form is now **local and synchronous** — it attaches the profile and moves the
  scan `captured → queued`. It cannot fail for want of a signal, which is the point.
- The queue runs only while signed in: a signed-out app holds no tokens, so draining would burn five
  attempts per scan on nothing.

**No connectivity check, deliberately.** `expo-network` is not in the project and would need approval,
but it would add little: the only honest test of a connection is a request, and a failed request is
already a first-class path with a backoff behind it. What it would add is a faster wake-up when the
network returns, and `kick()` covers the cases the app can see.

**Done when:** airplane mode → capture 3 scans → force-close the app → restore network → reopen →
all 3 upload and complete. Run exactly that, on a real device.
**Verified:** lint 0 · tsc clean · 256 tests pass (44 new) · prettier clean · `expo export --platform
android` bundles at 4.8 MB. No new dependency; no rebuild needed, since `expo-sqlite` was already in
the dev client.
**Not verified:** everything the acceptance test covers. SQLite itself, the force-close, the real
upload. The SQL is thin precisely so that little judgement is left unwitnessed — see the checklist.

**Device checklist for this stage**

1. Take a photograph, leave capture, force-stop the app, reopen. The Scan tab says a scan is open with
   that photograph still attached.
2. Settings → Scale reference → change it. The open scan still reports the reference it was shot
   against, not the new one.
3. Turn on airplane mode. Complete three scans through the context form. Each one submits without an
   error — no spinner, no failure.
4. The Scan tab shows three waiting; the queue screen lists all three as "Waiting for a network".
5. Watch one attempt and fail: the countdown appears and the attempt count goes to 1.
6. **Force-close the app mid-backoff, reopen.** All three are still listed, and the counts are intact.
7. Turn airplane mode off. They upload **one at a time** — never two `Uploading` at once — and reach
   "Processing on the server".
8. Force-close during an upload, reopen: that scan returns to waiting and the queue keeps going rather
   than stalling.
9. Settings → Mock backend → Offline. Queue a scan and let it exhaust all five attempts: it goes to
   "Could not be uploaded" with the error text and a Retry button.
10. Set the scenario back to Everything works and tap Retry: the attempt count resets and it uploads.
11. Discard a failed scan. It leaves the queue, and the photograph is still in the captures directory.
12. In हिन्दी, walk the queue screen: every status reads in Hindi without clipping.

---

## 6. Phase C — The results path

This is the demo.

### Stage 7 · Processing and low-confidence confirmation ✅ (device check pending)

**Requirements:** FR-06

**What shipped**

- `src/features/processing/stages.ts` — the eight server stages with the architecture's **own** names
  and S-numbers (S2–S8, S10; S1 is on the device and S9 is not on this path). Not friendly
  inventions: when a demo stalls, "stuck on S4 OCR" is a debuggable sentence and "still working…"
  is not.
- **An unknown stage renders as unknown.** `Scan.pipelineStage` is new on the domain type and is null
  when the backend publishes nothing; `pipelineProgress` then returns **null rather than 0**, and the
  screen says so in words. A bar derived from elapsed time looks identical whether the worker is
  advancing or wedged, and the wedged case is the only one the screen is needed for.
- `src/features/processing/confidence.ts` — and the load-bearing piece of the whole stage,
  **`verdictsAreProvisional`**. The rules engine is deterministic and citable, so whatever it is given
  it will defend: fed `249.00` misread as `219.00` it produces a confident FAIL, with a gazette
  citation, against a pack that complies — CLAUDE.md §3.4's named failure mode. So an unconfirmed field
  does not merely raise a prompt, it makes every verdict on that scan provisional, and the scan screen
  labels the summary accordingly with the sheet as its primary action.
- A field already confirmed by a human is **never re-asked** — `source === 'human'` is the record, and
  re-asking would also silently overwrite the correction with the machine's value.
- Lowest confidence first in the sheet: the worst read is the likeliest to be wrong, and it belongs in
  front of someone who may answer only one before putting the phone away.
- `src/features/processing/crop.ts` — the crop is a **transform, not a file**.
  `expo-image-manipulator` would write a JPEG per field, asynchronously, to be cleaned up later; a
  scaled and offset `<Image>` in an `overflow: hidden` box shows the same pixels synchronously and
  works identically on a bundled fixture and a presigned URL. The geometry is the same arithmetic
  Stage 8's tappable overlay needs, so it is one module and one test suite — boxes that sit *near*
  their text read as a rendering bug long before anyone suspects maths.
- `src/api/asset-source.ts` — so **no screen imports a fixture.** The mock's rectified image is a
  bundled PNG behind `fixture://`; the real one is an HTTPS URL. At Stage 13 the fixture branch is
  deleted and nothing above it changes.
- `src/features/processing/degradation.ts` — §11's table as named, tested functions rather than an `if`
  in a screen. `no_marker` and `reduced_extraction` are **degraded but final**: those results are
  complete and correctly labelled, with metric rules already `NOT_ASSESSABLE`. Only an unanswered
  question makes a verdict provisional.
- The mock gained the **`llm-unavailable`** path, which had no implementation: the LLM-sourced
  extractions are now *absent* rather than down-rated, because down-rating them would send them to the
  confirmation sheet as misreads when they were never read at all. Scans also carry the scenario's
  `issues`, so a degraded run cannot show a clean header above a page of `NOT_ASSESSABLE` rows.
- **The queue now learns when a scan finishes.** `runner.ts` polls `processing` rows and moves the local
  row to `complete`. Without it Stage 6 handed a scan to the server and never heard back: the row sat
  at `processing` forever and the pending count never cleared. A failed poll costs no attempt — the
  server is working whether this phone can reach it or not.
- All four verdict counts are shown on the summary, **including zeroes**. A summary that hides an empty
  group teaches the reader that the groups it shows are the only ones there are.

**Deferred, deliberately:** the OCR-prefill of the context form, carried over from Stage 5. It needs an
extraction to prefill *from*, which now exists — but prefilling a form that is filled in *before*
processing would mean re-opening a submitted scan's context, which is Stage 8's edit path, not this one.

> **Closed, 2026-09-13**, and not by an edit path: the form is filled *before* it is submitted, from
> its own read of the photograph. The confirmation idea built here is what it reuses — a
> machine-supplied value is shown with the text it was read from and affirmed by a person before it
> can carry a verdict — but applied to the profile rather than to an extraction.

**Done when:** the deliberately blurred MRP fixture triggers the sheet, the correction is
recorded with `source=human`, and the verdict recomputes.
**Verified:** lint 0 · tsc clean · 308 tests pass (52 new) · prettier clean · `expo export --platform
android` bundles at 4.8 MB. The full acceptance path is tested end to end against the mock transport —
scenario, findings, sheet, recompute — because each of those four could be individually right while the
path is broken. No new dependency.
**Not verified:** that the crops land on the right text on a real screen, and Devanagari layout in the
sheet. Both need the device.

**Device checklist for this stage**

1. Complete a scan and open it from the queue. The stage list shows S2–S10 with the current one
   emphasised, advancing over about four seconds.
2. Once complete: the four verdict counts, the rule pack version, and a disabled "View findings".
3. Settings → Mock backend → **Low-confidence field**. Open a completed scan: the provisional banner
   appears *above* the counts, and "Confirm 1 field" is the primary action.
4. Open the sheet. The MRP crop shows `MRP ₹ 249.00` — readable, with context either side, not a
   tight cut around the digits.
5. Edit it to `MRP ₹ 249.00 (incl. of all taxes)` and confirm. The recompute banner appears, the list
   empties, and going back shows the summary **without** the provisional banner.
6. Reopen the sheet: it says everything is confirmed rather than asking again.
7. Clear the field entirely: the confirm button disables rather than sending a deletion.
8. Settings → Mock backend → **No marker detected**. A completed scan shows the no-marker banner, and
   the Not assessable count is greater than zero while Pass and Fail are not both zero.
9. Settings → Mock backend → **LLM unavailable**. The reduced-extraction banner appears, and the
   confirmation sheet is *not* offered — the LLM fields are absent, not misread.
10. Settings → Mock backend → **Server error**, then open a scan: an error state, not a blank screen.
11. In हिन्दी: the stage labels and the sheet read in Hindi without clipping.
12. Force-close while a scan is processing and reopen: the queue picks the poll back up and the row
    reaches Complete on its own.

### Stage 8 · Findings viewer ✅ (device check pending)

**Requirements:** FR-05

| Mode | Difference |
|---|---|
| A | Evidence panel: image hash, findings hash, capture time and location. Editing locked after issue |
| B | A remediation suggestion per failing finding — what to change on the artwork |

**What shipped**

- `src/features/findings/viewport.ts` — pan, zoom and the arithmetic that decides **which finding a
  tap opens.** Three coordinate spaces are named once, at the top of the file, so the rest of the
  stage stops guessing which one it is in: *image* pixels (where every `BBox` lives), *canvas* (image
  pixels × the fit scale, where the `<Image>` and the SVG are laid out) and *viewport* (the pane, where
  taps arrive). The outline is placed by `boxOnCanvas` and the tap resolved by `viewportToImage` plus
  `hitTest` — **one transform, inverted**, because two near-identical sets of sums would look right
  and open the wrong rule. The round-trip is tested over every region of the fixture label at the real
  20 px/mm.
- **Four groups, always four, even when three are empty.** `groupFindings` returns one entry per
  verdict in `VERDICT_DISPLAY_ORDER` and the screen renders an empty one as its heading plus "None on
  this pack." A list that hides empty groups teaches its reader that the groups shown are the only
  ones that exist, and the first casualty is BORDERLINE. There is deliberately **no** helper in the
  module that returns "problems" or "issues" — that merge is CLAUDE.md §3.4's named failure mode, and
  it gets added by someone who only wanted a badge count.
- **A BORDERLINE prints its band.** `detailFor` carries `band` only on a BORDERLINE (a band beside a
  FAIL reads as "we are not sure" next to a verdict that says we are), and when a BORDERLINE arrives
  with `band: null` it sets `bandMissing` so the screen states what the verdict means rather than
  rendering a gap. `domain/finding.ts` already said it: a BORDERLINE without its band is an
  unexplained accusation.
- **The smallest box wins a tap, and a tie goes to the failure.** Regions genuinely nest — the
  clear-space rule's box surrounds the net-quantity declaration it is measured against — so `hitTest`
  picks by area, and a tap on the numerals selects the numerals rather than the margin around them.
  Where two findings share one box exactly, as the MRP region's PASS and FAIL do, the tie is broken by
  `findingsInDisplayOrder`, which is the same order the list renders in. Relying on paint order would
  have made the answer depend on the order the server serialised its rows.
- `findingsMissingAnchor` — **a FAIL or BORDERLINE with no region is reported, not hidden.** FR-05's
  acceptance promises every one of them has a box, so one without is a contract violation; and it
  would otherwise be invisible, listed below while the label looked complete.
- **A 10 mm scale bar, and none at all without a marker.** `scaleBarLength` returns null when
  `pxPerMm` is null, and the pane then draws nothing. A ruler over an image of unknown scale would
  assert the one thing the product refuses to guess (CLAUDE.md §3.3) — and on the happy path the bar
  is the most direct visual evidence that the rectification is real.
- **Selecting from the image selects; selecting from the list also moves the view.** Someone who
  tapped a box already knows where it is, and jumping the zoom under their finger is disorienting.
  Someone who tapped a row does not know where on the pack the rule applies, so `focusOn` centring it
  *is* the highlight — an outline drawn around text five units high is a smudge, not a highlight.
- **No gesture can lose the label.** Pinch and pan both end in `clampOffset`, which keeps the image
  covering the pane on any axis where it is larger and centred on any axis where it is smaller. A
  consequence worth knowing before it is filed as a bug: a box near an edge lands fully visible but
  **off-centre**, because centring it would expose the label's own edge. `crop.ts` makes the same
  trade with its padding.
- `src/components/findings-overlay.tsx` — presentational, memoised, and weighted by verdict: FAIL and
  BORDERLINE solid, NOT_ASSESSABLE dashed (nothing was measured inside it, and a solid box would imply
  something was), PASS thin and half-transparent so it is present and tappable without competing.
  Thirteen equal outlines on one label is a thicket, and the first thing lost in a thicket is the two
  boxes someone needs.
- `src/features/findings/evidence.ts` — Mode A's panel, with one refusal: **the rectified image's hash
  is never offered as the image hash.** `01-architecture.md` §10 records the SHA-256 of the *raw*
  upload; the rectified image is derived by a homography, so its hash verifies a computation rather
  than a photograph, and a chain built on it would be unfalsifiable while looking exactly as
  reassuring. The hero fixture gained a `raw` asset so the honest value exists to show.
- **Editing locks after issue, and only after issue.** `editingLocked` is Mode A plus
  `reportIssuedAt !== null`. The reason is not that an inspector cannot be trusted: a report already
  in someone's hands embeds a findings hash, and a field edited afterwards would leave that document
  disagreeing with its own source with no trace of which came first. Locking is about *editing* only —
  a locked scan still shows every finding, every citation and the whole evidence panel.
- Remediation is **Mode B only**, gated on mode rather than on the field being present, so a backend
  that sends it to both cannot put design advice into an inspection record.
- The provisional banner from Stage 7 is repeated here, above the groups, because this is the screen
  where the verdicts are actually read.
- A `__DEV__` "Sample inspection" panel in Settings opens the hero fixture's findings directly. The
  viewer was otherwise reachable only by completing a whole scan, and the hero scan is also the one
  fixture with a report issued over it — so it is the only way to see the Mode A lock.

**Deferred, deliberately:** the OCR-prefill of the context form, carried forward from Stages 5 and 7
again. Re-opening a submitted scan's context is an edit path, and Mode A's editing rules only became
concrete in this stage — a prefill built before them would have had to be rebuilt around
`editingLocked`. It belongs with Stage 10's history, where re-opening a past scan is the point.

> **Closed, 2026-09-13.** `editingLocked` never came into it: the prefill fills a form for a scan
> that does not exist yet, so there is nothing locked to edit. The three deferrals were all reasoning
> about a *post-processing* prefill, which remains unbuilt and is now optional — the field a user
> would have gone back to correct is filled before they submit.

**Done when:** every FAIL and BORDERLINE has a bounding box that highlights on tap, and the
citation text is visible without leaving the screen.
**Verified:** lint 0 · tsc clean · 381 tests pass (73 new) · prettier clean · `expo export --platform
android` bundles at 4.8 MB. The transform is tested against its own inverse over every region of the
fixture label, and the FR-05 acceptance is asserted directly: every FAIL and BORDERLINE in the fixture
has a box, and a tap at its centre resolves to a finding on that box. No new dependency —
`react-native-svg` and `react-native-gesture-handler` were both already installed.
**Not verified:** that a pinch feels smooth. The transform is applied on the JS thread
(`.runOnJS(true)` on every gesture) so that the arithmetic stays in one tested pure module instead of
being duplicated as worklets; the overlay is memoised on the canvas so a drag restyles one view rather
than thirteen rectangles, but whether that is enough on a mid-range phone is a device question. Also
unverified: that the outlines land on the right text on real glass, and Devanagari in the detail panel.

**Device checklist for this stage**

1. Complete a scan, open it, tap **View findings**. The label appears with outlines over it and a
   `10 mm` scale bar bottom-left. Check the bar against a ruler held to the screen — it will not be
   10 real millimetres, but it must be the same length as 10 mm of the label's own text height.
2. Four group headings, in order: Failures, Borderline, Not assessable, Passed — each with a count,
   and **none of them missing** even at zero.
3. Tap the Borderline row. The detail panel shows the uncertainty band
   (`3.2 mm from a 4.0 mm margin, ±1.0 mm`), not a bare verdict, and the label moves to centre that
   region.
4. Tap a Failures row. Required, Observed and the citation verbatim are all visible **without
   scrolling the screen** — only the panel itself may scroll.
5. Tap the outline over `MRP ₹ 249.00` on the label directly. It selects the **FAIL**, not the PASS
   that shares the same box.
6. Tap bare label away from any outline: the selection clears.
7. Pinch to zoom in and drag around. Outlines stay on their text at every zoom, and the outline
   thickness stays roughly constant rather than growing into bars.
8. Drag hard in one direction repeatedly. The label cannot be pushed out of the pane; a **Fit**
   button appears once the view has moved and returns it.
9. Tap the thin fine-print region at the opening zoom — it is about five units tall on screen and must
   still be tappable (that is the tap slop working).
10. Settings → Mock backend → **No marker detected**, then open a scan's findings: every size rule is
    in Not assessable with its box still drawn, and **the scale bar is gone**.
11. Settings → Mock backend → **Low-confidence field**: the provisional banner is above the groups and
    "Confirm 1 field" opens the sheet from here.
12. Sign in as the **enforcement** fixture account. The evidence panel appears at the bottom: raw image
    SHA-256 in 8-character groups, findings SHA-256, capture time, location with its accuracy, district.
13. Sign in as the **industry** account: no evidence panel, and a failing finding shows "What to
    change". In enforcement it does not.
14. Settings → **Sample inspection** → Open sample findings, signed in as enforcement. The record is
    closed: the "This record is closed" banner appears and the confirm button is disabled.
15. In हिन्दी: group headings, Required/Observed/Legal source and the detail panel read in Hindi
    without clipping. The citation itself stays in English — it is verbatim legal text.
16. Rotate the phone. The view re-fits rather than leaving the label pressed off one edge.

### Stage 9 · Report export and share ✅ (device check pending)

**Requirements:** FR-08

**What shipped**

- **The stage's one refusal: provisional verdicts block a report, they do not warn.**
  `features/reports/eligibility.ts`. Stage 7 established that an unconfirmed low-confidence field
  makes every verdict provisional, and Stage 8's findings screen says so in a banner. A banner is
  enough on a screen — the reader is holding the phone and the next scan replaces it. A PDF is not a
  screen: it leaves the device, embeds a findings hash, quotes gazette citations beside a
  measurement, and **cannot be retracted from an inbox**. A report over a misread MRP is CLAUDE.md
  §3.4's failure mode made permanent and distributable, so the screen refuses, explains why, and
  offers the confirmation sheet as the fix.
- **A degraded run is not blocked.** No marker, or an unavailable LLM, produce complete and correctly
  labelled results, and `01-architecture.md` §11 says such a report is issued **flagged** rather than
  withheld. Withholding it would leave an inspector with no record of an inspection they actually
  made. So those surface as banners that travel with the document. That is Stage 7's
  `isDegradedButFinal` distinction doing its job: an unanswered question blocks, a stated limitation
  does not.
- **Generation is asynchronous, and the app polls.** `Report` gained `status`, `formats`,
  `requestedAt`, `generatedAt` and `error`. A POST that blocked until an annotated PDF was rendered
  would tie a share button to a render that takes seconds and can fail, with nothing to show either
  way. `hasTimedOut` exists because an endless spinner is where someone decides the app is broken and
  asks again — which renders the same document twice.
- **`missingFormats`.** A report can come back `ready` with the PDF and not the DOCX. Without this the
  screen shows one share button and looks entirely correct, and the user never learns the document
  they asked for does not exist.
- `scripts/make-sample-report.py` — **the mock writes real files.** A genuine PDF 1.4 carrying the
  annotated label as an embedded JPEG, the findings table and both hashes; and a genuine OOXML
  package whose findings table is a real `<w:tbl>`, not a picture of one (FR-27). A mock that
  resolved with a plausible URI would let "both files open in an external viewer" pass in testing and
  fail in front of a judge. The generator imports the label script for its region geometry and reads
  the hashes out of `hero-scan.ts`, so a sample report cannot quote a different findings hash from
  the one the evidence panel shows — if the regex stops matching, it fails rather than emitting a lie.
- Base64 rather than bundled binaries, because bundling a `.pdf` needs a `metro.config.js` asset
  extension and approval (flag 13). `File.write(…, { encoding: 'base64' })` decodes natively, so
  nothing is decoded in JS.
- `Transport.download` — the mirror of Stage 6's `upload`, and separate from `request` for the same
  reasons: file bytes rather than a JSON envelope, a presigned URL on a third-party host, and our
  `Authorization` header must not travel there. It exists because **a share sheet needs a file**:
  handing Android an https URL produces an intent most apps cannot open, and the user sees a share
  that silently does nothing.
- **The filename is not cosmetic.** `anupalan-<product>-<date>-<id>.<ext>`. A report lands in someone's
  WhatsApp next to everything else they were sent that week, and `report.pdf` is indistinguishable
  from every other report ever generated. The scan-id tail is what stops two scans of the same pack on
  the same day overwriting each other in a downloads folder — that failure is silent and the file lost
  is evidence. A Devanagari product name reduces to nothing under the ASCII-safe sanitiser and falls
  back to a generic segment, because transliterating would give a name neither readable to a Hindi
  speaker nor accurate to anyone else.
- JSON is a real report format (FR-27) and is deliberately **not** offered for sharing. Its home is the
  API; in a phone's share sheet it invites sending a machine artefact to a trader who cannot read it.
- The report screen is reachable **only from the findings screen**. Issuing a report is a decision
  taken after reading the findings, and a shortcut from the summary would let someone send a document
  over verdicts they never opened.
- A `report-failed` mock scenario, beyond §11's table: report generation is S10 and can fail on its
  own, and the screen has to handle a `failed` report whether or not §11 lists it.

**Done when:** both files share out of the app and open in an external viewer.
**Verified:** lint 0 · tsc clean · 474 tests pass (49 new) · prettier clean · `expo export --platform
android` bundles at 5.0 MB. The sample files are asserted to be genuine: `%PDF-` header and `%%EOF`
trailer, a `PK\x03\x04` ZIP containing `word/document.xml`, `/DCTDecode` for the embedded image, and
both hashes present in the PDF's bytes. No new dependency — `expo-sharing` and `expo-file-system` were
already installed.
**Not verified:** that the PDF opens in a viewer and the DOCX opens in Word with an editable table.
Nothing in a test runner can open either, which is what items 6–8 of the checklist are for.

**Device checklist for this stage**

1. From a completed scan, open the findings, scroll to the bottom and tap **Generate the report**.
2. With the **Low-confidence field** scenario on, the screen refuses instead of offering a button:
   "Confirm the low-confidence fields first", with a button that goes to the sheet. Confirm the field,
   come back, and the refusal is gone.
3. Both PDF and Word are selected by default. Deselecting both disables Generate.
4. Generate: a pending state for a few seconds, then "Report ready" with two files, their sizes and
   a filename per file. The filename contains the product, the date and a short id.
5. The preview above shows all four verdict counts, both hashes in 8-character groups, and the rule
   pack version — before anything is shared.
6. **Share the PDF.** The system share sheet opens. Send it to yourself and open it: one A4 page with
   the annotated label top-right, the findings table colour-coded by verdict, both hashes and the
   advisory disclaimer.
7. **Share the DOCX** and open it in Word, Google Docs or WPS. The findings table must be a **real
   table** you can click into and edit — not a picture (FR-27).
8. Share the same file twice. The second share works and does not create a duplicate copy.
9. Settings → Mock backend → **Report generation fails**, then generate: an error state with the
   server's reason and a button to try again, not a spinner.
10. Settings → Mock backend → **Offline**, then tap Share: the share fails with an explanation, and
    the report itself is still listed.
11. Settings → Mock backend → **No marker detected**: the report is still offered, with the no-marker
    banner above the preview. It must not be blocked.
12. Signed in as **enforcement**, before generating: the "Issuing a report closes this record" notice
    appears. Generate, then go back to the findings — the record is now closed and the confirm button
    is disabled.
13. In हिन्दी: the format names, the refusal copy and the buttons read in Hindi without clipping.

### Stage 10 · History and search ✅ (device check pending)

**Requirements:** FR-09

| Mode | Difference |
|---|---|
| A | District filter; inspection framing. Reached through the **Inspections** tab |
| B | No location filter, since none is collected. Reached through **History** |

**What shipped**

- **One verdict per question, and `matchesVerdict` reads exactly one number.** This is the stage, and
  it is the reason the filter is a module rather than a `useState` object in a screen. A verdict
  filter is the easiest place in the whole app to collapse BORDERLINE into FAIL, and the collapse
  would not look like a bug: a "problems" filter returning `fail > 0 || borderline > 0` gives a
  longer, more impressive list in which every scan really does have something on it. What it destroys
  is the distinction the product rests on — an inspector who filters for failures and is shown a
  compliant pack whose measurement merely sat inside the uncertainty band has been handed CLAUDE.md
  §3.4's failure mode by the search box. So the filter is **single-select**, the predicate is a switch
  over one field of `FindingsSummary`, and there is deliberately no helper that takes a set of
  verdicts.
- **The seeded fixture had no scan that could catch that collapse, and now does.** Every borderline in
  the 220-scan set sat beside a failure, so a merged filter would have returned an identical list and
  passed every test written against the data. `buildSummary` gained a borderline-only bucket. The
  hero fixture's doc comment already made this argument for the findings screen; it had not been
  carried through to the history set.
- **Two fixture inconsistencies the Mode B test surfaced, both on the hero scan.** Its `orgId` was the
  industry org while its `userId` was the enforcement inspector — a cross-org row CLAUDE.md §3.7 makes
  impossible — and it carried a `geo` and a `district` that `01-architecture.md` §10 says Mode B never
  collects, contradicting `geoForScan`, which the app enforces at capture. It is now an enforcement
  inspection, which is what everything else about it already said.
- **One list, two tabs.** Mode A reaches it through Inspections and Mode B through History; building
  it twice would have meant two places to forget that Mode B has no district filter. `toQuery` drops
  `district` for Mode B **at the point the request is built**, so a future screen that forgets to hide
  the control still cannot send one.
- `FlatList` with `getItemLayout` over a fixed `SCAN_ROW_HEIGHT` exported by the row, so the list
  never measures a row. Without it two hundred rows are measured on every scroll and the stutter is
  impossible to attribute afterwards.
- **Every row shows all four verdict counts, including the zeroes**, rather than a headline verdict. A
  single badge would need a rule for ranking the four, and any such rule is one step from "this scan
  failed" appearing on a pack whose only mark was a BORDERLINE.
- **Two different empty states.** "No scans yet" and "nothing matches those filters" look the same and
  mean opposite things; only one of them has an action. The filter bar also always states how many
  filters are narrowing the list, because a list showing a fraction of the data and looking like all
  of it is how someone concludes a scan was lost and re-photographs a pack.
- Date presets — Today, Last 7 days, Last 30 days — computed from a `now` that is **passed in**, never
  `Date.now()` in a render. `toIsoDate` builds a local calendar date rather than slicing an ISO
  string, which would give the UTC day and file every evening scan in India under tomorrow. A
  hand-picked range reports as `custom` rather than lighting up a preset chip the user did not choose.
- A reversed date range is **put the right way round**, not answered with an empty list: someone who
  picked the dates in the wrong order asked a clear question.
- The mock's `to` filter compares against the end of that day. Comparing a `YYYY-MM-DD` against a full
  timestamp would silently drop every scan taken after midnight on the last day of the range — the
  most recent ones.

**Deferred, deliberately:** Mode B's "filter by brand and SKU". `ProductProfile` has neither field —
there is a `name` and, on `Product`, a `gtin`. Inventing a brand and an SKU on the product model to
satisfy a filter would be the wrong order of work; SKUs become real in Stage 12's bulk listing check,
which is where the model should gain them. Mode B gets the product filter and free-text search in the
meantime. See flag 25.

**Done when:** filtering 200 seeded scans by `verdict=FAIL` returns only scans with at least one
FAIL, within 500 ms. Measure it and record the number.
**Measured:** **0.020 ms per pass** — filtering and paging all 220 seeded scans by `verdict=FAIL`,
mean of 200 passes after a warm-up, on the development machine through the mock transport. The test
prints it (`__tests__/history.test.ts`) so the number in this document is one that was actually taken;
it is timed in bulk because a single pass lands under the millisecond clock and would record 0 ms.
That is the filter cost only — what remains on a device is the list render, which `getItemLayout`
exists to bound and which item 2 of the checklist measures.
**Verified:** lint 0 · tsc clean · 474 tests pass (44 new) · prettier clean · `expo export --platform
android` bundles at 5.0 MB. No new dependency.
**Not verified:** scroll smoothness through 220 rows on real hardware, and Devanagari in the filter
chips.

**Device checklist for this stage**

1. Sign in as **industry** and open **History**. The list fills with past scans, newest first, each
   showing four verdict counts.
2. Scroll to the bottom fast. It should stay smooth and keep loading pages; time from tapping the tab
   to the first rows appearing — that is the number FR-09 cares about on hardware.
3. Filters → **Fail**. Every row shown has a non-zero count in the first (red) position.
4. Filters → **Borderline**. The list changes, and it is *not* the same list as Fail — at least one
   scan appears here that did not appear there. This is the acceptance test for the whole stage.
5. Tapping the selected verdict chip again clears it; one tap undoes one tap.
6. Type a product name into Search: the list narrows. Clear it: the list returns.
7. Filters → **Last 7 days**, then **Today**. The counts change and the chip that is selected is the
   one you tapped.
8. Set filters that match nothing (a product plus a date range): "Nothing matches those filters", with
   a Clear button — not the "No scans yet" empty state.
9. The filter button reads "Filters (2)" when two are active, so a narrowed list never looks like the
   whole archive.
10. Sign in as **enforcement** and open **Inspections**: the same list, plus a **District** filter.
    Filter by Nadia and check every row shows that district.
11. Back in industry mode: **there is no District filter at all.**
12. Tap any row: it opens that scan.
13. In हिन्दी: the filter chips, "Today"/"Yesterday" and the empty states read in Hindi without
    clipping.

---

## 7. Phase D — Assistant, bulk, hardening

Droppable from the bottom if the timeline compresses.

### Stage 11 · Sahayak chat and BIS applicability ✅ (device check pending)

**Requirements:** FR-07

| Mode | Difference |
|---|---|
| A · B | None. The assistant is the same in both modes — an inspector and a brand ask the same questions of the same public corpus, and neither gets a different answer |

**What shipped**

- **A citation the app cannot place on an official host is not shown, and an answer left with no
  citation is not shown as an answer.** This is the stage. Everything else in a Sahayak response is
  prose a reader can judge; a chip reading "Compulsory Registration Scheme — list of products under
  mandatory registration" is an assertion that such a page exists and says what the answer just said,
  and it is the part nobody checks. A model that invents one has not produced a worse answer, it has
  produced a **more convincing** one. The client cannot verify that a page says what an answer claims
  — only the retrieval layer can — but it can refuse a citation pointing somewhere the corpus could
  never have come from, which is what a fabricated one looks like: a plausible title over a `.com`
  reseller. So `OFFICIAL_HOSTS` gates every chip, and an `answered` response with nothing left after
  that filter is **presented as not-found with its prose suppressed entirely**. An uncited answer
  about whether a product needs BIS registration is a guess, and the whole proposition is that this
  app does not guess.
- **The fixture set now contains a fabricated citation on purpose.** `ans_fabricated` claims
  `answered` and cites `standards-india-handbook.com` — real-sounding title, https, a section
  reference. Without it the guard would have been asserted rather than proved, since every other
  fixture cites a genuine BIS page and would pass whether the filter ran or not. The test that catches
  it fails loudly if anyone "fixes" the host or widens the allowlist to make one chip render.
- **`unclear` is not `no`.** CLAUDE.md §3.4's collapse running in the opposite direction, and doing
  more damage. `qcoApplicable: 'unclear'` means the public Quality Control Orders and product lists do
  not *settle* whether a product needs certification; rendering that as "not required" tells a brand
  they may ship uncertified goods on an authority this tool never established. Unlike a wrong FAIL,
  nobody disputes it — it says what the reader hoped. So there are three stances over three QCO
  values, `isConclusive` gates every affirmative row on the screen (the certification route, the
  standards list, the heading), and there is deliberately no helper mapping `QcoApplicable` to a
  boolean. `scheme: 'none'` on an unclear record is the *absence* of a claim, not the claim "no route
  applies", and the row is hidden rather than shown.
- **IS numbers stay candidates until the stance is settled.** They are `candidateIsNumbers` in the
  domain type for a reason. A list of IS numbers under a heading like "standards you must certify
  against" reads as settled to anyone skimming, and on an `unclear` record nothing is settled.
- **A record that mandates certification and names no route is surfaced as incomplete**, not rendered
  with the scheme row quietly omitted — the same reasoning as `missingFormats` in Stage 9. A screen
  that simply leaves it out looks complete while withholding the one fact the user came for.
- **The freshness stamp is not a footer detail.** Quality Control Orders are notified and amended by
  gazette notification on no fixed schedule, so an answer can be impeccably retrieved, correctly cited
  and wrong. It is the difference between "BIS registration is not required for this product" and "as
  of 30 August, the public lists did not require it", and only the second is supportable. `unknown` is
  a real tier rather than an error case: an answer whose `asOf` will not parse has no provenance in
  time, which is worse than an old one, and it must not fall through to `fresh`. A stamp in the
  *future* is `unknown` too — that is a clock disagreement, not a brand-new corpus.
- **Confidence is shown only on a genuine answer.** Both refusals carry `confidence: 0` — correctly,
  there is no claim to be confident about — and "0%" printed beside a deliberate, correct refusal
  reads as a broken answer rather than a boundary held on purpose.
- **Source chips are labelled by what they are claiming.** "Sources" under an answer, "Where to check"
  under a refusal. Not cosmetic: the not-found response's whole value is the official page it points
  at, and labelling both "Sources" would make a refusal read as a cited *finding of absence*, which is
  a stronger claim than "I could not find it".
- **The withheld count is shown rather than swallowed.** An answer that quietly loses two of three
  chips looks thinner than it claimed and gives nobody a reason to investigate the model that produced
  them.
- **One question at a time**, and the reason is ordering rather than politeness. Two overlapping asks
  can complete out of order, and a transcript where the second question's answer sits under the first
  is worse than a disabled button: nothing on screen reveals it, and the citations under the wrong
  question still look official. `inFlight` is read from the mutation rather than stored, so there is no
  second copy of it to be wrong.
- **A failed question stays in the transcript as a failure.** One that vanishes when the network drops
  looks like one that was never asked, so the user retypes it — which on a flaky link is how one
  question becomes four billed requests. Retry re-sends the question, found by walking back to the
  nearest question turn.
- **An answer turn is stamped `receivedAt` when it arrives**, and the freshness tier is computed
  against that rather than `Date.now()` in a render. React's purity rule forbids the latter — the lint
  rule caught it, exactly as `features/history/presets` had warned — and an answer already on screen
  should not silently re-grade its own sources on an incidental re-render. The BIS screen uses the
  query's `dataUpdatedAt`, the same clock Stage 9's report screen polls with.
- **The transcript is local UI state, not server state, and is not persisted.** It has no id, nothing
  fetches or invalidates it, and each answer is immutable on arrival — which is what CLAUDE.md §5 means
  by local. Caching answers by question would actively break it: asking the same question twice is a
  thing people do when they doubt the first answer, and a cache hit would replay it. Nothing is
  restored on a warm start either — a month-old answer about a since-amended QCO, under a freshness
  stamp nobody re-reads, is worse than an empty chat.
- **The mock's answer routing was rewritten.** It scored word overlap on any word over four
  characters, so a question opening "Which…" matched the first fixture whose question also did — which
  made the priced-content refusal and the fabricated citation, the two cases a demo most needs, two of
  the hardest to reach. Explicit keywords now, refusal checked first, falling back to not-found, which
  is the honest default for an assistant over a finite corpus.
- **`POST /bis/applicability` no longer defaults to the atta profile** for an unrecognised product. It
  answered a question about one product with a different product's applicability — the exact confident
  wrong clearance the stance logic exists to prevent. A scan whose profile was typed in has no
  `productId`, and the screen renders that as "no applicability record" without a round trip.
- Hindi is filled for the whole assistant, both blocks, rather than stubbed. The two refusals are the
  responses whose wording carries the entire value, and a Hindi-speaking user handed the English
  refusal has received the least useful version of the most important answer.

**Deferred, deliberately:** nothing in the stage scope. See flag 28 for the two applicability branches
that have no fixture reachable from a scan.

**Done when:** the unanswerable fixture returns the explicit not-found response with an official
link, and never a fabricated citation.
**Met:** asking "Is there a QCO covering bamboo furniture?" returns `outcome: 'not_found'`, prose
opening "Not found in official sources", one citation on `bis.gov.in`, and zero withheld. Separately,
the fabricated fixture is caught: `outcome: 'answered'` in, `presentationFor` out as `not_found`,
`showsModelText` false, zero showable citations. Both are pinned in `__tests__/sahayak.test.ts`.
**Verified:** lint 0 · tsc clean · 532 tests pass (58 new) · prettier clean. One dependency moved from
installed-but-unused to used: `expo-web-browser` — see the approved table in §2.
**Not verified:** whether a source chip actually opens Chrome Custom Tabs and dismisses back to the
transcript, the keyboard-avoiding composer on a real keyboard, and Devanagari line lengths in the
answer cards — Hindi answer bodies are long paragraphs and this is the first screen to render one.

**Device checklist for this stage**

1. Open the **Sahayak** tab. Three suggested questions; tap the first — an answer appears with source
   chips under it.
2. Tap a source chip. Chrome Custom Tabs opens the BIS page **in-app**; the back gesture returns to
   the answer you were reading, not to the tab bar.
3. Ask "What is the tensile strength limit in IS 1786?". The answer is the refusal, headed "Cannot
   quote a standard", pointing at the purchase route — **and there is no confidence percentage on it.**
4. Ask "Is there a QCO covering bamboo furniture?". "Not found in official sources", with the chips
   headed **"Where to check"** rather than "Sources". This is the stage's acceptance test.
5. Ask "Which QCO covers stainless steel cookware?". A red "Answer withheld — no official source"
   banner, the not-found copy, and **no answer paragraph at all**. The fabricated citation is not
   rendered anywhere on the card. This is the other half of the acceptance test.
6. Switch to **हिन्दी** in Settings and ask about a phone charger. The answer comes back in Hindi.
   Check the long paragraph does not clip or overflow its card.
7. Turn on Airplane mode and ask anything. The question **stays** in the transcript with an error and
   a Retry; Retry re-sends that question once you are back online.
8. Type past 500 characters. The field shows the cap message and the Ask button is disabled.
9. Tap Ask twice quickly. Only one request goes out — the button is disabled while one is running.
10. Switch to another tab mid-sentence and back. The half-typed draft is still there.
11. Force-close and reopen the app. The transcript is **empty** — this is deliberate, not a bug.
12. Complete a scan, open it, and tap **Check BIS requirement**. The atta product shows "BIS
    certification is not required", a route row, next steps and sources.
13. Do the same from an **olive oil** scan. It reads **"Not established"** with a warning tone, and
    there is **no certification-route row at all**. If it says "not required", the collapse this stage
    exists to prevent has happened.
14. Check the freshness chip on both: "Sources as of 2026-08-30".

### Stage 12 · Bulk listing check ✅ (device check pending)

**Requirements:** FR-10 · Mode B only

| Mode | Difference |
|---|---|
| A | Not offered. The tab is absent from the enforcement tab bar by construction (`features/navigation/tabs`) |
| B | The whole stage |

**What shipped**

- **Over fifty rows blocks rather than truncates.** This is the stage's first refusal. Fifty-one
  pasted, fifty checked, a results table showing fifty — and a seller who believes their catalogue
  was cleared, having never seen the row that was dropped. It is Stage 9's report gate in a different
  place: the output leaves the app, gets forwarded, gets acted on, and the row silently discarded is
  the one that was non-compliant. So `parseListings` counts the excess, `blocksSubmit` returns
  `over_limit`, and the screen names the number. `rows` also holds only the first `MAX_ROWS`, so a
  future caller who reads it and ignores `overLimit` still cannot submit past the cap.
- **A metric verdict from listing text is refused, downgraded and reported.** The second refusal, and
  the more interesting one, because it **assumes the backend is wrong and checks**. The failure it
  guards against would look like the product working: `LM-9-2-TABLE1 · PASS · 4.2 mm` beside a
  gazette citation, from a source containing no millimetres at all. It is the most convincing wrong
  output this system can produce. The realistic cause is not a bug but a well-meant feature — a Rule
  9 path that reads the listing's own product photograph — landing three layers from anyone thinking
  about CLAUDE.md §3.3. `guard.ts` forces any metric PASS, FAIL **or BORDERLINE** back to
  `NOT_ASSESSABLE`, clears the number with it, recomputes the summaries, and the screen says it did.
  A silent correction would leave the server emitting a forbidden verdict with nobody the wiser.
- **BORDERLINE counts as an asserted verdict.** It means a measurement landed inside the uncertainty
  band, which presupposes a measurement. Treating it as the safe middle would have left the one
  verdict that sounds cautious as the way through the guard.
- **The one list of metric rules moved out of the mock and into app code.** It was a literal in
  `api/mock/index.ts`, which was the wrong home twice: the mock is deleted at Stage 13, so the guard
  would have lost its list, and two places could disagree about what a metric rule is.
  `features/bulk/metric-rules.ts` is now the single definition and the mock imports it — the same
  narrowing the mock already does for `matchesVerdict`.
- **The fixture set can break the rule on purpose.** `buildViolatingCheck` emits `PASS · 4.2 mm` on
  the Rule 9 family, and a `listing-metric-verdict` dev scenario routes to it. Stage 11's lesson
  applied: a guard cannot be shown to work against a mock incapable of being wrong, and the normal
  route emits correct output, so a suite that only went through it would pass whether the guard
  existed or not.
- **A row with no result is neither passing nor failing.** A listing whose page could not be fetched
  gets an error, no findings and four zeroes — and is excluded from `cleanRows`, so a short results
  table cannot read as a clean bill of health. It also gets its own line in the CSV, so the file has
  as many listings in it as were submitted.
- **`NOT_ASSESSABLE` does not count against a row.** Every row carries five unassessable metric rules
  by construction, so ranking on "total non-passes" would put every row at the top and rank none of
  them. A row is clean when it has no FAIL, no BORDERLINE and no error — and it is still never called
  *compliant*, because a listing check covers presence and format and says nothing about the pack.
- **Two different counts are reported, because they answer two questions.** Listings-with-a-problem
  and total-problems. Giving only the second makes eight defects on one listing look like eight bad
  listings.
- **The "no physical scale" explanation appears before the check runs, not only on each row.** A
  seller who reads "not assessable" forty times without having been told why concludes the checker is
  broken. Said up front, it points at the other half of the product: photograph the pack with a
  marker.
- **Rule 6(10A) is the one rule where the two input kinds genuinely differ.** The country-of-origin
  filter is a property of the marketplace *page*, so it is assessable from a URL and
  `not_in_listing` from pasted copy — its absence from the listing text is not evidence the filter is
  missing from the site.
- **`ListingFinding` is a separate type from `Finding`.** `Finding` carries a `scanId`, a `bbox` and
  a `band`, and all three would be structurally present and permanently null here. A type whose
  fields are always null invites a screen to render an empty evidence panel and a reader to wonder
  what is missing. What a listing finding has instead is a `notAssessableReason`, which a scan
  finding does not need because the scan's own `issues` carry it.
- **The CSV is one row per finding, not per listing**, because the first thing anyone does with it is
  filter on a rule id — which a wide column of semicolon-joined text prevents. Every field is quoted
  unconditionally, and a field opening `=`, `+`, `-` or `@` is prefixed with an apostrophe: Excel and
  Sheets execute those, and listing copy is attacker-influenced text.
- Duplicates are collapsed and counted. `…/p/1`, `…/p/1/` and `…/p/1?ref=share` are one listing
  pasted from three places; checking it three times inflates the very counts someone reads to size
  the work.
- `Field` gained an `inputStyle` passthrough, narrow on purpose — `style` stays omitted so a caller
  cannot replace the border, radius or error colour, and the one thing a caller does know better is
  how tall the box should be.

**Deferred, deliberately:** picking a CSV **file**. `expo-document-picker` is not an approved
dependency (CLAUDE.md §7), so the paste box is the only input — which takes CSV content pasted from a
spreadsheet, and is the more likely phone workflow anyway since the file is already open in another
app on the same device. See flag 32.

**Done when:** a 50-row CSV produces 50 result rows with a summary count, and no metric rule ever
returns PASS or FAIL from listing text alone.
**Met:** both halves pinned in `__tests__/bulk.test.ts`. Fifty URLs in produce fifty rows numbered 1
to 50, with `check.summary` equal to the sum of the row summaries and each row summary equal to a
recount of its own findings. Every Rule 9 finding comes back `NOT_ASSESSABLE` with
`no_physical_scale`, `observed` null and `required` null — and the guard is separately proved against
`buildViolatingCheck`, which asserts `PASS · 4.2 mm` on those same rules.
**Verified:** lint 0 · tsc clean · 586 tests pass (54 new) · prettier clean. No new dependency.
**Not verified:** whether the CSV opens correctly in Excel and Google Sheets on a real device, the
share sheet itself, scroll behaviour through fifty expandable cards, and Devanagari in the results
chips.

**Device checklist for this stage**

1. Sign in as **industry**. The **Bulk** tab is present. Sign in as **enforcement**: it is absent.
2. On the Bulk tab, before typing anything: the "Measurement rules cannot run on a listing" panel is
   visible. This is the explanation, and it comes first.
3. Paste three marketplace URLs, one per line. The chip reads "3 listings ready". Tap Check.
4. Results appear: a summary card with listings-with-a-failure / borderline / clean counts, then a
   second row of four numbers for the rule checks, then the rows worst-first.
5. Expand any row. Every Rule 9 rule shows **Not assessable** with the sentence about a listing having
   no physical scale. **None of them shows a millimetre value.**
6. Paste the same URL three times with `/` and `?ref=x` variations. It collapses to one listing and
   the chip says "2 duplicates collapsed".
7. Paste 55 URLs. A red "Too many listings" banner names the excess, and **Check is disabled**. Delete
   five lines: it enables.
8. Paste exactly 50 and check. Count the rows — there must be 50, numbered 1 to 50. This is the
   acceptance test.
9. Tap **Export CSV**. The share sheet opens; send it to Drive or mail and open it in Sheets. The
   header row matches, the `rulepack_version` column is filled on every line, and a row with no
   result still has a line.
10. Settings → dev panel → **Listing check returns a metric verdict**. Run a check: a red
    "Measurement verdicts were rejected" banner appears and every Rule 9 row still reads **Not
    assessable**. This is the other half of the acceptance test.
11. Paste listing *text* rather than URLs. Rule 6(10A) reads "not assessable from listing text";
    with a URL it returns a real verdict.
12. In हिन्दी: the panel, the block message and the not-assessable reasons read in Hindi without
    clipping.

### Stage 13 · Hardening and the live-backend cutover 🔨 (partly blocked — see below)

**Requirements:** NFR-02, NFR-07, NFR-08

**What shipped**

- **The mock backend is now genuinely absent from a live bundle, and that is measured rather than
  asserted.** It was not before. `__DEV__` gates kept the fixture panels off a user's screen and did
  nothing about what was bundled: three screens imported `@/api/mock` statically for the fixture OTP
  and account switcher, so the whole fixture graph — 220 seeded scans, the base64 sample PDF and
  DOCX, every gazette citation — was in a production export. `npm run verify:bundle` exports a
  production bundle with `EXPO_PUBLIC_API_MODE=live` and fails if any of five mock-only sentinel
  strings appears in it. **It failed on the first run**, which is the entire reason it exists.
- **A conditional `require` was not enough, and finding that out is the useful part.**
  `EXPO_PUBLIC_API_MODE` is inlined to a literal by `babel-preset-expo`, so `if (API_MODE === 'live')`
  is statically dead in a live build — but **Metro resolves `require()` targets while building the
  module graph, before any dead-code elimination**, so a `require` inside an unreachable branch still
  pulls its whole subtree in. The exclusion had to move to resolution time: `metro.config.js` (new,
  no dependency) resolves anything under `src/api/mock/` to an empty module when the mode is `live`.
- **`src/api/dev.ts` is the one door to the fixture layer.** The three screens that wanted fixture
  conveniences now read a `DevBridge | null`, which is null in any build that should not have one.
  `null` rather than empty stubs, so a caller has to handle the state a release build is actually in —
  and the panels keep compiling after the fixtures folder is deleted.
- **Hindi is complete: 145 strings written, 586 of 586 keys covered.** It shipped incomplete for
  twelve stages on purpose, with an English fallback so a missing key never rendered as
  `settings.appearance`. The fallback stays; the gap is closed. A test now fails when an English
  string lands without its Hindi, and a second one fails on an orphaned Hindi key left behind by a
  rename. A third catches a Hindi value that is still a copy of the English, with an explicit
  exception list for the nine strings that are correct *because* they are not Hindi (`English`,
  `JSON`, `URL`, the unit placeholders).
- **The accessibility pass found three real contrast failures, and contrast is now arithmetic.**
  Nobody reads a hex value and sees 3.19:1. Light `textSubtle` measured **3.19:1** on `surfaceAlt`,
  **3.41:1** on `bg` and **3.63:1** on `surface` — it carries captions, which are 12 px and therefore
  *normal* text under WCAG, so the 3:1 large-text allowance does not apply. Light `pass` measured
  **4.36:1** on `passSoft`, a pair read on every findings screen. Dark `textSubtle` measured
  **4.03:1** on `surfaceAlt`. Fixed by luminance-only adjustments: `#7C8891`→`#636D75` (light),
  `#1B7F4B`→`#1A7A48`, `#7C8891`→`#87929A` (dark). The two themes no longer share a subtle grey,
  which is correct — one colour cannot sit 4.5:1 from both a near-white and a near-black ground. All
  24 rendered pairs × 2 themes are now asserted in `__tests__/hardening.test.ts`.
- **Two touch targets were under 44 px.** A pressable `Chip` lands around 28 px tall, and chips are
  real controls — history filters, verdict filters, Sahayak suggestions. Growing them would destroy
  the one thing a chip is for, so the *touch* area grew instead: `hitSlop={HIT_SLOP}`, whose 8 px
  exactly matches the `gap` used between chips everywhere, so adjacent slop regions meet in the
  middle of the gap rather than stealing each other's taps. `SegmentedControl` segments are 36 px and
  sit edge to edge, so they got vertical-only slop — horizontal would have each segment taking its
  neighbour's taps. Stage 12's row header also gained the 44 px minimum.
- **The cold-start instrument reports what it can measure and says what it cannot.**
  `src/lib/startup.ts` measures JS bundle evaluation to first interactive frame, which is the part
  the app's own code controls and the part that regresses when a screen does work at import time. It
  is a **floor** on the real number, never the whole of it — everything before
  `__BUNDLE_START_TIME__` is already over by the time JS can run. It returns **null** rather than a
  number when there is no bundle start time, because `Date.now()` there would report a cold start of
  zero milliseconds, and it refuses a negative or absurd interval as a clock disagreement rather than
  a measurement. Idempotent, so navigating back cannot overwrite a cold figure with a warm one. The
  figure shows in Settings → About, **not** dev-gated, because the number that matters comes from a
  release build. The `adb` commands for the whole figure are in the module's own doc comment.
- **Loading, empty and error states audited across all 21 routes.** No gaps: the two that looked
  empty delegate to `ScanList`, which carries its own skeleton, empty state, filtered-empty state and
  error banner; the two auth screens surface mutation errors through `Field`'s error slot. The §11
  degradation table is reachable end to end from the dev scenario panel, which now has seven
  scenarios — Stage 12 added `listing-metric-verdict`.
- `.env.example` added, documenting both cutover variables, why `localhost` does not work from a
  physical device, and that everything in it is readable in the shipped bundle.

**Blocked, and why**

- **The cutover itself cannot be performed.** It requires a deployed backend publishing an OpenAPI
  schema: `npm run gen:api` fetches `/openapi.json` and there is nothing to fetch. Deleting the
  fixtures folder now would leave the app with no data source at all in the only mode it can
  currently run in. What *is* done is everything that makes the cutover a folder deletion — the seam
  is unchanged, no app code imports the fixture layer (asserted by test), and the live bundle is
  already fixture-free. The remaining work is: point `ANUPALAN_API_URL` at the deployed API, run
  `gen:api`, fix what the compiler flags against the 11 assumed contract shapes (flags 5, 8, 16, 18,
  21, 22, 23, 26, 27, 29, 30), then delete `src/api/mock/`, `src/api/dev.ts`, `metro.config.js`'s
  resolver branch and the four dev panels in Settings.

  **Updated 2026-09-12.** The backend reached B16, so the diff is now measured rather than assumed:
  **eight of the app's fifteen calls have a server**, and the full register is
  `06-wiring-contract.md`. Two items change the plan above. `npm run gen:api` still cannot run —
  not for want of a deployment, but because `backend/.venv` is missing `pgvector` and the app
  cannot be imported, so there is no `openapi.json` to fetch. And the cutover is now sequenced
  **backend gaps first, wire once**: six backend changes (W1–W6) land before any adapter is
  written, because one of them — the findings response omitting `extractions`, flag 36 — cannot
  be adapted around without silently disabling this app's own report gate.
- **The cold-start number cannot be taken here.** It needs the EAS dev build on a physical 4 GB
  Android 12 phone. The instrument and the `adb` procedure are in place; the figure is item 1 of the
  checklist and belongs in `docs/eval-results.md`.
- **`__tests__/i18n.test.ts` now fails, and I have not touched it** (CLAUDE.md §6: do not edit tests
  to make them pass). Its fallback test uses `scan.subtitle` as a stand-in for "a key missing from
  `hi`", and the Hindi completion pass translated that key. The fallback *mechanism* is still correct
  and still needs a test; the conflict is that it cannot be demonstrated with a real app key once
  Hindi is complete. Two requirements are in direct opposition here and the resolution is a
  judgement call, not a fix — see the note below.

**Done when:** cold start is measured and reported, the app runs against the real backend with no
screen changes, and the mock transport is gone from the release build.
**Met:** the third. `npm run verify:bundle` passes — a production live export contains none of the
five mock sentinels. Measured: **4.85 MB in mock mode, 4.76 MB in live mode**, so 92 KB of fixtures
are genuinely gone (unminified Hermes bytecode, `--no-minify` so the sentinels stay findable).
**Not met:** the first, for want of a device; the second, for want of a backend.
**Verified:** lint 0 · tsc clean · prettier clean · 644 of 645 tests pass (59 new); the one failure is
the pre-existing `i18n.test.ts` case described above. No new dependency — `metro.config.js` uses
`expo/metro-config`, which ships with Expo.
**Not verified:** cold start on hardware, Devanagari layout at the new string lengths (145 of them
have never been on a screen), focus order with TalkBack, and the app against a real backend.

**Device checklist for this stage**

1. Build a **release** APK, force-stop it, then
   `adb shell am start -W -n in.anupalan.app/.MainActivity`. Record `TotalTime`. Cross-check against
   `adb logcat -d | grep "Displayed in.anupalan.app"`. Target 3 s on a 4 GB Android 12 phone. Put
   both numbers in `docs/eval-results.md` with the device model.
2. Open Settings → About on that build. The `JS→frame` line shows the JS-side figure; it should be
   well under the `TotalTime` from step 1. If it is *larger*, something is wrong with the clocks.
3. Switch to **हिन्दी** and walk every screen: Scan, Capture, Context, Queue, Processing, Confirm,
   Findings, Report, History, Inspections, Sahayak, BIS, Bulk, Settings. Look for clipped labels,
   truncated buttons and wrapped chips — Devanagari runs longer than English and 145 of these strings
   have never been rendered.
4. The longest strings are the ones to watch: `report.blockProvisionalBody`,
   `context.whyBody`, `bulk.blockOverLimitBody`, `sahayak.outcomeRefusedBody` and
   `findings.noBoxBody`.
5. Enable **TalkBack**. Swipe through the Findings screen: every verdict badge announces its verdict,
   every finding row is reachable, and the image announces its label rather than "unlabelled image".
6. With TalkBack on, check the tab bar announces the selected tab, and that Settings' two segmented
   controls announce as radio groups with the current selection.
7. Tap a **Chip** at the edge of its visible bounds — a history filter, or a Sahayak suggestion. It
   should respond from about 8 px outside the pill.
8. Switch the system theme to **dark** and walk the same screens. Check captions and the `mono` rule
   ids are readable on cards, and that the four verdict colours are still tellable apart.
9. Switch to a large system font size (Settings → Display → Font size, largest). Nothing should
   truncate irrecoverably; the findings list and the bulk rows are the ones most likely to.
10. Walk the whole §11 degradation table from Settings → dev panel: no marker, low-confidence field,
    LLM unavailable, report failed, listing metric verdict, offline, server error. Each should show a
    named state rather than a spinner or a blank screen.
11. Airplane mode on: capture a scan end to end. It queues, survives a force-close, and uploads on
    reconnect (this is also the FR-04 check).

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

> **2026-09-12 — the API contract flags now have answers, and the backend side is built.** The
> backend is at B24 (the first reading of it was against a stale branch and undercounted it: B17–B23
> had already landed). **All fifteen of this app's API calls now have a server.** Every flag here that says *agree with the backend* is resolved,
> confirmed or superseded in **`06-wiring-contract.md`**, which carries the endpoint coverage
> table, the gap register and a handoff card per backend change. Flags 5, 16, 18, 21, 22, 23, 24
> and 25 are tracked there as gaps G6, G1, G1, G2, G4, G8, G6 and G6/G7 respectively, and every one
> of them is now **closed** — `06-wiring-contract.md` §8 records what was built. Flags 6, 8, 9 and 10
> are answered inline below. Read that document before touching `src/api/`.

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
   **Answered 2026-09-12: it does.** `FindingsOut` omits inapplicable rules from `findings` and
   reports them in `not_applicable_rule_ids`, with a fifth *count* in the summary and no fifth
   verdict. The app currently discards that list, which is its own gap to close —
   `06-wiring-contract.md` §3.3.
7. **`react-native-nitro-modules` is an auto-installed peer** of MMKV and vision-camera, not
   declared in `package.json`. If the EAS dev-client build fails on autolinking, check this first.
8. **TRD §5 has no refresh endpoint**, although `auth/otp/verify` returns a refresh token and
   `01-architecture.md` §197 specifies access/refresh JWTs. Stage 2 assumes
   `POST /v1/auth/refresh {refreshToken} -> {accessToken, refreshToken}`, returning **401** when the
   refresh token is rejected — the status the client uses to decide a session is over rather than
   merely unreachable. **Answered 2026-09-12: the endpoint exists**, with rotation, exactly as
   assumed. One difference, and it is not cosmetic — the body field is `refresh`, not
   `refreshToken`, and `StrictModel` sets `extra="forbid"`, so the app's current body is a **422**.
   `live-transport.ts` reads any non-ok refresh as a rejected token and signs the user out, so this
   would log people out every time an access token expired. `06-wiring-contract.md` §3.3.
9. **TRD §5 has no session endpoint.** `user` and `org` arrive exactly once, in the verify response,
   so the app cannot revalidate who it is after a restart and caches them locally. A `GET /v1/auth/me`
   would let the org and role be refreshed as server state instead — worth having if a user's role
   can change while they are signed in.
   **Answered 2026-09-12: `GET /v1/auth/me` exists** and returns the user and org. The app should
   adopt it for session restore rather than trusting the local cache.
10. **TRD §5 sketches snake_case field names** (`{request_id}`, `{access, refresh}`) while the
    client types are camelCase throughout. One of the two has to give, and FastAPI can alias on the
    way out. **This affects every endpoint, so settle it early** — it is cheap now and a
    find-and-replace across the app later.
    **Decided 2026-09-12: the app converts**, with explicit per-endpoint adapters rather than a
    generic deep key transform, because a blind converter would rewrite the rule pack's own field
    names inside `profile` and the `x-amz-*` presigned headers. Note what raises the stakes:
    `extra="forbid"` means a mismatched *request* key is a 422, not a dropped field, so sign-in
    fails at the first call rather than degrading. `06-wiring-contract.md` §3.3.
11. **The refresh token is in unencrypted MMKV.** A rooted device, or one with ADB backup enabled,
    can read it off disk. The right home is the Android Keystore via `expo-secure-store`, which is a
    new dependency and needs approval (CLAUDE.md §7). `src/lib/storage.ts` keeps it behind one
    interface so the swap is a one-file change.
12. **`02-trd.md` declares `SR-xx` security requirement ids in §1 and defines none.** Auth therefore
    has no acceptance tests in the TRD, and Stage 2 was built from `01-architecture.md` §3 and §14
    instead. Worth adding them: org isolation and session handling are the requirements most likely
    to be assumed rather than checked.
13. **The marker sheet is a repo artefact, not an in-app download.** It prints from
    `mobile/assets/marker/anupalan-marker-a4.pdf`, which suits the real workflow — print from a
    laptop. Handing it to a printer *from the phone* would need `expo-asset` (already installed as
    Expo's own dependency) plus a `metro.config.js` change to bundle `.pdf`, and both need
    approval. Worth doing if a field user ever has to print without a computer.
14. **Marker generation lives in two places by necessity.** `mobile/scripts/make-marker-sheet.py`
    draws the sheet; `backend/scripts/make_chart.py` (P0.1, not yet written) draws the E1 evaluation
    chart. Both must use `DICT_4X4_50` id 0 at 40.0 mm. If they ever disagree, the measurements are
    wrong in a way no test on either side would catch — **agree the constants with the backend.**
15. **Stage 4 is unverified on hardware.** The gate policy is pure and fully tested; the camera,
    the permission flow and the disk write are not reachable from a test runner. Until the EAS dev
    client has been run through the device checklist in Stage 4, treat FR-01 as code-complete and
    not as done.
16. **`POST /v1/scans` carries three fields TRD §5 does not list.** `Scan` has `capturedAt`, `geo`
    and `district`, and the server can only learn all three from the client, so Stage 5 sends them
    in the create body. `capturedAt` matters most: it is when the shutter fired, which on a queued
    scan is not when the request arrived, and the evidence trail needs the former. **Agree the
    names before Stage 13** — if the backend prefers them nested under an `evidence` object,
    `src/api/types.ts` changes and nothing above it does.
17. **Unit normalisation in the form is not the same as excusing a wrong symbol on a pack.**
    `normaliseUnit` rewrites the operator's own typing (`gms` → `g`) so a scan is not blocked over
    it. What the *pack* declares is read off the photograph and judged by the rule pack, where a
    non-prescribed symbol is a finding. Keep the two apart — a future "helpful" reuse of this
    function on extracted text would silently erase a whole class of defect.
18. **A retry of `POST /v1/scans` must return the existing scan and fresh upload URLs.** The queue
    retries the whole pass — create, upload, submit — with the idempotency key minted at capture, so
    the second call has to be recognised as the first *and* hand back presigned URLs that have not
    expired. TRD §5 has no "get upload targets" endpoint, and adding one would be the alternative.
    **Agree this with the backend before Stage 13**; if it would rather expose
    `GET /v1/scans/{id}/uploads`, the runner changes in one place.
19. **`Scan` needs a `pipelineStage`, and TRD §5 does not have one.** The progress screen shows the
    architecture's own S2–S10 stage names, and it can only honestly highlight one if the server says
    which it is on. Stage 7 added `pipelineStage: PipelineStage | null` to the domain type and the
    screen renders null as "the server has not said" rather than guessing from elapsed time. **Agree
    whether the worker publishes it** — if not, the list stays unhighlighted and the feature degrades
    to a plain spinner, which is a real loss in a demo.
20. **Nothing yet recomputes a verdict when a *measurement* is corrected** — only an extracted field
    value. FR-06's acceptance only covers the field path, and the measurement path may not need one,
    but the asymmetry is worth a decision before Stage 8's findings viewer invites a user to question
    a millimetre.
21. **`GET /v1/scans/{id}/findings` needs a `findingsSha256`, and TRD §5 only puts the hashes on a
    report.** Mode A's evidence panel shows it *before* anyone asks for a PDF, because that is the
    moment an inspector decides whether to issue one. Stage 8 added `findingsSha256: string` to
    `FindingsResult`. It must be a hash of the **same blob** the report embeds, or the two surfaces
    will disagree for no reason a reader could diagnose. **Agree before Stage 13.**
22. **`Scan` needs a `reportIssuedAt`, and TRD §5 does not have one.** It is the only signal the app
    has for "editing is locked after issue" (FR-05's Mode A column), and it has to be on the scan
    rather than inferred from a reports collection — the findings screen must know without a second
    request. Null means no report has been issued. If the backend would rather expose
    `GET /v1/scans/{id}/reports`, `editingLocked` changes in one place. **Agree before Stage 9**, which
    is what sets it.
23. **Report generation is asynchronous and TRD §5 defines nothing to poll.** §5 has
    `POST /v1/scans/{id}/report` and no way to ask again. Rendering an annotated PDF is S10 of the
    pipeline, so Stage 9 assumes the POST returns a report with `status: 'pending'` and
    `GET /v1/reports/{reportId}` returns the same shape until it leaves that state. `Report` also
    gained `formats`, `requestedAt`, `generatedAt | null` and `error | null`. `formats` is kept
    alongside `files` on purpose: a report that came back ready with one of two requested documents
    must be visible as a short delivery rather than looking like the user only asked for one.
    **Agree before Stage 13.**
24. **`ScanListItem` needs a `productId`.** FR-09 filters by product, and the list row carried only a
    `productName` — two products can share a name, and a filter matching on text would quietly fold
    them together. Stage 10 added `productId: string | null`, null for a scan whose profile was typed
    in and never matched to a catalogue product.
25. **TRD §5 has no search parameter, and no brand or SKU anywhere.** Stage 10 assumes
    `GET /v1/scans?q=` as free text over the product name. Separately, the frontend plan's Mode B row
    asks for "filter by brand and SKU" and **neither field exists on `ProductProfile`** — there is a
    `name`, and a `gtin` on `Product`. Inventing them to satisfy a filter would be the wrong order of
    work; SKUs become real in Stage 12's bulk listing check, which is where the product model should
    gain them. **Decide with the backend before Stage 12.**
26. **The citation host allowlist exists in two places and must not drift.** `OFFICIAL_HOSTS` in
    `features/sahayak/citations.ts` is the client's only defence against a fabricated citation, and it
    has to be a superset of whatever `services/bis/ingest.py` is actually allowed to fetch. If the
    backend ingests a host the client does not list, **valid citations are silently withheld** and
    real answers get downgraded to not-found — a failure that looks like a bad model rather than a
    config mismatch. This is flag 14's problem in a second place. **Agree the list with the backend**,
    and prefer having the API return the allowlist over maintaining it twice.
27. **The backend must actually emit `qcoApplicable: 'unclear'`.** The whole three-stance design
    collapses if the applicability service defaults an unresolved lookup to `'no'`, because the client
    cannot tell the difference — `'no'` renders as "certification is not required", which is a
    clearance. This is the BIS half's version of the §3.4 non-negotiable and it needs the same
    treatment as a verdict: **unresolved is its own value, never the negative one.** Confirm before
    Stage 13.
28. **Two applicability branches have no fixture reachable from a scan.** `required` and the
    inconsistent record (mandatory certification, no named route) are covered by unit tests over
    constructed records, but none of the four fixture products is genuinely covered by a QCO, and
    inventing one would put a fabricated legal claim in a fixture set whose whole discipline is that
    its citations are real. So the `required` stance is **only demonstrable in the chat** (the CRS
    charger answer) and not from the BIS screen until the real corpus lands. Worth a real covered
    product in the catalogue when one can be cited properly.
29. **`SahayakAskBody.lang` assumes the server answers in the language asked for**, rather than the
    client translating afterwards. TRD §5 does not specify it. It matters more than it looks: a cited
    answer translated client-side would have its citations re-attached to text no source supports.
    Also unspecified — whether the corpus itself is bilingual, or whether a Hindi answer is an English
    retrieval with a Hindi generation over it. **Agree before Stage 13**; the second is acceptable, the
    first is better, and the app cannot tell which it got.
30. **TRD §5 has no listing-check endpoint, although FR-10 is a numbered requirement with its own
    acceptance criterion.** Stage 12 assumes `POST /v1/listings/check` taking up to 50
    `{lineNumber, kind, source}` rows and returning one result per row, the batch stamped with the
    rule pack version. It honours `Idempotency-Key` like `POST /scans` — a retry after a dropped
    response must not re-run fifty listings through the rules engine and bill for them twice. The
    response also needs `ListingRowResult.error` for a page that could not be fetched: a row with no
    result is neither passing nor failing, and omitting it would make a short table read as a clean
    result. **Agree before Stage 13.**
31. **The metric-rule list is remembered in app code and must not drift from the pack.**
    `features/bulk/metric-rules.ts` is what lets the client enforce FR-10's "no metric verdict from
    listing text" criterion, and it is a hand-maintained list of the Rule 9 family. A new metric rule
    added to `rulepacks/lm-2011-v1.yaml` and not added there is a rule the guard waves through. The
    right fix is a **`metric: true` flag on the rule in the pack**, surfaced on the finding, so the
    client reads the property instead of remembering the ids — worth doing when the pack is next
    revised, and it is flag 14's hazard for the third time.
32. **Picking a CSV file needs `expo-document-picker`, which is not approved.** FR-10 says "paste or
    upload"; Stage 12 shipped paste only. Pasting CSV content from a spreadsheet is the same input and
    arguably the more realistic phone workflow, but a seller with a file in Drive and no way to open
    it will read the feature as half-built. One dependency, one screen change — worth approving.
33. **`__tests__/i18n.test.ts` fails, deliberately left failing, and needs a decision.** Its fallback
    case asserts `translate('hi', 'scan.subtitle') === translate('en', 'scan.subtitle')`, using a real
    app key as its example of "a key missing from `hi`". Stage 13's Hindi completion pass translated
    that key, so the assertion now fails. **CLAUDE.md §6 says not to edit a test to make it pass**, so
    it has not been touched. The two requirements are in genuine opposition: NFR-08 wants complete
    Hindi, and this test wants a real untranslated key to point at. The fallback *mechanism* still
    works and still needs covering. Three options, in the order I would pick them: **(a)** re-point
    the assertion at a synthetic key that is absent by construction (`translate('hi', 'zz.missing' as
    TranslationKey)`), which tests the mechanism without depending on a gap in the app's own copy;
    **(b)** delete the case and rely on `hardening.test.ts`'s completeness tests, which lose coverage
    of the fallback path itself; **(c)** leave one key untranslated to keep the test honest, which
    trades a real user-facing gap for a test fixture and is the wrong way round. (a) is a one-line
    change to a test, and it needs sign-off rather than a unilateral edit.
34. **`metro.config.js` now exists and is load-bearing for NFR-07.** It did not before Stage 13. Its
    only job is resolving `src/api/mock/**` to an empty module when `EXPO_PUBLIC_API_MODE=live`, which
    is what actually keeps the fixtures out of a release bundle — a conditional `require` does not,
    because Metro resolves require targets before dead-code elimination. Anyone adding Metro config
    later must keep the resolver chain intact (it calls through to `upstream ?? context.resolveRequest`
    rather than replacing it). `npm run verify:bundle` is the check; it belongs in CI.

35. **`POST /v1/scans` takes a list of assets with a required SHA-256 per asset, not an
    `asset_count`.** The backend refined TRD §5 deliberately and documented why: a count cannot
    produce presigned URLs, because the content type is part of the signature and the size ceiling is
    enforced when the capability is issued rather than after the bytes have arrived. The worker then
    verifies the stored object against the declared hash and fails the scan on a mismatch. The app
    computes none, so the capture path cannot reach the server as written. **Decided 2026-09-12: the
    app computes it**, with `expo-crypto` approved for the purpose — see `06-wiring-contract.md` §3.1
    G1 for the rejected alternative, which was to let the worker compute the hash instead.
36. **`GET /v1/scans/{id}/findings` omits `extractions`, and there is no safe default.** This is the
    most consequential thing the wiring audit found. `verdictsAreProvisional` is
    `result.extractions.some(needsConfirmation)`, and `blocksReport` uses it to refuse a PDF while any
    field sits below the 0.75 threshold. Defaulting the field to `[]` makes `.some()` false, so **the
    report gate opens for every scan** and the app issues reports over unverified readings while
    showing no caveat — Stage 9's entire refusal, reintroduced invisibly. Leaving it absent crashes
    the screen instead. FR-06's confirmation sheet is empty in both cases, so the one mechanism for
    correcting a bad read becomes unreachable. The backend computes these rows already
    (`_domain_extractions`) and drops them. This is why W1 is first in `06-wiring-contract.md` §6.
    **Closed 2026-09-12:** the response now carries `extractions`, `measurements` and
    `findings_sha256`, pinned by a test that fails if a confidence is ever defaulted.
37. **`district` does not exist in the backend at all** — not in the create body, not in the scan
    response, and not as a column on `scans`, which carries `geo_lat`/`geo_lon` only. So it cannot be
    sent, stored or returned: the history row has nothing to show, the Mode A filter has nothing to
    filter, and FR-30's "violations by district" has no column to group by. It is a schema change and
    CLAUDE.md §7 wants agreement, which is cheaper now than after the table has rows.
    `06-wiring-contract.md` §3.1 G3, card W3. **Closed 2026-09-12 with no migration needed** —
    B17's dashboard work had already added the column and its index; only the create body and the
    response were missing.
38. **`GET /v1/scans/{id}` omits `profile`, `org_id` and `user_id`.** `profile` is the one that bites:
    it is already a JSON column on the row and simply is not in `ScanOut`, and the scan screen and the
    report filename both read it. `report_issued_at` (flag 22) arrives with the reports work rather
    than as a null that means "no reports endpoint exists yet". `issues` is **not** being asked for —
    the app derives it from the status, the findings envelope's `reduced_extraction` and flag 36's
    confidences, and a second source of truth for the same thing would drift.
    **Closed 2026-09-12:** `ScanOut` now returns `profile`, `org_id`, `user_id`, `geo` and
    `district`. `issues` was deliberately not added, for the reason above.
39. **The status and marker vocabularies differ, and one difference strands a queued scan.** The
    server has `created` and `no_marker` where the app has the queue's local `captured` and
    `uploading`. `features/queue/runner.ts` leaves `processing` only on `complete` or `failed`, so a
    **`no_marker` scan would sit in the queue forever and the pending badge would never clear**. The
    app maps it to `complete` plus the `no_marker` issue, which is what §11 means by degraded *but
    final*. Marker values differ too (`aruco_4x4_50`/`user_declared` against
    `aruco_40mm`/`user_dimension`) and the **server's names are better** — `aruco_4x4_50` names the
    ArUco dictionary that flag 14 says must not drift, and the 40 mm already lives in `marker_mm`. The
    app renames. Both mappings are recorded in `06-wiring-contract.md` §3.1 G5, which is where they
    have to change if either vocabulary does.
40. **Seven of the app's fifteen API calls have no server, and three are dated November.**
    `GET /v1/scans` (FR-09, and never in TRD §5), `GET /v1/products`, the two report endpoints, and
    then Sahayak, BIS applicability and the listing check, which are B19–B21. So Stages 10, 11 and 12
    stay on fixtures after the first cutover, and `src/api/mock/` is deleted at the end of that
    sequence rather than with the first endpoint. Plan the demo around what is wired, not around the
    stage count. **Superseded 2026-09-12:** this flag was written from a stale branch. Sahayak, BIS
    applicability, the bulk listing check and the dashboards all existed on `main`; the four that
    genuinely did not exist have since been built. All fifteen calls now have a server.

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-09-12 | Created. Fourteen stages defined; Stage 0 completed and recorded. |
| 2026-09-12 | Stage 1 completed. Two API contract gaps recorded as flags 5 and 6. |
| 2026-09-12 | Stage 2 completed. Settings moved off the tab bar; flags 8–12 added, three of them API contract gaps. Stage 1's MSW deviation and Stage 2's session design recorded in `decisions.md`. |
| 2026-09-12 | Stage 3 completed. Printable marker sheet generated and detector-verified; flags 13 and 14 added. |
| 2026-09-12 | Stage 4 completed in code; the camera path awaits a physical-device check. Flag 15 added. |
| 2026-09-12 | Stage 5 completed. The capture draft freezes the scale reference; `qtyBasis` derived from the unit rather than asked; flags 16 and 17 added, one an API contract gap. |
| 2026-09-12 | Stage 6 completed. The in-memory draft was replaced by a SQLite row from the first shutter press; no outbox table; `Transport` grew `upload`; flag 18 added. |
| 2026-09-12 | Stage 7 completed. `pipelineStage` added to the domain; crops are a transform rather than a file; the mock's `llm-unavailable` path implemented; the queue now polls processing scans to completion. Flags 19 and 20 added. |
| 2026-09-12 | Stage 8 completed. One inverted transform serves both the outlines and the taps; four verdict groups kept structurally; a 10 mm scale bar that disappears without a marker; Mode A's evidence panel reads the *raw* image hash only. Flags 21 and 22 added, both API contract gaps. |
| 2026-09-12 | Stage 9 completed. Provisional verdicts **block** a report rather than warning; a degraded-but-final run is issued flagged. Generation is async and polled. The mock writes genuinely valid PDF and DOCX files. `Transport` grew `download`. Flag 23 added. |
| 2026-09-12 | Stage 10 completed. Single-select verdict filter over one count each; the seeded set gained a borderline-only bucket that can actually catch a merge; the hero scan's cross-org and Mode-B-location inconsistencies fixed. Filter measured at 0.020 ms per pass over 220 scans. Flags 24 and 25 added. |
| 2026-09-12 | Stage 11 completed. A citation that cannot be placed on an official host is withheld, and an `answered` response left with none is presented as not-found with its prose suppressed; the fixture set gained a deliberately fabricated citation so the guard is proved rather than asserted. `unclear` is not `no` — every affirmative row on the applicability screen is gated on `isConclusive`. Freshness has an `unknown` tier that does not fall through to `fresh`. The mock's word-overlap answer routing was replaced, and its applicability route no longer defaults to another product's record. `expo-web-browser` moved from installed-but-unused to used. Flags 26–29 added, three of them API contract gaps. |
| 2026-09-12 | Stage 12 completed. Over fifty rows blocks rather than truncating; a metric PASS, FAIL or BORDERLINE from listing text is refused, downgraded and reported, with a `listing-metric-verdict` fixture built to break it. The one metric-rule list moved out of the mock into app code. A row with no result is neither passing nor failing and is excluded from the clean count. `NOT_ASSESSABLE` does not count against a row. CSV export is one line per finding, every field quoted, formulas neutralised. `ListingFinding` is its own type rather than a `Finding` with three permanently null fields. Flags 30–32 added, one an API contract gap. |
| 2026-09-12 | **The app is wired to the real API.** `src/api/adapters/` maps every endpoint's wire shape to a domain type — explicit per resource, because a generic key transformer would rewrite the rule pack's own field names inside `profile` and the `x-amz-*` presigned headers. `expo-crypto` installed and the queue now hashes each photograph before `POST /v1/scans`. **Found and fixed a live sign-out bug:** the refresh body was `{refreshToken}` where the server wants `{refresh}`, and with `extra="forbid"` that is a 422 — which the transport read as a dead session, so users would have been signed out on every token expiry. Only a 401 ends a session now. The mock emits wire shapes through `to-wire.ts` so mock mode exercises the same code path as live. 670 mobile tests (25 new, round-tripping the adapters) and 691 backend tests pass; the one failure is the pre-existing flag 33. Nothing has run on hardware. |
| 2026-09-12 | Backend side of the cutover built (B24). The first audit was against a stale branch and undercounted the backend — B17–B23 had landed, so Sahayak, BIS and the bulk listing check already existed. Four endpoints genuinely did not and were written: `GET /v1/scans` with keyset cursors and a single-verdict filter, `GET /v1/products`, and the two report endpoints. The findings response gained `extractions`, `measurements` and the stored `findings_sha256`; `ScanOut` gained `profile`, `geo`, `district`, `org_id`, `user_id`. **All fifteen client calls now have a server.** 682 backend tests pass, 64 new. Flags 36–39 closed, 40 superseded. Nothing in `mobile/` has been touched yet. |
| 2026-09-12 | Wiring audit against the finished backend. Both halves read end to end and the diff recorded in the new `docs/06-wiring-contract.md`: **eight of the app's fifteen API calls have a server.** Flags 6, 8, 9 and 10 answered; flags 35–40 added. The finding that set the order of work: the findings response omits `extractions`, and defaulting that to `[]` would silently open Stage 9's report gate for every scan. Decided — the app computes each asset's SHA-256 (`expo-crypto` approved), and the backend gaps close before any wiring starts. |
| 2026-09-12 | Stage 13 partly completed. The mock backend is now genuinely absent from a live bundle, verified by `npm run verify:bundle` — which failed on its first run, because a conditional `require` does not remove a module from a Metro graph; `metro.config.js` resolves the fixture folder to an empty module instead, and `src/api/dev.ts` became the one door to it. Hindi completed: 145 strings, 586 of 586 keys, with completeness, orphan and copy-of-English tests. The accessibility pass found three real contrast failures (light `textSubtle` at 3.19:1, light `pass` at 4.36:1, dark `textSubtle` at 4.03:1) and two touch targets under 44 px; all 24 rendered colour pairs are now asserted in both themes. Cold-start instrument added, reporting null rather than a fabricated number. **Blocked:** the cutover needs a deployed backend, and the cold-start figure needs a physical device. Flags 33 and 34 added; flag 33 is a failing pre-existing test left untouched per CLAUDE.md §6 and needs a decision. |
