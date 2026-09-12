/**
 * Opening a cited page — FR-07.
 *
 * *Chat in English and Hindi, with inline source chips that open the cited page.*
 *
 * In-app via Chrome Custom Tabs (`expo-web-browser`) rather than handing the URL to the browser.
 * The reason is the reading task: a source chip is tapped *while* reading an answer, to check one
 * claim in it, and the user then wants to be back at the answer. A custom tab dismisses to exactly
 * where they were. `Linking.openURL` leaves the app, and coming back depends on the Android task
 * stack — which, after a couple of hops inside Chrome, does not reliably return to the transcript.
 *
 * `Linking` is kept as a fallback rather than dropped. A device with no Custom Tabs provider — some
 * AOSP builds, and any device where the user has disabled Chrome — throws rather than degrading, and
 * a dead source chip on an answer is precisely the wrong thing to ship: the chip is the app's offer
 * to be checked.
 *
 * **The URL is re-checked here.** `isShowable` already gated the chip at render time, and this
 * checks again before opening, because these are different moments and only one of them is a
 * navigation. A belt-and-braces check on the one call that leaves the app is cheap.
 */

import * as WebBrowser from 'expo-web-browser';
import { Linking } from 'react-native';

import type { Citation } from '@/domain';

import { isShowable } from './citations';

/**
 * Open a citation, or do nothing.
 *
 * Returns whether it opened, so a caller can surface a failure instead of leaving a tap that
 * appears to have done nothing at all. Never throws: a source chip is a read-only convenience and
 * should not be able to take a screen down with it.
 */
export async function openSource(citation: Citation): Promise<boolean> {
  if (!isShowable(citation)) return false;

  try {
    await WebBrowser.openBrowserAsync(citation.url);
    return true;
  } catch {
    // No Custom Tabs provider. Fall back to whatever will take an https URL.
    try {
      await Linking.openURL(citation.url);
      return true;
    } catch {
      return false;
    }
  }
}
