/**
 * Fallback for an unmatched route. Reachable from a bad deep link.
 *
 * Deliberately outside both `Stack.Protected` blocks in the root layout, so it is always mountable
 * — which means the way out has to account for being signed out. `/` is inside the tab shell and
 * does not exist until there is a session, so offering it unconditionally would send a signed-out
 * user from one dead route to another.
 */

import { Link, Stack } from 'expo-router';

import { EmptyState, Screen, Text } from '@/components';
import { useT } from '@/i18n';
import { useIsAuthenticated } from '@/store/session';

export default function NotFoundScreen() {
  const t = useT();
  const isAuthenticated = useIsAuthenticated();

  return (
    <>
      <Stack.Screen options={{ title: t('errors.notFound') }} />
      <Screen>
        <EmptyState
          title={t('errors.notFound')}
          body={t('errors.notFoundBody')}
          action={
            <Link href={isAuthenticated ? '/' : '/phone'}>
              <Text variant="bodyStrong" tone="brand">
                {isAuthenticated ? t('errors.goHome') : t('errors.goSignIn')}
              </Text>
            </Link>
          }
        />
      </Screen>
    </>
  );
}
