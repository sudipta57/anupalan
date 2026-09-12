/**
 * Products the fixture scans point at.
 *
 * The profiles are chosen to exercise different branches of the rules: a 1 kg pack lands in
 * Table-I's "above 500 g" row, a 180 g pack in the 200 g row, an imported product turns the
 * importer rule on, and a stationery pack switches the basis to Table-II.
 */

import type { Product } from '@/domain';

export const PRODUCTS: Product[] = [
  {
    id: 'prd_atta_1kg',
    orgId: 'org_annapurna',
    gtin: '8901234567890',
    mrpPaise: 24_900,
    createdAt: '2026-06-01T05:00:00Z',
    profile: {
      name: 'Sampoorna Whole Wheat Atta 1 kg',
      categoryCode: 'food.flour',
      packType: 'flexible',
      surface: 'printed',
      isImported: false,
      qtyBasis: 'weight_or_volume',
      netQuantity: { value: 1, unit: 'kg' },
      channel: 'retail',
      pdpAreaCm2: 70,
    },
  },
  {
    id: 'prd_biscuit_180g',
    orgId: 'org_annapurna',
    gtin: '8901234567906',
    mrpPaise: 4_500,
    createdAt: '2026-06-04T05:00:00Z',
    profile: {
      name: 'Digestive Biscuits 180 g',
      categoryCode: 'food.bakery',
      packType: 'flexible',
      surface: 'printed',
      isImported: false,
      qtyBasis: 'weight_or_volume',
      netQuantity: { value: 180, unit: 'g' },
      channel: 'retail',
      pdpAreaCm2: 42,
    },
  },
  {
    id: 'prd_olive_oil_500ml',
    orgId: 'org_annapurna',
    gtin: '8412345678903',
    mrpPaise: 89_900,
    createdAt: '2026-06-11T05:00:00Z',
    profile: {
      name: 'Extra Virgin Olive Oil 500 ml',
      categoryCode: 'food.oil',
      packType: 'glass',
      surface: 'embossed',
      isImported: true,
      qtyBasis: 'weight_or_volume',
      netQuantity: { value: 500, unit: 'ml' },
      channel: 'ecommerce',
      pdpAreaCm2: 120,
    },
  },
  {
    id: 'prd_notebook_200',
    orgId: 'org_annapurna',
    gtin: '8901234567913',
    mrpPaise: 6_000,
    createdAt: '2026-06-18T05:00:00Z',
    profile: {
      name: 'Ruled Notebook, 200 pages',
      categoryCode: 'stationery.paper',
      packType: 'other',
      surface: 'printed',
      isImported: false,
      qtyBasis: 'length_area_or_number',
      netQuantity: { value: 200, unit: 'N' },
      channel: 'retail',
      pdpAreaCm2: 310,
    },
  },
];

export const PRODUCTS_BY_ID: Record<string, Product> = Object.fromEntries(
  PRODUCTS.map((p) => [p.id, p])
);
