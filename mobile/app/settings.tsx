/**
 * Settings — account, language, appearance.
 *
 * A root stack route rather than a tab: Mode B already fills four tabs and five is where an
 * Android tab bar starts truncating labels. Reached from the header gear on every tab.
 *
 * Language is here from Stage 0 rather than bolted on later: NFR-08 requires Hindi and English,
 * and a switch that works from the first screen is what keeps every later screen honest about
 * going through `t()`.
 */

import { router } from 'expo-router';
import { useSyncExternalStore } from 'react';
import { StyleSheet, View } from 'react-native';
import Constants from 'expo-constants';

import { API_MODE } from '@/api';
// Dev-only imports. This whole section, and these imports, are deleted at Stage 13 along with the
// rest of the mock backend.
import { FIXTURE_ACCOUNTS, FIXTURE_OTP, HERO_SCAN_ID } from '@/api/mock';
import {
  SCENARIOS,
  SCENARIO_LABELS,
  getScenario,
  setScenario,
  subscribeToScenario,
  type Scenario,
} from '@/api/mock/scenario';
import {
  Button,
  Card,
  Chip,
  Screen,
  SegmentedControl,
  Text,
  type SegmentedOption,
} from '@/components';
import { useRequestOtp, useSignOut, useVerifyOtp } from '@/features/auth';
import { useT, type Locale } from '@/i18n';
import {
  GATE_SIMULATIONS,
  GATE_SIMULATION_LABELS,
  getGateSimulation,
  setGateSimulation,
  subscribeToGateSimulation,
  type GateSimulation,
} from '@/features/capture';
import { useMarkerStore } from '@/store/marker';
import { usePreferences, type ThemePreference } from '@/store/preferences';
import { useCurrentOrg, useCurrentUser } from '@/store/session';
import { spacing } from '@/theme';

/** Who is signed in, what they can do, and the way out. */
function AccountCard() {
  const t = useT();
  const user = useCurrentUser();
  const org = useCurrentOrg();
  const signOut = useSignOut();

  if (!user || !org) return null;

  const isEnforcement = org.mode === 'enforcement';

  return (
    <Card>
      <Text variant="heading">{t('account.title')}</Text>

      <View style={styles.rows}>
        <View style={styles.row}>
          <Text variant="label" tone="muted">
            {t('account.signedInAs')}
          </Text>
          <Text variant="bodyStrong">{user.name}</Text>
        </View>

        <View style={styles.row}>
          <Text variant="label" tone="muted">
            {t('account.organisation')}
          </Text>
          <Text variant="body">
            {org.name} · {org.state}
          </Text>
        </View>

        <View style={styles.row}>
          <Text variant="label" tone="muted">
            {t('account.role')}
          </Text>
          <Text variant="body">{t(`roles.${user.role}`)}</Text>
        </View>

        <View style={styles.row}>
          <Text variant="label" tone="muted">
            {t('account.mode')}
          </Text>
          <Text variant="body">
            {isEnforcement ? t('account.modeEnforcement') : t('account.modeIndustry')}
          </Text>
          <Text variant="caption" tone="subtle">
            {isEnforcement ? t('account.modeEnforcementBody') : t('account.modeIndustryBody')}
          </Text>
        </View>
      </View>

      <Button label={t('account.signOut')} variant="secondary" onPress={signOut} />
    </Card>
  );
}

/**
 * Switch between the fixture accounts, one per org mode.
 *
 * Runs the **real** OTP request and verify, rather than writing a session into the store directly.
 * The point of the switch is to demonstrate that one build serves both shells; a back door into
 * the store would demonstrate something else, and would stop exercising the path that ships.
 */
function FixtureAccountPanel() {
  const org = useCurrentOrg();
  const requestOtp = useRequestOtp();
  const verifyOtp = useVerifyOtp();
  const busy = requestOtp.isPending || verifyOtp.isPending;

  const switchTo = (phone: string) => {
    requestOtp.mutate(phone, {
      onSuccess: ({ requestId }) => verifyOtp.mutate({ requestId, code: FIXTURE_OTP }),
    });
  };

  return (
    <Card>
      <Text variant="heading">Fixture accounts</Text>
      <Text variant="caption" tone="muted">
        Dev only. Signs in as the other mode so the tab bar can be compared from one build.
      </Text>
      <View style={styles.chips}>
        {FIXTURE_ACCOUNTS.map((account) => (
          <Chip
            key={account.mode}
            label={account.org.name}
            tone={account.org.id === org?.id ? 'brand' : 'neutral'}
            selected={account.org.id === org?.id}
            disabled={busy}
            onPress={() => switchTo(account.phone)}
          />
        ))}
      </View>
    </Card>
  );
}

/**
 * The scale reference is a device setting, so it is reachable from where device settings live —
 * not only from the Scan screen that blocks on it.
 */
function MarkerCard() {
  const t = useT();
  const reference = useMarkerStore((s) => s.reference);

  const name =
    reference?.type === 'aruco_40mm'
      ? t('marker.arucoName')
      : reference?.type === 'id1_card'
        ? t('marker.id1Name')
        : t('marker.userName');

  return (
    <Card>
      <Text variant="heading">{t('marker.title')}</Text>
      <Text variant="body" tone={reference ? 'muted' : 'fail'}>
        {reference ? `${name} · ${reference.mm} mm` : t('marker.notSet')}
      </Text>
      <Button
        label={reference ? t('marker.change') : t('marker.setUp')}
        variant="secondary"
        onPress={() => router.push('/marker')}
      />
    </Card>
  );
}

/**
 * Choose what the simulated frame processor is pretending to see.
 *
 * Each capture gate has its own instruction, and an instruction nobody can trigger is an
 * instruction nobody has read. Deleted when the native ArUco plugin lands.
 */
function GateSimulationPanel() {
  const t = useT();
  const mode = useSyncExternalStore(
    subscribeToGateSimulation,
    getGateSimulation,
    getGateSimulation
  );

  return (
    <Card>
      <Text variant="heading">{t('capture.simulated')}</Text>
      <Text variant="caption" tone="muted">
        {t('capture.simulatedBody')}
      </Text>
      <View style={styles.chips}>
        {GATE_SIMULATIONS.map((value: GateSimulation) => (
          <Chip
            key={value}
            label={GATE_SIMULATION_LABELS[value]}
            tone={value === mode ? 'brand' : 'neutral'}
            selected={value === mode}
            onPress={() => setGateSimulation(value)}
          />
        ))}
      </View>
    </Card>
  );
}

/**
 * Force the mock backend into one of its failure modes.
 *
 * The degradation paths are acceptance criteria, so they need to be reachable without editing
 * code — otherwise they get built once, demoed never, and broken silently.
 */
function MockScenarioPanel() {
  const scenario = useSyncExternalStore(subscribeToScenario, getScenario, getScenario);

  return (
    <Card>
      <Text variant="heading">Mock backend</Text>
      <Text variant="caption" tone="muted">
        Dev only. Forces the failure modes from the architecture&apos;s degradation table.
      </Text>
      <View style={styles.chips}>
        {SCENARIOS.map((value: Scenario) => (
          <Chip
            key={value}
            label={SCENARIO_LABELS[value]}
            tone={value === scenario ? 'brand' : 'neutral'}
            selected={value === scenario}
            onPress={() => setScenario(value)}
          />
        ))}
      </View>
    </Card>
  );
}

/**
 * A way into the sample inspection without photographing anything.
 *
 * The findings viewer is otherwise only reachable by completing a whole scan, which makes it slow to
 * check and impossible to check at all until the camera path works. This scan is also the only
 * fixture with a report issued over it, so it is the one that shows Mode A's editing lock.
 */
function SampleInspectionPanel() {
  return (
    <Card>
      <Text variant="heading">Sample inspection</Text>
      <Text variant="caption" tone="muted">
        Dev only. The hero fixture, complete, with a report already issued over it.
      </Text>
      <Button
        label="Open sample findings"
        variant="secondary"
        onPress={() => router.push(`/scan/${HERO_SCAN_ID}/findings`)}
      />
    </Card>
  );
}

export default function SettingsScreen() {
  const t = useT();
  const locale = usePreferences((s) => s.locale);
  const setLocale = usePreferences((s) => s.setLocale);
  const themePreference = usePreferences((s) => s.themePreference);
  const setThemePreference = usePreferences((s) => s.setThemePreference);

  const localeOptions: SegmentedOption<Locale>[] = [
    { value: 'en', label: t('settings.languageEnglish') },
    { value: 'hi', label: t('settings.languageHindi') },
  ];

  const themeOptions: SegmentedOption<ThemePreference>[] = [
    { value: 'system', label: t('settings.appearanceSystem') },
    { value: 'light', label: t('settings.appearanceLight') },
    { value: 'dark', label: t('settings.appearanceDark') },
  ];

  const version = Constants.expoConfig?.version ?? '0.0.0';

  return (
    <Screen scroll>
      <AccountCard />

      <MarkerCard />

      <Card>
        <Text variant="heading">{t('settings.language')}</Text>
        <SegmentedControl
          options={localeOptions}
          value={locale}
          onChange={setLocale}
          accessibilityLabel={t('settings.language')}
        />
      </Card>

      <Card>
        <Text variant="heading">{t('settings.appearance')}</Text>
        <SegmentedControl
          options={themeOptions}
          value={themePreference}
          onChange={setThemePreference}
          accessibilityLabel={t('settings.appearance')}
        />
      </Card>

      {__DEV__ ? <GateSimulationPanel /> : null}
      {__DEV__ ? <FixtureAccountPanel /> : null}
      {__DEV__ ? <MockScenarioPanel /> : null}
      {__DEV__ ? <SampleInspectionPanel /> : null}

      <View style={styles.about}>
        <Text variant="label" tone="muted">
          {t('settings.about')}
        </Text>
        <Text variant="mono" tone="subtle">
          {t('settings.version', { version })}
        </Text>
        <Text variant="mono" tone="subtle">
          API mode: {API_MODE}
        </Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  about: { gap: spacing.xs, paddingHorizontal: spacing.xs },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  row: { gap: spacing.xs },
  rows: { gap: spacing.md },
});
