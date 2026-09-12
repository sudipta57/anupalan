# Anupalan — mobile

React Native (Expo), Android. Enforcement and industry modes over one backend.

Repository-wide context is in the root [CLAUDE.md](../CLAUDE.md) and
[README.md](../README.md). This file covers what is specific to the app.

---

## ⚠️ Expo Go will not work. You need an EAS dev client.

**`react-native-vision-camera` frame processors do not run in Expo Go.** Frame processors are
what drive the FR-01 capture gates — live ArUco marker detection, blur (variance of Laplacian
≥ 120), glare (< 2% of pixels ≥ 250 luminance) and tilt (≤ 25°) — and the shutter stays disabled
until all four pass. In Expo Go the camera will mount and the gates will never evaluate, which
looks like a bug in your code and is not.

**Build the dev client on day one of mobile work.** Discovering this in week three costs days
(CLAUDE.md §8, docs/03-implementation-plan.md §P3.2).

```bash
npm install
npx eas build --profile development --platform android   # dev-client APK, internal distribution
# install the APK on the device, then:
npx expo start --dev-client
```

The `development` profile in [eas.json](eas.json) is configured for exactly this: `developmentClient: true`,
`distribution: internal`, Android `buildType: apk`.

If the native marker plugin stalls, ship the interim path — upload a frame every 500 ms for
server-side gate checks — and swap the plugin in later behind the same interface. Do not let the
plugin block the rest of the app (docs/03-implementation-plan.md §P3.3).

From Stage 4 the capture screen is real, so this is no longer theoretical: **`npx expo start` with
Expo Go cannot open the Scan flow at all.** Build the dev client first.

### Expo Go is not a partial fallback either

`react-native-mmkv` 4 is a Nitro module as well, and the preferences store reads from it during
the first render, so Expo Go does not degrade to "the camera screen is broken" — it fails at
launch. There is exactly one way to run this app on a phone, and it is the dev client.

What runs with no device at all:

```bash
npm run lint          # eslint, zero warnings tolerated
npm test              # jest
npx tsc --noEmit      # typecheck
```

---

## Running it on a physical Android device

One-time setup, then a loop you repeat all day. The cloud build is only rebuilt when **native**
dependencies change — JavaScript changes reload over Metro in seconds.

### Once: build and install the dev client

```bash
npm i -g eas-cli            # or prefix every command below with `npx eas-cli@latest`
eas login                   # free account at expo.dev/signup
eas init                    # writes extra.eas.projectId into app.json — expected, commit it
npx expo-doctor             # catches config problems before a 20-minute cloud build
eas build --profile development --platform android
```

Then put the APK on the phone, with the phone connected over USB:

```bash
adb devices                          # must list your phone, not "unauthorized"
eas build:run -p android --latest    # downloads the APK and installs it
```

`adb devices` showing nothing means the phone has not enabled **Developer options → USB
debugging**, or the RSA fingerprint prompt on its screen was never accepted. Some vendors
(Xiaomi, Oppo, Vivo) also gate a separate **Install via USB** toggle.

### Every day: start Metro and reload

```bash
npx expo start --dev-client    # then press `a` to launch on the connected device
```

Press `r` to reload, `j` to open the debugger. The phone may instead be on the same Wi-Fi and scan
the QR from the dev client's own launcher screen — but USB is the one that does not depend on the
network letting devices talk to each other. If Metro is unreachable over Wi-Fi, forward the port
instead of debugging the network:

```bash
adb reverse tcp:8081 tcp:8081
```

### What you should see

Four tabs — Scan, History, Sahayak, Settings — rendering against fixtures, because
`EXPO_PUBLIC_API_MODE` defaults to `mock`. Settings is where to look first: it switches
English/Hindi and light/dark/system, reports the live API mode, and in a dev build carries a
**Mock backend** panel that forces the failure modes from the architecture's degradation table
(no marker, low confidence, LLM unavailable, offline, server error). Those paths are acceptance
criteria, so they are reachable without editing code.

### A local build instead of the cloud

`npx expo run:android` works, but it needs the Android SDK installed and a JDK that the Gradle
plugin supports. Neither is set up on this machine, and a cloud build needs neither, so the EAS
`development` profile is the shorter path until there is a reason to build natively.

---

## Layout

Per CLAUDE.md §2:

```
mobile/
├── app/              # expo-router screens
│   ├── (auth)/       # phone → otp, shown only when signed out
│   ├── (tabs)/       # the mode-aware tab shell
│   ├── settings.tsx  # root route behind the header gear, not a tab
│   └── +not-found.tsx
├── src/
│   ├── api/          # generated client + TanStack Query hooks — no `any`
│   ├── domain/       # types shared with backend schemas — no `any`
│   ├── features/     # auth, navigation, capture, findings, sahayak, history, reports
│   ├── components/   # shared primitives — Button, Card, VerdictBadge, AdvisoryDisclaimer
│   ├── db/           # SQLite offline queue
│   ├── native/       # vision-camera frame processor plugin
│   ├── theme/        # design tokens, light and dark
│   ├── i18n/         # t() plus en and hi bundles
│   ├── store/        # zustand — preferences and the session
│   ├── providers/    # app providers and the root error boundary
│   └── lib/          # storage and other small utilities
├── assets/
│   └── marker/       # the printable A4 scale-reference sheet, and its in-app preview
├── scripts/          # asset generators — run occasionally, output committed
├── test-utils/       # render() helper wrapping providers
└── __tests__/
```

**One build, two shells.** The org's mode comes off the session and the tab bar composes from it
(`src/features/navigation/tabs.ts`): enforcement sees Scan · Inspections · Sahayak, industry sees
Scan · Bulk · History · Sahayak. Mode A has no History tab because Inspections _is_ its history.
The other mode's route is removed from the navigator by `Tabs.Protected`, not merely hidden.

> The Expo template generates routes into `src/app/`. They live at `mobile/app/` here, because
> CLAUDE.md §2 is the authoritative layout. expo-router resolves either.

Each `src/` folder carries an `index.ts` naming the TRD requirements it will implement. The tab
shell, theme, i18n and shared primitives landed in Stage 0; domain types and the dummy-data engine
in Stage 1. The feature screens arrive in this order: Capture → Context form → Processing →
Findings → Report → History → Sahayak. Status per stage lives in
[docs/04-frontend-plan.md](../docs/04-frontend-plan.md), which is updated in the same change that
completes a stage.

---

## Conventions

From CLAUDE.md §5, enforced in CI:

- **No `any` in `src/api/` or `src/domain/`.** An eslint override makes it an error in those two
  folders, and `reportUnusedDisableDirectives` stops a disable comment being the way around it.
  `src/api` is generated from the backend's OpenAPI schema and `src/domain` mirrors the Pydantic
  schemas — an `any` in either is how the two sides silently drift.
- **Server state via TanStack Query. Local UI state via zustand. Never put server data in
  zustand.** The offline queue is neither: it is durable local state in SQLite.
- **Verdicts are four-valued** — `PASS | FAIL | BORDERLINE | NOT_ASSESSABLE` (`src/domain`).
  Never collapse BORDERLINE into FAIL, in a type, a filter or a UI grouping (CLAUDE.md §3.4).
- **Money as integer paise, lengths as float millimetres.** Never mix units in a name —
  `heightMm`, not `height`.
- **Every findings screen carries the advisory disclaimer**: pre-audit tool, not a certification
  (CLAUDE.md §3.8).

---

## Types come from the backend

Types flow one way. The backend publishes an OpenAPI schema; this app generates its client from
it. Never hand-maintain duplicate types (CLAUDE.md §2).

```bash
npm run gen:api                              # against http://localhost:8000
ANUPALAN_API_URL=https://api.example npm run gen:api
```

Today this snapshots the schema to `src/api/openapi.json`. Generating the typed client and query
hooks needs a generator dependency, which needs approval before it is added (CLAUDE.md §7) — see
[scripts/gen-api.mjs](scripts/gen-api.mjs).

Until the real API exists, screens read through one seam and never wait on the backend:

```
screens → hooks (TanStack Query) → src/api/transport.ts → mock | live
```

`EXPO_PUBLIC_API_MODE` picks the implementation and defaults to `mock`. The live HTTP transport is
already written against the TRD §5 contract, so the fixtures were built to satisfy a real
interface rather than the interface being shaped around the fixtures. Cutover at Stage 13 is
setting the flag to `live` and deleting `src/api/mock/` — no screen changes
(docs/03-implementation-plan.md §P3.6).

---

## Scripts

| Script                 | What it does                                    |
| ---------------------- | ----------------------------------------------- |
| `npm start`            | Metro with `--dev-client`                       |
| `npm run android`      | Metro and launch on a connected Android device  |
| `npm run lint`         | eslint, `--max-warnings=0`                      |
| `npm test`             | jest                                            |
| `npm run typecheck`    | regenerate route types, then `tsc --noEmit`     |
| `npm run types:routes` | rewrite `.expo/types/router.d.ts` without Metro |

Two asset generators are run by hand, not by npm, because they need Python tools that are in no
manifest. Their output is committed, so you only run them if you change what they draw:

| Script                                 | Produces                                      | Needs                                      |
| -------------------------------------- | --------------------------------------------- | ------------------------------------------ |
| `python3 scripts/make-marker-sheet.py` | the printable A4 marker sheet and its preview | `opencv-contrib-python-headless`, `Pillow` |
| `python3 scripts/make-sample-label.py` | the fixture label image and its coordinates   | `Pillow`                                   |
| `npm run gen:api`                      | refresh the OpenAPI schema from the backend   |
| `npm run format`                       | prettier write                                |

---

## Gotchas

- **Expo Go cannot run frame processors.** See the top of this file.
- **The marker must print at exactly 100% scale.** If the printer scales the page, every
  millimetre downstream is wrong and the bug looks like a code bug for days. The sheet at
  [assets/marker/anupalan-marker-a4.pdf](assets/marker/anupalan-marker-a4.pdf) carries its own
  100 mm ruler for exactly this — measure it before you use it. The app will not save a reference
  until you confirm you did.
- **Never hand-draw an ArUco tag.** The predefined dictionaries are fixed codebooks, not
  algorithms, so a tag that merely looks right is not in the dictionary and will never be detected.
  Regenerate the sheet with `scripts/make-marker-sheet.py`, which reads the pattern from OpenCV and
  refuses to write a sheet the detector cannot read back.
- **There is no web target.** MMKV has no web implementation, so `expo start --web` would crash
  at the first preference read. The `web` script was removed rather than left to mislead.
- **React Native Testing Library 14 is async.** `render()` and `unmount()` both return promises;
  forgetting to await them gives you "`render` function has not been called", which reads like a
  setup problem and is not. Use the helper in `test-utils/render.tsx`.
- **`expo-env.d.ts` and `.expo/types/` are generated** and gitignored. The typed-route
  declarations are normally written by the **dev server's** file watcher, so on a fresh clone or in
  CI `tsc` would check against a stale route union — ours still listed a route deleted two stages
  earlier, which went unnoticed only because nothing navigated anywhere yet. Use
  `npm run typecheck`, which regenerates them first. `npx expo export` does **not** write them.
- **`react-native-vision-camera` 5.x is not a config plugin.** It ships no `app.plugin.js`, so
  listing it in `app.json` `plugins` makes `expo config` and `expo prebuild` fail with
  `PluginError`. It also declares no permission in its own manifest, so the camera permission is
  declared directly as `android.permissions` in [app.json](app.json). Check for an
  `app.plugin.js` in the package before adding anything to `plugins`.
- **`eas.json` takes `//` line comments, but not a `"//"` key.** The schema rejects an unknown
  property, so `"//": "a note"` inside a build profile fails validation with
  `"build.development.//" is not allowed` — and it fails on `eas init`, before you get anywhere
  near a build. eas-cli parses the file as JSON first and falls back to JSON5, so real `//`
  comments are fine. Note that if EAS ever patches the file itself (remote version bumps), it
  rewrites it as plain JSON and the comments go.
- **Native folders are not committed.** `android/` and `ios/` are generated by prebuild. Configure
  native behaviour through `app.json` plugins, never by editing generated native code.
