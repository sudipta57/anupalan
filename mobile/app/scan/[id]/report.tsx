/**
 * Report export and share — FR-08.
 *
 * *Accept: both files share out of the app and open in an external viewer.*
 *
 * The screen has four states and they are deliberately not interchangeable: **blocked**, **ready to
 * generate**, **generating**, and **generated**. The first is the one that matters.
 *
 * A PDF is not a screen. It leaves the device, it embeds a findings hash, it quotes gazette citations
 * beside a millimetre, and it cannot be retracted from an inbox. So while any field is unconfirmed,
 * this screen does not offer a disabled button with a caption — it refuses, explains why in the
 * rules engine's own terms, and points at the one action that fixes it. The findings screen may carry
 * a provisional banner and still show verdicts; a document may not.
 *
 * What it does *not* refuse is a degraded run. No marker, or an unavailable LLM, produce a complete
 * and correctly labelled result — `01-architecture.md` §11 says such a report is issued **flagged**,
 * not withheld. Withholding it would leave an inspector with no record of an inspection they made.
 * So those appear as banners above the preview, and the report goes out carrying them.
 *
 * Everything the user is about to distribute is shown before they distribute it: both hashes, the
 * rule pack version, all four verdict counts including the zeroes, and the advisory disclaimer.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError, useCreateReport, useFindings, useReport, useScan } from '@/api';
import {
  AdvisoryDisclaimer,
  Banner,
  Button,
  Card,
  Chip,
  Screen,
  Skeleton,
  Text,
  VerdictBadge,
} from '@/components';
import type { FindingsResult, Report, ReportFile, ReportFormat, Scan } from '@/domain';
import { evidenceFor, hashGroups, showsEvidence } from '@/features/findings';
import { ISSUE_COPY, issuesToReport } from '@/features/processing';
import {
  BLOCK_COPY,
  FORMAT_HINT_KEYS,
  FORMAT_LABEL_KEYS,
  SHAREABLE_FORMATS,
  blocksReport,
  fileNameFor,
  formatBytes,
  hasTimedOut,
  isEmptyFile,
  materialiseReport,
  missingFormats,
  orderedFiles,
  shareReport,
} from '@/features/reports';
import { useT } from '@/i18n';
import { useOrgMode } from '@/store/session';
import { radius, spacing, useTheme } from '@/theme';

/* -------------------------------------------------------------------------- */
/*  Blocked                                                                    */
/* -------------------------------------------------------------------------- */

function Blocked({ scanId, block }: { scanId: string; block: keyof typeof BLOCK_COPY }) {
  const t = useT();
  const copy = BLOCK_COPY[block];

  return (
    <Screen scroll>
      <Card>
        <Text variant="display">{t('report.title')}</Text>
        <Banner tone="warning" title={t(copy.titleKey)} body={t(copy.bodyKey)} />

        {copy.fix === 'confirm' ? (
          <Button
            label={t('report.openConfirm')}
            size="lg"
            onPress={() => router.push(`/scan/${scanId}/confirm`)}
          />
        ) : null}

        <Button label={t('common.back')} variant="ghost" onPress={() => router.back()} />
      </Card>

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

/* -------------------------------------------------------------------------- */
/*  What the report will carry                                                 */
/* -------------------------------------------------------------------------- */

function Preview({ scan, result }: { scan: Scan; result: FindingsResult }) {
  const t = useT();
  const mode = useOrgMode();

  const evidence = evidenceFor(scan, result);

  const counts = [
    { verdict: 'FAIL' as const, count: result.summary.fail },
    { verdict: 'BORDERLINE' as const, count: result.summary.borderline },
    { verdict: 'NOT_ASSESSABLE' as const, count: result.summary.notAssessable },
    { verdict: 'PASS' as const, count: result.summary.pass },
  ];

  return (
    <Card>
      <Text variant="heading">{t('report.integrity')}</Text>

      <Text variant="label" tone="muted">
        {t('report.verdictCounts')}
      </Text>
      <View style={styles.counts}>
        {/* All four, including the zeroes: a report with five Not assessable rules is a different
            document from one with none, and the person sending it should know which they have. */}
        {counts.map((row) => (
          <View key={row.verdict} style={styles.countRow}>
            <VerdictBadge verdict={row.verdict} />
            <Text variant="bodyStrong">{row.count}</Text>
          </View>
        ))}
      </View>

      <Text variant="label" tone="muted">
        {t('evidence.findingsHash')}
      </Text>
      <Text variant="mono">{hashGroups(evidence.findingsSha256)}</Text>

      <Text variant="label" tone="muted">
        {t('evidence.imageHash')}
      </Text>
      <Text variant="mono" tone={evidence.imageSha256 ? 'default' : 'subtle'}>
        {evidence.imageSha256 ? hashGroups(evidence.imageSha256) : t('evidence.imageHashMissing')}
      </Text>

      <Text variant="mono" tone="subtle">
        {t('disclaimer.rulepack', { version: result.rulepackVersion })}
      </Text>

      {/* Enforcement only: issuing is what closes the record, and the person about to issue should
          learn that before they tap, not from a disabled button afterwards. */}
      {showsEvidence(mode) && evidence.reportIssuedAt === null ? (
        <Banner tone="info" title={t('report.issuedNotice')} body={t('report.issuedNoticeBody')} />
      ) : null}
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/*  One generated file                                                         */
/* -------------------------------------------------------------------------- */

function FileRow({
  file,
  scan,
  onError,
}: {
  file: ReportFile;
  scan: Scan;
  onError: (message: string) => void;
}) {
  const t = useT();
  const { colors } = useTheme();

  const [busy, setBusy] = useState(false);

  const name = fileNameFor(scan, file.format);
  const empty = isEmptyFile(file);

  const share = useCallback(async () => {
    setBusy(true);
    try {
      // Downloaded first: a share intent over an https URL produces something most target apps
      // cannot open, and the user sees a share that silently does nothing.
      const localUri = await materialiseReport(file, name);
      await shareReport(localUri, file.format, t('report.share', { format: name }));
    } catch (cause) {
      onError(cause instanceof ApiError ? cause.message : t('report.shareFailed'));
    } finally {
      setBusy(false);
    }
  }, [file, name, onError, t]);

  return (
    <View style={[styles.file, { borderColor: colors.border }]}>
      <View style={styles.fileHead}>
        <Chip label={t(FORMAT_LABEL_KEYS[file.format])} tone="brand" selected />
        <Text variant="caption" tone="muted">
          {formatBytes(file.sizeBytes)}
        </Text>
      </View>

      <Text variant="mono" tone="subtle">
        {name}
      </Text>

      {empty ? (
        <Banner tone="error" title={t('report.emptyFile')} />
      ) : (
        <Button
          label={t('report.share', { format: t(FORMAT_LABEL_KEYS[file.format]) })}
          loading={busy}
          disabled={busy}
          onPress={() => void share()}
        />
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Generated                                                                  */
/* -------------------------------------------------------------------------- */

function Generated({
  report,
  scan,
  onRegenerate,
}: {
  report: Report;
  scan: Scan;
  onRegenerate: () => void;
}) {
  const t = useT();
  const [error, setError] = useState<string | null>(null);

  const files = orderedFiles(report);
  const missing = missingFormats(report);

  return (
    <>
      <Card>
        <Text variant="heading">{t('report.readyTitle')}</Text>
        <Text variant="body" tone="muted">
          {t('report.readyBody', { at: report.generatedAt ?? '' })}
        </Text>
        <Text variant="caption" tone="subtle">
          {t('report.downloadHint')}
        </Text>
      </Card>

      {error ? <Banner tone="error" title={error} /> : null}

      {/* A ready report that produced only one of two requested documents would otherwise look
          correct — one share button, no sign that anything is missing. */}
      {missing.length > 0 ? (
        <Banner
          tone="warning"
          title={t('report.missingFormats', {
            formats: missing.map((format) => t(FORMAT_LABEL_KEYS[format])).join(', '),
          })}
        />
      ) : null}

      <Card>
        {files.map((file) => (
          <FileRow key={file.format} file={file} scan={scan} onError={setError} />
        ))}
      </Card>

      <Button label={t('report.regenerate')} variant="secondary" onPress={onRegenerate} />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  The screen                                                                 */
/* -------------------------------------------------------------------------- */

function Loaded({ scan, result }: { scan: Scan; result: FindingsResult }) {
  const t = useT();

  const [formats, setFormats] = useState<ReportFormat[]>([...SHAREABLE_FORMATS]);
  const [reportId, setReportId] = useState<string | null>(null);

  const createReport = useCreateReport(scan.id);
  const report = useReport(reportId ?? undefined, scan.id);

  const issues = issuesToReport(scan.issues);

  const generate = useCallback(() => {
    createReport.mutate({ formats }, { onSuccess: (created) => setReportId(created.id) });
  }, [createReport, formats]);

  const toggle = useCallback((format: ReportFormat) => {
    setFormats((current) =>
      current.includes(format)
        ? current.filter((value) => value !== format)
        : [...SHAREABLE_FORMATS].filter((value) => value === format || current.includes(value))
    );
  }, []);

  const data = report.data;

  // The clock is the poll's own timestamp, not `Date.now()`. It advances once per poll, which is the
  // only cadence on which this can change, and it keeps the render pure — a `Date.now()` here would
  // give a different answer on every incidental re-render.
  const timedOut = data ? hasTimedOut(data, report.dataUpdatedAt) : false;

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="display">{t('report.title')}</Text>
        <Text variant="body" tone="muted">
          {t('report.intro')}
        </Text>
      </View>

      {/* Degraded but final: §11 issues these flagged rather than withholding them, so they warn
          here and travel with the document rather than blocking it. */}
      {issues.map((issue) => (
        <Banner
          key={issue}
          tone={ISSUE_COPY[issue].tone}
          title={t(ISSUE_COPY[issue].titleKey)}
          body={t(ISSUE_COPY[issue].bodyKey)}
        />
      ))}

      <Preview scan={scan} result={result} />

      {data?.status === 'ready' ? (
        <Generated
          report={data}
          scan={scan}
          onRegenerate={() => {
            setReportId(null);
            createReport.reset();
          }}
        />
      ) : data?.status === 'failed' ? (
        <Card>
          <Banner
            tone="error"
            title={data.error ?? t('report.failedTitle')}
            body={t('report.failedBody')}
          />
          <Button
            label={t('report.regenerate')}
            onPress={() => {
              setReportId(null);
              createReport.reset();
            }}
          />
        </Card>
      ) : reportId ? (
        <Card>
          <Text variant="heading">{t('report.generating')}</Text>
          <Text variant="body" tone="muted">
            {t('report.generatingBody')}
          </Text>
          <Skeleton height={44} />

          {/* A spinner with no end is where someone decides the app is broken and asks again,
              which renders the same document twice. */}
          {timedOut ? (
            <Banner
              tone="warning"
              title={t('report.timedOutTitle')}
              body={t('report.timedOutBody')}
            />
          ) : null}
        </Card>
      ) : (
        <Card>
          <Text variant="heading">{t('report.chooseFormats')}</Text>
          <Text variant="caption" tone="muted">
            {t('report.chooseFormatsBody')}
          </Text>

          <View style={styles.formats}>
            {SHAREABLE_FORMATS.map((format) => (
              <Chip
                key={format}
                label={t(FORMAT_LABEL_KEYS[format])}
                tone={formats.includes(format) ? 'brand' : 'neutral'}
                selected={formats.includes(format)}
                onPress={() => toggle(format)}
              />
            ))}
          </View>

          {formats.map((format) => (
            <Text key={format} variant="caption" tone="subtle">
              {t(FORMAT_HINT_KEYS[format])}
            </Text>
          ))}

          {createReport.isError ? (
            <Banner
              tone="error"
              title={
                createReport.error instanceof ApiError
                  ? createReport.error.message
                  : t('report.failedTitle')
              }
            />
          ) : null}

          <Button
            label={t('report.generate')}
            size="lg"
            disabled={formats.length === 0 || createReport.isPending}
            loading={createReport.isPending}
            onPress={generate}
          />
        </Card>
      )}

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

export default function ReportScreen() {
  const t = useT();
  const { id } = useLocalSearchParams<{ id: string }>();

  const scan = useScan(id);
  const findings = useFindings(scan.data?.status === 'complete' ? id : undefined);

  if (scan.isPending) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={28} />
          <Skeleton height={140} />
        </Card>
      </Screen>
    );
  }

  if (!scan.data) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('processing.notFound')}</Text>
          <Text variant="body" tone="muted">
            {t('processing.notFoundBody')}
          </Text>
          <Button label={t('errors.goHome')} onPress={() => router.dismissTo('/(tabs)')} />
        </Card>
      </Screen>
    );
  }

  if (scan.data.status !== 'complete') {
    return <Blocked scanId={id} block="scan_incomplete" />;
  }

  if (!findings.data) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={28} />
          <Skeleton height={140} />
        </Card>
      </Screen>
    );
  }

  const block = blocksReport(scan.data, findings.data);
  if (block) return <Blocked scanId={id} block={block} />;

  return <Loaded scan={scan.data} result={findings.data} />;
}

const styles = StyleSheet.create({
  countRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.md,
    justifyContent: 'space-between',
  },
  counts: { gap: spacing.sm },
  file: {
    borderRadius: radius.md,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  fileHead: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  formats: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  intro: { gap: spacing.xs },
});
