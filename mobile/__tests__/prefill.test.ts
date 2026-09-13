/**
 * Context prefill — FR-03's "pre-filled from OCR ... and confirmed by the user".
 *
 * The point of the feature is that nobody types eight fields after every photograph. The risk is
 * that a machine quietly fills the three that decide **which rules run**. So most of what is
 * asserted here is what prefill refuses to do:
 *
 * - it fills blanks and never overwrites a person, whenever the read happens to land;
 * - `isImported` goes one way only — a label with no importer line never becomes `domestic`,
 *   because that would switch the importer rules off on the strength of an absence;
 * - a category is matched only when the name says so unambiguously, because the code goes on to a
 *   BIS applicability lookup where a wrong one is a wrong answer about a licence;
 * - the rule-relevant fields it filled stay unconfirmed until a person says otherwise.
 *
 * Everything under test here is pure. The hook that shrinks the photograph and polls is not — it is
 * a thin shell over these functions, which is the point of splitting them.
 */

import { toPrefill, type WirePrefill } from '@/api/adapters';
import { fromPrefill } from '@/api/mock/to-wire';
import {
  MAX_PREFILL_IMAGES,
  RULE_RELEVANT,
  TIMEOUT_BASE_MS,
  TIMEOUT_CEILING_MS,
  TIMEOUT_PER_IMAGE_MS,
  anyFilled,
  applySuggestions,
  defaultContextValues,
  photographsToRead,
  suggestCategory,
  timeoutFor,
  unconfirmedRuleFields,
  type ContextFormValues,
  type Suggestion,
} from '@/features/scan-context';
import { en } from '@/i18n/locales/en';
import type { TranslationKey } from '@/i18n';

/** The real English strings, so a category match is tested against what users actually read. */
function t(key: TranslationKey): string {
  const path = key.split('.');
  let value: unknown = en;
  for (const segment of path) value = (value as Record<string, unknown>)?.[segment];
  return typeof value === 'string' ? value : key;
}

function suggestion(field: string, value: string, confidence = 0.95): Suggestion {
  return {
    field,
    value,
    confidence,
    fromFieldCode: field === 'name' ? 'common_name' : 'net_quantity',
    sourceText: value,
  };
}

function blankForm(): ContextFormValues {
  return defaultContextValues('enforcement');
}

// ------------------------------------------------------------------ filling the form

describe('a read label fills the form', () => {
  it('fills the fields that are tedious to type', () => {
    const { values } = applySuggestions(
      blankForm(),
      [
        suggestion('name', 'Roasted Chana'),
        suggestion('net_qty_value', '250'),
        suggestion('net_qty_unit', 'g'),
      ],
      t
    );

    expect(values.name).toBe('Roasted Chana');
    expect(values.quantityValue).toBe('250');
    expect(values.quantityUnit).toBe('g');
  });

  it('reports what filled each field, so the screen can say where it came from', () => {
    const { filled } = applySuggestions(blankForm(), [suggestion('net_qty_value', '250')], t);

    expect(filled.quantityValue?.fromFieldCode).toBe('net_quantity');
    expect(filled.quantityValue?.sourceText).toBe('250');
    expect(anyFilled(filled)).toBe(true);
  });

  it('ignores a field this build does not know rather than guessing at it', () => {
    const { values, filled } = applySuggestions(
      blankForm(),
      [suggestion('some_future_field', 'whatever')],
      t
    );

    expect(values).toEqual({});
    expect(anyFilled(filled)).toBe(false);
  });
});

describe('a read label never overwrites a person', () => {
  it('leaves a field the user has already typed in', () => {
    const typed: ContextFormValues = { ...blankForm(), quantityValue: '500', quantityUnit: 'g' };

    const { values, filled } = applySuggestions(
      typed,
      [suggestion('net_qty_value', '250'), suggestion('net_qty_unit', 'kg')],
      t
    );

    expect(values.quantityValue).toBeUndefined();
    expect(values.quantityUnit).toBeUndefined();
    expect(filled.quantityValue).toBeUndefined();
  });

  it('fills the blanks around a half-filled form', () => {
    const half: ContextFormValues = { ...blankForm(), name: 'My own name' };

    const { values } = applySuggestions(
      half,
      [suggestion('name', 'Roasted Chana'), suggestion('net_qty_value', '250')],
      t
    );

    expect(values.name).toBeUndefined();
    expect(values.quantityValue).toBe('250');
  });

  it('ignores a suggestion whose value is blank', () => {
    const { values } = applySuggestions(blankForm(), [suggestion('name', '   ')], t);

    expect(values.name).toBeUndefined();
  });
});

// ------------------------------------------------------------------ the safety property

describe('the imported flag goes one way only', () => {
  it('sets imported when the label declares an importer', () => {
    const { values, filled } = applySuggestions(
      blankForm(),
      [{ ...suggestion('is_imported', 'true'), fromFieldCode: 'importer_name' }],
      t
    );

    expect(values.isImported).toBe(true);
    expect(filled.isImported).toBeDefined();
  });

  it('never fills domestic, because an absent importer line is not evidence of one', () => {
    // The server does not send `false` — this asserts the client would refuse it anyway. A pack
    // with no importer declaration is exactly the pack in breach of Rule 6, and turning that
    // omission into `isImported: false` switches the rules that would have caught it off.
    const { values, filled } = applySuggestions(
      blankForm(),
      [suggestion('is_imported', 'false')],
      t
    );

    expect(values.isImported).toBeUndefined();
    expect(filled.isImported).toBeUndefined();
  });

  it('never proposes a surface, which selects a Rule 9 threshold column', () => {
    const { values } = applySuggestions(
      blankForm(),
      [suggestion('surface', 'embossed'), suggestion('pack_type', 'rigid')],
      t
    );

    expect(values.surface).toBeUndefined();
    expect(values.packType).toBeUndefined();
  });
});

// ------------------------------------------------------------------ the category match

describe('the category is matched from the name, or not at all', () => {
  it('matches a commodity the keyword list knows', () => {
    expect(suggestCategory('Whole Wheat Atta', t)).toBe('food.flour');
    expect(suggestCategory('Basmati Rice', t)).toBe('food.rice');
    expect(suggestCategory('Toor Dal', t)).toBe('food.pulses');
  });

  it('matches inside a longer product name', () => {
    expect(suggestCategory('Sampoorna Whole Wheat Atta 1 kg', t)).toBe('food.flour');
  });

  it('refuses a name that matches two categories equally', () => {
    // "oil" is a keyword of both the edible-oil category and the cosmetics one. The label did not
    // say which, and a coin toss here is a wrong code on a BIS applicability lookup.
    expect(suggestCategory('Mustard Oil', t)).not.toBe('personal.cosmetics');
  });

  it('refuses a name it cannot place', () => {
    expect(suggestCategory('Zorbex 9000', t)).toBeNull();
    expect(suggestCategory('', t)).toBeNull();
  });

  it('does not match a keyword that is only a fragment of a word', () => {
    // "oil" sits inside "boiled". A fragment match would file boiled sweets under edible oils.
    expect(suggestCategory('Boiled Sweets', t)).toBe('food.confectionery');
  });

  it('matches the plural form packs are actually printed in', () => {
    // The keyword list is singular; labels are not. "Biscuits" must reach the bakery category or
    // the list misses the only form of the word that appears on a pack.
    expect(suggestCategory('Marie Biscuits', t)).toBe('food.bakery');
    expect(suggestCategory('Mixed Pulses', t)).toBe('food.pulses');
  });

  it('derives the category from a suggested name, and records where it came from', () => {
    const { values, filled } = applySuggestions(
      blankForm(),
      [suggestion('name', 'Whole Wheat Atta', 0.7)],
      t
    );

    expect(values.categoryCode).toBe('food.flour');
    // Inherited from the name: a category matched off an unsure reading is not more sure than it.
    expect(filled.categoryCode?.confidence).toBe(0.7);
  });

  it('leaves a category the user has already chosen', () => {
    const chosen: ContextFormValues = { ...blankForm(), categoryCode: 'food.snacks' };

    const { values } = applySuggestions(chosen, [suggestion('name', 'Whole Wheat Atta')], t);

    expect(values.categoryCode).toBeUndefined();
  });
});

// ------------------------------------------------------------------ the confirmation gate

describe('rule-relevant fields wait for a person', () => {
  it('lists what a machine filled and nobody has confirmed', () => {
    const { filled } = applySuggestions(
      blankForm(),
      [suggestion('net_qty_value', '250'), suggestion('net_qty_unit', 'g')],
      t
    );

    expect(unconfirmedRuleFields(filled, false)).toEqual(['quantityValue', 'quantityUnit']);
  });

  it('is empty once confirmed', () => {
    const { filled } = applySuggestions(blankForm(), [suggestion('net_qty_value', '250')], t);

    expect(unconfirmedRuleFields(filled, true)).toEqual([]);
  });

  it('does not gate on a field that is not rule-relevant', () => {
    // A wrong product name is a labelling mistake in a report's header. A wrong net quantity is a
    // different row of Rule 9's table, so only one of the two stops a submit.
    const { filled } = applySuggestions(blankForm(), [suggestion('name', 'Roasted Chana')], t);

    expect(unconfirmedRuleFields(filled, false)).toEqual([]);
    expect(anyFilled(filled)).toBe(true);
  });

  it('gates on every field that changes which rules run', () => {
    expect(RULE_RELEVANT).toEqual(['quantityValue', 'quantityUnit', 'isImported']);
  });
});

// ------------------------------------------- how many photographs are read

describe('a read takes at most three photographs', () => {
  const uris = (n: number) => Array.from({ length: n }, (_, i) => `file:///photo-${i}.jpg`);

  it('sends every photograph when there are three or fewer', () => {
    for (const n of [1, 2, 3]) {
      expect(photographsToRead(uris(n))).toEqual(uris(n));
    }
  });

  it('keeps the first three and drops the rest', () => {
    // Capture order is roughly panel order — front framed first, back second — so the first three
    // are the faces the declarations are actually printed on.
    expect(photographsToRead(uris(5))).toEqual([
      'file:///photo-0.jpg',
      'file:///photo-1.jpg',
      'file:///photo-2.jpg',
    ]);
  });

  it('never returns more than the ceiling, whatever it is handed', () => {
    for (const n of [4, 7, 10, 40]) {
      expect(photographsToRead(uris(n))).toHaveLength(MAX_PREFILL_IMAGES);
    }
  });

  it('has nothing to read when nothing was captured', () => {
    expect(photographsToRead([])).toEqual([]);
  });

  it('returns the list it was given when no photograph is dropped', () => {
    // Identity matters: the hook joins this into the key that decides "same photographs", and a
    // fresh array on every render would restart a read that is already in flight.
    const three = uris(3);
    expect(photographsToRead(three)).toBe(three);
  });

  it('caps at three, which is what the server accepts', () => {
    // Pinned against backend/app/schemas/prefill.py. The client dropping the fourth photograph is
    // the only thing standing between a five-photograph capture and a 422 on the capture path.
    expect(MAX_PREFILL_IMAGES).toBe(3);
  });
});

// ------------------------------------------------------------------ the wait

describe('the wait scales with how many photographs were sent', () => {
  it('budgets for one photograph at the base', () => {
    expect(timeoutFor(1)).toBe(TIMEOUT_BASE_MS);
  });

  it('adds time per extra photograph, because the worker recognises each one', () => {
    // Three photographs is not three times the network, but it is three times the OCR.
    expect(timeoutFor(3)).toBe(TIMEOUT_BASE_MS + TIMEOUT_PER_IMAGE_MS * 2);
    expect(timeoutFor(3)).toBeGreaterThan(timeoutFor(1));
  });

  it('covers the most photographs that can be sent, well inside the ceiling', () => {
    // Three is the most `photographsToRead` will hand over, so this is the real outer bound on a
    // wait — 50 s, not the 90 s ceiling, which no longer has a reachable argument.
    expect(timeoutFor(MAX_PREFILL_IMAGES)).toBeLessThan(TIMEOUT_CEILING_MS);
  });

  it('never waits longer than the ceiling', () => {
    // Unreachable through the hook now, and kept anyway: `timeoutFor` is pure and its bound should
    // hold for any argument, not only for the ones today's caller passes.
    expect(timeoutFor(10)).toBe(TIMEOUT_CEILING_MS);
    expect(timeoutFor(100)).toBe(TIMEOUT_CEILING_MS);
  });

  it('does not go below the base for a degenerate count', () => {
    expect(timeoutFor(0)).toBe(TIMEOUT_BASE_MS);
  });
});

// ------------------------------------------------------------------ the wire

describe('the prefill wire shape', () => {
  it('survives the round trip', () => {
    const domain = {
      prefillId: 'pf_1',
      status: 'ready' as const,
      suggestions: [suggestion('net_qty_value', '250')],
      wordCount: 96,
      reduced: false,
    };

    expect(toPrefill(fromPrefill(domain))).toEqual(domain);
  });

  it('reads a server response that omits its optional fields', () => {
    const sparse = { prefill_id: 'pf_2', status: 'reading' } as WirePrefill;

    expect(toPrefill(sparse)).toEqual({
      prefillId: 'pf_2',
      status: 'reading',
      suggestions: [],
      wordCount: 0,
      reduced: false,
    });
  });
});
