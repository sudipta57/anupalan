import { useSyncExternalStore } from 'react';
import { useColorScheme as useRNColorScheme } from 'react-native';

const subscribe = () => () => {};
const getSnapshot = () => true;
const getServerSnapshot = () => false;

/**
 * To support static rendering, this value needs to be re-calculated on the client side for web.
 *
 * Uses useSyncExternalStore rather than setState-in-an-effect: React takes the server snapshot
 * during hydration and the client snapshot after, which is the same result without the cascading
 * render that react-hooks/set-state-in-effect flags (the Expo template ships the effect version).
 */
export function useColorScheme() {
  const hasHydrated = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const colorScheme = useRNColorScheme();

  return hasHydrated ? colorScheme : 'light';
}
