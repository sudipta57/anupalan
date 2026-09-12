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

### What *does* work without a dev build

`npx expo start` brings up Metro and the non-camera screens render. Lint, typecheck and tests all
run with no device:

```bash
npm run lint          # eslint, zero warnings tolerated
npm test              # jest
npx tsc --noEmit      # typecheck
```

---

## Layout

Per CLAUDE.md §2:

```
mobile/
├── app/              # expo-router screens (currently the Expo default)
├── src/
│   ├── api/          # generated client + TanStack Query hooks — no `any`
│   ├── domain/       # types shared with backend schemas — no `any`
│   ├── features/     # capture, findings, sahayak, history, reports
│   ├── components/
│   ├── db/           # SQLite offline queue
│   ├── native/       # vision-camera frame processor plugin
│   ├── constants/    # theme (Expo default)
│   └── hooks/        # (Expo default)
├── assets/
└── __tests__/
```

> The Expo template generates routes into `src/app/`. They live at `mobile/app/` here, because
> CLAUDE.md §2 is the authoritative layout. expo-router resolves either.

Each `src/` folder carries an `index.ts` naming the TRD requirements it will implement. No screen
beyond the Expo default exists yet — screens land in P3, in this order: Capture → Context form →
Processing → Findings → Report → History → Sahayak.

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

Until the real API exists, mobile builds against an MSW mock generated from the same schema, so it
never waits on the backend (docs/03-implementation-plan.md §P3.6).

---

## Scripts

| Script | What it does |
|---|---|
| `npm start` | Metro with `--dev-client` |
| `npm run android` | Metro and launch on a connected Android device |
| `npm run lint` | eslint, `--max-warnings=0` |
| `npm test` | jest |
| `npm run gen:api` | refresh the OpenAPI schema from the backend |
| `npm run format` | prettier write |

---

## Gotchas

- **Expo Go cannot run frame processors.** See the top of this file.
- **The marker must print at exactly 100% scale.** If the printer scales the page, every
  millimetre downstream is wrong and the bug looks like a code bug for days. Verify printed
  markers with a ruler.
- **`expo-env.d.ts` and `.expo/types/` are generated** by `expo start` and are gitignored. On a
  fresh clone, `npx tsc --noEmit` reports missing CSS-module and router types until you have
  started Metro once.
- **`react-native-vision-camera` 5.x is not a config plugin.** It ships no `app.plugin.js`, so
  listing it in `app.json` `plugins` makes `expo config` and `expo prebuild` fail with
  `PluginError`. It also declares no permission in its own manifest, so the camera permission is
  declared directly as `android.permissions` in [app.json](app.json). Check for an
  `app.plugin.js` in the package before adding anything to `plugins`.
- **Native folders are not committed.** `android/` and `ios/` are generated by prebuild. Configure
  native behaviour through `app.json` plugins, never by editing generated native code.
