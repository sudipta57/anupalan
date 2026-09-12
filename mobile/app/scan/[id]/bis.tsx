/**
 * BIS applicability for a scanned product — FR-07, SIH26107.
 *
 * The second Sahayak entry point, and the one that makes the two problem statements one system: the
 * `ProductProfile` the rules engine used to evaluate Legal Metrology declarations is the same object
 * that decides which Quality Control Order applies (`01-architecture.md` §2). No question is typed
 * here — the scan already knows what the product is.
 *
 * **`unclear` is not `no`, and this screen is where that would be lost.** `features/sahayak/
 * applicability` carries the argument in full; what it means here is that every affirmative row —
 * the certification route, the standards list, the plain-language heading — is gated on
 * `isConclusive`. Rendering a `scheme: 'none'` row on an undetermined record would answer the
 * question the stance just declined to answer, and it would answer it with "no certification
 * needed", which is what the reader hoped to hear.
 *
 * A scan whose profile was typed in rather than matched to a catalogue product has no `productId`, so
 * there is nothing to look up and the request is never made. That is the not-found state, reached
 * without a round trip.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { useBisApplicability, useScan } from '@/api';
import {
  AdvisoryDisclaimer,
  Banner,
  Button,
  Card,
  Chip,
  Screen,
  Skeleton,
  Text,
} from '@/components';
import type { BisApplicability } from '@/domain';
import {
  FRESHNESS_AGEING_DAYS,
  FRESHNESS_COPY,
  SCHEME_BODY_KEYS,
  SCHEME_LABEL_KEYS,
  STANCE_COPY,
  freshnessFor,
  isConclusive,
  isInconsistent,
  isNumbersLabelKey,
  needsRecheck,
  nextSteps,
  showsScheme,
  stanceFor,
} from '@/features/sahayak';
import { SourceList } from '@/features/sahayak/source-list';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

function Result({ record, now }: { record: BisApplicability; now: number }) {
  const t = useT();

  const stance = stanceFor(record.qcoApplicable);
  const copy = STANCE_COPY[stance];
  const steps = nextSteps(record);
  const freshness = freshnessFor(record.asOf, now);
  const freshCopy = FRESHNESS_COPY[freshness];

  return (
    <Screen scroll>
      <Card>
        <Text variant="caption" tone="subtle">
          {t('bis.product')}
        </Text>
        <Text variant="heading">{record.profile.name}</Text>
        <Text variant="mono" tone="subtle">
          {record.profile.categoryCode}
        </Text>
      </Card>

      {/* The stance first. A reader who starts with a list of IS numbers has already concluded that
          certification applies. */}
      <Card>
        <Banner tone={copy.tone} title={t(copy.titleKey)} body={t(copy.bodyKey)} />

        {/* A record that says "mandatory" and names no route is a hole in the source data, not an
            answer. Stated rather than papered over by omitting the scheme row. */}
        {isInconsistent(record) ? (
          <Banner
            tone="error"
            title={t('bis.inconsistentTitle')}
            body={t('bis.inconsistentBody')}
          />
        ) : null}
      </Card>

      {showsScheme(record) ? (
        <Card>
          <Text variant="label" tone="muted">
            {t('bis.schemeLabel')}
          </Text>
          <Text variant="bodyStrong">{t(SCHEME_LABEL_KEYS[record.scheme])}</Text>
          <Text variant="body" tone="muted">
            {t(SCHEME_BODY_KEYS[record.scheme])}
          </Text>
        </Card>
      ) : null}

      {record.candidateIsNumbers.length > 0 ? (
        <Card>
          <Text variant="label" tone="muted">
            {t(isNumbersLabelKey(record))}
          </Text>
          <View style={styles.row}>
            {record.candidateIsNumbers.map((number) => (
              <Chip key={number} label={number} tone="brand" />
            ))}
          </View>
          {/* The standards can be named but not quoted (CLAUDE.md §3.5). Said here, next to the
              numbers, rather than only in the chat's refusal. */}
          <Text variant="caption" tone="subtle">
            {t('bis.isNumbersHint')}
          </Text>
        </Card>
      ) : null}

      {steps.length > 0 ? (
        <Card>
          <Text variant="label" tone="muted">
            {t('bis.nextSteps')}
          </Text>
          {steps.map((step) => (
            <Text key={step} variant="body">
              {step}
            </Text>
          ))}
        </Card>
      ) : null}

      <Card>
        <SourceList
          citations={record.sources}
          role={isConclusive(record) ? 'support' : 'signpost'}
        />
        <View style={styles.row}>
          <Chip label={t('sahayak.asOf', { date: record.asOf })} />
          {freshness === 'fresh' ? null : (
            <Chip
              label={
                freshness === 'ageing'
                  ? t(freshCopy.labelKey, { days: FRESHNESS_AGEING_DAYS })
                  : t(freshCopy.labelKey)
              }
              tone={freshCopy.tone}
            />
          )}
        </View>
        {needsRecheck(freshness) || !isConclusive(record) ? (
          <Text variant="caption" tone="borderline">
            {t('sahayak.recheck')}
          </Text>
        ) : null}
      </Card>

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

function NotFound() {
  const t = useT();

  return (
    <Screen scroll>
      <Card>
        <Text variant="heading">{t('bis.notFoundTitle')}</Text>
        <Text variant="body" tone="muted">
          {t('bis.notFoundBody')}
        </Text>
        <Button label={t('tabs.sahayak')} onPress={() => router.dismissTo('/(tabs)/sahayak')} />
      </Card>
      <AdvisoryDisclaimer />
    </Screen>
  );
}

export default function BisScreen() {
  const t = useT();
  const { id } = useLocalSearchParams<{ id: string }>();

  const scan = useScan(id);
  const productId = scan.data?.productId ?? undefined;
  const profile = scan.data?.profile;

  const applicability = useBisApplicability(productId, profile ? { profile } : undefined);

  if (scan.isPending) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={28} />
          <Skeleton height={18} width="70%" />
        </Card>
      </Screen>
    );
  }

  // Nothing to look up, so nothing was asked. Not an error — a typed-in profile was never matched to
  // a catalogue product, and inventing a match would be a confident answer about a different product.
  if (!scan.data || !productId) return <NotFound />;

  if (applicability.isPending) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="body" tone="muted">
            {t('bis.pending')}
          </Text>
          <Skeleton height={120} />
        </Card>
      </Screen>
    );
  }

  if (applicability.isError || !applicability.data) return <NotFound />;

  // The fetch's own timestamp, not `Date.now()` — the same clock the report screen polls with. It
  // advances when the record does, which is the only cadence on which its freshness can change, and
  // it keeps the render pure.
  return <Result record={applicability.data} now={applicability.dataUpdatedAt} />;
}

const styles = StyleSheet.create({
  row: {
    alignItems: 'center',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
});
