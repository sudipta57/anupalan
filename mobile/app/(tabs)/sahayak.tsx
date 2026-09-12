/**
 * Sahayak — the BIS and Indian Standards assistant (FR-07).
 *
 * *Chat in English and Hindi, with inline source chips that open the cited page.*
 *
 * The free-chat entry point. The other one is `/scan/[id]/bis`, which skips the question entirely and
 * sends the scanned product's profile.
 *
 * **The locale is sent, not guessed at render time.** `lang` goes on the request, so an answer is
 * composed in the language it will be read in rather than translated afterwards — and a transcript
 * keeps whatever language each answer arrived in, because re-asking in Hindi is a new question with a
 * new answer, not a re-render of the old one.
 *
 * **One question at a time.** `canSend` blocks a second ask while one is running, and the reason is
 * ordering rather than politeness: two overlapping requests can complete out of order, and a
 * transcript where the second question's answer sits under the first is worse than a disabled
 * button — nothing on screen would reveal it, and the citations under the wrong question still look
 * official.
 */

import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';

import { useAskSahayak } from '@/api';
import { AdvisoryDisclaimer, Banner, Button, Card, Chip, Field, Text } from '@/components';
import {
  MAX_QUESTION_LENGTH,
  canSend,
  charactersRemaining,
  isEmpty,
  isOverLength,
  questionFor,
} from '@/features/sahayak';
// The file, not the barrel — the same narrowing the history screens do for `ScanList`, so a test
// importing one predicate does not drag the component tree in behind it.
import { AnswerCard } from '@/features/sahayak/answer-card';
import { useLocale, useT } from '@/i18n';
import { useSahayakStore } from '@/store/sahayak';
import { spacing, useTheme } from '@/theme';

/** The three starter questions. Chosen to reach an answer, a hallmarking answer, and a comparison. */
const SUGGESTIONS = ['sahayak.suggestion1', 'sahayak.suggestion2', 'sahayak.suggestion3'] as const;

export default function SahayakScreen() {
  const t = useT();
  const locale = useLocale();
  const { colors } = useTheme();

  const transcript = useSahayakStore((s) => s.transcript);
  const draft = useSahayakStore((s) => s.draft);
  const setDraft = useSahayakStore((s) => s.setDraft);
  const ask = useSahayakStore((s) => s.ask);
  const record = useSahayakStore((s) => s.answer);
  const fail = useSahayakStore((s) => s.fail);
  const reset = useSahayakStore((s) => s.reset);

  const mutation = useAskSahayak();

  /**
   * A chip that could not be opened at all. Screen-local rather than in the store: it is about this
   * tap, it is cleared by the next one, and it has no business surviving a tab switch.
   */
  const [openFailed, setOpenFailed] = useState(false);

  const send = (text: string) => {
    if (!canSend(text, mutation.isPending)) return;

    setOpenFailed(false);
    const question = ask(text);

    mutation.mutate(
      { question, lang: locale },
      {
        // Wrapped, not passed by reference: a mutation callback's second argument is the request
        // body, which would arrive where the arrival timestamp belongs.
        onSuccess: (answer) => record(answer),
        // The question stays in the transcript as a failed turn. A question that vanishes on a
        // dropped connection looks like one that was never asked, and the user retypes it — which
        // on a flaky link is how one question becomes four requests to a metered model.
        onError: (error) => fail(error.message || t('sahayak.askFailed')),
      }
    );
  };

  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={[styles.fill, { backgroundColor: colors.bg }]}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        >
          {isEmpty(transcript) ? (
            <Card>
              <Text variant="display">{t('sahayak.title')}</Text>
              <Text variant="body" tone="muted">
                {t('sahayak.subtitle')}
              </Text>
              <Text variant="caption" tone="subtle">
                {t('sahayak.emptyHint')}
              </Text>

              <View style={styles.suggestions}>
                {SUGGESTIONS.map((key) => (
                  <Chip
                    key={key}
                    label={t(key)}
                    tone="brand"
                    disabled={mutation.isPending}
                    onPress={() => send(t(key))}
                  />
                ))}
              </View>
            </Card>
          ) : null}

          {transcript.turns.map((turn, index) => {
            if (turn.kind === 'question') {
              return (
                <Card key={turn.id}>
                  <Text variant="caption" tone="subtle">
                    {t('sahayak.you')}
                  </Text>
                  <Text variant="bodyStrong">{turn.text}</Text>
                </Card>
              );
            }

            if (turn.kind === 'error') {
              // The question this failure belongs to — the nearest question turn above it. Retrying
              // has to re-send *that*, not the error text, and `questionFor` is why the transcript
              // keeps the failed question rather than discarding it.
              const question = questionFor(transcript, index);

              return (
                <Card key={turn.id}>
                  <Banner
                    tone="error"
                    title={t('sahayak.askFailed')}
                    body={turn.message}
                    action={
                      question ? (
                        <Button
                          label={t('common.retry')}
                          variant="secondary"
                          disabled={mutation.isPending}
                          onPress={() => send(question)}
                        />
                      ) : null
                    }
                  />
                </Card>
              );
            }

            return (
              <AnswerCard
                key={turn.id}
                answer={turn.answer}
                // The turn's own arrival stamp, not `Date.now()`: the render stays pure, and an
                // answer already on screen does not re-grade its sources on a re-render.
                now={Date.parse(turn.receivedAt)}
                onOpenFailed={() => setOpenFailed(true)}
              />
            );
          })}

          {mutation.isPending ? (
            <Card>
              <Text variant="body" tone="muted">
                {t('sahayak.sending')}
              </Text>
            </Card>
          ) : null}

          {openFailed ? <Banner tone="warning" title={t('sahayak.openFailed')} /> : null}

          {isEmpty(transcript) ? null : (
            <Button label={t('sahayak.clear')} variant="ghost" onPress={reset} />
          )}

          <AdvisoryDisclaimer />
        </ScrollView>

        <View
          style={[
            styles.composer,
            { backgroundColor: colors.surface, borderTopColor: colors.border },
          ]}
        >
          <Field
            label={t('sahayak.inputLabel')}
            placeholder={t('sahayak.inputPlaceholder')}
            value={draft}
            onChangeText={setDraft}
            multiline
            // A cap rather than a truncation: `maxLength` would silently drop the tail of a pasted
            // question and answer something the user did not ask.
            error={
              isOverLength(draft) ? t('sahayak.tooLong', { max: MAX_QUESTION_LENGTH }) : undefined
            }
            hint={t('sahayak.charactersLeft', { count: Math.max(0, charactersRemaining(draft)) })}
            onSubmitEditing={() => send(draft)}
            returnKeyType="send"
          />
          <Button
            label={mutation.isPending ? t('sahayak.sending') : t('sahayak.send')}
            size="lg"
            loading={mutation.isPending}
            disabled={!canSend(draft, mutation.isPending)}
            onPress={() => send(draft)}
          />
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  composer: {
    borderTopWidth: 1,
    gap: spacing.sm,
    paddingBottom: spacing.lg,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  fill: { flex: 1 },
  scroll: {
    gap: spacing.md,
    padding: spacing.lg,
  },
  suggestions: {
    gap: spacing.sm,
  },
});
