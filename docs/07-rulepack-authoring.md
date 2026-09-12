# Anupalan — rule pack authoring guide

**Doc version:** v1.0 · **Written:** 12 Sep 2026
**Applies to:** `rulepacks/*.yaml` · **Engine:** `backend/app/services/rules/`

A rule pack is the legal logic of this system, written as data. It is the reason a Legal Metrology
amendment is a reviewed file change rather than a deploy (NFR-06), and the reason every verdict can
name the clause behind it.

> **Changing anything in `rulepacks/` is ask-first** (`CLAUDE.md` §7). Rule text has legal
> consequences. A pack is reviewed before it is published, and the pack in this repository is an
> **engineering transcription pending legal review** — it says so in its own header and in every
> report generated from it.

---

## 1. The contract the engine holds you to

Four rules, none of them negotiable, and each of them is enforced by something other than good
intentions.

**1. No threshold lives in Python.** Every millimetre, every table row, every effective date is in
the pack. `evaluate.py` contains no bare float, and `tests/test_hardening.py` greps for date
literals in `services/rules/` and fails if one appears. If you need a number, add it to the pack —
if the engine cannot read it from there yet, that is an engine change, and it is a smaller one than
you think.

**2. Every rule carries a citation.** `id`, `kind`, `citation`, `severity` and `message` are
required by the schema, so a rule without a citation is rejected at load. A finding without a
citation cannot go in a report, and a schema is what has to stop it — not a code review.

**3. Verdicts are four-valued.** `PASS | FAIL | BORDERLINE | NOT_ASSESSABLE`. You cannot author a
fifth. A rule that does not apply produces **no finding**; `assemble()` recovers the difference
from the pack and lists it under `not_applicable_rule_ids`.

**4. A metric rule with no measurement is `NOT_ASSESSABLE`, always.** No marker means no
millimetres. You cannot write a pack that guesses a length, because the engine will not evaluate a
metric rule without one.

---

## 2. Anatomy

```yaml
meta:
  code: LM-2011                 # stable; with version it forms LM-2011-v1.0
  version: "1.0"                # A STRING. See §6.
  effective_from: "2011-04-01"
  jurisdiction: IN
  source_notes: >
    Which instrument, which amendments, and the review status.
  measurement:
    px_per_mm: 20
    default_uncertainty_mm: 0.25
    borderline_policy: "if |observed - required| <= uncertainty then BORDERLINE"

tables:                         # lookup tables the rules reference by name
  numeral_height_by_weight_volume:
    unit_basis: weight_or_volume
    rows:
      - { max_qty_g_or_ml: 200,  min_mm_normal: 1, min_mm_embossed: 2 }
      - { max_qty_g_or_ml: 500,  min_mm_normal: 2, min_mm_embossed: 4 }
      - { max_qty_g_or_ml: null, min_mm_normal: 4, min_mm_embossed: 6 }   # open-ended top row

rules:
  - id: LM-6-1-A-MANUFACTURER
    kind: presence
    fields: [manufacturer_name, manufacturer_address]
    severity: major
    citation: "Rule 6(1)(a), Legal Metrology (Packaged Commodities) Rules, 2011"
    message: "Name and complete address of the manufacturer/packer must appear on the package."
```

### Required on every rule

| Key | Notes |
|---|---|
| `id` | Stable and unique. It is stamped on every finding and quoted in dashboards, so **never reuse an id for a different rule** — do not rename, add a new one and retire the old |
| `kind` | One of the seven in §3 |
| `citation` | The sub-rule, verbatim. This is printed in the report |
| `severity` | `major` / `minor`, used for ordering and for the report's emphasis |
| `message` | A template — see §4 |

### Optional

| Key | Notes |
|---|---|
| `effective_from` | ISO date. Before it, the rule yields **no finding** rather than a pass |
| `when` | A predicate on the profile, for `conditional` |

---

## 3. The seven kinds

| Kind | Answers | Needs a measurement? |
|---|---|---|
| `presence` | Is this declaration on the pack at all? | no |
| `any_of` | Is at least one of these present? | no |
| `format` | Does the declared value match a required form? | no |
| `metric` | Is a measured length at or above a threshold? | **yes** |
| `geometry` | Is there enough clear space around a declaration? | **yes** |
| `conditional` | Apply an inner rule only when `when` holds | inherits |
| `composite` | Several sub-rules judged together | inherits |

### `presence`

```yaml
- id: LM-6-1-B-COMMON-NAME
  kind: presence
  fields: [common_name]
  severity: major
  citation: "Rule 6(1)(b), LMPC Rules, 2011"
  message: "The common or generic name of the commodity must be declared."
```

A field is present only when it carries a **non-blank** value. An empty string extracted with high
confidence is an absent declaration, not a present one.

### `format`

```yaml
- id: LM-QTY-UNIT-SYMBOL
  kind: format
  field: net_quantity
  pattern: '^\d+(\.\d+)?\s?(g|kg|ml|l|L)$'
  severity: minor
  citation: "Rule 8, LMPC Rules, 2011"
  message: "Net quantity must use the standard unit symbol; found {observed}."
```

> **Format rules read `value_raw`, never `value_norm`.** Normalisation turns `250 gms` into
> `250 g` — which is exactly the defect `LM-QTY-UNIT-SYMBOL` exists to catch. Reading the
> normalised value makes the rule pass every label it was written for. The engine enforces this;
> the trap is worth knowing anyway, because it is the one you will hit when adding a format rule.

### `metric`

```yaml
- id: LM-9-2-TABLE1
  kind: metric
  field: net_quantity
  measure: numeral_height_mm
  table: numeral_height_by_weight_volume
  key: profile.net_qty_in_g_or_ml
  threshold_column: { normal: min_mm_normal, embossed: min_mm_embossed }
  comparator: ">="
  severity: major
  citation: "Rule 9(2) read with Table-I, LMPC Rules, 2011"
  message: "Numeral height is {observed} mm; Table-I requires at least {required} mm for {qty} {unit}."
```

Three things the engine does that you should author against:

- **The borderline band is symmetric and is checked first.** `|observed - required| <= uncertainty`
  makes the verdict `BORDERLINE` even when `observed > required`. An observed 2.05 against a
  required 2.0 with 0.25 uncertainty is BORDERLINE, not PASS.
- **Table rows are ordered, and the first row whose bound is not exceeded wins.** `500` belongs to
  the `≤500` row, not the one above it. A `null` bound is the open-ended top row and must be last.
- **`threshold_column` is selected by the profile's surface**, not by the pack picking one.
  Embossed, blown, formed, moulded and perforated all select the raised-text column.

### `conditional`

```yaml
- id: LM-6-1-IMPORTER
  kind: conditional
  when: { profile.is_imported: true }
  then:
    kind: presence
    fields: [importer_name, importer_address]
  severity: major
  citation: "Rule 6(1)(a) proviso, LMPC Rules, 2011"
  message: "Imported packages must declare the name and address of the importer in India."
```

When `when` is false there is **no finding at all** — not a PASS. An importer rule must never
appear on a domestic pack, in either direction.

---

## 4. Message templates

Rendered with `str.format_map` from values the engine supplies:

| Variable | Meaning |
|---|---|
| `{observed}` | What was found or measured |
| `{required}` | What the rule required |
| `{qty}` / `{unit}` | Net quantity and its unit |
| `{surface}` | The profile's surface |
| `{pdp}` | Principal display panel area |

**A missing variable raises.** "Numeral height is  mm; Table-I requires at least  mm" in an
inspection report is worse than a loud failure in a test, so the engine refuses to render an empty
placeholder. Only use a variable the rule's kind actually provides — a `presence` rule has no
`{observed}`.

Write the message for the person who has to fix the package. State what is wrong and what is
required, in that order, and do not restate the citation: the citation is printed separately and
verbatim.

---

## 5. Adding a rule

1. **Write the tests first.** Every new rule needs at least one PASS case, one FAIL case and one
   BORDERLINE case (`CLAUDE.md` §6). For a `conditional`, add a case where it does not apply and
   assert that **no finding** is produced.
2. Add the rule to the pack.
3. `pytest tests/test_rulepack_loader.py tests/test_rules.py` — the loader validates the schema and
   reports a **line number** on failure.
4. Check the golden files. `tests/test_pipeline_golden.py` pins the pipeline's output; a new rule
   changes it. That diff is a reviewed change, never a silent update — regenerate with
   `pytest --update-golden`, which **fails the run on purpose** so the diff has to be looked at and
   the suite re-run.
5. Update `docs/eval-results.md` after re-running E3. A new rule changes the false-FAIL rate, and
   that is the number that decides whether anyone trusts the tool.

---

## 6. Traps

**`version` must be a string.** `version: 1.0` is a float in YAML, and `1.10` and `1.1` are then
the same pack. The loader rejects a float version outright.

**A published version is immutable.** `rulepacks.body` stores the YAML, so a report regenerated
next year reproduces its verdict from the database alone. Editing a published pack in place means
that report now reproduces a verdict from rules that were changed since. Publish a new version.

**Never reuse a rule id.** It is stamped on findings that already exist, quoted in dashboards, and
resolved by `confirm-fields` recomputes. Retire and replace.

**The checksum is over the file bytes, not the parsed dictionary.** Reformatting the YAML changes
the checksum even though the rules are identical — which is correct: the checksum identifies the
artefact that was reviewed, and two files that parse to one dictionary are still two files.

**An effective date in the future yields no finding, not a failure.** Cases 10 and 11 of the
baseline suite differ only in `as_of`, and the difference must be visible in the output: "not yet
in force" and "could not be measured" mean opposite things to the person reading the report.

**Rule 9 is about numerals, and an unidentifiable glyph is not a numeral.** The two dots of the
colon in `Net Qty: 250 g` failed a compliant label at 0.75 mm until cap height was used to tell a
digit from a mark. If you write a rule about character heights, write it about the characters the
metrology layer can actually identify.

---

## 7. Publishing

Loaded at boot from `RULEPACK_PATH`, and — once FR-26's endpoint lands — through
`POST /v1/admin/rulepacks`, which validates, checksums and stores the body.

**An invalid pack is rejected and the previous one stays active.** That is the acceptance test for
FR-26 and the reason the loader validates before it activates: a pack that fails to parse must not
be able to take the engine down with it.

Before publishing:

- [ ] Every new rule has PASS, FAIL and BORDERLINE cases
- [ ] `pytest` green, golden diffs reviewed
- [ ] E3 re-run and the false-FAIL rate still ≤ 2%
- [ ] `docs/eval-results.md` updated with a date
- [ ] Legal review booked — a release blocker, not a nice-to-have
