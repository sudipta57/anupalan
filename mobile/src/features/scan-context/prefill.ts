/**
 * Filling the context form from what the label says — FR-03's "pre-filled from OCR".
 *
 * The form exists because the rules engine needs a product profile, and three of its fields decide
 * which rules run at all (`profile.ts`). That is a good reason for the *data* to exist and a bad
 * reason to make a person type it after every photograph, when the pack in their hand already says
 * most of it. So the backend reads the photograph and proposes values; this module decides what the
 * form does with the proposals.
 *
 * **Suggestions fill blanks. They never overwrite a person.** `applySuggestions` takes the current
 * form values and returns only the fields that were empty. A prefill that lands while someone is
 * halfway through typing a quantity must not move it under their thumb, and a user who corrects a
 * suggested value must not have the correction reverted by a late poll.
 *
 * **Nothing here is accepted silently.** Every field this fills comes back in `filled`, which the
 * screen uses to mark the field as read-from-the-label and to gate submission behind one
 * confirmation. The machine may fill the form; the person still affirms it before a scan exists
 * (CLAUDE.md §3.1). `RULE_RELEVANT` names the fields where that gate is not optional.
 *
 * **The category is matched here, not on the server.** The 26-code vocabulary is the client's
 * (`categories.ts`) and the server has no copy of it — duplicating the list in Python would be two
 * lists to keep in step and a code that could drift out of a rule pack's filter. The server
 * proposes the commodity's common name; `suggestCategory` matches that against the keywords the
 * search box already uses. A name that matches two categories equally well matches neither: an
 * ambiguous guess here is a wrong `category_code` on a BIS applicability lookup.
 */

import type { TranslationKey } from '@/i18n';

import { CATEGORIES, type Category } from './categories';
import type { ContextFormValues } from './profile';

/** One proposed value, as the server sends it. */
export interface Suggestion {
  /** A profile field name: `name`, `net_qty_value`, `net_qty_unit` or `is_imported`. */
  field: string;
  /** Always a string, including for the boolean (`'true'`). */
  value: string;
  /** Inherited from the declaration it was read from. Below 0.75 the machine is unsure. */
  confidence: number;
  /** The declaration it came from — shown so "why does it say this" has an answer. */
  fromFieldCode: string;
  /** What was recognised on the pack, verbatim. */
  sourceText: string;
}

/** Where one prefill has got to. */
export type PrefillStatus = 'reading' | 'ready' | 'failed';

export interface PrefillResult {
  prefillId: string;
  status: PrefillStatus;
  suggestions: Suggestion[];
  /** Words recognised. Zero with no suggestions means the photograph was read and had nothing on it. */
  wordCount: number;
  /** Extraction ran pattern-only, so no product name was proposed. */
  reduced: boolean;
}

/**
 * FR-06's threshold, repeated here rather than imported from the findings feature.
 *
 * The same number for the same reason — below it the machine does not believe its own reading — but
 * a different decision hangs on it: there, whether a verdict may rest on a value; here, only how
 * loudly a filled field says "check this". Coupling the two would make a change to one a change to
 * the other.
 */
export const UNSURE_BELOW = 0.75;

/**
 * Form fields that change which rules run, and therefore cannot be accepted without a person.
 *
 * Surface is the third rule-relevant field and is deliberately absent: the server never proposes
 * it (nothing in a label's words says whether its text is embossed), so it is never in a state that
 * needs confirming.
 */
export const RULE_RELEVANT: readonly (keyof ContextFormValues)[] = [
  'quantityValue',
  'quantityUnit',
  'isImported',
];

/** The form field each suggested profile field lands in. */
const FIELD_FOR: Readonly<Record<string, keyof ContextFormValues>> = {
  name: 'name',
  net_qty_value: 'quantityValue',
  net_qty_unit: 'quantityUnit',
  is_imported: 'isImported',
};

/** Whether a form value is empty enough to be filled without overwriting anyone. */
function isBlank(value: unknown): boolean {
  if (typeof value === 'string') return value.trim().length === 0;
  // `isImported` is a boolean with a default of false. False is "not yet said", which is why the
  // server never proposes a `false` — see the note on `applySuggestions`.
  return value === false || value === undefined || value === null;
}

export interface AppliedPrefill {
  /** Only the fields that were blank. Spread over the form; never a whole form. */
  values: Partial<ContextFormValues>;
  /** What filled each one, keyed by form field — the screen's provenance chips. */
  filled: Partial<Record<keyof ContextFormValues, Suggestion>>;
}

/**
 * Work out which form fields a set of suggestions may fill.
 *
 * Args:
 *   current: the form as it stands. A non-blank field is left alone.
 *   suggestions: what the server read off the label.
 *
 * Returns the values to apply and the provenance for each.
 *
 * **`isImported` is only ever set to true.** The server proposes it in one direction for a reason
 * that matters more than it looks: `is_imported=false` switches the importer and country-of-origin
 * rules *off*, and a pack with no importer line is exactly the pack most likely to be in breach of
 * Rule 6. So an absent declaration never becomes a filled `domestic`, here or there — the form's
 * own default stands, where the user can see it and change it.
 */
export function applySuggestions(
  current: ContextFormValues,
  suggestions: readonly Suggestion[],
  translate: (key: TranslationKey) => string
): AppliedPrefill {
  const values: Partial<ContextFormValues> = {};
  const filled: Partial<Record<keyof ContextFormValues, Suggestion>> = {};

  for (const suggestion of suggestions) {
    const field = FIELD_FOR[suggestion.field];
    if (!field) continue; // a field this build does not know — ignored, never guessed at
    if (!isBlank(current[field])) continue;

    if (field === 'isImported') {
      if (suggestion.value !== 'true') continue;
      values.isImported = true;
    } else {
      const text = suggestion.value.trim();
      if (text.length === 0) continue;
      (values as Record<string, string>)[field] = text;
    }

    filled[field] = suggestion;
  }

  // The category follows from the name rather than from a declaration of its own, so it is derived
  // here — after the loop, from whichever name is now in play — rather than proposed by the server,
  // which has no copy of the vocabulary (see the module docstring).
  const name = values.name ?? current.name;
  if (name && isBlank(current.categoryCode)) {
    const code = suggestCategory(name, translate);
    if (code) {
      values.categoryCode = code;
      filled.categoryCode = {
        field: 'category_code',
        value: code,
        // Inherited from the name it was derived from: a category matched off an uncertain reading
        // is no more certain than the reading.
        confidence: filled.name?.confidence ?? 1,
        fromFieldCode: filled.name?.fromFieldCode ?? 'common_name',
        sourceText: name,
      };
    }
  }

  return { values, filled };
}

/**
 * The category a product name implies, or null when the name does not clearly say.
 *
 * Scored rather than filtered: `searchCategories` answers "what could the user mean" for a search
 * box, where showing six options is helpful. This answers "which one is it" for a field that goes
 * to a BIS applicability lookup, where a wrong code is a wrong answer about whether a licence is
 * needed. So a tie wins nothing.
 *
 * `translate` is passed in rather than imported, like `searchCategories`, so the match works in
 * either locale and the function stays pure.
 */
export function suggestCategory(
  name: string,
  translate: (key: TranslationKey) => string
): string | null {
  const haystack = name.toLowerCase();
  if (haystack.trim().length === 0) return null;

  const scored = CATEGORIES.map((category) => ({
    category,
    score: scoreCategory(category, haystack, translate),
  })).filter((entry) => entry.score > 0);

  if (scored.length === 0) return null;

  const best = Math.max(...scored.map((entry) => entry.score));
  const winners = scored.filter((entry) => entry.score === best);

  // A tie is ambiguity, not a coin toss. "Mustard Oil" scoring equally as oil and as spices means
  // the label did not say, and the user picks from the list they would have used anyway.
  return winners.length === 1 ? winners[0].category.code : null;
}

/**
 * How well one category matches a product name.
 *
 * A label match counts double: "Edible Oil" naming the category outright is stronger evidence than
 * a keyword that happens to appear inside a longer word.
 */
function scoreCategory(
  category: Category,
  haystack: string,
  translate: (key: TranslationKey) => string
): number {
  let score = 0;

  const label = translate(category.labelKey).toLowerCase();
  if (label.length > 0 && haystack.includes(label)) score += 2;

  for (const keyword of category.keywords) {
    if (matchesWord(haystack, keyword)) score += 1;
  }

  return score;
}

/**
 * Whether a keyword appears in the name as a word rather than as a fragment.
 *
 * Fragments produce nonsense: "oil" sits inside "boiled", and matching it would file boiled sweets
 * under edible oils. So the character before the keyword must not be part of a word.
 *
 * **A plural suffix is still the word.** Packs say "Biscuits", "Sweets", "Pulses" — requiring an
 * exact boundary on both sides makes the keyword list miss the form the words are actually printed
 * in, which is the only form that matters here. A trailing `s` or `es` is allowed; anything longer
 * is a different word.
 *
 * Checked by hand rather than with a `RegExp` built from the keyword, which would need escaping for
 * a list that is fixed, small and inspectable.
 */
function matchesWord(haystack: string, keyword: string): boolean {
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(keyword, from);
    if (at < 0) return false;

    const before = at === 0 ? ' ' : haystack[at - 1];
    if (!isWordChar(before) && endsWord(haystack, at + keyword.length)) return true;

    from = at + 1;
  }
}

/** Whether the word ends at `at`, allowing an English plural suffix. */
function endsWord(haystack: string, at: number): boolean {
  const charAt = (index: number) => (index >= haystack.length ? ' ' : haystack[index]);

  if (!isWordChar(charAt(at))) return true;
  if (charAt(at) === 's' && !isWordChar(charAt(at + 1))) return true;
  return charAt(at) === 'e' && charAt(at + 1) === 's' && !isWordChar(charAt(at + 2));
}

function isWordChar(char: string): boolean {
  return /[a-z0-9]/.test(char);
}

/**
 * Which rule-relevant fields a prefill filled and a person has not yet touched.
 *
 * The screen's submit gate reads this: while it is non-empty, the form has machine-supplied values
 * behind a rule that decides whether a rule runs, and the user is asked to confirm them once. It
 * empties when they confirm, and also when they edit the field themselves — editing *is*
 * confirming, and asking twice for the same assurance teaches people to tap past it.
 */
export function unconfirmedRuleFields(
  filled: Partial<Record<keyof ContextFormValues, Suggestion>>,
  confirmed: boolean
): (keyof ContextFormValues)[] {
  if (confirmed) return [];
  return RULE_RELEVANT.filter((field) => filled[field] !== undefined);
}

/** Whether any field was filled at all — what the screen's banner is about. */
export function anyFilled(filled: Partial<Record<keyof ContextFormValues, Suggestion>>): boolean {
  return Object.keys(filled).length > 0;
}
