/**
 * Bulk listing check — Mode B only (FR-10).
 *
 * *Accept: a 50-row CSV produces 50 result rows with a summary count, and no metric rule ever
 * returns PASS or FAIL from listing text alone.*
 *
 * Three things this screen refuses to do, and each is the same failure in a different place: a number
 * a reader will trust without checking.
 *
 * - **It will not check a truncated list.** Over fifty rows blocks submission and names the count.
 *   Fifty-one pasted, fifty checked, a table of fifty — and a seller who believes their catalogue was
 *   cleared, having never seen the row that was dropped.
 * - **It will not render a measured verdict on a listing.** `sanitise` forces any metric PASS, FAIL
 *   or BORDERLINE back to `NOT_ASSESSABLE`, and the banner says it did. A quiet correction would
 *   leave the server emitting a forbidden verdict with nobody the wiser.
 * - **It will not call a clean row compliant.** A listing check covers presence and format; every
 *   millimetre in Rule 9 is untested, by construction. "Nothing against them" is the strongest claim
 *   available, and the panel above the table says why.
 *
 * Picking a CSV *file* is not wired: `expo-document-picker` is not an approved dependency
 * (CLAUDE.md §7, and flag 32). Pasting the file's contents is the same input and the more likely
 * phone workflow anyway — the CSV is already in a spreadsheet app on the same device.
 */

import { useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { useCheckListings } from '@/api';
import { AdvisoryDisclaimer, Banner, Button, Card, Chip, Field, Screen, Text } from '@/components';
import type { ListingCheck } from '@/domain';
import {
  MAX_ROWS,
  blocksSubmit,
  canSubmit,
  cleanRows,
  erroredRows,
  orderedRows,
  parseListings,
  rowsWith,
  sanitise,
  shareCsv,
  violations,
  writeCsv,
} from '@/features/bulk';
// The file, not the barrel — the same narrowing the history and sahayak screens use.
import { ListingRowCard } from '@/features/bulk/row-card';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

/**
 * Idempotency keys for a check.
 *
 * A module counter rather than a random id, for the reason `POST /scans` needs one: a retry after a
 * dropped response must be recognised as the same request, and fifty listings re-run through the
 * rules engine is a bill as well as a wrong second result.
 */
let checkCounter = 0;

function Summary({ check }: { check: ListingCheck }) {
  const t = useT();

  const findingCount = check.rows.reduce((total, row) => total + row.findings.length, 0);

  return (
    <Card>
      <Text variant="heading">{t('bulk.resultsTitle')}</Text>
      <Text variant="body" tone="muted">
        {t('bulk.resultsSummary', { rows: check.rows.length, findings: findingCount })}
      </Text>

      {/* Listings-with-a-problem and total-problems are different questions, so both are given.
          Reporting only the finding counts makes eight defects on one listing look like eight bad
          listings. */}
      <View style={styles.chips}>
        <Chip label={t('bulk.listingsWithFail', { count: rowsWith(check, 'fail') })} tone="fail" />
        <Chip
          label={t('bulk.listingsWithBorderline', { count: rowsWith(check, 'borderline') })}
          tone="borderline"
        />
        <Chip label={t('bulk.listingsClean', { count: cleanRows(check).length })} tone="pass" />
        {erroredRows(check).length > 0 ? (
          <Chip
            label={t('bulk.listingsErrored', { count: erroredRows(check).length })}
            tone="notAssessable"
          />
        ) : null}
      </View>

      <Text variant="label" tone="muted">
        {t('bulk.findingCounts')}
      </Text>
      <View style={styles.chips}>
        <Chip label={`${check.summary.fail}`} tone="fail" />
        <Chip label={`${check.summary.borderline}`} tone="borderline" />
        <Chip label={`${check.summary.notAssessable}`} tone="notAssessable" />
        <Chip label={`${check.summary.pass}`} tone="pass" />
      </View>

      <Text variant="mono" tone="subtle">
        {t('disclaimer.rulepack', { version: check.rulepackVersion })}
      </Text>
    </Card>
  );
}

export default function BulkScreen() {
  const t = useT();

  const [input, setInput] = useState('');
  const [raw, setRaw] = useState<ListingCheck | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);

  const mutation = useCheckListings();

  const parsed = useMemo(() => parseListings(input), [input]);
  const block = blocksSubmit(parsed);

  /**
   * The result as it may be shown.
   *
   * `sanitise` returns its input unchanged when there is nothing to correct, so the common case costs
   * nothing. The violations are computed from `raw`, not from this — asking the sanitised copy what
   * was wrong with it would always answer "nothing".
   */
  const check = useMemo(() => (raw ? sanitise(raw) : null), [raw]);
  const rejected = useMemo(() => (raw ? violations(raw) : []), [raw]);

  const submit = () => {
    if (!canSubmit(parsed, mutation.isPending)) return;

    checkCounter += 1;
    setExportError(false);

    mutation.mutate(
      {
        body: { rows: parsed.rows },
        idempotencyKey: `listing-check-${checkCounter}`,
      },
      { onSuccess: (result) => setRaw(result) }
    );
  };

  const exportCsv = () => {
    if (!check) return;

    setExporting(true);
    setExportError(false);

    // Written then shared. The bytes have to be on disk before the sheet opens, for the reason
    // Stage 9's `share.ts` documents.
    void (async () => {
      try {
        const uri = writeCsv(check);
        await shareCsv(uri, t('bulk.exportDialog'));
      } catch {
        setExportError(true);
      } finally {
        setExporting(false);
      }
    })();
  };

  return (
    <Screen scroll>
      <Card>
        <Text variant="display">{t('bulk.title')}</Text>
        <Text variant="body" tone="muted">
          {t('bulk.subtitle')}
        </Text>
      </Card>

      {/* Said before the check runs, not after. A seller who reads "not assessable" forty times on a
          results table without having been told why concludes the checker is broken. */}
      <Card>
        <Banner tone="info" title={t('bulk.scaleTitle')} body={t('bulk.scaleBody')} />
      </Card>

      <Card>
        <Field
          label={t('bulk.inputLabel')}
          placeholder={t('bulk.inputPlaceholder')}
          hint={t('bulk.inputHint', { max: MAX_ROWS })}
          value={input}
          onChangeText={setInput}
          multiline
          numberOfLines={6}
          inputStyle={styles.input}
        />

        {input.trim().length > 0 ? (
          <View style={styles.chips}>
            <Chip
              label={
                parsed.rows.length === 1
                  ? t('bulk.parsedRows', { count: parsed.rows.length })
                  : t('bulk.parsedRowsPlural', { count: parsed.rows.length })
              }
              tone="brand"
            />
            {parsed.duplicates > 0 ? (
              <Chip
                label={
                  parsed.duplicates === 1
                    ? t('bulk.parsedDuplicates', { count: parsed.duplicates })
                    : t('bulk.parsedDuplicatesPlural', { count: parsed.duplicates })
                }
              />
            ) : null}
            {parsed.blank > 0 ? (
              <Chip
                label={
                  parsed.blank === 1
                    ? t('bulk.parsedBlank', { count: parsed.blank })
                    : t('bulk.parsedBlankPlural', { count: parsed.blank })
                }
              />
            ) : null}
            {parsed.tooLong > 0 ? (
              <Chip
                label={
                  parsed.tooLong === 1
                    ? t('bulk.parsedTooLong', { count: parsed.tooLong })
                    : t('bulk.parsedTooLongPlural', { count: parsed.tooLong })
                }
                tone="borderline"
              />
            ) : null}
          </View>
        ) : null}

        {/* Blocked, not truncated. The count is named so the user can see what to trim. */}
        {block === 'over_limit' ? (
          <Banner
            tone="error"
            title={t('bulk.blockOverLimit')}
            body={t('bulk.blockOverLimitBody', {
              over: parsed.overLimit,
              max: MAX_ROWS,
              total: parsed.rows.length + parsed.overLimit,
            })}
          />
        ) : null}

        <Button
          label={
            mutation.isPending
              ? t('bulk.checking')
              : parsed.rows.length === 1
                ? t('bulk.check', { count: parsed.rows.length })
                : t('bulk.checkPlural', { count: parsed.rows.length })
          }
          size="lg"
          loading={mutation.isPending}
          disabled={!canSubmit(parsed, mutation.isPending)}
          onPress={submit}
        />

        {input.length > 0 ? (
          <Button
            label={t('bulk.clear')}
            variant="ghost"
            onPress={() => {
              setInput('');
              setRaw(null);
              setExpanded(null);
            }}
          />
        ) : null}
      </Card>

      {mutation.isError ? (
        <Card>
          <Banner
            tone="error"
            title={t('bulk.checkFailed')}
            body={mutation.error.message}
            action={<Button label={t('common.retry')} variant="secondary" onPress={submit} />}
          />
        </Card>
      ) : null}

      {check ? (
        <>
          {/* A server fault, stated as one. The verdicts are already corrected below; this says that
              they were, because a silent fix teaches nobody that the backend broke a non-negotiable. */}
          {rejected.length > 0 ? (
            <Card>
              <Banner
                tone="error"
                title={t('bulk.guardTitle')}
                body={
                  rejected.length === 1
                    ? t('bulk.guardBody', { count: rejected.length })
                    : t('bulk.guardBodyPlural', { count: rejected.length })
                }
              />
            </Card>
          ) : null}

          <Summary check={check} />

          <Card>
            <Button
              label={exporting ? t('bulk.exporting') : t('bulk.export')}
              variant="secondary"
              loading={exporting}
              disabled={exporting}
              onPress={exportCsv}
            />
            {exportError ? <Banner tone="error" title={t('bulk.exportFailed')} /> : null}
          </Card>

          <View style={styles.rows}>
            {orderedRows(check).map((row) => (
              <ListingRowCard
                key={row.rowId}
                row={row}
                expanded={expanded === row.rowId}
                onToggle={() => setExpanded(expanded === row.rowId ? null : row.rowId)}
              />
            ))}
          </View>
        </>
      ) : null}

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  // Tall enough that a paste of a dozen listings is visible without scrolling inside the field.
  input: { minHeight: 120, textAlignVertical: 'top' },
  rows: { gap: spacing.md },
});
