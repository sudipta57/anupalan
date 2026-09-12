/**
 * Mode A's evidence panel, and the lock that comes with it — FR-05's enforcement column.
 *
 * `01-architecture.md` §10: *SHA-256 of the raw image recorded at upload; `audit_log` is hash-chained;
 * reports embed both hashes. Anyone can verify a report was not altered after issue.* The panel is
 * the app's half of that claim — it shows an inspector the four things that tie a verdict to a moment
 * and a place, before they decide to issue anything.
 *
 * Two deliberate refusals:
 *
 * - **The rectified image's hash is not offered as the image hash.** §10 records the hash of what came
 *   off the camera. The rectified image is derived from it by a homography, so its hash verifies a
 *   computation rather than a photograph, and a chain built on it would be unfalsifiable while
 *   looking exactly as reassuring. If there is no raw asset, `imageSha256` is null and the panel says
 *   the hash is not available yet.
 * - **Nothing here computes a hash.** The integrity claim belongs to the server; see flag 2 in
 *   `docs/04-frontend-plan.md` — until the backend lands, these are fixture values and the UI is real
 *   while the claim is not. A hash computed on the phone would be a hash of whatever the phone chose
 *   to send.
 *
 * Pure. The coordinate pair itself is formatted by `features/scan-context`'s `formatGeo`, which is
 * where the app already decided how many decimal places a recorded fix is printed to.
 */

import type { FindingsResult, GeoPoint, IsoDateTime, OrgMode, Scan } from '@/domain';

export interface Evidence {
  /** SHA-256 of the **raw** upload. Null when the scan carries no raw asset. */
  imageSha256: string | null;
  /** SHA-256 over the findings blob. */
  findingsSha256: string;
  /** When the shutter fired — not when the server received it (`src/api/types.ts`, flag 16). */
  capturedAt: IsoDateTime;
  geo: GeoPoint | null;
  district: string | null;
  /** Set once a report exists. After this, editing is locked. */
  reportIssuedAt: IsoDateTime | null;
}

/** The evidence panel is an enforcement feature. Mode B collects no location and issues no record. */
export function showsEvidence(mode: OrgMode | null): boolean {
  return mode === 'enforcement';
}

/**
 * The raw image's hash, or null.
 *
 * Null rather than the rectified asset's hash — see the note at the top of this file.
 */
export function rawImageHash(scan: Scan): string | null {
  return scan.assets.find((asset) => asset.kind === 'raw')?.sha256 ?? null;
}

export function evidenceFor(scan: Scan, result: Pick<FindingsResult, 'findingsSha256'>): Evidence {
  return {
    imageSha256: rawImageHash(scan),
    findingsSha256: result.findingsSha256,
    capturedAt: scan.capturedAt,
    geo: scan.geo,
    district: scan.district,
    reportIssuedAt: scan.reportIssuedAt,
  };
}

/**
 * Whether corrections are closed on this scan.
 *
 * Mode A only, and only after a report exists. The reasoning is not that an inspector cannot be
 * trusted — it is that a report already in someone's hands embeds a findings hash, and a field edited
 * afterwards would leave that document disagreeing with its own source with no trace of which came
 * first. Mode B has no issued record to contradict, so a brand may keep correcting a draft.
 *
 * Locking is about *editing*, never about reading: a locked scan shows every finding, every citation
 * and the whole evidence panel.
 */
export function editingLocked(mode: OrgMode | null, scan: Scan): boolean {
  return showsEvidence(mode) && scan.reportIssuedAt !== null;
}

/**
 * A hash in eight-character groups.
 *
 * Printed in full, because a truncated hash cannot be checked against anything, and grouped because a
 * human comparing two 64-character strings on a phone needs somewhere to rest their eye. The grouping
 * is presentation only — stripping the spaces gives the original back, which is what the test pins.
 */
export function hashGroups(hash: string, size = 8): string {
  if (size <= 0) return hash;
  return (hash.match(new RegExp(`.{1,${size}}`, 'g')) ?? []).join(' ');
}
