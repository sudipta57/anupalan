/**
 * What the app actually puts on the wire.
 *
 * `adapters.test.ts` proves each translator is correct in isolation. That is not the same as proving
 * `endpoints.ts` *calls* it, and the difference is not academic: `createScan` shipped sending the
 * app's own camelCase `ProductProfile` straight through, because a comment in that file claimed the
 * profile's field names were the rule pack's contract and therefore passed through untouched. Half
 * true — the *wire* names are the rule pack's, and the app's are camelCase — so every scan created
 * on a real device came back **422** while every adapter unit test stayed green.
 *
 * `ProfileIn` and `ScanCreateIn` set `extra="forbid"`, so a wrong spelling is never a dropped field.
 * It is a rejected request. These tests therefore assert on the body handed to the transport rather
 * than on any translator's return value, and they fail if a key is camelCase or unexpected.
 */

import { api } from '@/api/endpoints';
import type { CreateScanBody } from '@/api/types';
import type { ProductProfile } from '@/domain';

const sent: { path: string; body: Record<string, unknown> }[] = [];

jest.mock('@/api/transport', () => ({
  transport: {
    request: jest.fn((spec: { path: string; body?: unknown }) => {
      sent.push({ path: spec.path, body: (spec.body ?? {}) as Record<string, unknown> });
      // Enough of a response for each adapter under test to map without throwing.
      return Promise.resolve({ scan_id: 'sc_1', uploads: [] });
    }),
  },
}));

const PROFILE: ProductProfile = {
  name: 'Protein Bar',
  categoryCode: 'food.dairy',
  packType: 'flexible',
  surface: 'printed',
  isImported: false,
  qtyBasis: 'weight_or_volume',
  netQuantity: { value: 500, unit: 'g' },
  channel: 'ecommerce',
  pdpAreaCm2: null,
};

const BODY: CreateScanBody = {
  profile: PROFILE,
  markerType: 'id1_card',
  // An ID-1 card is 85.6 mm on its long edge, which is the point of using one as a scale.
  markerMm: 85.6,
  assets: [{ contentType: 'image/jpeg', sizeBytes: 1024, sha256: 'a'.repeat(64) }],
  capturedAt: '2026-09-12T10:00:00.000Z',
  geo: null,
  district: null,
};

/** Exactly the keys `ProfileIn` declares. Anything else is a 422, not a warning. */
const PROFILE_IN_KEYS = new Set([
  'is_imported',
  'surface',
  'qty_basis',
  'channel',
  'net_qty_in_g_or_ml',
  'pdp_area_cm2',
  'net_qty_value',
  'net_qty_unit',
  'pack_type',
  'category_code',
  'name',
]);

beforeEach(() => {
  sent.length = 0;
});

describe('POST /scans', () => {
  it('sends the profile in the rule pack’s spelling, not the app’s', async () => {
    await api.createScan(BODY, 'idem_1');

    const profile = sent[0].body.profile as Record<string, unknown>;

    expect(profile.is_imported).toBe(false);
    expect(profile.category_code).toBe('food.dairy');
    expect(profile.pack_type).toBe('flexible');
    expect(profile.net_qty_value).toBe(500);
    expect(profile.net_qty_unit).toBe('g');
    // Normalised to the Table-I key, which is the translation a round trip would not catch.
    expect(profile.net_qty_in_g_or_ml).toBe(500);
  });

  it('sends no key ProfileIn does not declare', async () => {
    await api.createScan(BODY, 'idem_1');

    const profile = sent[0].body.profile as Record<string, unknown>;
    const unexpected = Object.keys(profile).filter((key) => !PROFILE_IN_KEYS.has(key));

    // Names the offenders rather than just failing a count, because the whole class of bug here is
    // one misspelled key among ten correct ones.
    expect(unexpected).toEqual([]);
  });

  it('carries no camelCase key anywhere in the body', async () => {
    await api.createScan(BODY, 'idem_1');

    const camel: string[] = [];
    const walk = (value: unknown, trail: string): void => {
      if (value === null || typeof value !== 'object') return;
      if (Array.isArray(value)) {
        value.forEach((item, i) => walk(item, `${trail}[${i}]`));
        return;
      }
      for (const [key, inner] of Object.entries(value)) {
        if (/[a-z][A-Z]/.test(key)) camel.push(`${trail}.${key}`);
        walk(inner, `${trail}.${key}`);
      }
    };
    walk(sent[0].body, 'body');

    expect(camel).toEqual([]);
  });

  it('declares each asset the way AssetIn expects', async () => {
    await api.createScan(BODY, 'idem_1');

    const assets = sent[0].body.assets as Record<string, unknown>[];

    expect(assets).toHaveLength(1);
    expect(assets[0]).toEqual({
      content_type: 'image/jpeg',
      size_bytes: 1024,
      sha256: 'a'.repeat(64),
      kind: 'raw',
    });
  });
});

describe('POST /bis/applicability', () => {
  it('also converts the profile — the one endpoint that always did', async () => {
    await api.bisApplicability({ profile: PROFILE });

    const profile = sent[0].body.profile as Record<string, unknown>;

    expect(profile.is_imported).toBe(false);
    expect(profile.net_qty_in_g_or_ml).toBe(500);
    expect(Object.keys(profile).filter((k) => !PROFILE_IN_KEYS.has(k))).toEqual([]);
  });
});
