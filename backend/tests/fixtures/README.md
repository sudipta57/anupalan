# tests/fixtures

Committed test data. Loaders and the golden-file helper are in [`../conftest.py`](../conftest.py).

## Layout

```
fixtures/
├── profiles/<name>.json    product profiles — the context a scan is evaluated in
├── ocr/<name>.json         recorded OCR word lists, replayed by the stub engine (B6)
├── findings/<name>.json    GOLDEN — committed pipeline output
└── rulepacks/<name>.yaml   deliberately broken packs, for the loader's rejection tests
```

## The golden-file rule

`findings/` holds golden files. They pin the committed output of the pipeline.

**A diff in a golden file must be a deliberate, reviewed change, never a silent update**
(`CLAUDE.md` §6). A verdict that changes without anyone deciding it should is the exact failure
this repository is built to prevent: findings are legal statements about a product, and a report
regenerated next year must reproduce the verdict issued under the rules in force at scan time.

So when a golden test fails, the question is never "how do I make this pass". It is:

1. **Did the rule pack change?** Then the diff is expected — but the pack change needed review of
   its own first (`CLAUDE.md` §7), and the new findings must carry the new `rulepack_version`.
2. **Did the pipeline change?** Then either the change is an intended improvement, and the diff
   goes in the PR for a human to read line by line, or it is a regression and the code is wrong.
3. **Did neither change?** Then something is non-deterministic, which is a bug in itself —
   `evaluate()` is a pure function and must produce byte-identical output across runs.

To regenerate after a reviewed change:

```bash
pytest tests/test_pipeline_golden.py --update-golden   # rewrites, and FAILS on purpose
git diff tests/fixtures/findings/                      # read every line
pytest tests/test_pipeline_golden.py                   # then confirm green
```

`--update-golden` deliberately fails the run it rewrites, so "it passed" can never mean "it
silently rewrote the truth".

## Size

Keep images under 300 KB. These are committed binaries; the large image corpora live under
`eval/`, which is gitignored (see `docs/eval-results.md`).
