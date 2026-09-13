/**
 * Theme access for components.
 *
 * The colour scheme follows the device by default, but the user can pin light or dark from
 * Settings — an inspector working outdoors often wants light locked on regardless of the time
 * of day. The preference lives in the preferences store; this module only resolves it.
 */

import { useMemo } from 'react';
import { useColorScheme as useDeviceColorScheme } from 'react-native';

import { usePreferences } from '@/store/preferences';

import {
  elevations,
  HIT_SLOP,
  MIN_TOUCH_TARGET,
  palettes,
  radius,
  spacing,
  typography,
} from './tokens';
import type { ColorScheme, ElevationStyle, Palette, TypographyVariant } from './tokens';

export { spacing, radius, typography, palettes, elevations, HIT_SLOP, MIN_TOUCH_TARGET };
export type { ColorScheme, ElevationStyle, Palette, TypographyVariant };

export interface Theme {
  scheme: ColorScheme;
  colors: Palette;
  spacing: typeof spacing;
  radius: typeof radius;
  typography: typeof typography;
  elevation: (typeof elevations)[ColorScheme];
}

/** Resolve the active scheme from the user's preference, falling back to the device. */
export function useColorScheme(): ColorScheme {
  const preference = usePreferences((s) => s.themePreference);
  const device = useDeviceColorScheme();

  if (preference === 'light' || preference === 'dark') {
    return preference;
  }
  return device === 'dark' ? 'dark' : 'light';
}

export function useTheme(): Theme {
  const scheme = useColorScheme();

  return useMemo(
    () => ({
      scheme,
      colors: palettes[scheme],
      spacing,
      radius,
      typography,
      elevation: elevations[scheme],
    }),
    [scheme]
  );
}

/** Shorthand for the common case of needing only colours. */
export function useColors(): Palette {
  return useTheme().colors;
}
