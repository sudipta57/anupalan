/**
 * The one error envelope (TRD NFR-07).
 *
 * Every screen branches on `ApiError.code`, and the query client decides whether to retry from
 * `isClientError`, so both have to survive a malformed body without throwing.
 */

import { ApiError, isErrorEnvelope } from '@/api';

describe('isErrorEnvelope', () => {
  it('accepts the documented shape', () => {
    expect(isErrorEnvelope({ error: { code: 'validation_error', message: 'bad' } })).toBe(true);
  });

  it('rejects anything else', () => {
    expect(isErrorEnvelope(null)).toBe(false);
    expect(isErrorEnvelope({})).toBe(false);
    expect(isErrorEnvelope({ error: 'boom' })).toBe(false);
    expect(isErrorEnvelope({ error: { code: 1, message: 'bad' } })).toBe(false);
  });
});

describe('ApiError.fromResponse', () => {
  it('carries the server code and details through', () => {
    const error = ApiError.fromResponse(422, {
      error: {
        code: 'validation_error',
        message: 'Request validation failed',
        details: [{ field: 'mrp' }],
      },
    });

    expect(error.code).toBe('validation_error');
    expect(error.message).toBe('Request validation failed');
    expect(error.status).toBe(422);
    expect(error.details).toEqual([{ field: 'mrp' }]);
  });

  it('degrades to a status-derived code when the body is not an envelope', () => {
    const error = ApiError.fromResponse(502, '<html>gateway</html>');

    expect(error.code).toBe('http_502');
    expect(error.isClientError).toBe(false);
  });

  it('treats 4xx as a client error so the query client does not retry it', () => {
    // Cross-org access returns 404 by design; retrying it three times is pointless.
    expect(ApiError.fromResponse(404, null).isClientError).toBe(true);
    expect(ApiError.fromResponse(500, null).isClientError).toBe(false);
  });
});
