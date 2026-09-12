/**
 * Root layout: providers, theme-aware navigation chrome, status bar, and the auth boundary.
 *
 * **The auth boundary is `Stack.Protected`, not a redirect.** A guarded-off route is removed from
 * the navigator rather than mounted and then navigated away from, so a signed-out user never
 * briefly renders a screen that fetches org-scoped data, and deep-linking into `/settings` while
 * signed out resolves to the sign-in flow instead of flashing the screen first.
 *
 * The session is read synchronously from MMKV (`src/store/session.ts`), so `isAuthenticated` is
 * already correct on the very first render. There is no loading state here, and no frame of the
 * login screen shown to someone who is already signed in.
 *
 * Screens beyond the tab shell are pushed onto this stack — capture, findings, reports, settings —
 * so the tab bar stays out of the way during a scan.
 *
 * **The upload queue runs while signed in, and only while signed in.** Starting it here rather than
 * at module scope ties it to the session: a signed-out app holds no tokens, so a drain would fail
 * every scan and burn its five attempts on nothing. Stopping it on sign-out leaves the rows exactly
 * where they are — they belong to the device, and they resume on the next sign-in (FR-04).
 */

import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo } from 'react';

import { startQueue, stopQueue } from '@/features/queue';
import { useT } from '@/i18n';
import { AppProviders } from '@/providers/app-providers';
import { useIsAuthenticated } from '@/store/session';
import { useTheme } from '@/theme';

export const unstable_settings = { initialRouteName: '(tabs)' };

function RootNavigator() {
  const { colors, scheme } = useTheme();
  const isAuthenticated = useIsAuthenticated();
  const t = useT();

  useEffect(() => {
    if (!isAuthenticated) return;

    startQueue();
    return stopQueue;
  }, [isAuthenticated]);

  const navigationTheme = useMemo(() => {
    const base = scheme === 'dark' ? DarkTheme : DefaultTheme;

    return {
      ...base,
      colors: {
        ...base.colors,
        primary: colors.brand,
        background: colors.bg,
        card: colors.surface,
        text: colors.text,
        border: colors.border,
      },
    };
  }, [colors, scheme]);

  return (
    <ThemeProvider value={navigationTheme}>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerShadowVisible: false,
          headerStyle: { backgroundColor: colors.bg },
          headerTitleStyle: { color: colors.text },
          headerTintColor: colors.brand,
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        <Stack.Protected guard={isAuthenticated}>
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="settings" options={{ title: t('settings.title') }} />
          <Stack.Screen name="marker" options={{ title: t('marker.title') }} />
          <Stack.Screen name="capture" options={{ title: t('capture.title') }} />
          <Stack.Screen name="scan-context" options={{ title: t('context.title') }} />
          <Stack.Screen name="queue" options={{ title: t('queue.title') }} />
          <Stack.Screen name="scan/[id]/index" options={{ title: t('processing.title') }} />
          <Stack.Screen name="scan/[id]/findings" options={{ title: t('findings.title') }} />
          {/* A sheet, so the scan stays behind it — the verdicts being confirmed are the context. */}
          <Stack.Screen
            name="scan/[id]/confirm"
            options={{ title: t('confirm.title'), presentation: 'modal' }}
          />
        </Stack.Protected>

        <Stack.Protected guard={!isAuthenticated}>
          <Stack.Screen name="(auth)" options={{ headerShown: false }} />
        </Stack.Protected>
      </Stack>
    </ThemeProvider>
  );
}

export default function RootLayout() {
  return (
    <AppProviders>
      <RootNavigator />
    </AppProviders>
  );
}
