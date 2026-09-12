/**
 * Tab shell, composed from the org's mode.
 *
 * | Mode | Tabs |
 * |---|---|
 * | A — enforcement | Scan · Inspections · Sahayak |
 * | B — industry | Scan · Bulk · History · Sahayak |
 *
 * Mode is an org-level attribute read off the session (docs/01-architecture.md §3), so this is one
 * APK serving an inspector and a brand analyst, not two builds.
 *
 * **`Tabs.Protected`, not a hidden tab button.** A guarded-off route is removed from the navigator
 * entirely, so `/bulk` typed into a deep link by an enforcement user resolves to not-found rather
 * than rendering the other mode's screen with no way back to it. Hiding the button would leave the
 * route reachable and the screen fetching data its org has no reason to see.
 *
 * Settings is not a tab — it is a root stack route behind the header gear. See
 * `src/features/navigation/tabs.ts` for why.
 */

import { Tabs, router } from 'expo-router';
import { Pressable, StyleSheet, type ColorValue } from 'react-native';

import {
  BulkIcon,
  HistoryIcon,
  InspectionsIcon,
  SahayakIcon,
  ScanIcon,
  SettingsIcon,
} from '@/components';
import { isTabVisible } from '@/features/navigation';
import { useT } from '@/i18n';
import { useOrgMode } from '@/store/session';
import { MIN_TOUCH_TARGET, spacing, useTheme } from '@/theme';

interface TabIconProps {
  color: ColorValue;
  size: number;
}

// Declared at module scope with real names: an inline arrow here is an anonymous component,
// which React DevTools shows as "Unknown" and eslint rejects outright.
function ScanTabIcon({ color, size }: TabIconProps) {
  return <ScanIcon color={color} size={size} />;
}

function InspectionsTabIcon({ color, size }: TabIconProps) {
  return <InspectionsIcon color={color} size={size} />;
}

function BulkTabIcon({ color, size }: TabIconProps) {
  return <BulkIcon color={color} size={size} />;
}

function HistoryTabIcon({ color, size }: TabIconProps) {
  return <HistoryIcon color={color} size={size} />;
}

function SahayakTabIcon({ color, size }: TabIconProps) {
  return <SahayakIcon color={color} size={size} />;
}

/** Settings lives off the tab bar, so every tab carries the way to it. */
function SettingsHeaderButton() {
  const { colors } = useTheme();
  const t = useT();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={t('settings.title')}
      onPress={() => router.push('/settings')}
      style={({ pressed }) => [styles.headerButton, pressed ? styles.pressed : null]}
    >
      <SettingsIcon color={colors.textMuted} size={22} />
    </Pressable>
  );
}

function renderSettingsButton() {
  return <SettingsHeaderButton />;
}

export default function TabLayout() {
  const { colors } = useTheme();
  const t = useT();
  const mode = useOrgMode();

  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: colors.brand,
        tabBarInactiveTintColor: colors.textSubtle,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
        headerStyle: { backgroundColor: colors.bg },
        headerTitleStyle: { color: colors.text },
        headerShadowVisible: false,
        // Rendered as an element, not passed as the component: React Navigation calls
        // `headerRight` during the header's own render, and this one uses hooks.
        headerRight: renderSettingsButton,
        sceneStyle: { backgroundColor: colors.bg },
      }}
    >
      {/* Scan is in both modes, and is the one tab that must always exist. */}
      <Tabs.Screen name="index" options={{ title: t('tabs.scan'), tabBarIcon: ScanTabIcon }} />

      <Tabs.Protected guard={isTabVisible('inspections', mode)}>
        <Tabs.Screen
          name="inspections"
          options={{ title: t('tabs.inspections'), tabBarIcon: InspectionsTabIcon }}
        />
      </Tabs.Protected>

      <Tabs.Protected guard={isTabVisible('bulk', mode)}>
        <Tabs.Screen name="bulk" options={{ title: t('tabs.bulk'), tabBarIcon: BulkTabIcon }} />
      </Tabs.Protected>

      <Tabs.Protected guard={isTabVisible('history', mode)}>
        <Tabs.Screen
          name="history"
          options={{ title: t('tabs.history'), tabBarIcon: HistoryTabIcon }}
        />
      </Tabs.Protected>

      <Tabs.Screen
        name="sahayak"
        options={{ title: t('tabs.sahayak'), tabBarIcon: SahayakTabIcon }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  headerButton: {
    minWidth: MIN_TOUCH_TARGET,
    minHeight: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.xs,
  },
  pressed: { opacity: 0.6 },
});
