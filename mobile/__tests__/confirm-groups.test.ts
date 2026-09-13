/**
 * The confirmation sheet folds fields below 70% under "Also unclear" — and folds, never filters.
 *
 * The backend holds every verdict on a scan until each field under FR-06's 0.75 is confirmed. So the
 * property worth pinning is not the split point but that the two groups together are exactly what
 * the scan is waiting on: a field that fell out of both would leave the scan "Read, not yet judged"
 * with nothing on screen to confirm.
 *
 * The fixture is the real scan that prompted the change — a Dabur back panel, where the one field
 * below 70% was a `best_before` read as "please see top panel."
 */

import type { Extraction } from '@/domain';
import {
  UNCLEAR_BELOW,
  fieldsNeedingConfirmation,
  groupForConfirmation,
} from '@/features/processing';

function extraction(overrides: Partial<Extraction>): Extraction {
  return {
    id: `ext_${overrides.fieldCode ?? 'mrp'}`,
    scanId: 'scn_1',
    fieldCode: 'mrp',
    valueRaw: 'Rs.20/-',
    valueNorm: null,
    source: 'llm',
    confidence: 0.7,
    bbox: null,
    ...overrides,
  };
}

const dabur = {
  extractions: [
    extraction({
      fieldCode: 'best_before',
      valueRaw: 'please see top panel.',
      source: 'regex',
      confidence: 0.25,
    }),
    extraction({ fieldCode: 'consumer_care_email', valueRaw: 'daburcares@dabur.com' }),
    extraction({ fieldCode: 'net_quantity', valueRaw: '180 ml' }),
    extraction({ fieldCode: 'mrp', valueRaw: 'Rs.20/-' }),
    extraction({ fieldCode: 'country_of_origin', valueRaw: 'Nenal' }),
    extraction({
      fieldCode: 'consumer_care_phone',
      valueRaw: '1800-103-1644',
      source: 'regex',
      confidence: 0.95,
    }),
  ],
};

describe('groupForConfirmation', () => {
  it('lists the readable fields and folds the unreadable one', () => {
    const { likely, unclear } = groupForConfirmation(dabur);

    expect(unclear.map((item) => item.fieldCode)).toEqual(['best_before']);
    expect(likely.map((item) => item.fieldCode).sort()).toEqual(
      ['consumer_care_email', 'country_of_origin', 'mrp', 'net_quantity'].sort()
    );
  });

  it('drops nothing the scan is waiting on', () => {
    const { likely, unclear } = groupForConfirmation(dabur);
    const waiting = fieldsNeedingConfirmation(dabur);

    expect([...likely, ...unclear].map((item) => item.id).sort()).toEqual(
      waiting.map((item) => item.id).sort()
    );
  });

  it('puts a field exactly at the boundary in the main list', () => {
    const { likely, unclear } = groupForConfirmation({
      extractions: [extraction({ confidence: UNCLEAR_BELOW })],
    });

    expect(likely).toHaveLength(1);
    expect(unclear).toHaveLength(0);
  });

  it('never lists a confident or already-confirmed field in either group', () => {
    const { likely, unclear } = groupForConfirmation({
      extractions: [
        extraction({ fieldCode: 'mrp', confidence: 0.95, source: 'regex' }),
        extraction({ fieldCode: 'best_before', confidence: 0.25, source: 'human' }),
      ],
    });

    expect([...likely, ...unclear]).toEqual([]);
  });

  it('keeps the fold as a presentation choice, below the confirmation threshold', () => {
    expect(UNCLEAR_BELOW).toBeLessThan(0.75);
  });
});
