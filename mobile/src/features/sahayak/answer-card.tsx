/**
 * One answer, rendered — FR-07.
 *
 * The order of this card is the argument it makes, and it is deliberate:
 *
 * 1. **What kind of response this is**, before the prose. A reader who starts with the paragraph has
 *    already begun to believe it; a reader who starts with "Not found in official sources" reads the
 *    paragraph as an explanation of an absence, which is what it is.
 * 2. **The prose** — or the app's own copy in its place, when `showsModelText` is false. A downgraded
 *    answer's text is the thing under suspicion and is not shown at all.
 * 3. **The sources.**
 * 4. **The freshness stamp**, last, because it qualifies everything above it.
 *
 * Confidence is shown only on a genuine answer (`showsConfidence`). Both refusals carry
 * `confidence: 0` — correctly, there is no claim to be confident about — and "0%" printed beside a
 * deliberate, correct refusal reads as a broken answer rather than a boundary held on purpose.
 */

import { StyleSheet, View } from 'react-native';

import { Banner, Card, Chip, Text } from '@/components';
import type { SahayakAnswer } from '@/domain';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

import { citationRole } from './citations';
import { FRESHNESS_AGEING_DAYS, FRESHNESS_COPY, freshnessFor, needsRecheck } from './freshness';
import { PRESENTATION_COPY, presentationFor, showsConfidence, showsModelText } from './outcome';
import { SourceList } from './source-list';

export interface AnswerCardProps {
  answer: SahayakAnswer;
  /** Passed in rather than read from the clock, so this component stays pure to render. */
  now: number;
  onOpenFailed?: () => void;
}

export function AnswerCard({ answer, now, onOpenFailed }: AnswerCardProps) {
  const t = useT();

  const presentation = presentationFor(answer);
  const copy = PRESENTATION_COPY[presentation];
  const freshness = freshnessFor(answer.asOf, now);
  const freshCopy = FRESHNESS_COPY[freshness];
  const downgraded = !showsModelText(answer);

  return (
    <Card>
      {/* The downgrade is stated as its own banner, above everything. It is a statement about the
          assistant rather than about the question, and burying it under the not-found copy would
          hide the only signal that the extraction layer is returning uncited prose. */}
      {downgraded ? (
        <Banner
          tone="error"
          title={t('sahayak.downgradedTitle')}
          body={t('sahayak.downgradedBody')}
        />
      ) : null}

      <Banner tone={copy.tone} title={t(copy.labelKey)} body={t(copy.bodyKey)} />

      {downgraded ? null : (
        <Text variant="body" selectable>
          {answer.answer}
        </Text>
      )}

      <SourceList
        citations={answer.citations}
        role={citationRole(presentation)}
        onOpenFailed={onOpenFailed}
      />

      <View style={styles.stamps}>
        {/* The date is a fact and stays neutral; the judgement about it is the chip beside it. */}
        <Chip label={t('sahayak.asOf', { date: answer.asOf })} />
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
        {showsConfidence(answer) ? (
          <Chip
            label={t('sahayak.confidence', { percent: Math.round(answer.confidence * 100) })}
            tone="neutral"
          />
        ) : null}
      </View>

      {needsRecheck(freshness) ? (
        <Text variant="caption" tone="borderline">
          {t('sahayak.recheck')}
        </Text>
      ) : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  stamps: {
    alignItems: 'center',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
});
