/**
 * Tab and UI icons, drawn with react-native-svg.
 *
 * Hand-drawn rather than pulled from an icon set: the scan icon is a viewfinder framing a
 * marker square, which is literally what this app asks the user to do. A generic camera glyph
 * would say less.
 */

import type { ColorValue } from 'react-native';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

export interface IconProps {
  /** ColorValue rather than string: React Navigation hands tabBarIcon a ColorValue. */
  color: ColorValue;
  size?: number;
}

const STROKE = 1.75;

export function ScanIcon({ color, size = 24 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M4 9V6.5A2.5 2.5 0 0 1 6.5 4H9M15 4h2.5A2.5 2.5 0 0 1 20 6.5V9M20 15v2.5a2.5 2.5 0 0 1-2.5 2.5H15M9 20H6.5A2.5 2.5 0 0 1 4 17.5V15"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
      />
      <Rect x="9" y="9" width="6" height="6" rx="1" stroke={color} strokeWidth={STROKE} />
    </Svg>
  );
}

export function HistoryIcon({ color, size = 24 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Circle cx="12" cy="12" r="8.25" stroke={color} strokeWidth={STROKE} />
      <Path
        d="M12 7.25V12l3 1.75"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

export function SahayakIcon({ color, size = 24 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M4.75 6.5A1.75 1.75 0 0 1 6.5 4.75h11a1.75 1.75 0 0 1 1.75 1.75v7a1.75 1.75 0 0 1-1.75 1.75H9.5l-4.75 3.5V6.5Z"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinejoin="round"
      />
    </Svg>
  );
}

export function SettingsIcon({ color, size = 24 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M4 8h8M17 8h3M4 16h4M13 16h7"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
      />
      <Circle cx="14.5" cy="8" r="2.25" stroke={color} strokeWidth={STROKE} />
      <Circle cx="10.5" cy="16" r="2.25" stroke={color} strokeWidth={STROKE} />
    </Svg>
  );
}

/** Mode A. A clipboard with a tick: a recorded inspection, not a generic list. */
export function InspectionsIcon({ color, size = 24 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M9 4.75h6M8.25 6.25H6.5A1.75 1.75 0 0 0 4.75 8v10.25A1.75 1.75 0 0 0 6.5 20h11a1.75 1.75 0 0 0 1.75-1.75V8a1.75 1.75 0 0 0-1.75-1.75h-1.75"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Rect x="9" y="3.25" width="6" height="3" rx="1" stroke={color} strokeWidth={STROKE} />
      <Path
        d="M8.75 13.25l2 2 4.5-4.5"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

/** Mode B. Stacked rows: many listings checked in one pass (FR-10). */
export function BulkIcon({ color, size = 24 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Rect
        x="3.75"
        y="4.75"
        width="16.5"
        height="4.5"
        rx="1.25"
        stroke={color}
        strokeWidth={STROKE}
      />
      <Rect
        x="3.75"
        y="11.75"
        width="16.5"
        height="4.5"
        rx="1.25"
        stroke={color}
        strokeWidth={STROKE}
      />
      <Path d="M6.75 19.25h10.5" stroke={color} strokeWidth={STROKE} strokeLinecap="round" />
    </Svg>
  );
}

export function AlertIcon({ color, size = 20 }: IconProps) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Circle cx="12" cy="12" r="8.5" stroke={color} strokeWidth={STROKE} />
      <Path d="M12 7.75v4.75" stroke={color} strokeWidth={STROKE} strokeLinecap="round" />
      <Circle cx="12" cy="16" r="1" fill={color} />
    </Svg>
  );
}
