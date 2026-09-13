/**
 * The Sahayak conversation, as a component (FR-07).
 *
 * Extracted from the tab so a scan can carry its own. The two entry points differ in exactly three
 * things — which thread they append to, whether a `scanId` rides along, and what sits above the
 * transcript — and everything else about a conversation is identical, so everything else is here.
 *
 * **`scanId` is what makes a scan's chat about that scan.** It is sent with every question, and the
 * backend loads that scan's *frozen* profile into the prompt as grounding. The question still
 * reaches retrieval exactly as typed — the profile steers how an answer is worded, never which
 * sources it may cite — and no answer here decides applicability. That stays with the deterministic
 * lookup, for the reason `routers/sahayak.py` gives: a wrong "no licence needed" is a seized
 * consignment.
 *
 * **One question at a time.** `canSend` blocks a second ask while one is running, and the reason is
 * ordering rather than politeness: two overlapping requests can complete out of order, and a
 * transcript where the second question's answer sits under the first is worse than a disabled
 * button — nothing on screen would reveal it, and the citations under the wrong question still look
 * official.
 */

import { type ReactNode, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';

import { useAskSahayak } from '@/api';
import { AdvisoryDisclaimer, Banner, Button, Card, Chip, Field, Text } from '@/components';
import { useLocale, useT, type TranslationKey } from '@/i18n';
import { useSahayakStore, useThread } from '@/store/sahayak';
import { spacing, useTheme } from '@/theme';

import { AnswerCard } from './answer-card';
import {
  MAX_QUESTION_LENGTH,
  canSend,
  charactersRemaining,
  isEmpty,
  isOverLength,
  questionFor,
} from './index';

export interface SahayakChatProps {
  /** Which conversation to append to. `FREE_THREAD`, or `scanThread(id)`. */
  thread: string;
  /** Grounds every question in this scan's frozen profile. Omitted for free chat. */
  scanId?: string;
  /** i18n keys for the starter questions offered while the transcript is empty. */
  suggestions: readonly TranslationKey[];
  /** Rendered above the transcript, always. The scan screen puts its verdict card here. */
  header?: ReactNode;
  /** Rendered above the suggestions, only while the transcript is empty. */
  intro?: ReactNode;
}

export function SahayakChat({
  thread,
  scanId,
  suggestions,
  header,
  intro,
}: SahayakChatProps): ReactNode {
  const t = useT();
  const locale = useLocale();
  const { colors, elevation } = useTheme();

  const { transcript, draft } = useThread(thread);
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
    const question = ask(thread, text);

    mutation.mutate(
      { question, lang: locale, ...(scanId ? { scanId } : {}) },
      {
        // Wrapped, not passed by reference: a mutation callback's second argument is the request
        // body, which would arrive where the arrival timestamp belongs.
        onSuccess: (answer) => record(thread, answer),
        // The question stays in the transcript as a failed turn. A question that vanishes on a
        // dropped connection looks like one that was never asked, and the user retypes it — which
        // on a flaky link is how one question becomes four requests to a metered model.
        onError: (error) => fail(thread, error.message || t('sahayak.askFailed')),
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
          {header}

          {isEmpty(transcript) ? (
            <Card>
              {intro}
              <View style={styles.suggestions}>
                {suggestions.map((key) => (
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
                <View key={turn.id} style={styles.questionRow}>
                  <Card style={[styles.questionBubble, { backgroundColor: colors.brandSoft }]}>
                    <Text variant="caption" tone="subtle">
                      {t('sahayak.you')}
                    </Text>
                    <Text variant="bodyStrong">{turn.text}</Text>
                  </Card>
                </View>
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
            <Button label={t('sahayak.clear')} variant="ghost" onPress={() => reset(thread)} />
          )}

          <AdvisoryDisclaimer />
        </ScrollView>

        <View
          style={[
            styles.composer,
            { backgroundColor: colors.surface, borderTopColor: colors.border },
            { ...elevation.md, shadowOffset: { width: 0, height: -4 } },
          ]}
        >
          <Field
            label={t('sahayak.inputLabel')}
            placeholder={t('sahayak.inputPlaceholder')}
            value={draft}
            onChangeText={(text) => setDraft(thread, text)}
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
  questionBubble: { maxWidth: '86%' },
  questionRow: { alignItems: 'flex-end' },
  scroll: {
    gap: spacing.md,
    padding: spacing.lg,
  },
  suggestions: {
    gap: spacing.sm,
  },
});
