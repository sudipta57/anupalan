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

// Each weight is imported from its own subpath rather than the package root: the root `index.js`
// unconditionally `require()`s all fourteen IBM Plex weights (and all ten JetBrains Mono weights,
// italics included) as one module, so importing even a single named export from it bundles every
// unused weight too — well over 2 MB of typefaces nobody asked for, directly against NFR-02's
// cold-start budget. The per-weight subpath only pulls in that one file.
import { IBMPlexSans_400Regular } from '@expo-google-fonts/ibm-plex-sans/400Regular';
import { IBMPlexSans_500Medium } from '@expo-google-fonts/ibm-plex-sans/500Medium';
import { IBMPlexSans_600SemiBold } from '@expo-google-fonts/ibm-plex-sans/600SemiBold';
import { IBMPlexSans_700Bold } from '@expo-google-fonts/ibm-plex-sans/700Bold';
import { JetBrainsMono_500Medium } from '@expo-google-fonts/jetbrains-mono/500Medium';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo } from 'react';

import { startQueue, stopQueue } from '@/features/queue';
import { markFirstFrame } from '@/lib/startup';
import { useT } from '@/i18n';
import { AppProviders } from '@/providers/app-providers';
import { useIsAuthenticated } from '@/store/session';
import { useTheme } from '@/theme';

export const unstable_settings = { initialRouteName: '(tabs)' };

// The native splash stays up until the type-scale fonts are ready, so nothing ever renders one
// frame in the system font and then reflows into IBM Plex Sans / JetBrains Mono a moment later.
void SplashScreen.preventAutoHideAsync();

function RootNavigator() {
  const { colors, scheme } = useTheme();
  const isAuthenticated = useIsAuthenticated();
  const t = useT();

  useEffect(() => {
    if (!isAuthenticated) return;

    startQueue();
    return stopQueue;
  }, [isAuthenticated]);

  /**
   * Mark the first interactive frame for the NFR-02 cold-start figure.
   *
   * In an effect on the root navigator, which runs after the first commit — the earliest point at
   * which something is actually on screen. `markFirstFrame` is idempotent, so a re-render or a
   * navigation back here cannot overwrite a cold-start number with a warm one.
   *
   * Deliberately not gated on `__DEV__`: the number is wanted from a release build on a real phone,
   * which is the only build whose timing means anything. It costs one subtraction.
   */
  useEffect(() => {
    markFirstFrame();
  }, []);

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
          <Stack.Screen name="scan/[id]/report" options={{ title: t('report.title') }} />
          <Stack.Screen name="scan/[id]/bis" options={{ title: t('bis.title') }} />
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
  const [fontsLoaded, fontError] = useFonts({
    IBMPlexSans_400Regular,
    IBMPlexSans_500Medium,
    IBMPlexSans_600SemiBold,
    IBMPlexSans_700Bold,
    JetBrainsMono_500Medium,
  });

  const ready = fontsLoaded || fontError != null;

  useEffect(() => {
    if (ready) void SplashScreen.hideAsync();
  }, [ready]);

  // A font load failure falls back to the platform font rather than stranding the app on the
  // splash screen forever — a missing typeface is a cosmetic loss, not a reason to block startup.
  if (!ready) return null;

  return (
    <AppProviders>
      <RootNavigator />
    </AppProviders>
  );
}
