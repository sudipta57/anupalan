/**
 * Product context — FR-03.
 *
 * *Accept: net quantity value and unit, the imported flag and the surface type are present on every
 * completed scan — all three change which rules apply.*
 *
 * The form itself needs a device to exercise, so everything that decides a rule outcome is pure and
 * pinned here: what a typed unit means, which Rule 9 table it implies, when the display-panel area
 * becomes mandatory, and the two guards that refuse an incomplete profile. The Mode B location
 * promise is tested as a promise — `geoForScan` is handed a coordinate and must still return null.
 */

import type { ProductProfile } from '@/domain';
import {
  IncompleteProfileError,
  MAX_PDP_AREA_CM2,
  MAX_QUANTITY_VALUE,
  NET_QUANTITY_UNITS,
  assertRuleRelevantFields,
  basisForUnit,
  buildProfile,
  buildQuantity,
  categoryFor,
  collectsLocation,
  defaultContextValues,
  districtForScan,
  geoForScan,
  isLooseFix,
  isValidName,
  normaliseUnit,
  pdpAreaRequired,
  requiresPdpArea,
  searchCategories,
  toGeoPoint,
  wasRewritten,
  type ContextFormValues,
} from '@/features/scan-context';
import { CATEGORIES } from '@/features/scan-context/categories';
import { PRODUCTS } from '@/api/mock/fixtures/products';

/** A complete, valid form. Individual tests spoil exactly one field. */
const FILLED: ContextFormValues = {
  name: 'Sampoorna Whole Wheat Atta 1 kg',
  categoryCode: 'food.flour',
  packType: 'flexible',
  surface: 'printed',
  isImported: false,
  quantityValue: '1',
  quantityUnit: 'kg',
  pdpAreaCm2: '70',
  channel: 'retail',
  district: 'Nadia',
};

describe('normaliseUnit', () => {
  it('rewrites the variants FR-03 names', () => {
    expect(normaliseUnit('gms')).toBe('g');
    expect(normaliseUnit('Gm')).toBe('g');
    expect(normaliseUnit('ltr')).toBe('l');
  });

  it.each([
    ['GMS', 'g'],
    ['grams', 'g'],
    ['Kgs', 'kg'],
    ['KILOGRAM', 'kg'],
    ['millilitres', 'ml'],
    ['cc', 'ml'],
    ['litre', 'l'],
    ['Liters', 'l'],
    ['mtr', 'm'],
    ['centimeters', 'cm'],
    ['pcs', 'N'],
    ['nos', 'N'],
    ['units', 'U'],
  ] as const)('maps %s to %s', (typed, expected) => {
    expect(normaliseUnit(typed)).toBe(expected);
  });

  it('tolerates surrounding space and a trailing full stop', () => {
    expect(normaliseUnit('  gms. ')).toBe('g');
    expect(normaliseUnit('kg.')).toBe('kg');
  });

  it('leaves an exact prescribed symbol alone, capital L included', () => {
    // The Second Schedule prescribes both `l` and `L` for litre. Lowercasing everything would
    // silently narrow a declaration the law allows.
    expect(normaliseUnit('L')).toBe('L');
    expect(normaliseUnit('l')).toBe('l');
    expect(normaliseUnit('N')).toBe('N');
    expect(normaliseUnit('U')).toBe('U');
  });

  it('returns every prescribed symbol unchanged', () => {
    for (const unit of NET_QUANTITY_UNITS) {
      expect(normaliseUnit(unit)).toBe(unit);
    }
  });

  it('refuses what is not a unit at all rather than guessing', () => {
    for (const nonsense of ['', '   ', 'packet', 'pouch', 'x', 'kgg', '500']) {
      expect(normaliseUnit(nonsense)).toBeNull();
    }
  });

  it('knows when it changed what was typed, so the form can say so', () => {
    expect(wasRewritten('gms', 'g')).toBe(true);
    expect(wasRewritten('kg', 'kg')).toBe(false);
    expect(wasRewritten(' kg ', 'kg')).toBe(false);
  });
});

describe('which Rule 9 table applies', () => {
  it('reads Table I for weight and volume', () => {
    for (const unit of ['g', 'kg', 'ml', 'l', 'L'] as const) {
      expect(basisForUnit(unit)).toBe('weight_or_volume');
    }
  });

  it('reads Table II for length, area and number', () => {
    for (const unit of ['mm', 'cm', 'm', 'N', 'U'] as const) {
      expect(basisForUnit(unit)).toBe('length_area_or_number');
    }
  });

  it('classifies every prescribed symbol — a unit with no table has no thresholds', () => {
    for (const unit of NET_QUANTITY_UNITS) {
      expect(['weight_or_volume', 'length_area_or_number']).toContain(basisForUnit(unit));
    }
  });

  it('needs the display panel area exactly when Table II applies', () => {
    expect(requiresPdpArea('N')).toBe(true);
    expect(requiresPdpArea('cm')).toBe(true);
    expect(requiresPdpArea('kg')).toBe(false);
  });

  it('does not demand the area from a half-typed unit', () => {
    // `k` on the way to `kg` must not turn a second field red.
    expect(pdpAreaRequired('k')).toBe(false);
    expect(pdpAreaRequired('')).toBe(false);
    expect(pdpAreaRequired('N')).toBe(true);
  });
});

describe('buildQuantity', () => {
  it('pairs a parsed value with a prescribed symbol', () => {
    expect(buildQuantity('500', 'gms')).toEqual({
      quantity: { value: 500, unit: 'g' },
      unit: 'g',
    });
  });

  it('accepts a decimal, because 1.5 l is a real declaration', () => {
    expect(buildQuantity('1.5', 'l')?.quantity).toEqual({ value: 1.5, unit: 'l' });
  });

  it('refuses zero, negatives and nonsense rather than producing NaN', () => {
    for (const value of ['0', '-5', '', 'abc', '1.2.3', '1e5']) {
      expect(buildQuantity(value, 'kg')).toBeNull();
    }
  });

  it('refuses a slipped decimal point', () => {
    expect(buildQuantity(String(MAX_QUANTITY_VALUE + 1), 'kg')).toBeNull();
    expect(buildQuantity(String(MAX_QUANTITY_VALUE), 'kg')).not.toBeNull();
  });

  it('refuses a value it cannot pair with a unit', () => {
    expect(buildQuantity('500', 'packet')).toBeNull();
  });
});

describe('buildProfile', () => {
  it('carries the three fields FR-03 makes mandatory', () => {
    const profile = buildProfile(FILLED);

    expect(profile).not.toBeNull();
    expect(profile?.netQuantity).toEqual({ value: 1, unit: 'kg' });
    expect(profile?.isImported).toBe(false);
    expect(profile?.surface).toBe('printed');
  });

  it('derives the basis instead of taking it from the form', () => {
    expect(buildProfile({ ...FILLED, quantityUnit: 'kg' })?.qtyBasis).toBe('weight_or_volume');
    expect(
      buildProfile({ ...FILLED, quantityUnit: 'N', quantityValue: '200', pdpAreaCm2: '310' })
        ?.qtyBasis
    ).toBe('length_area_or_number');
  });

  it('normalises the unit on the way into the profile', () => {
    // The rules engine branches on the symbol and must never be handed `gms`.
    expect(
      buildProfile({ ...FILLED, quantityValue: '500', quantityUnit: 'gms' })?.netQuantity
    ).toEqual({ value: 500, unit: 'g' });
  });

  it('trims the name but keeps it as printed otherwise', () => {
    expect(buildProfile({ ...FILLED, name: '  Atta 1 kg  ' })?.name).toBe('Atta 1 kg');
  });

  it('refuses an incomplete form rather than filling a gap with a default', () => {
    expect(buildProfile({ ...FILLED, name: '' })).toBeNull();
    expect(buildProfile({ ...FILLED, name: 'x' })).toBeNull();
    expect(buildProfile({ ...FILLED, categoryCode: '' })).toBeNull();
    expect(buildProfile({ ...FILLED, quantityValue: '' })).toBeNull();
    expect(buildProfile({ ...FILLED, quantityUnit: '' })).toBeNull();
  });

  it('requires the display panel area when Table II applies', () => {
    const byNumber = { ...FILLED, quantityValue: '200', quantityUnit: 'N' };

    expect(buildProfile({ ...byNumber, pdpAreaCm2: '' })).toBeNull();
    expect(buildProfile({ ...byNumber, pdpAreaCm2: '310' })?.pdpAreaCm2).toBe(310);
  });

  it('treats the area as optional under Table I, and null means not measured', () => {
    expect(buildProfile({ ...FILLED, pdpAreaCm2: '' })?.pdpAreaCm2).toBeNull();
  });

  it('rejects an area that is not a display panel', () => {
    expect(buildProfile({ ...FILLED, pdpAreaCm2: String(MAX_PDP_AREA_CM2 + 1) })).toBeNull();
    expect(buildProfile({ ...FILLED, pdpAreaCm2: '0' })).toBeNull();
  });

  it('builds a profile that matches a fixture product, field for field', () => {
    // If the form can express the fixtures, the fixtures are a fair model of the form's output —
    // and a drift in either direction fails here rather than in front of a judge.
    const atta = PRODUCTS.find((p) => p.id === 'prd_atta_1kg');
    expect(buildProfile(FILLED)).toEqual(atta?.profile);
  });
});

describe('assertRuleRelevantFields', () => {
  const valid = buildProfile(FILLED) as ProductProfile;

  it('passes a complete profile straight through', () => {
    expect(assertRuleRelevantFields(valid)).toBe(valid);
  });

  it('refuses a quantity that parsed to NaN — what the type system cannot catch', () => {
    expect(() =>
      assertRuleRelevantFields({ ...valid, netQuantity: { value: Number.NaN, unit: 'kg' } })
    ).toThrow(IncompleteProfileError);
  });

  it('refuses a zero or negative quantity', () => {
    for (const value of [0, -1]) {
      expect(() =>
        assertRuleRelevantFields({ ...valid, netQuantity: { value, unit: 'kg' } })
      ).toThrow(IncompleteProfileError);
    }
  });

  it('names what is missing, so the failure is diagnosable', () => {
    try {
      assertRuleRelevantFields({
        ...valid,
        qtyBasis: 'length_area_or_number',
        pdpAreaCm2: null,
      });
      throw new Error('should have refused');
    } catch (cause) {
      expect(cause).toBeInstanceOf(IncompleteProfileError);
      expect((cause as IncompleteProfileError).missing).toContain('pdpAreaCm2');
    }
  });

  it('refuses a Table II profile with no display panel area', () => {
    // Those height rules would have no row to read, and a guess is worse than NOT_ASSESSABLE.
    expect(() =>
      assertRuleRelevantFields({ ...valid, qtyBasis: 'length_area_or_number', pdpAreaCm2: null })
    ).toThrow(IncompleteProfileError);
  });
});

describe('location policy', () => {
  const point = { latitude: 23.4012, longitude: 88.5023, accuracyM: 8 };

  it('collects location in enforcement mode only', () => {
    expect(collectsLocation('enforcement')).toBe(true);
    expect(collectsLocation('industry')).toBe(false);
    expect(collectsLocation(null)).toBe(false);
  });

  it('passes the point through in Mode A', () => {
    expect(geoForScan('enforcement', point)).toBe(point);
  });

  it('returns null in Mode B even when handed a coordinate', () => {
    // This is the whole reason the function exists. The permission can already be granted from a
    // previous Mode A session on the same phone, so nothing would prompt and nothing would fail —
    // only this refusal stops a Mode B scan carrying a coordinate.
    expect(geoForScan('industry', point)).toBeNull();
    expect(geoForScan(null, point)).toBeNull();
  });

  it('drops the district in Mode B too', () => {
    expect(districtForScan('enforcement', 'Nadia')).toBe('Nadia');
    expect(districtForScan('industry', 'Nadia')).toBeNull();
  });

  it('treats a blank district as absent rather than as an empty string', () => {
    expect(districtForScan('enforcement', '   ')).toBeNull();
  });

  it('converts a raw position, and refuses one with no coordinates', () => {
    expect(toGeoPoint({ latitude: 1, longitude: 2, accuracy: 5 })).toEqual({
      latitude: 1,
      longitude: 2,
      accuracyM: 5,
    });
    expect(toGeoPoint({ latitude: Number.NaN, longitude: 2, accuracy: 5 })).toBeNull();
    expect(toGeoPoint(null)).toBeNull();
  });

  it('keeps a coordinate that arrives without an accuracy figure', () => {
    // Losing a real fix over a missing metadata field would be the worse trade.
    expect(toGeoPoint({ latitude: 1, longitude: 2, accuracy: null })?.accuracyM).toBe(0);
  });

  it('flags a loose fix without blocking it', () => {
    expect(isLooseFix({ ...point, accuracyM: 400 })).toBe(true);
    expect(isLooseFix(point)).toBe(false);
    expect(isLooseFix(null)).toBe(false);
  });
});

describe('categories', () => {
  it('has a unique code for every entry', () => {
    expect(new Set(CATEGORIES.map((c) => c.code)).size).toBe(CATEGORIES.length);
  });

  it('covers every code the fixture products use', () => {
    // A fixture profile the form cannot express is a fixture that has drifted from the product.
    for (const product of PRODUCTS) {
      expect(categoryFor(product.profile.categoryCode)).not.toBeNull();
    }
  });

  it('finds a product by the name people actually use', () => {
    const byCode = (query: string) =>
      searchCategories(query, (key) => key).map((category) => category.code);

    expect(byCode('atta')).toContain('food.flour');
    expect(byCode('dal')).toContain('food.pulses');
    expect(byCode('charger')).toContain('electronics.accessory');
  });

  it('returns everything for an empty query, and nothing for a miss', () => {
    expect(searchCategories('', (key) => key)).toHaveLength(CATEGORIES.length);
    expect(searchCategories('zzzzz', (key) => key)).toHaveLength(0);
  });
});

describe('form defaults', () => {
  it('starts Mode B on an online listing, which turns Rule 6(10A) on rather than off', () => {
    expect(defaultContextValues('industry').channel).toBe('ecommerce');
    expect(defaultContextValues('enforcement').channel).toBe('retail');
  });

  it('leaves every mandatory field empty, so nothing is recorded by default', () => {
    const defaults = defaultContextValues('enforcement');

    expect(defaults.name).toBe('');
    expect(defaults.categoryCode).toBe('');
    expect(defaults.quantityValue).toBe('');
    expect(defaults.quantityUnit).toBe('');
    expect(buildProfile(defaults)).toBeNull();
  });

  it('rejects a name that is too long for a label line', () => {
    expect(isValidName('a'.repeat(121))).toBe(false);
    expect(isValidName('a'.repeat(120))).toBe(true);
  });
});
