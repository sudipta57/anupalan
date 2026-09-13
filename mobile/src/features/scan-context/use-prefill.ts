/**
 * Asking the server to read the label, and holding the answer — FR-03.
 *
 * The only file that talks to `expo-image-manipulator`, the same way `use-location.ts` is the only
 * file that talks to `expo-location`. Everything it decides is pure and lives in `prefill.ts`; this
 * is the impure shell: shrink a photograph, send it, poll, and report where it got to.
 *
 * **The screen waits for this, and that is a deliberate product decision** (docs/decisions.md,
 * 2026-09-13). An earlier version ran it beside a form that rendered immediately; the form then
 * rearranged itself under anyone who had started typing, and invited exactly the work the feature
 * exists to remove. So the form is not rendered until this settles, and it arrives filled.
 *
 * **Which makes the ways out of the wait the important part.** Three of them end it: an answer, a
 * failure, and `timeoutFor`. A failure is a `failed` state that the screen renders as an ordinary
 * empty form, never as an error — and the gate offers "fill it in myself" on the first tap. That
 * is what keeps FR-04 intact: a capture in a market with no signal must still reach the queue, and
 * it does, because nothing here can block indefinitely and nothing here can fail loudly.
 *
 * **Up to three photographs, downscaled.** The mandatory declarations are spread across a pack's
 * faces — net quantity and commodity name on the front, importer, country of origin and
 * consumer-care line on the back — so reading only the front panel proposes nothing for most of the
 * fields a user would otherwise type. The first three go, and the worker merges their words before
 * extracting once. `MAX_PREFILL_IMAGES` says why three.
 *
 * Downscaled because prefill reads words and never measures, so it has no use for the marker or
 * for full resolution. `MAX_EDGE_PX` is about recognising 8 pt text on a packet, not about
 * fidelity — and the difference between three 4 MB originals and three ~200 KB thumbnails is the
 * difference between this being usable on 3G and not.
 */

import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { usePrefill as usePrefillQuery, usePrefillRequest } from '@/api/hooks';

import type { PrefillStatus, Suggestion } from './prefill';

/**
 * Longest edge of the image that is sent, in pixels.
 *
 * 1600 is the smallest size at which the small print on an Indian retail pack — the consumer-care
 * line, the FSSAI number — survives recognition; the net quantity and MRP are legible well below
 * it. Chosen for the hardest text on the label rather than the easiest, because the fields prefill
 * is *for* are not the big ones.
 */
export const MAX_EDGE_PX = 1600;

/** JPEG quality for the same image. 0.7 is where text edges are still clean. */
export const COMPRESS = 0.7;

/**
 * How many photographs one read sends. Matches the server's own ceiling
 * (`backend/app/schemas/prefill.py`), which is what makes a fourth photograph a drop here rather
 * than a 422 there.
 *
 * **Three because a pack has three faces worth reading**, and the read is a wait somebody is
 * watching. A fourth photograph is nearly always another angle on a face already covered, so it
 * proposes no new declaration and still costs a full OCR pass — the user pays fifteen seconds for
 * nothing. This is a budget on patience, which is why it is not the scan's asset limit: more
 * evidence on a scan is better, more photographs in front of a spinner is worse.
 */
export const MAX_PREFILL_IMAGES = 3;

/**
 * The photographs a read will actually use, from everything the capture holds.
 *
 * The first three in capture order, because capture order is roughly panel order — the front is
 * framed first and the back second, so the declarations arrive in the order they matter. Dropping
 * the tail is silent on purpose: a capture of five is a user who photographed carefully, and
 * telling them two of their pictures were ignored would read as a fault when the form is about to
 * fill anyway.
 */
export function photographsToRead(uris: readonly string[]): readonly string[] {
  return uris.length <= MAX_PREFILL_IMAGES ? uris : uris.slice(0, MAX_PREFILL_IMAGES);
}

/**
 * How long to wait for a read before giving up on it, given how many photographs were sent.
 *
 * A ceiling on a wait somebody is *watching*, now that the form is held back until this settles —
 * so it is the outer bound on being stuck, not a budget to spend. It scales with the photograph
 * count because the worker recognises each one: a measured read of a single pack on a warm worker
 * lands in twelve to sixteen seconds over USB, and three photographs is not three times the
 * network but is three times the OCR.
 *
 * It is the *last* of the three ways out, and the least used: an answer or a failure ends the wait
 * first, and the gate's "fill it in myself" ends it on the first tap.
 *
 * `TIMEOUT_CEILING_MS` is no longer reachable through this hook now that `MAX_PREFILL_IMAGES`
 * caps the count at three (50 s). It stays because `timeoutFor` is a pure function with its own
 * tests, and a bound that holds for any argument is worth more than one that happens to be
 * unreachable today.
 */
export const TIMEOUT_BASE_MS = 20_000;
export const TIMEOUT_PER_IMAGE_MS = 15_000;
export const TIMEOUT_CEILING_MS = 90_000;

export function timeoutFor(imageCount: number): number {
  return Math.min(
    TIMEOUT_CEILING_MS,
    TIMEOUT_BASE_MS + TIMEOUT_PER_IMAGE_MS * Math.max(0, imageCount - 1)
  );
}

export interface PrefillState {
  status: PrefillStatus | 'idle';
  suggestions: Suggestion[];
  /** True while the photograph is being shrunk, sent, or read. */
  working: boolean;
  /** The read finished and proposed nothing — a blur, a back panel, an unreadable pack. */
  readNothing: boolean;
  /** The read ran pattern-only, so no product name was proposed. */
  reduced: boolean;
}

const IDLE: PrefillState = {
  status: 'idle',
  suggestions: [],
  working: false,
  readNothing: false,
  reduced: false,
};

/**
 * Shrink one captured photograph to something worth sending, as base64.
 *
 * Returns null rather than throwing, so one unreadable capture out of three costs its own words
 * and not the other two photographs'. Exported for the sake of being testable on its own.
 */
export async function downscaleForPrefill(uri: string): Promise<string | null> {
  try {
    const rendered = await ImageManipulator.manipulate(uri)
      .resize({ width: MAX_EDGE_PX })
      .renderAsync();

    const saved = await rendered.saveAsync({
      base64: true,
      compress: COMPRESS,
      format: SaveFormat.JPEG,
    });

    return saved.base64 ?? null;
  } catch {
    // A capture whose file has gone, or a manipulator that failed. Neither is worth telling the
    // user about: it resolves to `failed`, the gate gives way, and they get the form they would
    // have got anyway.
    return null;
  }
}

/**
 * Read the label, and report where that has got to.
 *
 * Held by the screen rather than by the form, so that it survives the gate giving way to the form:
 * the request is issued once and is not restarted by the transition.
 *
 * Args:
 *   uris: every captured photograph, in capture order. At most `MAX_PREFILL_IMAGES` of them are
 *     read — the cap is applied here, where the request is assembled, so no caller can send the
 *     server a body it will refuse. Empty means do nothing: the state is `idle`, `working` is
 *     false, and the screen goes straight to an empty form.
 *
 * Returns the settled state. `working` is what the screen gates on; `suggestions` is what seeds the
 * form once it is not.
 */
export function useLabelPrefill(uris: readonly string[]): PrefillState {
  const request = usePrefillRequest();
  const [prefillId, setPrefillId] = useState<string | undefined>();
  const [shrinking, setShrinking] = useState(false);
  const [gaveUp, setGaveUp] = useState(false);
  // How many photographs actually went up, which is what the wait is budgeted against.
  const [sentCount, setSentCount] = useState(1);

  // Guards a double-start under React 19's strict-mode double-effect, and a re-run if the uri
  // identity changes without the photograph changing.
  const started = useRef<string | null>(null);

  const { mutateAsync } = request;

  const start = useCallback(
    async (sources: readonly string[]) => {
      setShrinking(true);
      try {
        // Serially rather than with `Promise.all`: each resize is native work on a 4 MB JPEG, and
        // three at once on a mid-range phone competes for the same decoder to finish no sooner.
        const images: { imageBase64: string; contentType: 'image/jpeg' }[] = [];
        for (const source of sources) {
          const imageBase64 = await downscaleForPrefill(source);
          // A capture whose file has gone. Skipped, not fatal — the rest are still worth reading.
          if (imageBase64) images.push({ imageBase64, contentType: 'image/jpeg' });
        }

        if (images.length === 0) {
          setGaveUp(true);
          return;
        }

        setSentCount(images.length);
        const accepted = await mutateAsync({ images });
        setPrefillId(accepted.prefillId);
      } catch {
        // Offline, rate-limited, prefill switched off server-side — all the same thing here.
        setGaveUp(true);
      } finally {
        setShrinking(false);
      }
    },
    [mutateAsync]
  );

  // Identity of the list changes on every render, so the join is what decides "same photographs".
  // Capped first, so a sixth photograph arriving does not look like a different capture and
  // restart a read whose answer would be identical.
  const key = photographsToRead(uris).join('\u0000');

  useEffect(() => {
    if (key.length === 0 || started.current === key) return;
    started.current = key;
    void start(key.split('\u0000'));
  }, [key, start]);

  const query = usePrefillQuery(prefillId);

  const answered = query.data !== undefined && query.data.status !== 'reading';

  // Stop waiting eventually. A `reading` with nothing behind it would otherwise hold the gate —
  // and therefore the whole screen — for as long as the user is willing to look at it.
  //
  // Armed **only while still reading**. An unconditional timer fires thirty seconds after the id is
  // issued whether or not the answer arrived, and that is exactly what shipped: on a real device the
  // suggestions appeared, were applied, and then the banner and the confirmation card vanished
  // mid-form while the user was still filling in the rest of it. Found by running it on a phone;
  // no test caught it, because the bug is in the passage of time rather than in a value.
  useEffect(() => {
    if (!prefillId || gaveUp || answered) return;
    const timer = setTimeout(() => setGaveUp(true), timeoutFor(sentCount));
    return () => clearTimeout(timer);
  }, [answered, gaveUp, prefillId, sentCount]);

  return useMemo(() => {
    if (key.length === 0) return IDLE;

    const result = query.data;

    // A result that is in hand wins over everything else, and is checked first for that reason:
    // nothing that happens later — a timeout, a failed refetch of an answer already collected —
    // may take back suggestions the form is already showing.
    if (result?.status === 'ready') {
      return {
        status: 'ready' as const,
        suggestions: result.suggestions,
        working: false,
        readNothing: result.suggestions.length === 0,
        reduced: result.reduced,
      };
    }

    if (result?.status === 'failed' || gaveUp || query.isError) {
      return { ...IDLE, status: 'failed' as const };
    }

    if (shrinking || !prefillId || !result || result.status === 'reading') {
      return { ...IDLE, status: 'reading' as const, working: true };
    }

    return IDLE;
  }, [gaveUp, key, prefillId, query.data, query.isError, shrinking]);
}
