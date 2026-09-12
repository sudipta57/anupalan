/**
 * Report formats, and what a shared file is called — FR-08.
 *
 * **The filename is the part that looks cosmetic and is not.** A report leaves the app through the
 * system share sheet and lands in someone's WhatsApp, Drive or mail client, where it sits in a list
 * next to everything else they were sent that week. `report.pdf` is indistinguishable from every
 * other report ever generated, including the ones about different packs; an inspector forwarding
 * three of them cannot tell which is which without opening all three. So the name carries the
 * product, the capture date and enough of the scan id to break a tie.
 *
 * It is also the part most likely to break on real data. Product names are free text, arrive in
 * Devanagari, and contain slashes, quotes and emoji; a filename is not free text. Everything here is
 * pure so each of those is a test rather than a crash on a phone in a market.
 */

import type { ReportFormat, Scan } from '@/domain';
import type { TranslationKey } from '@/i18n';

/**
 * The formats offered for sharing.
 *
 * JSON is a real report format (FR-27) and is deliberately **not** here. It exists for a system that
 * consumes findings programmatically, and the place to fetch it is the API; putting it in a phone's
 * share sheet invites someone to send a machine artefact to a trader who cannot read it.
 */
export const SHAREABLE_FORMATS: readonly ReportFormat[] = ['pdf', 'docx'] as const;

export const MIME_TYPES: Record<ReportFormat, string> = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  json: 'application/json',
};

export const EXTENSIONS: Record<ReportFormat, string> = {
  pdf: 'pdf',
  docx: 'docx',
  json: 'json',
};

export const FORMAT_LABEL_KEYS: Record<ReportFormat, TranslationKey> = {
  pdf: 'report.formatPdf',
  docx: 'report.formatDocx',
  json: 'report.formatJson',
};

export const FORMAT_HINT_KEYS: Record<ReportFormat, TranslationKey> = {
  pdf: 'report.formatPdfHint',
  docx: 'report.formatDocxHint',
  json: 'report.formatJsonHint',
};

/** Longest the product part of a filename may run. Long names are truncated, never rejected. */
export const MAX_NAME_SEGMENT = 40;

/**
 * One path segment, safe on every filesystem and in every share target.
 *
 * Lowercase ASCII, digits and hyphens only. That is stricter than any one filesystem needs, and
 * deliberately so: the file crosses into apps that do their own escaping, and a name that survives
 * the strictest of them survives all of them.
 *
 * A name in Devanagari reduces to nothing here, which is correct rather than a bug — the caller
 * substitutes a generic segment. Transliterating Hindi into ASCII would produce a name that is
 * neither readable to a Hindi speaker nor accurate to anyone else.
 */
export function sanitiseSegment(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, MAX_NAME_SEGMENT)
    .replace(/-+$/g, '');
}

/** The date part, `YYYY-MM-DD`, or null if the timestamp is unusable. */
function dateSegment(iso: string): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(iso);
  return match ? match[1] : null;
}

/**
 * What the shared file is called.
 *
 * `anupalan-<product>-<date>-<id>.<ext>`. The scan id tail is what stops two scans of the same pack
 * on the same day from overwriting each other in a downloads folder — the failure there is silent,
 * and the file lost is evidence.
 */
export function fileNameFor(
  scan: Pick<Scan, 'id' | 'capturedAt' | 'profile'>,
  format: ReportFormat
): string {
  const product = sanitiseSegment(scan.profile.name) || 'scan';
  const date = dateSegment(scan.capturedAt);
  const tail = sanitiseSegment(scan.id).slice(-6) || 'report';

  return ['anupalan', product, date, tail].filter(Boolean).join('-') + `.${EXTENSIONS[format]}`;
}

/**
 * A file size a person can read.
 *
 * Shown next to each format because it is the one number that tells someone on a metered connection
 * whether to send the PDF now or wait — and because a report that comes back at 0 bytes is a
 * generation failure that would otherwise reach the share sheet looking fine.
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
