# Contributing to Anupalan

Read [CLAUDE.md](CLAUDE.md) first. It is the repository contract — layout (§2),
non-negotiables (§3), conventions (§5), testing rules (§6) and what to ask about before
doing (§7). This file covers process; CLAUDE.md covers substance. Where they disagree,
CLAUDE.md wins.

---

## 1. Commits — conventional commits

Every commit message follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `build`, `ci`, `revert`

**Scopes** track the layout: `vision`, `extraction`, `rules`, `reporting`, `bis`, `llm`,
`api`, `worker`, `models`, `mobile`, `infra`, `docs`, `rulepack`.

Subject line: imperative mood, lower case, no trailing full stop, under 72 characters.

```
feat(vision): FR-23 glyph cap-height measurement in mm
fix(rules): FR-25 borderline band was inclusive on the wrong side
test(rules): add BORDERLINE case for LM-9-2-TABLE2
docs(architecture): record the pgvector-over-separate-vector-db decision
```

A breaking change gets a `!` and a `BREAKING CHANGE:` footer — for this repo that mostly
means an API contract `mobile/` consumes.

---

## 2. One PR per TRD requirement id

**Every PR maps to exactly one requirement** from [docs/02-trd.md](docs/02-trd.md), and the
PR title carries its id:

```
feat(vision): FR-23 glyph metrology
feat(api): FR-20 scan intake and presigned uploads
feat(rules): FR-26 rule pack loading and validation
```

Ids are `FR-xx` functional, `NFR-xx` non-functional, `DR-xx` data, `SR-xx` security.

Why one requirement per PR: every requirement in the TRD has an acceptance test, and that
test is the definition of done. A PR covering three requirements cannot be reviewed against
three acceptance criteria without guessing which change satisfies which.

If your work genuinely has no requirement id, it is either `chore`/`docs`/`refactor` — say so
in the PR — or the TRD is missing a requirement, in which case add it in the same PR and say
that too.

**Docs ship in the same PR as the code.** Architecture changes update
[docs/01-architecture.md](docs/01-architecture.md) and append a dated line to
[docs/decisions.md](docs/decisions.md), in that same PR. A doc that lags the code by two
weeks is worse than no doc.

---

## 3. Do not edit tests to make them pass

From [CLAUDE.md](CLAUDE.md) §6, and it is the rule most likely to be broken under deadline
pressure:

> **Do not edit tests to make them pass.** Tests are written before implementation and are
> the specification. If a test looks wrong, say so and stop — do not change it.

Concretely:

- Tests are written **before** the implementation they test. The test is the spec.
- If a test fails, the default assumption is that **the implementation is wrong**.
- If you are convinced a test is genuinely wrong, **stop and raise it** — in the PR, in an
  issue, in review. Get agreement, then change the test in its own commit with the reasoning
  in the message. Never fold a test change into the commit that makes it pass.
- **Golden files** in `backend/tests/fixtures/` pin pipeline output. A diff in a golden file
  must be a deliberate, reviewed change with the reason stated in the PR — never a silent
  regeneration. `git checkout` the fixture and re-run rather than accepting a surprise diff.
- Relaxing an assertion, widening a tolerance, adding `pytest.mark.skip`, `xfail`, or
  narrowing an input set to dodge a failure all count as editing the test to make it pass.

An agent or a contributor who can edit their own tests will eventually make them pass the
wrong way. That is the whole reason for this rule.

Coverage floors: `services/rules/` and `services/vision/` hold **80%** — these are where a
bug is silent, because a wrong millimetre looks exactly like a right one.

---

## 4. Before you open a PR

```bash
# backend
cd backend && ruff check . && mypy app/services && pytest

# mobile
cd mobile && npm run lint && npm test
```

CI runs the same commands on push and pull request. Green locally before review, please.

---

## 5. Ask before doing

From [CLAUDE.md](CLAUDE.md) §7 — stop and ask rather than deciding alone:

- **Adding any dependency** (backend or mobile). CI will not fail you for it; review will.
- Changing the database schema or writing a migration
- Changing an API contract that `mobile/` consumes
- Adding or replacing a managed service (Neon, Redis Cloud, R2), or repointing one at a different provider
- **Changing anything in `rulepacks/`** — rule text has legal consequences and needs review
- Anything touching a §3 non-negotiable

Free to decide alone: internal refactors behind a stable interface, test additions,
error-message wording, logging, performance work that does not change output.

---

## 6. The non-negotiables, in one breath

You will be asked about these in review, so know them ([CLAUDE.md](CLAUDE.md) §3):

1. **The LLM never decides compliance.** Verdicts come from `services/rules/evaluate()`,
   a pure deterministic function over a rule pack.
2. **Thresholds live in the rule pack, never in code.** No millimetre value, no table row, no
   effective date in a `.py` file. `PX_PER_MM` is imported from config — never write `20` at
   a call site.
3. **Millimetres require the marker.** No marker means metric rules return `NOT_ASSESSABLE`.
   Never estimate a physical size.
4. **Verdicts are four-valued.** Never collapse `BORDERLINE` into `FAIL`.
5. **Never ingest priced Indian Standards texts** into the BIS corpus.
6. **Every finding carries `rulepack_version`.**
7. **Every query is org-scoped**, through `repositories/`. Cross-org access returns 404, not
   403 — do not leak existence.
8. **Every report and findings screen carries the advisory disclaimer.**

---

## 7. Secrets

No secret, token, key, password or real credential in any committed file — including
`.env.example`, which carries variable names and obviously-fake local defaults only.
`.env` is gitignored; keep it that way. If you commit a credential, rotate it first, then
rewrite history.
