/**
 * The sign-in stack.
 *
 * Two screens, one per endpoint: a phone number, then the code sent to it. Headerless — the
 * screens carry their own titles, because "Sign in" as a nav bar title above "Sign in" as a
 * heading is the kind of duplication that makes a first-run screen feel unconsidered.
 */

import { Stack } from 'expo-router';

export const unstable_settings = { initialRouteName: 'phone' };

export default function AuthLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
