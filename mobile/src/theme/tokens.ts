/**
 * Design tokens for the Anupalan app.
 *
 * Two rules shape this palette, and both come from what the product is:
 *
 * 1. **Verdict colour is semantic and separate from the brand.** The brand is a deep teal-blue;
 *    PASS is green. If the brand were green, a green chrome element would read as a passing
 *    verdict. Verdicts are the one thing in this app that must never be misread
 *    (CLAUDE.md §3.4), so they own their own hues and nothing else uses them.
 * 2. **Colour is never the only signal.** `VerdictBadge` pairs every colour with a distinct
 *    label, because a field officer may be colour-blind, in direct sunlight, or both.
 *
 * Fonts are the platform's own (Roboto on Android). No webfont is loaded: NFR-02 gives the app
 * a 3-second cold-start budget on a 4 GB device, and a font download is a poor way to spend it.
 */

export type ColorScheme = 'light' | 'dark';

export interface Palette {
  /** App background, behind everything. */
  bg: string;
  /** Raised surfaces: cards, sheets, the tab bar. */
  surface: string;
  /** Recessed or secondary fills inside a surface. */
  surfaceAlt: string;
  /** Hairlines and dividers. */
  border: string;
  /** Borders that need to read as an edge, e.g. an input at rest. */
  borderStrong: string;

  text: string;
  textMuted: string;
  textSubtle: string;
  /** Text and icons drawn on top of `brand`. */
  onBrand: string;

  brand: string;
  brandSoft: string;

  pass: string;
  passSoft: string;
  fail: string;
  failSoft: string;
  borderline: string;
  borderlineSoft: string;
  notAssessable: string;
  notAssessableSoft: string;

  /** Non-verdict status colours, for things that are not rule outcomes. */
  warning: string;
  warningSoft: string;
  info: string;
  infoSoft: string;

  /** Scrims and pressed states. */
  overlay: string;
}

const light: Palette = {
  bg: '#F6F8F9',
  surface: '#FFFFFF',
  surfaceAlt: '#EDF1F3',
  border: '#DCE2E6',
  borderStrong: '#BAC4CA',

  text: '#10171A',
  textMuted: '#54626A',
  // Darkened from #7C8891 at the Stage 13 accessibility pass. `textSubtle` carries captions, which
  // are 12 px and therefore *normal* text under WCAG — 4.5:1, not the 3:1 large-text allowance. The
  // old value measured 3.19:1 on `surfaceAlt`, which is the ground most captions sit on.
  textSubtle: '#636D75',
  onBrand: '#FFFFFF',

  brand: '#0B5F73',
  brandSoft: '#E0EDF1',

  // Darkened from #1B7F4B at the Stage 13 accessibility pass: 4.36:1 on `passSoft`, just under the
  // threshold. The verdict badges draw their own colour on their own soft ground, so this pair is
  // read on every findings screen.
  pass: '#1A7A48',
  passSoft: '#E2F3EA',
  fail: '#B3261E',
  failSoft: '#FBE7E5',
  borderline: '#8A6100',
  borderlineSoft: '#FAEFD9',
  notAssessable: '#5C6B73',
  notAssessableSoft: '#EAEEF0',

  warning: '#8A6100',
  warningSoft: '#FAEFD9',
  info: '#0B5F73',
  infoSoft: '#E0EDF1',

  overlay: 'rgba(16, 23, 26, 0.45)',
};

const dark: Palette = {
  bg: '#0E1315',
  surface: '#171D20',
  surfaceAlt: '#212A2E',
  border: '#2A3438',
  borderStrong: '#3D4A50',

  text: '#E6ECEE',
  textMuted: '#9FADB4',
  // Lightened from #7C8891, which measured 4.03:1 on `surfaceAlt`. The two themes no longer share a
  // subtle grey, which is correct — the same colour cannot sit 4.5:1 from both a near-white and a
  // near-black ground.
  textSubtle: '#87929A',
  onBrand: '#052029',

  brand: '#4BC5DA',
  brandSoft: '#10333C',

  pass: '#5CC98A',
  passSoft: '#123021',
  fail: '#F2897E',
  failSoft: '#3A1714',
  borderline: '#DBA92E',
  borderlineSoft: '#332711',
  notAssessable: '#94A2AA',
  notAssessableSoft: '#232B2F',

  warning: '#DBA92E',
  warningSoft: '#332711',
  info: '#4BC5DA',
  infoSoft: '#10333C',

  overlay: 'rgba(0, 0, 0, 0.6)',
};

export const palettes: Record<ColorScheme, Palette> = { light, dark };

/** 4pt base. Named by size, not by use, so a component cannot claim to own a value. */
export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export const radius = {
  sm: 4,
  md: 8,
  lg: 12,
  pill: 999,
} as const;

/**
 * Type scale. `mono` exists for rule ids (`LM-9-2-TABLE1`), millimetre readings and hashes —
 * anything where digits must line up or a character must not be misread.
 */
export const typography = {
  display: { fontSize: 28, lineHeight: 34, fontWeight: '700' },
  title: { fontSize: 22, lineHeight: 28, fontWeight: '700' },
  heading: { fontSize: 18, lineHeight: 24, fontWeight: '600' },
  body: { fontSize: 16, lineHeight: 24, fontWeight: '400' },
  bodyStrong: { fontSize: 16, lineHeight: 24, fontWeight: '600' },
  label: { fontSize: 14, lineHeight: 20, fontWeight: '500' },
  caption: { fontSize: 12, lineHeight: 16, fontWeight: '500' },
  mono: { fontSize: 13, lineHeight: 18, fontWeight: '500', fontFamily: 'monospace' },
} as const;

export type TypographyVariant = keyof typeof typography;

/** Minimum touch target. Field use means gloves, rain, and a phone held one-handed. */
export const HIT_SLOP = { top: 8, bottom: 8, left: 8, right: 8 } as const;
export const MIN_TOUCH_TARGET = 44;
