/**
 * The product context form's values, and the profile they build — FR-03.
 *
 * FR-03's acceptance is not "a form exists". It is that **net quantity, the imported flag and the
 * surface type are present on every completed scan**, because each of the three changes which rules
 * run:
 *
 * | Field | What it changes |
 * |---|---|
 * | `netQuantity` | Which Rule 9 Table-I row sets the minimum numeral height — and via the unit, which table applies at all. |
 * | `isImported` | Turns the importer-declaration rules on. A domestic pack needs a manufacturer, an imported one needs an importer and a country of origin. |
 * | `surface` | Embossed, blown, moulded and perforated text carries a higher height threshold than printed text in both tables. |
 *
 * So `buildProfile` is total and `assertRuleRelevantFields` is a choke point, the same shape as
 * `markerFieldsForScan` for the scale reference: the type system cannot stop a form producing `NaN`
 * for a quantity, so something has to refuse at runtime before a scan is created with a profile the
 * rules engine would silently misread.
 *
 * Everything here is pure. The form is a thin layer over it, which is what makes the rule-relevant
 * logic testable without rendering a screen.
 */

import type {
  NetQuantity,
  NetQuantityUnit,
  OrgMode,
  PackType,
  ProductProfile,
  SalesChannel,
  Surface,
} from '@/domain';
import type { TranslationKey } from '@/i18n';

import { basisForUnit, normaliseUnit, requiresPdpArea } from './units';

/** A typo guard, not a legal limit — a 10 tonne retail pack is a slipped decimal point. */
export const MAX_QUANTITY_VALUE = 1_000_000;

/** One square metre. Above this, the principal display panel is not a display panel. */
export const MAX_PDP_AREA_CM2 = 10_000;

export const MAX_NAME_LENGTH = 120;

export interface Option<T extends string> {
  value: T;
  labelKey: TranslationKey;
}

export const PACK_TYPES: readonly Option<PackType>[] = [
  { value: 'flexible', labelKey: 'context.packFlexible' },
  { value: 'rigid', labelKey: 'context.packRigid' },
  { value: 'glass', labelKey: 'context.packGlass' },
  { value: 'can', labelKey: 'context.packCan' },
  { value: 'other', labelKey: 'context.packOther' },
];

export const SURFACES: readonly Option<Surface>[] = [
  { value: 'printed', labelKey: 'context.surfacePrinted' },
  { value: 'embossed', labelKey: 'context.surfaceEmbossed' },
];

export const CHANNELS: readonly Option<SalesChannel>[] = [
  { value: 'retail', labelKey: 'context.channelRetail' },
  { value: 'ecommerce', labelKey: 'context.channelEcommerce' },
];

/**
 * What the form holds.
 *
 * Numbers are strings because that is what a `TextInput` produces, and parsing at the boundary is
 * better than a field that is sometimes `number` and sometimes `''`. `qtyBasis` is absent on
 * purpose — it is derived from the unit (see `units.ts`).
 */
export interface ContextFormValues {
  name: string;
  categoryCode: string;
  packType: PackType;
  surface: Surface;
  isImported: boolean;
  quantityValue: string;
  quantityUnit: string;
  pdpAreaCm2: string;
  channel: SalesChannel;
  /** Mode A only, and never read in Mode B. */
  district: string;
}

/**
 * Sensible starting values for the org's mode.
 *
 * Mode A is a field inspection of something already on a shelf, so retail. Mode B is most often
 * artwork for a marketplace listing, where Rule 6(10A) applies — so e-commerce, which turns the
 * country-of-origin rule on rather than leaving it off by default.
 */
export function defaultContextValues(mode: OrgMode | null): ContextFormValues {
  return {
    name: '',
    categoryCode: '',
    packType: 'flexible',
    surface: 'printed',
    isImported: false,
    quantityValue: '',
    quantityUnit: '',
    pdpAreaCm2: '',
    channel: mode === 'industry' ? 'ecommerce' : 'retail',
    district: '',
  };
}

/** Parse a typed decimal. Returns null rather than NaN, so callers cannot forget to check. */
export function parseDecimal(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) return null;
  if (!/^\d*\.?\d+$/.test(trimmed)) return null;

  const value = Number.parseFloat(trimmed);
  return Number.isFinite(value) ? value : null;
}

export function isValidName(raw: string): boolean {
  const trimmed = raw.trim();
  return trimmed.length >= 2 && trimmed.length <= MAX_NAME_LENGTH;
}

export function isValidQuantityValue(raw: string): boolean {
  const value = parseDecimal(raw);
  return value !== null && value > 0 && value <= MAX_QUANTITY_VALUE;
}

export function isValidPdpArea(raw: string): boolean {
  const value = parseDecimal(raw);
  return value !== null && value > 0 && value <= MAX_PDP_AREA_CM2;
}

/**
 * Whether the principal display panel area is required, given what has been typed so far.
 *
 * Unparseable units are "not required yet" rather than required: a half-typed `k` should not make a
 * second field go red.
 */
export function pdpAreaRequired(quantityUnit: string): boolean {
  const unit = normaliseUnit(quantityUnit);
  return unit !== null && requiresPdpArea(unit);
}

export interface BuiltQuantity {
  quantity: NetQuantity;
  unit: NetQuantityUnit;
}

/** The quantity a form's two fields describe, or null if either is not yet usable. */
export function buildQuantity(value: string, rawUnit: string): BuiltQuantity | null {
  const parsed = parseDecimal(value);
  const unit = normaliseUnit(rawUnit);

  if (parsed === null || parsed <= 0 || parsed > MAX_QUANTITY_VALUE || unit === null) return null;

  return { quantity: { value: parsed, unit }, unit };
}

/**
 * Build the profile the rules engine will read, or null if the form is not yet complete enough.
 *
 * Total by design: every branch that cannot produce a valid profile returns null, so there is no
 * path where a partially-filled form yields a profile with a `NaN` quantity in it.
 */
export function buildProfile(values: ContextFormValues): ProductProfile | null {
  if (!isValidName(values.name)) return null;
  if (values.categoryCode.trim().length === 0) return null;

  const built = buildQuantity(values.quantityValue, values.quantityUnit);
  if (!built) return null;

  const qtyBasis = basisForUnit(built.unit);

  // Table-II keys its thresholds on this area. Missing it is not a cosmetic gap: the height rules
  // would have no row to read (CLAUDE.md §3.3).
  const pdpArea = parseDecimal(values.pdpAreaCm2);
  if (
    qtyBasis === 'length_area_or_number' &&
    (pdpArea === null || !isValidPdpArea(values.pdpAreaCm2))
  )
    return null;
  if (values.pdpAreaCm2.trim().length > 0 && !isValidPdpArea(values.pdpAreaCm2)) return null;

  return {
    name: values.name.trim(),
    categoryCode: values.categoryCode,
    packType: values.packType,
    surface: values.surface,
    isImported: values.isImported,
    qtyBasis,
    netQuantity: built.quantity,
    channel: values.channel,
    pdpAreaCm2: pdpArea,
  };
}

/** Thrown rather than allowing a scan whose profile the rules engine would misread. */
export class IncompleteProfileError extends Error {
  constructor(readonly missing: readonly string[]) {
    super(`Product profile is missing: ${missing.join(', ')}`);
    this.name = 'IncompleteProfileError';
  }
}

/**
 * The FR-03 choke point: refuse a profile missing any of the three rule-changing fields.
 *
 * The compiler already requires them, so this catches the cases it cannot — a quantity that parsed
 * to `NaN`, a unit that survived as an empty string through a future refactor, a profile
 * deserialised from an older queued scan. The same reasoning as `markerFieldsForScan`: the
 * invariant is worth more than the line count, and a scan created without it is a report with a
 * confidently wrong verdict in it.
 */
export function assertRuleRelevantFields(profile: ProductProfile): ProductProfile {
  const missing: string[] = [];

  if (!Number.isFinite(profile.netQuantity.value) || profile.netQuantity.value <= 0)
    missing.push('netQuantity.value');
  if (!profile.netQuantity.unit) missing.push('netQuantity.unit');
  if (typeof profile.isImported !== 'boolean') missing.push('isImported');
  if (!profile.surface) missing.push('surface');
  if (profile.qtyBasis === 'length_area_or_number' && profile.pdpAreaCm2 === null)
    missing.push('pdpAreaCm2');

  if (missing.length > 0) throw new IncompleteProfileError(missing);

  return profile;
}
