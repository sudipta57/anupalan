/**
 * The product profile — the shared abstraction that makes SIH26034 and SIH26107 one system.
 *
 * It decides which declarations apply *and* which QCO or Indian Standard applies
 * (docs/01-architecture.md §2). Three fields on it change which rules run, which is why FR-03
 * makes all three mandatory on a completed scan: net quantity, the imported flag, and surface.
 */

import type { IsoDateTime, Paise } from './common';

/** Physical pack construction (FR-03). */
export type PackType = 'rigid' | 'flexible' | 'glass' | 'can' | 'other';

/**
 * How the declaration is applied to the pack.
 *
 * `embossed` covers blown, formed, moulded, embossed and perforated text, and carries a higher
 * numeral-height threshold in both Table-I and Table-II.
 */
export type Surface = 'printed' | 'embossed';

/** Which Rule 9 table applies: Table-I keys on quantity, Table-II on display-panel area. */
export type QtyBasis = 'weight_or_volume' | 'length_area_or_number';

/** Where the product is being checked. Rule 6(10A) applies only to e-commerce listings. */
export type SalesChannel = 'retail' | 'ecommerce';

/** Prescribed unit symbols (Rule 8, Second Schedule). `gms`, `Gm` and `ltr` are not units. */
export type NetQuantityUnit = 'g' | 'kg' | 'ml' | 'l' | 'L' | 'mm' | 'cm' | 'm' | 'N' | 'U';

export interface NetQuantity {
  value: number;
  unit: NetQuantityUnit;
}

/**
 * Everything the rules engine needs to know about the product, independent of any one scan.
 *
 * `evaluate()` is a pure function of this plus extractions, measurements and the rule pack
 * (TRD FR-25), so anything a rule branches on has to live here.
 */
export interface ProductProfile {
  name: string;
  categoryCode: string;
  packType: PackType;
  surface: Surface;
  isImported: boolean;
  qtyBasis: QtyBasis;
  netQuantity: NetQuantity;
  channel: SalesChannel;
  /** Principal display panel area in cm², used to key Table-II. Null when not measured. */
  pdpAreaCm2: number | null;
}

export interface Product {
  id: string;
  orgId: string;
  profile: ProductProfile;
  gtin: string | null;
  /** Declared retail sale price, in integer paise. */
  mrpPaise: Paise | null;
  createdAt: IsoDateTime;
}
