/**
 * Button.
 *
 * `disabled` is a first-class state here rather than an afterthought, because FR-01's capture
 * shutter spends most of its life disabled and must still look deliberate.
 */

import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
  type PressableProps,
  type ViewStyle,
} from 'react-native';

import { MIN_TOUCH_TARGET, radius, spacing, useTheme } from '@/theme';

import { Text } from './text';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'md' | 'lg';

export interface ButtonProps extends Omit<PressableProps, 'style' | 'children'> {
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  style?: ViewStyle;
}

export function Button({
  label,
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  style,
  ...rest
}: ButtonProps) {
  const { colors, elevation } = useTheme();
  const isDisabled = disabled === true || loading;

  // Only the two "committing" actions float above the page; secondary/ghost stay flat so a
  // screen with several buttons doesn't turn into a pile of equally-important shadows.
  const fills: Record<ButtonVariant, ViewStyle> = {
    primary: { backgroundColor: colors.brand, ...elevation.sm },
    secondary: {
      backgroundColor: colors.surface,
      borderWidth: 1,
      borderColor: colors.borderStrong,
    },
    ghost: { backgroundColor: 'transparent' },
    danger: { backgroundColor: colors.fail, ...elevation.sm },
  };

  const labelTone = variant === 'primary' || variant === 'danger' ? 'onBrand' : 'brand';
  const spinnerColor =
    variant === 'primary' || variant === 'danger' ? colors.onBrand : colors.brand;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      accessibilityLabel={label}
      disabled={isDisabled}
      style={({ pressed }) => [
        styles.base,
        size === 'lg' && styles.lg,
        fills[variant],
        pressed && !isDisabled ? styles.pressed : null,
        isDisabled ? styles.disabled : null,
        style,
      ]}
      {...rest}
    >
      <View style={styles.inner}>
        {loading ? <ActivityIndicator size="small" color={spinnerColor} /> : null}
        <Text
          variant="bodyStrong"
          tone={variant === 'danger' ? 'onBrand' : labelTone}
          style={styles.label}
        >
          {label}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: MIN_TOUCH_TARGET,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: { fontFamily: 'IBMPlexSans_700Bold' },
  lg: { minHeight: 56, paddingHorizontal: spacing.xl },
  inner: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.45, shadowOpacity: 0, elevation: 0 },
});
