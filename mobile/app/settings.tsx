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
// The dev bridge, not the mock itself. `dev` is null in any build that should not carry fixtures,
// which is what keeps them out of the production bundle — see `src/api/dev.ts`. This whole section
// and this import are deleted with the mock folder at the real cutover.
import { dev, type Scenario } from '@/api/dev';
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
import { COLD_START_BUDGET_MS, startupMeasurement, withinBudget } from '@/lib/startup';
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
            {/* The state is only shown when the server published one — a dangling separator reads
                like a value that failed to load. */}
            {org.state ? `${org.name} · ${org.state}` : org.name}
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

  if (!dev) return null;
  const bridge = dev;

  const switchTo = (phone: string) => {
    requestOtp.mutate(phone, {
      onSuccess: ({ requestId }) => verifyOtp.mutate({ requestId, code: bridge.fixtureOtp }),
    });
  };

  return (
    <Card>
      <Text variant="heading">Fixture accounts</Text>
      <Text variant="caption" tone="muted">
        Dev only. Signs in as the other mode so the tab bar can be compared from one build.
      </Text>
      <View style={styles.chips}>
        {bridge.fixtureAccounts.map((account) => (
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
  // Subscribed unconditionally so the hook order is stable; the no-op standins are only reached in a
  // build with no dev bridge, where the panel renders nothing anyway.
  const scenario = useSyncExternalStore(
    dev?.subscribeToScenario ?? (() => () => undefined),
    dev?.getScenario ?? (() => 'happy' as Scenario),
    dev?.getScenario ?? (() => 'happy' as Scenario)
  );

  if (!dev) return null;
  const bridge = dev;

  return (
    <Card>
      <Text variant="heading">Mock backend</Text>
      <Text variant="caption" tone="muted">
        Dev only. Forces the failure modes from the architecture&apos;s degradation table.
      </Text>
      <View style={styles.chips}>
        {bridge.scenarios.map((value: Scenario) => (
          <Chip
            key={value}
            label={bridge.scenarioLabels[value]}
            tone={value === scenario ? 'brand' : 'neutral'}
            selected={value === scenario}
            onPress={() => bridge.setScenario(value)}
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
  if (!dev) return null;
  const heroScanId = dev.heroScanId;

  return (
    <Card>
      <Text variant="heading">Sample inspection</Text>
      <Text variant="caption" tone="muted">
        Dev only. The hero fixture, complete, with a report already issued over it.
      </Text>
      <Button
        label="Open sample findings"
        variant="secondary"
        onPress={() => router.push(`/scan/${heroScanId}/findings`)}
      />
    </Card>
  );
}

/**
 * The NFR-02 cold-start figure, read on the device it was measured on.
 *
 * **Not dev-gated.** The number that matters is from a release build on a real 4 GB phone, and a
 * panel that only exists in development cannot produce it. It is one line of monospace text in the
 * About block, which is where someone taking the measurement will look.
 *
 * It states what it measures. "JS→frame" rather than "cold start", because everything before the
 * bundle began evaluating is invisible from here — `src/lib/startup.ts` has the `adb` commands for
 * the whole figure, and reporting this one as the cold start would understate it.
 */
function StartupLine() {
  const measurement = startupMeasurement();

  if (!measurement) return null;

  return (
    <Text variant="mono" tone={withinBudget(measurement) ? 'subtle' : 'borderline'}>
      JS→frame: {measurement.jsToFirstFrameMs} ms (budget {COLD_START_BUDGET_MS} ms, whole cold
      start is larger)
    </Text>
  );
}

function AboutFooter() {
  const t = useT();
  const version = Constants.expoConfig?.version ?? '0.0.0';

  return (
    <View style={styles.about}>
      <Text variant="caption" tone="subtle" style={styles.aboutLine}>
        {t('settings.about')}
      </Text>
      <Text variant="mono" tone="subtle" style={styles.aboutLine}>
        {t('settings.version', { version })}
      </Text>
      <Text variant="mono" tone="subtle" style={styles.aboutLine}>
        API mode: {API_MODE}
      </Text>
      <StartupLine />
    </View>
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

      <AboutFooter />
    </Screen>
  );
}

const styles = StyleSheet.create({
  about: { alignItems: 'center', gap: 2, paddingTop: spacing.lg },
  aboutLine: { textAlign: 'center' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  row: { gap: spacing.xs },
  rows: { gap: spacing.md },
});
