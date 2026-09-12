/**
 * Themed text. Every string in the app renders through this, so type scale and colour stay in
 * the token system rather than being re-invented per screen.
 */

import { Text as RNText, type TextProps as RNTextProps, type TextStyle } from 'react-native';

import { useTheme, type TypographyVariant } from '@/theme';

export type TextTone =
  | 'default'
  | 'muted'
  | 'subtle'
  | 'brand'
  | 'onBrand'
  | 'pass'
  | 'fail'
  | 'borderline'
  | 'notAssessable';

export interface TextProps extends RNTextProps {
  variant?: TypographyVariant;
  tone?: TextTone;
}

export function Text({ variant = 'body', tone = 'default', style, ...rest }: TextProps) {
  const { colors, typography } = useTheme();

  const toneColors: Record<TextTone, string> = {
    default: colors.text,
    muted: colors.textMuted,
    subtle: colors.textSubtle,
    brand: colors.brand,
    onBrand: colors.onBrand,
    pass: colors.pass,
    fail: colors.fail,
    borderline: colors.borderline,
    notAssessable: colors.notAssessable,
  };

  const base = typography[variant] as TextStyle;

  return <RNText style={[base, { color: toneColors[tone] }, style]} {...rest} />;
}
