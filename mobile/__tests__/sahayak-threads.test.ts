/**
 * Sahayak conversations are per-thread (FR-07).
 *
 * The store used to hold one transcript. It now holds one per thread, because a scan's chat is
 * grounded in that scan's frozen profile and the free-chat tab is grounded in nothing — so an
 * answer from one is not an answer in the other. The failure this guards against is quiet and
 * convincing: an answer about a 36 g dairy sachet rendered directly beneath a question about laptop
 * chargers, carrying the same official-looking citations either way.
 *
 * `draft` is threaded for the same reason at lower stakes: a half-typed question about one product
 * appearing in the composer of another is how the wrong question gets sent.
 */

import type { SahayakAnswer } from '@/domain';
import { FREE_THREAD, scanThread, useSahayakStore } from '@/store/sahayak';

const SCAN = 'f7c0a3d2-0000-4000-8000-000000000001';

function answerFrom(text: string): SahayakAnswer {
  return {
    id: `ans_${text}`,
    question: 'q',
    outcome: 'answered',
    answer: text,
    citations: [],
    confidence: 0,
    asOf: '2026-09-13',
  };
}

beforeEach(() => {
  useSahayakStore.setState({ threads: {} });
});

describe('sahayak threads', () => {
  it('keeps a scan conversation out of the free chat', () => {
    const { ask, answer } = useSahayakStore.getState();

    ask(scanThread(SCAN), 'Does this product need BIS certification?');
    answer(scanThread(SCAN), answerFrom('It is a dairy sachet.'));

    const free = useSahayakStore.getState().threads[FREE_THREAD];
    expect(free).toBeUndefined();

    const scan = useSahayakStore.getState().threads[scanThread(SCAN)];
    expect(scan.transcript.turns).toHaveLength(2);
  });

  it('keeps one scan conversation out of another', () => {
    const other = 'f7c0a3d2-0000-4000-8000-000000000002';
    const { ask } = useSahayakStore.getState();

    ask(scanThread(SCAN), 'about the sachet');
    ask(scanThread(other), 'about the charger');

    const a = useSahayakStore.getState().threads[scanThread(SCAN)].transcript;
    const b = useSahayakStore.getState().threads[scanThread(other)].transcript;

    expect(a.turns).toHaveLength(1);
    expect(b.turns).toHaveLength(1);
    expect(a.turns[0]).not.toEqual(b.turns[0]);
  });

  it('does not leak a draft between threads', () => {
    const { setDraft } = useSahayakStore.getState();

    setDraft(scanThread(SCAN), 'half a question about this pack');

    expect(useSahayakStore.getState().threads[FREE_THREAD]?.draft ?? '').toBe('');
  });

  it('clears only the thread it was asked to clear', () => {
    const { ask, reset } = useSahayakStore.getState();

    ask(FREE_THREAD, 'kept');
    ask(scanThread(SCAN), 'cleared');
    reset(scanThread(SCAN));

    expect(useSahayakStore.getState().threads[FREE_THREAD].transcript.turns).toHaveLength(1);
    expect(useSahayakStore.getState().threads[scanThread(SCAN)].transcript.turns).toHaveLength(0);
  });

  it('gives every turn its own id across threads', () => {
    // A repeated `key` renders answers under the wrong question, which is why the counter is
    // global rather than per-thread.
    const { ask } = useSahayakStore.getState();

    ask(FREE_THREAD, 'one');
    ask(scanThread(SCAN), 'two');

    const ids = [
      useSahayakStore.getState().threads[FREE_THREAD].transcript.turns[0].id,
      useSahayakStore.getState().threads[scanThread(SCAN)].transcript.turns[0].id,
    ];
    expect(new Set(ids).size).toBe(2);
  });
});
