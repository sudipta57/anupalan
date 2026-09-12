/**
 * The one error shape every backend response uses on failure (TRD NFR-07):
 *
 *     { "error": { "code": "validation_error", "message": "...", "details": ... } }
 *
 * `details` is `unknown`, never `any` — a caller must narrow it before use. That is enforced by
 * an eslint rule in this folder, and it is the difference between a typo surfacing at compile
 * time and surfacing in a report.
 */

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;

  const { error } = value as { error: unknown };
  if (typeof error !== 'object' || error === null) return false;

  const candidate = error as { code?: unknown; message?: unknown };
  return typeof candidate.code === 'string' && typeof candidate.message === 'string';
}

/**
 * A failed request, carrying the server's own code so screens can branch on meaning rather than
 * on a status number or a substring of a message.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(params: { code: string; message: string; status: number; details?: unknown }) {
    super(params.message);
    this.name = 'ApiError';
    this.code = params.code;
    this.status = params.status;
    this.details = params.details;
  }

  /** Build from a response body, tolerating a server that failed before it could shape one. */
  static fromResponse(status: number, body: unknown): ApiError {
    if (isErrorEnvelope(body)) {
      return new ApiError({
        code: body.error.code,
        message: body.error.message,
        status,
        details: body.error.details,
      });
    }

    return new ApiError({
      code: `http_${status}`,
      message: `Request failed with status ${status}`,
      status,
    });
  }

  /** 4xx means the request was wrong; retrying it unchanged will fail the same way. */
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
}
