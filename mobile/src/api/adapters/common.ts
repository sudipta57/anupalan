/**
 * Shared pieces of the wire→domain mapping.
 *
 * **Why this layer exists at all.** The API is snake_case and the app is camelCase, and the naive
 * fix — a recursive key transformer at the transport seam — would be a quiet disaster here. It would
 * rewrite `profile.is_imported` and `profile.net_qty_in_g_or_ml`, whose names are the *rule pack's*
 * contract rather than the API's, so a pack would stop matching its own fields; and it would rewrite
 * the presigned upload `headers` map, where `x-amz-*` must survive byte for byte or every upload
 * fails its signature. So each endpoint gets an explicit, typed, tested mapping instead.
 *
 * The second reason is that the differences are not only cosmetic. The server's status vocabulary is
 * not the app's, its marker names are not the app's, and several fields the app treats as certain
 * are nullable on the wire. Those are decisions, and decisions belong in named functions with the
 * reasoning written next to them — not in a transformer nobody can grep.
 *
 * Wire types live beside the function that maps them, so the two halves cannot drift apart
 * unnoticed. They are hand-written from `src/api/openapi.json`.
 */

import type { BBox } from '@/domain';

/** The server's bounding box. Same field names, so this is a shape check rather than a rename. */
export interface WireBBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function toBBox(wire: WireBBox | null | undefined): BBox | null {
  if (!wire) return null;
  return { x: wire.x, y: wire.y, width: wire.width, height: wire.height };
}

/**
 * A wire value that may be absent, as a definite `null`.
 *
 * FastAPI omits some optional keys rather than sending an explicit null, so `undefined` and `null`
 * arrive interchangeably. The app's types say `null`, and one of the two has to win here rather than
 * at every call site.
 */
export function orNull<T>(value: T | null | undefined): T | null {
  return value ?? null;
}

/**
 * Seconds between now and an ISO instant, never negative.
 *
 * The OTP endpoint reports an expiry instant and the app counts down a duration. Clamping at zero
 * matters because a phone whose clock is a minute fast would otherwise be handed a negative
 * countdown, and a timer running backwards reads as a broken app rather than an expired code.
 */
export function secondsUntil(iso: string, now: number = Date.now()): number {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return 0;
  return Math.max(0, Math.round((at - now) / 1000));
}
