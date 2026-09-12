/**
 * Product wire shapes and their mapping — `GET /v1/products`.
 *
 * **The catalogue is flatter than a scan's profile, and the gap is real rather than a naming
 * accident.** A scan carries a complete `ProductProfile` because FR-03's form makes the operator
 * supply every field that changes which rules run. A catalogue row carries whatever has been
 * recorded about a product, and the server deliberately does not invent a `qty_basis` or a
 * `channel` — the channel is where *this* check is happening, not a property of the product, and
 * the basis follows from the unit.
 *
 * So this mapping derives what can be derived and defaults the rest to the same values the context
 * form starts from. A product picked from the catalogue is a **starting point** for that form, not a
 * substitute for it.
 */

import type { NetQuantityUnit, PackType, Product, ProductProfile, Surface } from '@/domain';

import { orNull } from './common';

export interface WireProduct {
  product_id: string;
  org_id: string;
  name: string;
  brand?: string | null;
  category_code?: string | null;
  gtin?: string | null;
  is_imported?: boolean;
  pack_type?: string | null;
  surface?: string;
  net_qty_value?: number | null;
  net_qty_unit?: string | null;
  created_at: string;
}

export interface WireProductPage {
  items?: WireProduct[];
  next_cursor?: string | null;
}

/** Units Rule 9 keys Table-I on. Anything else means the pack is measured by length, area or count. */
const MASS_OR_VOLUME: ReadonlySet<string> = new Set(['g', 'kg', 'ml', 'l', 'L']);

/**
 * Which Rule 9 table a product's unit implies.
 *
 * Derived rather than stored, and derived here rather than asked of the user — `features/context`
 * makes the same inference from the unit they type, and the two must agree or a product picked from
 * the catalogue would be judged under a different table than the same pack entered by hand.
 */
export function qtyBasisFor(unit: string | null | undefined) {
  return unit && MASS_OR_VOLUME.has(unit)
    ? ('weight_or_volume' as const)
    : ('length_area_or_number' as const);
}

export function toProductProfile(wire: WireProduct): ProductProfile {
  return {
    name: wire.name,
    categoryCode: wire.category_code ?? '',
    packType: (wire.pack_type ?? 'other') as PackType,
    surface: (wire.surface ?? 'printed') as Surface,
    isImported: wire.is_imported ?? false,
    qtyBasis: qtyBasisFor(wire.net_qty_unit),
    netQuantity: {
      value: wire.net_qty_value ?? 0,
      unit: (wire.net_qty_unit ?? 'g') as NetQuantityUnit,
    },
    // Not a catalogue property: retail and e-commerce are two contexts for one product, and
    // Rule 6(10A) applies to the listing rather than to the pack.
    channel: 'retail',
    // Measured from a photograph, never from a catalogue row.
    pdpAreaCm2: null,
  };
}

export function toProduct(wire: WireProduct): Product {
  return {
    id: wire.product_id,
    orgId: wire.org_id,
    profile: toProductProfile(wire),
    gtin: orNull(wire.gtin),
    // The catalogue holds no price. An MRP is read off the pack and judged; a stored one would be a
    // second source of truth for the number a finding is about.
    mrpPaise: null,
    createdAt: wire.created_at,
  };
}
