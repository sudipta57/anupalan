/**
 * Sahayak — the BIS and Indian Standards assistant (FR-07).
 *
 * *Chat in English and Hindi, with inline source chips that open the cited page.*
 *
 * The free-chat entry point. The other one is `/scan/[id]/bis`, which opens the same conversation
 * grounded in a scanned product's frozen profile, under that scan's deterministic applicability
 * verdict.
 *
 * Everything about a conversation lives in `features/sahayak/chat`; this screen chooses the thread
 * and the starter questions. The split is what lets a scan have its own transcript without a second
 * copy of the composer, the retry path and the citation rendering.
 *
 * **The locale is sent, not guessed at render time.** `lang` goes on the request, so an answer is
 * composed in the language it will be read in rather than translated afterwards — and a transcript
 * keeps whatever language each answer arrived in, because re-asking in Hindi is a new question with
 * a new answer, not a re-render of the old one.
 */

import type { ReactNode } from 'react';

import { Text } from '@/components';
import { SahayakChat } from '@/features/sahayak/chat';
import { useT } from '@/i18n';
import { FREE_THREAD } from '@/store/sahayak';

/** The three starter questions. Chosen to reach an answer, a hallmarking answer, and a comparison. */
const SUGGESTIONS = ['sahayak.suggestion1', 'sahayak.suggestion2', 'sahayak.suggestion3'] as const;

export default function SahayakScreen(): ReactNode {
  const t = useT();

  return (
    <SahayakChat
      thread={FREE_THREAD}
      suggestions={SUGGESTIONS}
      intro={
        <>
          <Text variant="display">{t('sahayak.title')}</Text>
          <Text variant="body" tone="muted">
            {t('sahayak.subtitle')}
          </Text>
          <Text variant="caption" tone="subtle">
            {t('sahayak.emptyHint')}
          </Text>
        </>
      }
    />
  );
}
