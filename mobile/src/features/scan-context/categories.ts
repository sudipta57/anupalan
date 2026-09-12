/**
 * Product categories — FR-03's searchable category field.
 *
 * The category is the hinge between the two problem statements. It narrows which Legal Metrology
 * declarations apply (SIH26034) and it is the first thing a BIS applicability lookup keys on
 * (SIH26107) — one profile, two engines (docs/01-architecture.md §2). That is why it is a coded
 * list and not free text: a typed code can be matched against a Quality Control Order, a typed
 * phrase cannot.
 *
 * **Codes are the contract, labels are for people.** The code goes to the backend and into the
 * rule pack's category filters; the label is translated and may be reworded freely. The four codes
 * the fixture products already use are here verbatim, so a fixture profile stays expressible.
 *
 * `keywords` exist because people search for what a thing is called, not for its taxonomy — an
 * inspector holding a packet of atta types "atta", not "flour". They are matched alongside the
 * translated label, so searching works in either language without needing translated keywords.
 */

import type { TranslationKey } from '@/i18n';

export interface Category {
  /** Stable, sent to the backend. Never rename one — rule packs cite these. */
  code: string;
  labelKey: TranslationKey;
  /** Extra search terms, lowercase. Hindi terms transliterated as they are typed in practice. */
  keywords: readonly string[];
}

export const CATEGORIES: readonly Category[] = [
  // Food — the bulk of Legal Metrology enforcement work.
  {
    code: 'food.flour',
    labelKey: 'categories.foodFlour',
    keywords: ['atta', 'maida', 'besan', 'suji', 'rava', 'flour', 'wheat'],
  },
  {
    code: 'food.rice',
    labelKey: 'categories.foodRice',
    keywords: ['rice', 'chawal', 'basmati', 'poha', 'grain', 'cereal'],
  },
  {
    code: 'food.pulses',
    labelKey: 'categories.foodPulses',
    keywords: ['dal', 'daal', 'pulses', 'chana', 'moong', 'toor', 'lentil', 'rajma'],
  },
  {
    code: 'food.oil',
    labelKey: 'categories.foodOil',
    keywords: ['oil', 'tel', 'mustard', 'sarson', 'ghee', 'vanaspati', 'olive', 'refined'],
  },
  {
    code: 'food.spices',
    labelKey: 'categories.foodSpices',
    keywords: ['masala', 'spice', 'haldi', 'turmeric', 'chilli', 'mirch', 'jeera', 'dhania'],
  },
  {
    code: 'food.dairy',
    labelKey: 'categories.foodDairy',
    keywords: ['milk', 'doodh', 'paneer', 'butter', 'cheese', 'curd', 'dahi', 'dairy'],
  },
  {
    code: 'food.bakery',
    labelKey: 'categories.foodBakery',
    keywords: ['biscuit', 'cookie', 'bread', 'rusk', 'cake', 'bakery', 'namkeen'],
  },
  {
    code: 'food.snacks',
    labelKey: 'categories.foodSnacks',
    keywords: ['chips', 'namkeen', 'snack', 'wafer', 'mixture', 'bhujia'],
  },
  {
    code: 'food.confectionery',
    labelKey: 'categories.foodConfectionery',
    keywords: ['chocolate', 'candy', 'toffee', 'sweet', 'mithai', 'confectionery'],
  },
  {
    code: 'food.tea_coffee',
    labelKey: 'categories.foodTeaCoffee',
    keywords: ['tea', 'chai', 'coffee', 'green tea', 'instant'],
  },
  {
    code: 'food.baby',
    labelKey: 'categories.foodBaby',
    keywords: ['baby', 'infant', 'formula', 'cereal', 'weaning'],
  },
  {
    code: 'food.water',
    labelKey: 'categories.foodWater',
    keywords: ['water', 'pani', 'mineral', 'packaged drinking water'],
  },

  // Beverages.
  {
    code: 'beverage.soft_drink',
    labelKey: 'categories.beverageSoftDrink',
    keywords: ['cold drink', 'soda', 'soft drink', 'carbonated', 'energy drink'],
  },
  {
    code: 'beverage.juice',
    labelKey: 'categories.beverageJuice',
    keywords: ['juice', 'nectar', 'squash', 'sharbat', 'fruit drink'],
  },

  // Personal care.
  {
    code: 'personal.soap',
    labelKey: 'categories.personalSoap',
    keywords: ['soap', 'sabun', 'shampoo', 'handwash', 'bathing bar'],
  },
  {
    code: 'personal.cosmetics',
    labelKey: 'categories.personalCosmetics',
    keywords: ['cream', 'lotion', 'cosmetic', 'powder', 'kajal', 'lipstick', 'oil'],
  },
  {
    code: 'personal.oral',
    labelKey: 'categories.personalOral',
    keywords: ['toothpaste', 'manjan', 'brush', 'mouthwash', 'oral'],
  },

  // Household.
  {
    code: 'household.detergent',
    labelKey: 'categories.householdDetergent',
    keywords: ['detergent', 'surf', 'washing powder', 'liquid', 'bar'],
  },
  {
    code: 'household.cleaning',
    labelKey: 'categories.householdCleaning',
    keywords: ['cleaner', 'phenyl', 'floor', 'disinfectant', 'toilet'],
  },

  // Non-food, where Table-II and the QCO lists matter most.
  {
    code: 'stationery.paper',
    labelKey: 'categories.stationeryPaper',
    keywords: ['notebook', 'copy', 'register', 'paper', 'pen', 'stationery'],
  },
  {
    code: 'electronics.accessory',
    labelKey: 'categories.electronicsAccessory',
    keywords: ['charger', 'cable', 'adapter', 'battery', 'earphone', 'powerbank'],
  },
  {
    code: 'electronics.appliance',
    labelKey: 'categories.electronicsAppliance',
    keywords: ['appliance', 'mixer', 'iron', 'heater', 'fan', 'kettle'],
  },
  {
    code: 'textile.garment',
    labelKey: 'categories.textileGarment',
    keywords: ['garment', 'cloth', 'shirt', 'saree', 'textile', 'hosiery'],
  },
  {
    code: 'hardware.cement',
    labelKey: 'categories.hardwareCement',
    keywords: ['cement', 'putty', 'plaster', 'construction', 'bag'],
  },
  {
    code: 'hardware.fastener',
    labelKey: 'categories.hardwareFastener',
    keywords: ['screw', 'bolt', 'nail', 'fastener', 'hardware', 'washer'],
  },
  {
    code: 'other.general',
    labelKey: 'categories.otherGeneral',
    keywords: ['other', 'miscellaneous', 'general'],
  },
];

export const CATEGORIES_BY_CODE: Readonly<Record<string, Category>> = Object.fromEntries(
  CATEGORIES.map((category) => [category.code, category])
);

export function categoryFor(code: string): Category | null {
  return CATEGORIES_BY_CODE[code] ?? null;
}

/**
 * Filter the list by a typed query, matched against the translated label and the keywords.
 *
 * `translate` is passed in rather than imported so this stays pure and testable in either locale —
 * the screen hands it `t` from `useT()`.
 */
export function searchCategories(
  query: string,
  translate: (key: TranslationKey) => string
): readonly Category[] {
  const needle = query.trim().toLowerCase();
  if (needle.length === 0) return CATEGORIES;

  return CATEGORIES.filter(
    (category) =>
      translate(category.labelKey).toLowerCase().includes(needle) ||
      category.code.includes(needle) ||
      category.keywords.some((keyword) => keyword.includes(needle))
  );
}
