/**
 * Design tokens for the Anupalan app.
 *
 * Two rules shape this palette, and both come from what the product is:
 *
 * 1. **Verdict colour is semantic and separate from the brand.** The brand is near-black; PASS is
 *    green. If the brand were green, a green chrome element would read as a passing verdict.
 *    Verdicts are the one thing in this app that must never be misread (CLAUDE.md §3.4), so they
 *    own their own hues and nothing else uses them.
 * 2. **Colour is never the only signal.** `VerdictBadge` pairs every colour with a distinct
 *    label, because a field officer may be colour-blind, in direct sunlight, or both.
 *
 * Brand and type scale follow the approved Stitch design system: IBM Plex Sans for text, JetBrains
 * Mono for rule ids, hashes and millimetre readings, and a near-black primary rather than a hue —
 * a deliberate reversal of Stage 0's platform-font, teal-brand defaults, accepted for closer visual
 * parity with the reference designs. The two Google Font families are bundled (not downloaded at
 * runtime) and gate the splash screen in `app/_layout.tsx`, so NFR-02's cold-start budget still
 * measures a real, fully-typeset first frame rather than a font swap happening after it.
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

  brand: '#000000',
  brandSoft: '#EBEBEC',

  // Matched to the approved Stitch palette. Contrast checked against its own soft ground: pass
  // 5.0:1, fail 6.9:1, borderline 6.5:1 — all clear of the 4.5:1 body-text floor.
  pass: '#15803D',
  passSoft: '#DCFCE7',
  fail: '#B91C1C',
  failSoft: '#FEE2E2',
  borderline: '#B45309',
  borderlineSoft: '#FEF3C7',
  notAssessable: '#5C6B73',
  notAssessableSoft: '#F1F5F9',

  warning: '#B45309',
  warningSoft: '#FEF3C7',
  info: '#1D4ED8',
  infoSoft: '#DBEAFE',

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
  // Brand inverts to near-white in dark mode — a near-black CTA would vanish against a near-black
  // background — with `onBrand` flipping to a dark ink to keep the button's own text readable.
  onBrand: '#101114',

  brand: '#F2F2F3',
  brandSoft: '#26272A',

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
  info: '#60A5FA',
  infoSoft: '#132A4A',

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
// Each Google Font weight ships as its own family name (there is no single "IBM Plex Sans" family
// with a variable weight axis here), so the weight lives entirely in `fontFamily` and `fontWeight`
// is omitted — setting both invites Android/iOS to synthesise a second, conflicting bold.
export const typography = {
  display: {
    fontSize: 28,
    lineHeight: 34,
    fontFamily: 'IBMPlexSans_700Bold',
    letterSpacing: -0.4,
  },
  title: { fontSize: 22, lineHeight: 28, fontFamily: 'IBMPlexSans_700Bold', letterSpacing: -0.3 },
  heading: { fontSize: 18, lineHeight: 24, fontFamily: 'IBMPlexSans_600SemiBold' },
  body: { fontSize: 16, lineHeight: 24, fontFamily: 'IBMPlexSans_400Regular' },
  bodyStrong: { fontSize: 16, lineHeight: 24, fontFamily: 'IBMPlexSans_600SemiBold' },
  label: { fontSize: 14, lineHeight: 20, fontFamily: 'IBMPlexSans_500Medium' },
  caption: {
    fontSize: 12,
    lineHeight: 16,
    fontFamily: 'IBMPlexSans_500Medium',
    letterSpacing: 0.2,
  },
  mono: {
    fontSize: 13,
    lineHeight: 18,
    fontFamily: 'JetBrainsMono_500Medium',
    letterSpacing: 0.3,
  },
} as const;

export type TypographyVariant = keyof typeof typography;

/** Minimum touch target. Field use means gloves, rain, and a phone held one-handed. */
export const HIT_SLOP = { top: 8, bottom: 8, left: 8, right: 8 } as const;
export const MIN_TOUCH_TARGET = 44;

export interface ElevationStyle {
  shadowColor: string;
  shadowOffset: { width: number; height: number };
  shadowOpacity: number;
  shadowRadius: number;
  elevation: number;
}

/**
 * Optional depth for surfaces that need to read as raised above the page (a hero card, the
 * findings label pane) rather than merely bordered. Every existing card stays flat-and-bordered
 * by default; `sm`/`md` are opt-in. Dark mode uses pure black at higher opacity, since a
 * light-toned shadow is invisible against the app's near-black background.
 */
export const elevations: Record<ColorScheme, { sm: ElevationStyle; md: ElevationStyle }> = {
  light: {
    sm: {
      shadowColor: '#10171A',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.08,
      shadowRadius: 3,
      elevation: 2,
    },
    md: {
      shadowColor: '#10171A',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.12,
      shadowRadius: 10,
      elevation: 6,
    },
  },
  dark: {
    sm: {
      shadowColor: '#000000',
      shadowOffset: { width: 0, height: 1 },
      shadowOpacity: 0.4,
      shadowRadius: 3,
      elevation: 2,
    },
    md: {
      shadowColor: '#000000',
      shadowOffset: { width: 0, height: 4 },
      shadowOpacity: 0.5,
      shadowRadius: 10,
      elevation: 6,
    },
  },
};
