/**
 * Stage 9 — report export and share (FR-08).
 *
 * *Accept: both files share out of the app and open in an external viewer.*
 *
 * The eligibility gate gets the most attention here, because it is the one decision in the stage that
 * cannot be undone by the user. Everything else on a screen can be re-read, re-tapped or backed out
 * of; a PDF that has left the device cannot be recalled, and a report generated over a misread MRP is
 * CLAUDE.md §3.4's failure mode made permanent and distributable.
 *
 * Whether the files actually open in Acrobat and Word is, by construction, a device question — the
 * sample bytes are real (`scripts/make-sample-report.py`) but nothing in a test runner can open them.
 * That is items 6 and 7 of the Stage 9 device checklist.
 */

import { createMockTransport } from '@/api/mock';
import { FINDINGS_SHA256, HERO_FINDINGS_RESULT, HERO_SCAN } from '@/api/mock/fixtures/hero-scan';
import {
  SAMPLE_DOCX_BASE64,
  SAMPLE_DOCX_BYTES,
  SAMPLE_PDF_BASE64,
  SAMPLE_PDF_BYTES,
} from '@/api/mock/fixtures/report-files';
import { setScenario } from '@/api/mock/scenario';
import type { FindingsResult, Report, ReportFormat, Scan } from '@/domain';
import {
  BLOCK_COPY,
  EXTENSIONS,
  MIME_TYPES,
  REPORT_TIMEOUT_MS,
  SHAREABLE_FORMATS,
  blocksReport,
  canIssueReport,
  fileFor,
  fileNameFor,
  formatBytes,
  hasTimedOut,
  isEmptyFile,
  isFailed,
  isPending,
  isReady,
  missingFormats,
  orderedFiles,
  pollIntervalFor,
  sanitiseSegment,
} from '@/features/reports';

/**
 * `Buffer`, declared here rather than project-wide.
 *
 * `tsconfig.json` deliberately leaves `node` out of `types`, so the compiler catches a `process` or
 * an `fs` that wanders into `src/`. Tests genuinely run on Node, so the one global this file needs is
 * declared locally instead of weakening that guard for the whole app.
 */
declare const Buffer: {
  from(
    value: string,
    encoding: 'base64'
  ): {
    length: number;
    toString(encoding: 'latin1'): string;
    subarray(start?: number, end?: number): { toString(encoding: 'latin1'): string };
  };
};

/** A findings result with no unconfirmed fields — the only kind that may become a report. */
const CLEAN: FindingsResult = {
  ...HERO_FINDINGS_RESULT,
  extractions: HERO_FINDINGS_RESULT.extractions.map((extraction) => ({
    ...extraction,
    confidence: 0.95,
  })),
};

function reportWith(partial: Partial<Report>): Report {
  return {
    id: 'rpt_1',
    scanId: HERO_SCAN.id,
    rulepackVersion: 'LM-2011-v1.0',
    status: 'pending',
    formats: ['pdf', 'docx'],
    files: [],
    imageSha256: null,
    findingsSha256: FINDINGS_SHA256,
    requestedAt: '2026-09-12T10:00:00Z',
    generatedAt: null,
    error: null,
    ...partial,
  };
}

/* -------------------------------------------------------------------------- */
/*  The gate                                                                   */
/* -------------------------------------------------------------------------- */

describe('blocksReport', () => {
  it('allows a complete scan whose fields are all confirmed', () => {
    expect(blocksReport(HERO_SCAN, CLEAN)).toBeNull();
    expect(canIssueReport(HERO_SCAN, CLEAN)).toBe(true);
  });

  it('blocks while any field is unconfirmed', () => {
    // The whole point of the stage. A findings *screen* may show provisional verdicts behind a
    // banner; a PDF cannot be retracted from an inbox, so it waits for the answer.
    const provisional: FindingsResult = {
      ...CLEAN,
      extractions: CLEAN.extractions.map((extraction, index) =>
        index === 0 ? { ...extraction, confidence: 0.41, source: 'llm' as const } : extraction
      ),
    };

    expect(blocksReport(HERO_SCAN, provisional)).toBe('provisional_verdicts');
    expect(canIssueReport(HERO_SCAN, provisional)).toBe(false);
  });

  it('does not block a field a human already confirmed, however low the machine was', () => {
    const confirmed: FindingsResult = {
      ...CLEAN,
      extractions: CLEAN.extractions.map((extraction, index) =>
        index === 0 ? { ...extraction, confidence: 0.2, source: 'human' as const } : extraction
      ),
    };

    expect(blocksReport(HERO_SCAN, confirmed)).toBeNull();
  });

  it('blocks a scan that has not finished', () => {
    for (const status of ['captured', 'queued', 'uploading', 'processing', 'failed'] as const) {
      expect(blocksReport({ status }, CLEAN)).toBe('scan_incomplete');
    }
  });

  it('blocks a result with no findings at all', () => {
    expect(blocksReport(HERO_SCAN, { ...CLEAN, findings: [] })).toBe('no_findings');
  });

  it('reports the earliest problem, not the last check to fail', () => {
    // An unfinished scan with provisional verdicts is an unfinished scan: telling the user to confirm
    // a field on a scan that is still uploading would send them somewhere with nothing to do.
    const provisional: FindingsResult = {
      ...CLEAN,
      extractions: CLEAN.extractions.map((extraction) => ({ ...extraction, confidence: 0.3 })),
      findings: [],
    };

    expect(blocksReport({ status: 'processing' }, provisional)).toBe('scan_incomplete');
  });

  it('does NOT block a degraded-but-final run', () => {
    // Architecture §11: no marker and reduced extraction produce complete, correctly labelled results
    // and the report is issued *flagged*. Withholding it would leave an inspector with no record of
    // an inspection they actually made.
    const noMarker: Scan = { ...HERO_SCAN, issues: ['no_marker'] };
    const reduced: Scan = { ...HERO_SCAN, issues: ['reduced_extraction'] };

    expect(blocksReport(noMarker, CLEAN)).toBeNull();
    expect(blocksReport(reduced, CLEAN)).toBeNull();
  });

  it('offers the confirmation sheet as the fix, and only for the block that has one', () => {
    expect(BLOCK_COPY.provisional_verdicts.fix).toBe('confirm');
    expect(BLOCK_COPY.scan_incomplete.fix).toBe('none');
    expect(BLOCK_COPY.no_findings.fix).toBe('none');
  });
});

/* -------------------------------------------------------------------------- */
/*  Filenames                                                                  */
/* -------------------------------------------------------------------------- */

describe('fileNameFor', () => {
  const scanOf = (name: string, id = 'scn_local_12', capturedAt = '2026-09-11T09:42:18Z') => ({
    id,
    capturedAt,
    profile: { ...HERO_SCAN.profile, name },
  });

  it('names the product, the capture date and enough id to break a tie', () => {
    expect(fileNameFor(scanOf('Sampoorna Whole Wheat Atta'), 'pdf')).toBe(
      'anupalan-sampoorna-whole-wheat-atta-2026-09-11-cal-12.pdf'
    );
  });

  it('distinguishes two scans of the same pack on the same day', () => {
    const a = fileNameFor(scanOf('Atta', 'scn_aaaaaa'), 'pdf');
    const b = fileNameFor(scanOf('Atta', 'scn_bbbbbb'), 'pdf');

    // A collision here overwrites a file in someone's downloads folder, silently, and the thing lost
    // is evidence.
    expect(a).not.toBe(b);
  });

  it('strips everything a filesystem or a share target could choke on', () => {
    const name = fileNameFor(scanOf('Ghee 500g / "Pure" \\ 100%'), 'docx');

    expect(name).toMatch(/^[a-z0-9.-]+$/);
    expect(name.endsWith('.docx')).toBe(true);
  });

  it('falls back rather than producing an empty name for a Devanagari product', () => {
    // Transliterating would give a name neither readable to a Hindi speaker nor accurate to anyone
    // else, so the product part is simply dropped.
    const name = fileNameFor(scanOf('सम्पूर्ण गेहूँ आटा'), 'pdf');

    expect(name).toBe('anupalan-scan-2026-09-11-cal-12.pdf');
    expect(name).toMatch(/^[a-z0-9.-]+$/);
  });

  it('truncates a very long product name instead of rejecting it', () => {
    const name = fileNameFor(scanOf('a'.repeat(400)), 'pdf');

    expect(name.length).toBeLessThan(80);
    expect(name.startsWith('anupalan-aaa')).toBe(true);
  });

  it('omits the date rather than printing NaN when the timestamp is unusable', () => {
    expect(fileNameFor(scanOf('Atta', 'scn_x1', 'not a date'), 'pdf')).toBe(
      'anupalan-atta-scn-x1.pdf'
    );
  });

  it('uses the right extension for each format', () => {
    for (const format of ['pdf', 'docx', 'json'] as ReportFormat[]) {
      expect(fileNameFor(scanOf('Atta'), format).endsWith(`.${EXTENSIONS[format]}`)).toBe(true);
    }
  });
});

describe('sanitiseSegment', () => {
  it('collapses runs and trims the edges', () => {
    expect(sanitiseSegment('  Hello   World!!  ')).toBe('hello-world');
    expect(sanitiseSegment('---x---')).toBe('x');
  });

  it('returns an empty string for input with nothing usable', () => {
    expect(sanitiseSegment('!!!')).toBe('');
    expect(sanitiseSegment('')).toBe('');
    expect(sanitiseSegment('日本語')).toBe('');
  });

  it('never leaves a trailing hyphen after truncation', () => {
    expect(sanitiseSegment(`${'a'.repeat(39)} bcd`)).not.toMatch(/-$/);
  });
});

describe('formatBytes', () => {
  it('reads as a person would say it', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(31_397)).toBe('31 KB');
    expect(formatBytes(2_500_000)).toBe('2.4 MB');
  });

  it('does not print NaN for a missing size', () => {
    expect(formatBytes(Number.NaN)).toBe('—');
    expect(formatBytes(-1)).toBe('—');
  });
});

/* -------------------------------------------------------------------------- */
/*  Polling                                                                    */
/* -------------------------------------------------------------------------- */

describe('report status', () => {
  it('classifies the three states', () => {
    expect(isPending(reportWith({ status: 'pending' }))).toBe(true);
    expect(isReady(reportWith({ status: 'ready' }))).toBe(true);
    expect(isFailed(reportWith({ status: 'failed' }))).toBe(true);
  });

  it('polls while pending and stops the moment it is not', () => {
    expect(pollIntervalFor(reportWith({ status: 'pending' }))).toBeGreaterThan(0);
    // False, not a long interval: a finished report never changes again, and a query that keeps
    // waking has to be explained to whoever debugs the battery later.
    expect(pollIntervalFor(reportWith({ status: 'ready' }))).toBe(false);
    expect(pollIntervalFor(reportWith({ status: 'failed' }))).toBe(false);
  });

  it('polls before the first response has arrived', () => {
    expect(pollIntervalFor(undefined)).toBeGreaterThan(0);
  });
});

describe('hasTimedOut', () => {
  const requestedAt = '2026-09-12T10:00:00Z';
  const requested = Date.parse(requestedAt);

  it('is false while the wait is still reasonable', () => {
    expect(hasTimedOut(reportWith({ requestedAt }), requested + 10_000)).toBe(false);
  });

  it('is true once the worker has had far longer than it should need', () => {
    expect(hasTimedOut(reportWith({ requestedAt }), requested + REPORT_TIMEOUT_MS + 1)).toBe(true);
  });

  it('never fires on a report that already finished', () => {
    const late = requested + REPORT_TIMEOUT_MS * 10;

    expect(hasTimedOut(reportWith({ requestedAt, status: 'ready' }), late)).toBe(false);
    expect(hasTimedOut(reportWith({ requestedAt, status: 'failed' }), late)).toBe(false);
  });

  it('treats an unparseable timestamp as no evidence, rather than as a timeout', () => {
    // Showing an error over a report that is generating perfectly well is worse than showing none.
    expect(hasTimedOut(reportWith({ requestedAt: 'nonsense' }), Date.now())).toBe(false);
  });
});

describe('delivery', () => {
  const ready = reportWith({
    status: 'ready',
    formats: ['pdf', 'docx'],
    files: [{ format: 'pdf', uri: 'https://x/a.pdf', sizeBytes: 100 }],
  });

  it('names a format that was asked for and did not arrive', () => {
    // Without this the screen shows one share button and looks entirely correct.
    expect(missingFormats(ready)).toEqual(['docx']);
  });

  it('claims nothing is missing while the report is still pending', () => {
    expect(missingFormats(reportWith({ status: 'pending' }))).toEqual([]);
  });

  it('finds nothing missing on a complete delivery', () => {
    expect(
      missingFormats({
        ...ready,
        files: [
          { format: 'pdf', uri: 'https://x/a.pdf', sizeBytes: 1 },
          { format: 'docx', uri: 'https://x/a.docx', sizeBytes: 1 },
        ],
      })
    ).toEqual([]);
  });

  it('lists files in the order they were requested, not the order they arrived', () => {
    const scrambled = reportWith({
      status: 'ready',
      formats: ['pdf', 'docx'],
      files: [
        { format: 'docx', uri: 'https://x/a.docx', sizeBytes: 1 },
        { format: 'pdf', uri: 'https://x/a.pdf', sizeBytes: 1 },
      ],
    });

    expect(orderedFiles(scrambled).map((file) => file.format)).toEqual(['pdf', 'docx']);
  });

  it('finds one file by format', () => {
    expect(fileFor(ready, 'pdf')?.uri).toBe('https://x/a.pdf');
    expect(fileFor(ready, 'docx')).toBeNull();
  });

  it('refuses to treat a zero-byte file as shareable', () => {
    // A zero-byte PDF opens as a corrupt document in someone else's hands, which is worse than
    // refusing to send it.
    expect(isEmptyFile({ sizeBytes: 0 })).toBe(true);
    expect(isEmptyFile({ sizeBytes: Number.NaN })).toBe(true);
    expect(isEmptyFile({ sizeBytes: 1 })).toBe(false);
  });
});

/* -------------------------------------------------------------------------- */
/*  Formats offered                                                            */
/* -------------------------------------------------------------------------- */

describe('formats', () => {
  it('offers PDF and DOCX for sharing, and not JSON', () => {
    // JSON is a real report format (FR-27) whose home is the API. In a phone's share sheet it invites
    // sending a machine artefact to a trader who cannot read it.
    expect([...SHAREABLE_FORMATS]).toEqual(['pdf', 'docx']);
  });

  it('carries the MIME type each share target needs', () => {
    expect(MIME_TYPES.pdf).toBe('application/pdf');
    // Without this Android offers a generic chooser and a DOCX opens in a text editor as ZIP noise.
    expect(MIME_TYPES.docx).toContain('wordprocessingml.document');
  });
});

/* -------------------------------------------------------------------------- */
/*  Against the mock transport                                                 */
/* -------------------------------------------------------------------------- */

describe('report generation, end to end', () => {
  afterEach(() => setScenario('happy'));

  async function request(formats: ReportFormat[] = ['pdf', 'docx']): Promise<Report> {
    const transport = createMockTransport();
    return transport.request<Report>({
      method: 'POST',
      path: `/scans/${HERO_SCAN.id}/report`,
      body: { formats },
    });
  }

  it('comes back pending, with no files and the hashes already known', async () => {
    const report = await request();

    // Pending rather than ready: rendering an annotated PDF is S10 of the pipeline, and a POST that
    // blocked on it would tie a button to a render that can take seconds and can fail.
    expect(report.status).toBe('pending');
    expect(report.files).toEqual([]);
    expect(report.generatedAt).toBeNull();
    expect(report.findingsSha256).toBe(FINDINGS_SHA256);
  });

  it('quotes the same findings hash the evidence panel shows', async () => {
    const report = await request();

    // Two different values here would make the report and the app disagree about the one thing the
    // whole integrity claim rests on.
    expect(report.findingsSha256).toBe(HERO_FINDINGS_RESULT.findingsSha256);
  });

  it('reports the raw image hash, never the rectified one', async () => {
    const report = await request();

    const raw = HERO_SCAN.assets.find((asset) => asset.kind === 'raw');
    const rectified = HERO_SCAN.assets.find((asset) => asset.kind === 'rectified');

    expect(report.imageSha256).toBe(raw?.sha256);
    expect(report.imageSha256).not.toBe(rectified?.sha256);
  });

  it('becomes ready with one file per requested format', async () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-09-12T10:00:00Z'));
    try {
      const created = await request();

      jest.setSystemTime(new Date('2026-09-12T10:00:10Z'));
      const transport = createMockTransport();
      const ready = await transport.request<Report>({
        method: 'GET',
        path: `/reports/${created.id}`,
      });

      expect(ready.status).toBe('ready');
      expect(ready.files.map((file) => file.format)).toEqual(['pdf', 'docx']);
      expect(ready.generatedAt).not.toBeNull();
      expect(missingFormats(ready)).toEqual([]);
    } finally {
      jest.useRealTimers();
    }
  });

  it('honours a single-format request', async () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-09-12T11:00:00Z'));
    try {
      const created = await request(['pdf']);
      jest.setSystemTime(new Date('2026-09-12T11:00:10Z'));

      const ready = await createMockTransport().request<Report>({
        method: 'GET',
        path: `/reports/${created.id}`,
      });

      expect(ready.files.map((file) => file.format)).toEqual(['pdf']);
    } finally {
      jest.useRealTimers();
    }
  });

  it('surfaces a generation failure as a failed report, not as a hang', async () => {
    setScenario('report-failed');
    const created = await request();

    const failed = await createMockTransport().request<Report>({
      method: 'GET',
      path: `/reports/${created.id}`,
    });

    expect(failed.status).toBe('failed');
    expect(failed.error).toBeTruthy();
    expect(failed.files).toEqual([]);
    expect(pollIntervalFor(failed)).toBe(false);
  });

  it('404s on a report id that was never requested', async () => {
    await expect(
      createMockTransport().request<Report>({ method: 'GET', path: '/reports/rpt_nope' })
    ).rejects.toMatchObject({ status: 404 });
  });

  it('refuses a format it has no sample for, rather than writing an empty file', async () => {
    await expect(
      createMockTransport().download({
        url: 'fixture://report/scn_x.json',
        headers: {},
        fileUri: 'file:///tmp/x.json',
      })
    ).rejects.toMatchObject({ code: 'download_failed' });
  });

  it('fails the download when the scenario says the network is gone', async () => {
    setScenario('offline');

    await expect(
      createMockTransport().download({
        url: 'fixture://report/scn_x.pdf',
        headers: {},
        fileUri: 'file:///tmp/x.pdf',
      })
    ).rejects.toMatchObject({ code: 'network_unavailable' });
  });
});

/* -------------------------------------------------------------------------- */
/*  The sample files are real                                                  */
/* -------------------------------------------------------------------------- */

describe('the sample report files', () => {
  const decode = (base64: string) => Buffer.from(base64.replace(/\s+/g, ''), 'base64');

  it('the PDF really is a PDF', () => {
    const bytes = decode(SAMPLE_PDF_BASE64);

    // FR-08's acceptance is that the files open in an external viewer. A mock resolving with a
    // plausible URI would pass in testing and fail in front of a judge.
    expect(bytes.length).toBe(SAMPLE_PDF_BYTES);
    expect(bytes.subarray(0, 5).toString('latin1')).toBe('%PDF-');
    expect(bytes.subarray(-6).toString('latin1')).toContain('%%EOF');
  });

  it('the PDF carries both hashes and the rule pack version', () => {
    const text = decode(SAMPLE_PDF_BASE64).toString('latin1');

    // Read out of the fixtures by the generator, so a sample report cannot quote a different findings
    // hash from the one the evidence panel shows.
    expect(text).toContain(FINDINGS_SHA256.slice(0, 32));
    expect(text).toContain(HERO_FINDINGS_RESULT.rulepackVersion);
  });

  it('the PDF embeds the annotated image', () => {
    const text = decode(SAMPLE_PDF_BASE64).toString('latin1');

    expect(text).toContain('/DCTDecode');
    expect(text).toContain('/Subtype /Image');
  });

  it('the DOCX really is an OOXML package', () => {
    const bytes = decode(SAMPLE_DOCX_BASE64);

    expect(bytes.length).toBe(SAMPLE_DOCX_BYTES);
    // `PK\x03\x04` — a real ZIP, not a renamed text file.
    expect(bytes.subarray(0, 4).toString('latin1')).toBe('PK');
    expect(bytes.toString('latin1')).toContain('word/document.xml');
  });

  it('both sizes match what the mock advertises', async () => {
    jest.useFakeTimers().setSystemTime(new Date('2026-09-12T12:00:00Z'));
    try {
      const created = await createMockTransport().request<Report>({
        method: 'POST',
        path: `/scans/${HERO_SCAN.id}/report`,
        body: { formats: ['pdf', 'docx'] },
      });

      jest.setSystemTime(new Date('2026-09-12T12:00:10Z'));
      const ready = await createMockTransport().request<Report>({
        method: 'GET',
        path: `/reports/${created.id}`,
      });

      // A size that disagrees with the bytes would show the user one number and share another, and
      // `isEmptyFile` would stop trusting the only signal it has.
      expect(fileFor(ready, 'pdf')?.sizeBytes).toBe(SAMPLE_PDF_BYTES);
      expect(fileFor(ready, 'docx')?.sizeBytes).toBe(SAMPLE_DOCX_BYTES);
      expect(orderedFiles(ready).every((file) => !isEmptyFile(file))).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });
});
