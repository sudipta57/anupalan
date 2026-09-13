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
 * **The lookup runs off the scan's frozen profile, not a `productId`.** It used to require one, and
 * that was a dead end rather than a safeguard: a photographed label is almost never matched to a
 * catalogue product, so every scan in the field has `productId: null` and this screen reported "no
 * applicability record" for a record nobody had asked for. `POST /scans/{id}/applicability` needs no
 * product row — it reads the profile the scan was frozen with and stamps the answer with that scan's
 * capture date, so the verdict stays reproducible under the lists in force when the package was
 * photographed.
 *
 * **Underneath the verdict is a conversation, and the order is the point.** The deterministic lookup
 * answers "does this need certification"; the chat answers everything that is genuinely prose — how
 * to apply, which lab, what a scheme means. Sahayak is grounded in this scan, so it knows what the
 * product is without the user describing it, but it decides nothing: `services/bis/answer` requires
 * every claim to name a published passage, and a wrong "no licence needed" is a seized consignment.
 * Putting the chat above the verdict, or in place of it, would invert exactly that.
 */

import { useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { useBisApplicabilityForScan, useScan } from '@/api';
import {
  Banner,
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
import { SahayakChat } from '@/features/sahayak/chat';
import { SourceList } from '@/features/sahayak/source-list';
import { useT } from '@/i18n';
import { scanThread } from '@/store/sahayak';
import { spacing } from '@/theme';

/**
 * The deterministic verdict, as the chat's header.
 *
 * A fragment rather than a `Screen`: it is rendered inside the conversation's scroll view, so the
 * verdict and the questions about it scroll as one column instead of the answer being a tap away
 * from the thing it answers.
 */
function Verdict({ record, now }: { record: BisApplicability; now: number }) {
  const t = useT();

  const stance = stanceFor(record.qcoApplicable);
  const copy = STANCE_COPY[stance];
  const steps = nextSteps(record);
  const freshness = freshnessFor(record.asOf, now);
  const freshCopy = FRESHNESS_COPY[freshness];

  return (
    <>
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

    </>
  );
}

/**
 * The lookup could not answer, as the chat's header.
 *
 * A card rather than a screen. It used to replace the whole screen, which meant the one case where
 * a user most needs to ask a question — the lists do not place this product — was the one case with
 * nothing to ask it with. The chat below stays mounted; this only says the check came back empty.
 */
function Unavailable({ reason }: { reason: 'not-found' | 'failed' }) {
  const t = useT();

  return (
    <Banner
      tone={reason === 'failed' ? 'error' : 'warning'}
      title={t(reason === 'failed' ? 'bis.lookupFailed' : 'bis.notFoundTitle')}
      body={t(reason === 'failed' ? 'bis.lookupFailedBody' : 'bis.notFoundBody')}
    />
  );
}

/** The starter questions for a scan's thread. Product-generic, because the product is grounding. */
const SUGGESTIONS = ['bis.suggestion1', 'bis.suggestion2', 'bis.suggestion3'] as const;

export default function BisScreen() {
  const t = useT();
  const { id } = useLocalSearchParams<{ id: string }>();

  const scan = useScan(id);
  const profile = scan.data?.profile;

  // The scan's own frozen profile is the whole input. No `productId` — see the note at the top of
  // this file for why requiring one made this screen a dead end for every scan taken in the field.
  const applicability = useBisApplicabilityForScan(scan.data ? id : undefined, profile);

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

  const header = (() => {
    if (!scan.data) return <Unavailable reason="not-found" />;

    if (applicability.isPending) {
      return (
        <Card>
          <Text variant="body" tone="muted">
            {t('bis.pending')}
          </Text>
          <Skeleton height={120} />
        </Card>
      );
    }

    // A failed lookup is distinguished from an empty one. "We could not check" and "the lists do
    // not cover this" lead to different next actions, and collapsing them would let a dropped
    // connection read as an answer about the product.
    if (applicability.isError) return <Unavailable reason="failed" />;
    if (!applicability.data) return <Unavailable reason="not-found" />;

    // The fetch's own timestamp, not `Date.now()` — the same clock the report screen polls with. It
    // advances when the record does, which is the only cadence on which its freshness can change,
    // and it keeps the render pure.
    return <Verdict record={applicability.data} now={applicability.dataUpdatedAt} />;
  })();

  return (
    <SahayakChat
      thread={scanThread(id)}
      // What makes this conversation about this package: the backend loads the scan's frozen
      // profile into the prompt. The question still reaches retrieval exactly as typed.
      scanId={id}
      suggestions={SUGGESTIONS}
      header={header}
      intro={
        <>
          <Text variant="heading">{t('bis.askTitle')}</Text>
          <Text variant="body" tone="muted">
            {t('bis.askBody')}
          </Text>
        </>
      }
    />
  );
}

const styles = StyleSheet.create({
  row: {
    alignItems: 'center',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
});
