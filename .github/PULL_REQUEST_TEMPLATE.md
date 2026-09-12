## What and why

<!-- One or two sentences. What changes, and why now. -->

## TRD requirement

<!--
One requirement per PR, and the title carries its id (CONTRIBUTING.md §2):
    feat(vision): FR-23 glyph metrology
If this genuinely maps to no requirement, say which it is — chore / docs / refactor — or add the
missing requirement to docs/02-trd.md in this PR and say so.
-->

**Requirement id:** <!-- e.g. FR-23 -->
**Acceptance criterion it satisfies:** <!-- quote it from docs/02-trd.md -->

---

## Checklist

- [ ] **TRD requirement id** is in the PR title and named above; this PR covers **exactly one**
- [ ] **Tests added**, and they were written **before** the implementation
- [ ] **No test was edited to make it pass.** If a test looked wrong I stopped and raised it
      rather than changing it (CLAUDE.md §6, CONTRIBUTING.md §3). Any golden-file diff is
      deliberate and explained below
- [ ] **Docs updated in this same PR** — `01-architecture.md` for an architectural change, plus a
      dated line in `docs/decisions.md`; `02-trd.md` if a requirement changed
- [ ] **No new dependency**, or it is listed below and was approved before I added it
      (CLAUDE.md §7)
- [ ] `ruff check .`, `mypy app/services` and `pytest` pass locally (backend)
- [ ] `npm run lint` and `npm test` pass locally (mobile)
- [ ] **No secret, token, key or real credential** in any file, `.env.example` included

## Non-negotiables touched (CLAUDE.md §3)

Tick only what applies, and say how it is respected:

- [ ] Verdicts still come from `services/rules/evaluate()` — the LLM decides no compliance
- [ ] No threshold, millimetre value, table row or effective date added to a `.py` file
- [ ] `PX_PER_MM` imported from config, never written as `20` at a call site
- [ ] Metric rules return `NOT_ASSESSABLE` without a marker — no estimated physical sizes
- [ ] `BORDERLINE` stays distinct from `FAIL` everywhere it appears
- [ ] No priced Indian Standards text added to the BIS corpus
- [ ] Every finding carries `rulepack_version`
- [ ] Every query is org-scoped via `repositories/`; cross-org access returns 404, not 403
- [ ] Advisory disclaimer present on any report or findings surface touched

## New dependencies

<!-- Name, why it is needed, what was considered instead, and who approved it. "None" is the
     expected answer. A dependency added without prior approval will be asked to come back out. -->

None.

## Golden-file / fixture changes

<!-- Any diff under backend/tests/fixtures/ must be deliberate and reviewed. Say what changed in
     the pipeline to cause it, and why the new output is correct. "None" if untouched. -->

None.

## How it was verified

<!-- The commands you ran and what they printed. For measurement or rules work, the numbers. -->
