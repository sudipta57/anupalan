/**
 * Scaffolding smoke test: the repo skeleton and the four-valued verdict contract.
 *
 * Real feature tests arrive with their features (CLAUDE.md §6 — tests are written before the
 * implementation and are the specification). This one exists so `npm test` is a real gate in CI
 * from the first commit rather than something switched on later.
 */

import type { ErrorEnvelope } from '@/api';
import { VERDICTS } from '@/domain';

describe('verdict contract', () => {
  it('is four-valued', () => {
    // CLAUDE.md §3.4: never collapse BORDERLINE into FAIL, and NOT_ASSESSABLE is not a failure.
    expect(VERDICTS).toHaveLength(4);
    expect(VERDICTS).toContain('BORDERLINE');
    expect(VERDICTS).toContain('NOT_ASSESSABLE');
  });

  it('keeps BORDERLINE distinct from FAIL', () => {
    const failures = VERDICTS.filter((v) => v === 'FAIL');
    expect(failures).toEqual(['FAIL']);
  });
});

describe('contract layer stubs', () => {
  it('shapes every failure as the one error envelope', () => {
    // TRD NFR-07: all API responses use {error:{code,message,details}}.
    const envelope: ErrorEnvelope = {
      error: { code: 'validation_error', message: 'Request validation failed' },
    };

    expect(Object.keys(envelope.error).sort()).toEqual(['code', 'message']);
    expect(envelope.error.details).toBeUndefined();
  });
});
