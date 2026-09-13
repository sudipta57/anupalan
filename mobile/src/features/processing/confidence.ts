/**
 * Which extracted fields a human has to confirm — FR-06.
 *
 * `01-architecture.md` §11: *OCR confidence low on a field → field surfaced for one-tap human
 * confirmation; never silently guessed.* And §5 S6 puts it third in the extraction order, **before
 * the verdict is issued** — which is the part that makes this more than a nicety. A rule evaluated
 * against a misread MRP produces a confident, citable, wrong FAIL against a compliant pack, and
 * CLAUDE.md §3.4 names that as the failure mode that kills the product.
 *
 * So `verdictsAreProvisional` exists, and the findings screen must not present verdicts as final
 * while it returns true. That is the whole point of the module.
 *
 * **The threshold is a pipeline parameter, not a rule threshold.** It decides whether to *ask a
 * person*, never whether a pack complies, so it does not belong in the rule pack (CLAUDE.md §3.2) —
 * and the number is the one `src/domain/finding.ts` already documents on `Extraction.confidence`.
 *
 * Pure. The sheet is a thin layer over this.
 */

import type { Extraction, FieldCode, FindingsResult } from '@/domain';
import type { TranslationKey } from '@/i18n';

/**
 * Below this, a field goes to the confirmation sheet.
 *
 * 0.75 comes from TRD FR-06 and is documented on `Extraction.confidence`. It is deliberately not a
 * rule-pack value: no compliance decision reads it.
 */
export const CONFIDENCE_THRESHOLD = 0.75;

/**
 * Fields a human has already confirmed are never re-asked.
 *
 * `source === 'human'` is the record of that, and it is why `confirmFields` writes it (FR-06's
 * acceptance: *the correction is recorded with `source=human`*). Re-asking would also quietly
 * discard a correction, since the sheet would overwrite it with the machine's value.
 */
export function needsConfirmation(extraction: Extraction): boolean {
  if (extraction.source === 'human') return false;
  return extraction.confidence < CONFIDENCE_THRESHOLD;
}

/**
 * Everything awaiting confirmation, **lowest confidence first.**
 *
 * The worst read is the one most likely to be wrong, so it is the one to put in front of someone who
 * may only confirm one before putting the phone away.
 */
export function fieldsNeedingConfirmation(
  result: Pick<FindingsResult, 'extractions'>
): Extraction[] {
  return result.extractions.filter(needsConfirmation).sort((a, b) => a.confidence - b.confidence);
}

/**
 * True while any field is unconfirmed.
 *
 * The findings screen reads this and must say so rather than presenting a verdict as settled. A FAIL
 * computed from a 0.41-confidence MRP is not a finding yet, it is a question.
 */
export function verdictsAreProvisional(result: Pick<FindingsResult, 'extractions'>): boolean {
  return result.extractions.some(needsConfirmation);
}

/**
 * Below this, a field awaiting confirmation is folded away under "Also unclear" rather than listed.
 *
 * Presentation only. It decides the *order of asking*, never whether a field is asked: everything
 * under `CONFIDENCE_THRESHOLD` still has to be confirmed before a verdict is issued, folded or not.
 *
 * 0.70 is where the language model's readings land. What falls below it is almost always a reading
 * the plausibility screen capped at 0.25 because the string cannot be what its field claims — a real
 * Dabur scan's `best_before` came back as "please see top panel." Those are the least useful rows to
 * lead with: they are the ones a person corrects by typing, not by glancing and tapping.
 */
export const UNCLEAR_BELOW = 0.7;

export interface ConfirmationGroups {
  /** Worth a glance and a tap, in the order `fieldsNeedingConfirmation` gives them. */
  likely: Extraction[];
  /** Read too poorly to lead with. Still awaiting confirmation. */
  unclear: Extraction[];
}

/**
 * Everything awaiting confirmation, split at `UNCLEAR_BELOW`.
 *
 * Nothing is dropped: `likely` and `unclear` together are exactly `fieldsNeedingConfirmation`. That
 * is the property that matters, because the backend holds every verdict until each of those fields
 * is confirmed, so a field that is filtered out rather than folded leaves the scan unjudged for good.
 */
export function groupForConfirmation(
  result: Pick<FindingsResult, 'extractions'>
): ConfirmationGroups {
  const pending = fieldsNeedingConfirmation(result);

  return {
    likely: pending.filter((extraction) => extraction.confidence >= UNCLEAR_BELOW),
    unclear: pending.filter((extraction) => extraction.confidence < UNCLEAR_BELOW),
  };
}

/** Confidence as a whole-number percentage, for display. */
export function confidencePercent(confidence: number): number {
  return Math.round(Math.max(0, Math.min(1, confidence)) * 100);
}

/**
 * How sure the machine is, in three bands.
 *
 * Only used to colour the chip. Deliberately **not** the verdict palette: an inspector must not learn
 * to read "we are unsure what this says" in the same colour as "this pack does not comply".
 */
export type ConfidenceBand = 'low' | 'medium' | 'high';

export function confidenceBand(confidence: number): ConfidenceBand {
  if (confidence < 0.5) return 'low';
  if (confidence < CONFIDENCE_THRESHOLD) return 'medium';
  return 'high';
}

/** What each field is called in the sheet. Exhaustive by type: a new field code stops the build. */
export const FIELD_LABEL_KEYS: Record<FieldCode, TranslationKey> = {
  manufacturer_name: 'fields.manufacturerName',
  manufacturer_address: 'fields.manufacturerAddress',
  packer_name: 'fields.packerName',
  importer_name: 'fields.importerName',
  importer_address: 'fields.importerAddress',
  country_of_origin: 'fields.countryOfOrigin',
  common_name: 'fields.commonName',
  net_quantity: 'fields.netQuantity',
  mrp: 'fields.mrp',
  mfg_month_year: 'fields.mfgMonthYear',
  consumer_care_name: 'fields.consumerCareName',
  consumer_care_phone: 'fields.consumerCarePhone',
  consumer_care_email: 'fields.consumerCareEmail',
  unit_sale_price: 'fields.unitSalePrice',
  best_before: 'fields.bestBefore',
};

/**
 * A correction ready to send, or null if nothing changed.
 *
 * Confirming an unchanged value still has to be sent — that is what records `source=human` and stops
 * the field being asked again — so "nothing changed" here means the user cleared the field entirely,
 * which is not a correction but a deletion, and FR-06 has no path for one.
 */
export function correctionFor(
  extraction: Extraction,
  value: string
): { code: FieldCode; value: string } | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  return { code: extraction.fieldCode, value: trimmed };
}
