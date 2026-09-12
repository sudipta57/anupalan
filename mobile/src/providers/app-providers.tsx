/**
 * Everything the app needs wrapped around it, in one place.
 *
 * Order matters: safe-area and gesture handling are outermost because navigation depends on
 * them, and the error boundary sits inside the theme so a crash screen is still themed.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { useMemo, type ReactNode } from 'react';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { createQueryClient } from '@/api';
import { useClearCacheOnOrgChange } from '@/features/auth';
import { useLocale } from '@/i18n';
import { useColorScheme } from '@/theme';

import { ErrorBoundary } from './error-boundary';

export function AppProviders({ children }: { children: ReactNode }) {
  // One client for the life of the process. Recreating it would drop every cache on re-render.
  const queryClient = useMemo(() => createQueryClient(), []);
  const locale = useLocale();
  const scheme = useColorScheme();

  useClearCacheOnOrgChange(queryClient);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <ErrorBoundary locale={locale} scheme={scheme}>
            {children}
          </ErrorBoundary>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
