/**
 * Context prefill wire shapes and their mapping — `POST /v1/prefill`, `GET /v1/prefill/{id}`.
 *
 * A prefill is not a resource: it has no row, no history and a life of about a minute. The mapping
 * is correspondingly small — the only real work is snake_case to camelCase, done explicitly like
 * every other adapter here rather than by a generic transformer (`common.ts` says why).
 *
 * **The image goes up in the request body, base64.** Every other image in this app is PUT straight
 * to object storage at a presigned URL, and that rule is about evidence — the scan's own
 * photographs, whose SHA-256 is the chain a report cites. This one is a downscaled thumbnail the
 * server reads once and deletes, so it takes the short path: one request instead of three, and no
 * new method on the `Transport` interface, which is deliberately narrow.
 */

import type { PrefillResult, PrefillStatus, Suggestion } from '@/features/scan-context/prefill';

export interface WireSuggestion {
  field: string;
  value: string;
  confidence: number;
  from_field_code: string;
  source_text: string;
}

export interface WirePrefillAccepted {
  prefill_id: string;
  status: 'reading';
}

export interface WirePrefill {
  prefill_id: string;
  status: PrefillStatus;
  suggestions?: WireSuggestion[];
  word_count?: number;
  reduced?: boolean;
}

export function toSuggestion(wire: WireSuggestion): Suggestion {
  return {
    field: wire.field,
    value: wire.value,
    confidence: wire.confidence,
    fromFieldCode: wire.from_field_code,
    sourceText: wire.source_text,
  };
}

export function toPrefill(wire: WirePrefill): PrefillResult {
  return {
    prefillId: wire.prefill_id,
    status: wire.status,
    suggestions: (wire.suggestions ?? []).map(toSuggestion),
    wordCount: wire.word_count ?? 0,
    reduced: wire.reduced ?? false,
  };
}

/**
 * The accepted response, as a result the screen can hold immediately.
 *
 * Given a `reading` shape of its own rather than a null so the form can say "reading the label"
 * from the moment the request returns, rather than after the first poll.
 */
export function toAcceptedPrefill(wire: WirePrefillAccepted): PrefillResult {
  return {
    prefillId: wire.prefill_id,
    status: 'reading',
    suggestions: [],
    wordCount: 0,
    reduced: false,
  };
}
