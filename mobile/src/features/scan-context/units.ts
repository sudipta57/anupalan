/**
 * Net quantity units — FR-03.
 *
 * Rule 8 and the Second Schedule prescribe the *symbol*, not merely the unit. `500 gms` is a
 * declaration defect, `500 g` is not, and the difference is a rule outcome rather than a styling
 * preference. So this module does two separate jobs and keeps them separate:
 *
 * 1. **`normaliseUnit`** maps what a person types onto a prescribed symbol, because the profile
 *    feeds a rules engine that branches on the symbol and must never see `gms`.
 * 2. **`basisForUnit`** derives which Rule 9 table applies, because the unit already determines
 *    it and asking the user a second question only creates a way for the two answers to disagree.
 *
 * **Normalising here is not the same as excusing it on the label.** What the pack *says* is read
 * off the photograph by the extraction layer and judged by the rule pack; a wrong symbol printed
 * on a pack is a finding. This normalisation is only about the operator's own typing in this form,
 * where `gms` means grams and pretending otherwise would block a scan for no reason.
 *
 * Pure, so the whole table is testable without a form.
 */

import type { NetQuantityUnit, QtyBasis } from '@/domain';

/**
 * Units that put a product in Table-I: the table keyed on the declared quantity itself.
 *
 * Both `l` and `L` are prescribed for litre, so both survive normalisation — a user who types
 * `L` gets `L`, and only a non-symbol like `ltr` is rewritten.
 */
export const WEIGHT_OR_VOLUME_UNITS: readonly NetQuantityUnit[] = ['g', 'kg', 'ml', 'l', 'L'];

/** Units that put a product in Table-II: the table keyed on display-panel area. */
export const LENGTH_AREA_OR_NUMBER_UNITS: readonly NetQuantityUnit[] = ['mm', 'cm', 'm', 'N', 'U'];

export const NET_QUANTITY_UNITS: readonly NetQuantityUnit[] = [
  ...WEIGHT_OR_VOLUME_UNITS,
  ...LENGTH_AREA_OR_NUMBER_UNITS,
];

/**
 * What people actually type, and the symbol it means.
 *
 * Keys are lowercase; lookup lowercases the input. Anything already an exact prescribed symbol
 * skips this table entirely, which is what keeps `L` and `N` from being flattened to `l` and `n`.
 *
 * The entries are not decoration. `gms`, `Gm` and `ltr` are named in FR-03 precisely because they
 * are what appears on Indian packs and in the operators' own habits.
 */
const ALIASES: Readonly<Record<string, NetQuantityUnit>> = {
  // mass
  g: 'g',
  gm: 'g',
  gms: 'g',
  gram: 'g',
  grams: 'g',
  gramme: 'g',
  grammes: 'g',
  kg: 'kg',
  kgs: 'kg',
  kgm: 'kg',
  kilo: 'kg',
  kilos: 'kg',
  kilogram: 'kg',
  kilograms: 'kg',

  // volume
  ml: 'ml',
  mls: 'ml',
  millilitre: 'ml',
  millilitres: 'ml',
  milliliter: 'ml',
  milliliters: 'ml',
  cc: 'ml',
  l: 'l',
  lt: 'l',
  ltr: 'l',
  ltrs: 'l',
  lit: 'l',
  litre: 'l',
  litres: 'l',
  liter: 'l',
  liters: 'l',

  // length
  mm: 'mm',
  millimetre: 'mm',
  millimetres: 'mm',
  millimeter: 'mm',
  millimeters: 'mm',
  cm: 'cm',
  cms: 'cm',
  centimetre: 'cm',
  centimetres: 'cm',
  centimeter: 'cm',
  centimeters: 'cm',
  m: 'm',
  mtr: 'm',
  mtrs: 'm',
  metre: 'm',
  metres: 'm',
  meter: 'm',
  meters: 'm',

  // number
  n: 'N',
  no: 'N',
  nos: 'N',
  num: 'N',
  pc: 'N',
  pcs: 'N',
  piece: 'N',
  pieces: 'N',
  count: 'N',

  // unit (as the Second Schedule uses it: an item sold by the unit)
  u: 'U',
  unit: 'U',
  units: 'U',
};

function isPrescribedSymbol(value: string): value is NetQuantityUnit {
  return (NET_QUANTITY_UNITS as readonly string[]).includes(value);
}

/**
 * The prescribed symbol a typed unit means, or null if it means nothing.
 *
 * Exact symbols pass through untouched — `L` stays `L` — so normalisation can never narrow a
 * declaration the Second Schedule allows.
 */
export function normaliseUnit(raw: string): NetQuantityUnit | null {
  const trimmed = raw.trim().replace(/\.$/, '');
  if (trimmed.length === 0) return null;

  if (isPrescribedSymbol(trimmed)) return trimmed;

  return ALIASES[trimmed.toLowerCase()] ?? null;
}

/** True when what the user typed was not itself a prescribed symbol, so the form should say so. */
export function wasRewritten(raw: string, normalised: NetQuantityUnit): boolean {
  return raw.trim().replace(/\.$/, '') !== normalised;
}

/**
 * Which Rule 9 table the unit puts the product in.
 *
 * Derived rather than asked. Table-I is keyed on the declared quantity, which only exists for
 * weight and volume; everything else is keyed on the area of the principal display panel. A form
 * that asked for both would eventually be told `kg` and `length_area_or_number` in the same
 * submission, and the rules engine would silently read the wrong table.
 */
export function basisForUnit(unit: NetQuantityUnit): QtyBasis {
  return (WEIGHT_OR_VOLUME_UNITS as readonly string[]).includes(unit)
    ? 'weight_or_volume'
    : 'length_area_or_number';
}

/**
 * Whether the principal display panel area is needed for this unit.
 *
 * Table-II keys its height thresholds on that area, so for a count or length declaration the area
 * is not extra detail — without it the height rules have no row to read and must come back
 * NOT_ASSESSABLE (CLAUDE.md §3.3).
 */
export function requiresPdpArea(unit: NetQuantityUnit): boolean {
  return basisForUnit(unit) === 'length_area_or_number';
}

/** How the unit reads in a summary line: `1 kg`, `200 N`. */
export function formatQuantity(value: number, unit: NetQuantityUnit): string {
  return `${value} ${unit}`;
}
