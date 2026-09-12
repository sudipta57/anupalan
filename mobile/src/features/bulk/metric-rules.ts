/**
 * Which rules are metric — FR-10, and the no-marker path of `01-architecture.md` §11.
 *
 * A metric rule is a **millimetre comparison**. It cannot be evaluated without a physical scale, and
 * a physical scale reaches this system exactly one way: the marker homography (CLAUDE.md §3.3). No
 * marker, no millimetres. A marketplace listing has no marker and never will.
 *
 * **Why this list is in app code at all**, given that verdicts are the backend's to decide
 * (CLAUDE.md §3.1):
 *
 * It is not here to compute a verdict. It is here so the client can *check* one. FR-10's acceptance
 * criterion is that **no metric rule ever returns PASS or FAIL from listing text alone**, and a
 * criterion the client cannot evaluate is a criterion nobody will notice breaking. If the rules
 * engine one day gains a Rule 9 path that infers a numeral height from a listing's own image — a
 * plausible, well-meant feature — every affected listing would come back with a confident millimetre
 * verdict, and nothing in the app would object. `guard.ts` is what objects.
 *
 * It lived in the mock transport before this, which was the wrong home twice over: the mock is
 * deleted at Stage 13, and a guard that only exists in the fixture layer guards nothing.
 *
 * **Kept in step with the pack by hand, which is a known hazard.** These ids are the Rule 9 family in
 * `rulepacks/lm-2011-v1.yaml`. A new metric rule added to the pack and not added here would be a rule
 * the guard waves through — see flag 31. The right long-term answer is a `metric: true` flag on the
 * rule in the pack, surfaced on the finding, so the client reads it rather than remembering it.
 */

/**
 * The Rule 9 family.
 *
 * `LM-9-QTY-CLEAR-SPACE` is included although it reads like a layout rule rather than a measurement:
 * it is about the *area* surrounding the quantity declaration, which is a measured region of a
 * rectified image. From a listing there is no panel and no area, so it is as unassessable as a
 * numeral height.
 */
export const METRIC_RULE_IDS: readonly string[] = [
  'LM-9-2-TABLE1',
  'LM-9-2-TABLE2',
  'LM-9-LETTER-HEIGHT',
  'LM-9-3-WIDTH',
  'LM-9-QTY-CLEAR-SPACE',
] as const;

const METRIC_RULE_SET = new Set(METRIC_RULE_IDS);

export function isMetricRule(ruleId: string): boolean {
  return METRIC_RULE_SET.has(ruleId);
}

/**
 * Rules that need the marketplace page rather than the pack or the listing copy.
 *
 * Rule 6(10A)'s country-of-origin filter is a property of the **page**: whether the marketplace
 * offers a searchable, sortable filter. Pasted listing text cannot answer that in either direction —
 * its absence from the copy is not evidence the filter is missing from the site. So it is assessable
 * from a `url` row and `not_in_listing` from a `text` row, which is the one place the two input kinds
 * genuinely differ in what they can support.
 */
export const PAGE_CONTEXT_RULE_IDS: readonly string[] = ['LM-6-10A-COO-FILTER'] as const;

const PAGE_CONTEXT_RULE_SET = new Set(PAGE_CONTEXT_RULE_IDS);

export function needsPageContext(ruleId: string): boolean {
  return PAGE_CONTEXT_RULE_SET.has(ruleId);
}
