/**
 * Step one of sign-in: the phone number.
 *
 * Validation happens here, before the request, because `normalisePhone` already knows what a
 * valid Indian mobile number looks like and a round trip to be told so is a round trip wasted on
 * a field connection.
 *
 * The dev-only fixture buttons exist because the whole app changes shape with the org's mode, and
 * checking both shells has to be quicker than typing a number from memory.
 */

import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError } from '@/api';
// Dev-only import, deleted at Stage 13 with the rest of the mock backend.
import { dev } from '@/api/dev';
import { Button, Card, Chip, Field, Screen, Text } from '@/components';
import { InvalidPhoneError, formatPhone, useRequestOtp } from '@/features/auth';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

export default function PhoneScreen() {
  const t = useT();
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const requestOtp = useRequestOtp();

  const submit = (value: string) => {
    setError(null);

    requestOtp.mutate(value, {
      onSuccess: ({ phone: normalised, requestId, expiresInSeconds }) => {
        router.push({
          pathname: '/otp',
          params: { phone: normalised, requestId, expiresInSeconds: String(expiresInSeconds) },
        });
      },
      onError: (cause) => {
        if (cause instanceof InvalidPhoneError) {
          setError(t('auth.phoneInvalid'));
          return;
        }
        setError(cause instanceof ApiError ? cause.message : t('errors.generic'));
      },
    });
  };

  return (
    <Screen scroll>
      <View style={styles.brand}>
        <Text variant="display">{t('common.appName')}</Text>
        <Text variant="body" tone="muted">
          {t('auth.phoneSubtitle')}
        </Text>
      </View>

      <Card>
        <Text variant="heading">{t('auth.phoneTitle')}</Text>

        <Field
          label={t('auth.phoneLabel')}
          hint={t('auth.phoneHint')}
          error={error ?? undefined}
          value={phone}
          onChangeText={(next) => {
            setPhone(next);
            if (error) setError(null);
          }}
          keyboardType="phone-pad"
          autoComplete="tel"
          textContentType="telephoneNumber"
          maxLength={16}
          returnKeyType="send"
          onSubmitEditing={() => submit(phone)}
          editable={!requestOtp.isPending}
        />

        <Button
          label={t('auth.sendCode')}
          size="lg"
          loading={requestOtp.isPending}
          onPress={() => submit(phone)}
        />
      </Card>

      {__DEV__ ? (
        <Card>
          <Text variant="heading">{t('auth.fixtureAccounts')}</Text>
          <Text variant="caption" tone="muted">
            {t('auth.fixtureHint')}
          </Text>
          <View style={styles.fixtures}>
            {(dev?.fixtureAccounts ?? []).map((account) => (
              <Chip
                key={account.mode}
                label={`${account.org.name} · ${formatPhone(account.phone)}`}
                tone="neutral"
                onPress={() => {
                  setPhone(account.phone);
                  submit(account.phone);
                }}
              />
            ))}
          </View>
        </Card>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  brand: { gap: spacing.xs, paddingTop: spacing.xl },
  fixtures: { gap: spacing.sm },
});
