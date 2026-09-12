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

### 2026-09-12 — Mobile mocks the backend at a transport seam rather than with MSW
**Context:** `03-implementation-plan.md` §P3.6 suggests mocking the API with MSW generated from the
OpenAPI schema so the app never waits on the backend. The backend is being built in parallel, so
the app needs dummy data for every screen from Stage 1.
**Decision:** One interface, `src/api/transport.ts`, with two implementations — fixtures and HTTP —
chosen by `EXPO_PUBLIC_API_MODE`. Hooks, screens and types are identical in both. The HTTP
transport was written first so the fixtures had to satisfy a real contract.
**Alternatives:** MSW — rejected because it needs polyfills under Hermes and has a history of
friction in React Native, and because it buys network-level interception the app does not need: the
seam is one function call wide. Hand-written stubs inside each hook — rejected because they are the
thing that never gets deleted.
**Consequences:** Cutover at Stage 13 is an env var plus deleting `src/api/mock/`, with no change
above the transport. The cost is that the mock is not exercised over real HTTP, so serialisation
mistakes — casing, date formats — will surface at cutover rather than before it. The mock's failure
modes are reachable from a dev panel in Settings, which is what keeps the degradation paths in
`01-architecture.md` §11 demonstrable.
**PR:** n/a (Stage 1) · **Requirement:** n/a

### 2026-09-12 — Session state lives in zustand, read synchronously, and composes the navigation
**Context:** Mode is an org-level attribute (`01-architecture.md` §3) and the two shells differ in
their tab bars, so navigation has to know the org's mode before the first paint. CLAUDE.md §5 says
server data belongs in TanStack Query, and `user`/`org` come from the server.
**Decision:** Tokens plus the user and org live in a zustand store that reads MMKV **synchronously**
in its initialiser — no `persist` middleware. Navigation composes from `tabsForMode(mode)`, and the
auth boundary is `Stack.Protected`. Settings moved off the tab bar to a root route behind a header
gear. Refresh-on-401 lives in the transport, single-flight, behind `src/api/auth-bridge.ts`.
**Alternatives:** The session as a TanStack query — rejected because TRD §5 has no "who am I"
endpoint, so it would be a query with nothing to fetch. zustand's `persist` — rejected because it
resolves `getItem` through `Promise.resolve`, so hydration lands after the first render and every
cold start flashes the login screen at a signed-in user. Redirecting from a mounted screen instead
of `Protected` — rejected because the screen mounts and fetches first. Settings as a fifth tab —
rejected because Android truncates labels at five.
**Consequences:** Two MMKV instances, so signing out cannot take preferences with it. The refresh
token sits in unencrypted MMKV until `expo-secure-store` is approved — recorded as flag 11 in
`04-frontend-plan.md`. One subscription in `AppProviders` empties the query cache whenever the org
id changes, which is the only thing stopping cached org-scoped data from crossing accounts on a
shared phone. Three contract gaps now need agreeing with the backend, all in `04-frontend-plan.md`:
no refresh endpoint, no session endpoint, and snake_case in TRD §5 against camelCase in the client.
**PR:** n/a (Stage 2) · **Requirement:** n/a

### 2026-09-12 — The printable marker is generated from OpenCV's codebook, at 15 px/mm
**Context:** FR-02 needs a scale reference of an exactly known physical size, and every millimetre
in every report is derived from it. Two things can go wrong silently: the tag's **bit pattern**
(the ArUco predefined dictionaries are fixed codebooks, not algorithms, so a hand-drawn tag is
simply not in the dictionary) and the **print scale** (a printer set to "fit to page" rescales
every downstream millimetre by a constant factor).
**Decision:** `mobile/scripts/make-marker-sheet.py` reads the tag from
`cv2.aruco.DICT_4X4_50` — the same library the backend's detector uses — and renders an A4 page at
exactly **15 px/mm**, which makes the 40 mm tag exactly 600 px, six cells of 100. The script fails
rather than writing a bad sheet if anything is printed inside the 5 mm quiet zone, if the footer
collides with the body, or if a detector round trip does not find exactly one marker, id 0, at
40 mm. The sheet carries its own 100 mm ruler and an ID-1 outline, so the print scale and the
user's card can both be checked against the paper itself.
**Alternatives:** Hardcoding a bit pattern from memory or from a web image — rejected outright; it
would not be in the dictionary and nothing in the app would say so. Rendering at 300 dpi — rejected
because 40 mm is then 472.44 px and the six cells do not divide evenly. Shipping the marker as an
in-app download — deferred: it needs `expo-asset` and a Metro `assetExts` change, and printing from
a laptop is the actual workflow (flag 13).
**Consequences:** Regenerating the sheet needs `opencv-contrib-python-headless` and `Pillow`, which
are script-time tools and in no manifest — the same arrangement as `make-sample-label.py`. The PDF
is a repo artefact, not bundled into the app; only the preview PNG ships. The sheet's constants are
now duplicated in spirit with the backend's `make_chart.py` (P0.1, unwritten): both must use
DICT_4X4_50 id 0 at 40.0 mm, and a disagreement would produce wrong measurements that no test on
either side would catch (flag 14). A verified-once ruler check is stored with the reference, so the
store never holds an unverified one.
**PR:** n/a (Stage 3) · **Requirement:** FR-02

### 2026-09-12 — Capture gates are a pure policy behind an evaluator seam, simulated until the plugin lands
**Context:** FR-01's four gates decide when the shutter is enabled, and the shutter rule is the
product: a blurred or angled frame yields a glyph height that is confidently wrong, which is worse
than one that is missing. The native ArUco frame processor that would supply real metrics is the
riskiest piece of the mobile work, and `03-implementation-plan.md` §P3.3 explicitly says not to let
it block the rest of the app.
**Decision:** `evaluateGates(metrics)` is pure and holds the whole policy, including the thresholds.
`GateEvaluator` is a one-method interface supplying `FrameMetrics`; today a simulation, later the
frame processor, with nothing above the seam changing. Tilt is **three-valued** — `pass | fail |
unknown` — because it is the angle to the marker's plane and there is no angle without a marker.
`useGates` takes no `active` flag: mounting the live view is the activation.
**Alternatives:** Computing gates inside the camera screen — rejected because the policy would then
be untestable without hardware, and hardware is exactly what CI does not have. Treating a missing
marker as a tilt *failure* — rejected because the instruction it produces ("hold flatter") sends the
user to fix the wrong thing. An `active` flag on the hook — rejected because the window between the
flag flipping and the effect running leaves the previous session's metrics in state, and the worst
case is a shutter enabled by a stale all-green report.
**Consequences:** The gate policy is fully tested with no device, including every threshold
boundary. What is **not** tested anywhere is the camera itself — preview, permissions,
`capturePhoto`, the disk write — so FR-01 is code-complete and not done until the device checklist
in `04-frontend-plan.md` Stage 4 has been walked (flag 15). Captures are written to the document
directory, not the cache, because FR-04 requires them to survive a force-close and the system
deletes caches under storage pressure. An abandoned capture stays on disk until Stage 6's queue
adopts it; losing an inspector's photograph is the worse of the two failures.
**PR:** n/a (Stage 4) · **Requirement:** FR-01
