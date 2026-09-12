/**
 * 220 seeded scans for the history list.
 *
 * Generated from a fixed seed rather than written out, for two reasons: a 220-entry literal is
 * unreviewable, and FR-09's acceptance criterion — filter 200 scans by verdict inside 500 ms —
 * needs a realistic volume to be measured rather than assumed.
 *
 * Deterministic: the same seed gives the same 220 scans on every run and on every machine, so a
 * screenshot taken today matches one taken next week, and a failing test is reproducible.
 */

import type { FindingsSummary, ScanListItem, ScanStatus } from '@/domain';

import { HERO_FINDINGS_RESULT, HERO_SCAN } from './hero-scan';
import { DISTRICTS, ENFORCEMENT_ORG, INDUSTRY_ORG } from './orgs';
import { PRODUCTS } from './products';

/** mulberry32 — small, fast, and good enough for fixtures. Same seed, same output, always. */
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const SEED = 20260912;
const TOTAL = 220;

/** Newest scan in the set. Fixed so the list is stable across runs. */
const LATEST = Date.parse('2026-09-11T09:42:18Z');
const DAY_MS = 86_400_000;

function pick<T>(rand: () => number, items: readonly T[]): T {
  return items[Math.floor(rand() * items.length)];
}

function buildSummary(rand: () => number): FindingsSummary {
  const roll = rand();

  // Most real labels pass most rules. A set where half the scans fail would make the history
  // screen look impressive and teach us nothing about the common case.
  if (roll < 0.5)
    return { pass: 12 + Math.floor(rand() * 2), fail: 0, borderline: 0, notAssessable: 1 };

  // **Borderline and nothing else.** Without this bucket every borderline in the set would sit
  // beside a failure, and a verdict filter that merged the two — `fail > 0 || borderline > 0` —
  // would return an identical list and pass every test written against this data. This is the one
  // shape that catches the collapse CLAUDE.md §3.4 forbids, so the fixture has to contain it.
  if (roll < 0.62) return { pass: 11, fail: 0, borderline: 1, notAssessable: 1 };

  if (roll < 0.87)
    return { pass: 10, fail: 1 + Math.floor(rand() * 2), borderline: 1, notAssessable: 1 };
  return { pass: 7, fail: 3 + Math.floor(rand() * 3), borderline: 1, notAssessable: 2 };
}

function buildStatus(rand: () => number): ScanStatus {
  const roll = rand();
  if (roll < 0.94) return 'complete';
  if (roll < 0.97) return 'processing';
  return 'failed';
}

function generate(): ScanListItem[] {
  const rand = mulberry32(SEED);
  const items: ScanListItem[] = [];

  for (let i = 1; i < TOTAL; i += 1) {
    const product = pick(rand, PRODUCTS);
    const enforcement = rand() < 0.6;
    const status = buildStatus(rand);

    items.push({
      id: `scn_seed_${String(i).padStart(3, '0')}`,
      orgId: enforcement ? ENFORCEMENT_ORG.id : INDUSTRY_ORG.id,
      productId: product.id,
      productName: product.profile.name,
      status,
      // Spread back over roughly six months, newest first.
      capturedAt: new Date(LATEST - i * (DAY_MS * 0.8) - Math.floor(rand() * DAY_MS)).toISOString(),
      district: enforcement ? pick(rand, DISTRICTS) : null,
      summary:
        status === 'complete'
          ? buildSummary(rand)
          : { pass: 0, fail: 0, borderline: 0, notAssessable: 0 },
      thumbnailUri: null,
    });
  }

  return items;
}

/** The hero scan leads the list, so opening History and tapping the first row shows the good one. */
const HERO_ITEM: ScanListItem = {
  id: HERO_SCAN.id,
  orgId: HERO_SCAN.orgId,
  productId: HERO_SCAN.productId,
  productName: HERO_SCAN.profile.name,
  status: HERO_SCAN.status,
  capturedAt: HERO_SCAN.capturedAt,
  district: HERO_SCAN.district,
  summary: HERO_FINDINGS_RESULT.summary,
  thumbnailUri: 'fixture://rectified-label',
};

export const SCAN_LIST: ScanListItem[] = [HERO_ITEM, ...generate()];
