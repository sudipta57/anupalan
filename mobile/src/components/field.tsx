/**
 * Labelled text input.
 *
 * The error message sits under the field and is wired to the input's accessibility state, so a
 * screen reader announces "invalid" rather than the user discovering it on submit. FR-03's
 * context form leans on this heavily.
 */

import { useId } from 'react';
import { StyleSheet, TextInput, View, type TextInputProps } from 'react-native';

import { MIN_TOUCH_TARGET, radius, spacing, useTheme } from '@/theme';

import { Text } from './text';

export interface FieldProps extends Omit<TextInputProps, 'style'> {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
}

export function Field({ label, hint, error, required = false, ...inputProps }: FieldProps) {
  const { colors, typography } = useTheme();
  const id = useId();
  const invalid = Boolean(error);

  return (
    <View style={styles.wrap}>
      <Text variant="label" nativeID={`${id}-label`}>
        {label}
        {required ? (
          <Text variant="label" tone="fail">
            {' '}
            *
          </Text>
        ) : null}
      </Text>

      <TextInput
        accessibilityLabelledBy={`${id}-label`}
        accessibilityState={{ disabled: inputProps.editable === false }}
        placeholderTextColor={colors.textSubtle}
        style={[
          styles.input,
          typography.body,
          {
            backgroundColor: colors.surface,
            borderColor: invalid ? colors.fail : colors.borderStrong,
            color: colors.text,
          },
        ]}
        {...inputProps}
      />

      {error ? (
        <Text variant="caption" tone="fail">
          {error}
        </Text>
      ) : hint ? (
        <Text variant="caption" tone="subtle">
          {hint}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.xs },
  input: {
    minHeight: MIN_TOUCH_TARGET,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
});
