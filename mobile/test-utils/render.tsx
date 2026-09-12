/**
 * Render helper for component tests.
 *
 * Wraps the providers a screen needs — safe area with fixed metrics so layout is deterministic,
 * and a fresh QueryClient per test so cached data cannot leak between them.
 *
 * **`render` is async in React Native Testing Library 14**, and so is `unmount`. Await both, or
 * you get "`render` function has not been called" from a query that ran before the tree existed.
 * Query off the returned object rather than the `screen` singleton: tests that mount more than
 * one tree are then unambiguous about which one they are asserting on.
 */

import { QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderOptions, type RenderResult } from '@testing-library/react-native';
import type { ReactElement, ReactNode } from 'react';
import { SafeAreaProvider, type Metrics } from 'react-native-safe-area-context';

import { createQueryClient } from '@/api';

const METRICS: Metrics = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 24, left: 0, right: 0, bottom: 16 },
};

export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, 'wrapper'>
): Promise<RenderResult> {
  const queryClient = createQueryClient();

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <SafeAreaProvider initialMetrics={METRICS}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </SafeAreaProvider>
    );
  }

  return render(ui, { wrapper: Wrapper, ...options });
}

export { fireEvent, waitFor, act } from '@testing-library/react-native';
export type { RenderResult };
