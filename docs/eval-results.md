# Evaluation results

**Re-run every evaluation before any demo, and commit the numbers here with a date**
(CLAUDE.md §6, docs/03-implementation-plan.md §P5.1). A stale number is worse than no number: it
gets quoted on a slide.

The evaluation sets themselves are specified in [`02-trd.md`](02-trd.md) §7. Build them before
building the features they measure.

| Set | Measures | Headline metric |
|---|---|---|
| **E1** | Metrology ground truth — 300 images, digits at known cap-heights | MAE in mm, and % within ±0.3 mm |
| **E2** | Extraction ground truth — 200 annotated labels, 15 field codes | per-field precision / recall / F1 |
| **E3** | Rule verdicts — 100 human-reviewed labels | **false-FAIL rate** (target ≤ 2%) |
| **E4** | Sahayak QA — 60 questions incl. 10 unanswerable | citation accuracy, answer accuracy, refusal correctness |

**E1 and E3 are the ones that matter most.** E1 decides whether the core differentiator is real
(and the P0 decision gate hangs on it). E3's false-FAIL rate is the number that decides whether
anyone trusts the tool — accusing a compliant label is the failure that kills it.

```bash
cd backend
python -m scripts.eval_e1 --dir ../eval/e1    # measurement accuracy
python -m scripts.eval_e3 --dir ../eval/e3    # rule verdicts, false-FAIL rate
python -m scripts.eval_e4 --set ../eval/e4    # sahayak citations
```

Image corpora live under `eval/` and are **not committed** — they are large binaries, and `eval/`
is gitignored. Keep them backed up out of band; only the numbers live here.

---

## Format

One dated section per run. Record the commit and the rule pack version, or the number cannot be
reproduced or explained later.

```
## YYYY-MM-DD — <why this run: demo, gate, release>
**Commit:** <short sha> · **Rule pack:** LM-2011-v1.0 · **Run by:** <name>

### E1 — metrology
samples: 420 glyph rows across 60 images
MAE: 0.18 mm   |  within ±0.3mm: 92.4%  |  within ±0.5mm: 98.1%
worst case: 0.71 mm  (angle=25, dist=40, light=dim)
by truth height:  0.8mm MAE 0.24 | 1.0mm 0.19 | 2.0mm 0.14 | 4.0mm 0.11 | 6.0mm 0.09

### E3 — rule verdicts
labels: 100
false-FAIL rate: 1.8%   |  false-PASS rate: 3.1%
per-rule confusion matrix: <path to the committed table>

### E4 — sahayak
E4: 60 questions
answer accuracy 87%  | citation accuracy 93%  | hallucinated citations 0
refusals: 10/10 correct on priced-standard content

**Gate:** pass | fail — <which gate, and the decision taken>
**Notes:** what changed since the last run, and what the worst cases have in common.
```

---

## Runs

<!-- Append below, newest first. -->

**No evaluation has been run yet.** The repository is scaffolded; no pipeline exists to measure.

The first entry here is **E1, from the P0 measurement spike** — the phase that can invalidate the
concept, which is why it runs before anything else is built. Its decision gate
(docs/03-implementation-plan.md §P0):

| E1 result | Action |
|---|---|
| MAE ≤ 0.3 mm and ≥ 90% within ±0.3 mm | Proceed as planned; this becomes the headline slide |
| MAE 0.3–0.5 mm | Proceed, but tighten capture gates (max 15° tilt, max 30 cm) and widen the BORDERLINE band |
| MAE > 0.5 mm | **Do not claim automated font checking.** Reposition to presence/format checking plus assisted measurement where the user taps the two ends of a glyph |

Decide that in week one, not in the demo.
