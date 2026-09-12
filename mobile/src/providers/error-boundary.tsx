/**
 * Root error boundary.
 *
 * A crash in a field inspection is worse than a bug — the officer is standing in a shop with a
 * pack in their hand. This catches the render error, keeps the app alive, and offers a retry
 * rather than dropping the user on a white screen.
 *
 * Class component because React exposes no hook equivalent of componentDidCatch.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button, Text } from '@/components';
import { translate, type Locale } from '@/i18n';
import { palettes, spacing } from '@/theme';

interface Props {
  children: ReactNode;
  locale: Locale;
  scheme: 'light' | 'dark';
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Replaced by real crash reporting at P5. Logged for now so a device build is debuggable.
    console.error('[anupalan] unhandled render error', error, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    const { children, locale, scheme } = this.props;

    if (!error) return children;

    // Tokens are read directly: the boundary must render even if a theme hook is what broke.
    const colors = palettes[scheme];

    return (
      <View style={[styles.wrap, { backgroundColor: colors.bg }]}>
        <Text variant="title">{translate(locale, 'errors.title')}</Text>
        <Text variant="body" tone="muted" style={styles.centered}>
          {translate(locale, 'errors.generic')}
        </Text>
        <Button label={translate(locale, 'common.retry')} onPress={this.reset} />
      </View>
    );
  }
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
    padding: spacing.xl,
  },
  centered: { textAlign: 'center' },
});
