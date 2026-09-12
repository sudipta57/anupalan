# Anupalan — documentation index

Compliance engine for packaged commodities in India.
**SIH26034** (Legal Metrology label compliance scanning) + **SIH26107** (BIS / Indian Standards assistant), Department of Consumer Affairs.

| Doc | Read it when |
|---|---|
| `../CLAUDE.md` | Loaded automatically by Claude Code every session. Repo layout, non-negotiables, commands, conventions, gotchas. Humans should read it once too. |
| `01-architecture.md` | Before changing the pipeline, rules engine, data model or any technology choice. §9 records what was rejected and why — check it before re-litigating a decision. |
| `02-trd.md` | Before implementing any feature. Every FR/NFR has an acceptance test; the test is the definition of done. |
| `03-implementation-plan.md` | At the start of each phase, and before handing anything to Claude Code (§7 has the handoff template). |

| `04-backend-implementation-plan.md` | Before starting any `backend/` work. Backend-only sequence B0–B23, one ready-to-paste handoff card per work package, the dependency asks, and the backend release gates. |

| `05-frontend-plan.md` | Before any mobile work. The fourteen frontend stages, each with its TRD requirement and acceptance criterion, and a live status per stage. |
| `../rulepacks/lm-2011-v1.yaml` | Before touching rule logic. Thresholds live in the pack, never in code. |
| `decisions.md` | Append a dated line on every architectural change. Create on first change. |
| `eval-results.md` | Regenerate before every demo. Create at P0. |

## The three things to keep straight

1. **The LLM never decides compliance.** It extracts fields and writes explanations. Verdicts come from a deterministic function over a versioned rule pack, so they are reproducible, citable and regression-testable.
2. **Millimetres need a physical reference.** Every metric rule depends on the marker-based homography. No marker means metric rules return NOT_ASSESSABLE, not a guess.
3. **Standards texts are priced and copyrighted.** The BIS assistant is built on public QCO/CRS/FAQ/metadata only, and refuses to state technical clause content. That refusal is a design feature, not a gap.

## Immediate next action

P0, the measurement spike (`03-implementation-plan.md`). It is the only phase that can invalidate the concept, so it runs before anything else is built.
