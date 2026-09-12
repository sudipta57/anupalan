/**
 * Step two of sign-in: the code.
 *
 * On success the session lands in the store, `isAuthenticated` flips, and the root layout's
 * `Stack.Protected` swaps the auth stack for the app. **There is no `router.replace` here** — this
 * screen does not navigate anywhere. The guard owns that, which is what stops a half-navigated
 * state where the session exists but the user is still looking at a sign-in form.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError } from '@/api';
import { dev } from '@/api/dev';
import { Button, Card, Field, Screen, Text } from '@/components';
import { OTP_LENGTH, formatPhone, isCompleteOtp, useVerifyOtp } from '@/features/auth';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

export default function OtpScreen() {
  const t = useT();
  const { phone, requestId, expiresInSeconds } = useLocalSearchParams<{
    phone: string;
    requestId: string;
    expiresInSeconds: string;
  }>();

  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const verifyOtp = useVerifyOtp();

  const submit = () => {
    if (!isCompleteOtp(code)) {
      setError(t('auth.otpInvalid'));
      return;
    }

    setError(null);
    verifyOtp.mutate(
      { requestId, code },
      {
        onError: (cause) => {
          setError(cause instanceof ApiError ? cause.message : t('errors.generic'));
        },
      }
    );
  };

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="display">{t('auth.otpTitle')}</Text>
        <Text variant="body" tone="muted">
          {t('auth.otpSubtitle', {
            phone: formatPhone(phone),
            seconds: expiresInSeconds,
          })}
        </Text>
      </View>

      <Card>
        <Field
          label={t('auth.otpLabel')}
          error={error ?? undefined}
          value={code}
          onChangeText={(next) => {
            // Strip anything that is not a digit so a pasted "123 456" still verifies.
            setCode(next.replace(/\D/g, '').slice(0, OTP_LENGTH));
            if (error) setError(null);
          }}
          keyboardType="number-pad"
          autoComplete="sms-otp"
          textContentType="oneTimeCode"
          maxLength={OTP_LENGTH}
          autoFocus
          returnKeyType="done"
          onSubmitEditing={submit}
          editable={!verifyOtp.isPending}
        />

        <Button label={t('auth.verify')} size="lg" loading={verifyOtp.isPending} onPress={submit} />

        {__DEV__ ? (
          <Text variant="caption" tone="subtle">
            Mock backend: the code is {dev?.fixtureOtp}.
          </Text>
        ) : null}
      </Card>

      <Button label={t('auth.changeNumber')} variant="ghost" onPress={() => router.back()} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.xs, paddingTop: spacing.lg },
});
