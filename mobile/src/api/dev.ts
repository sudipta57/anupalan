/**
 * Dev-only access to the fixture layer — NFR-07, and the Stage 13 cutover.
 *
 * Three screens carry development conveniences: the fixture-account switcher, the fixture OTP hint,
 * and the mock scenario panel. All three are already gated on `__DEV__` at render time, which is
 * enough to keep them off a user's screen and **not** enough to keep them out of the bundle: a
 * static `import { FIXTURE_OTP } from '@/api/mock'` pulls the whole fixture graph — 220 seeded scans,
 * a base64 PDF, a base64 DOCX, every rule citation — into the production build regardless of what
 * `__DEV__` does afterwards.
 *
 * That is what this module exists to stop. Everything reaches the mock through one conditional
 * `require` behind `__DEV__ && API_MODE !== 'live'`, both of which are compile-time constants —
 * `__DEV__` from Metro and `EXPO_PUBLIC_API_MODE` inlined by `babel-preset-expo`. In a production
 * live build the condition is statically false, the `require` is unreachable, and the fixtures are
 * dropped from the graph.
 *
 * `null` is the honest return value rather than throwing or returning empty stubs: a caller has to
 * handle "there is no dev bridge here", which is exactly the state a release build is in. The dev
 * panels render nothing when it is null, so the screens keep working after the mock folder is
 * deleted at the real cutover.
 *
 * **This file goes with the mock.** It imports `type`s from `./mock`, which costs nothing at runtime
 * but does couple the two at compile time. When the fixtures folder is deleted, this module and the
 * three panels that use it are deleted in the same change — they are mock-only features, not app
 * features that happen to use the mock.
 */

import type { FixtureAccount } from './mock/accounts';
import type { Scenario } from './mock/scenario';

import { API_MODE } from './config';

export type { FixtureAccount, Scenario };

/** Everything the dev panels need, or nothing at all. */
export interface DevBridge {
  fixtureOtp: string;
  fixtureAccounts: readonly FixtureAccount[];
  /** The sample inspection the dev panel opens without reaching into the fixtures folder. */
  heroScanId: string;
  scenarios: readonly Scenario[];
  scenarioLabels: Record<Scenario, string>;
  getScenario: () => Scenario;
  setScenario: (scenario: Scenario) => void;
  subscribeToScenario: (listener: (scenario: Scenario) => void) => () => void;
}

function load(): DevBridge | null {
  // Both constants are inlined at build time, so a production live build evaluates this to `false`
  // and the `require` below becomes unreachable.
  if (!__DEV__ || API_MODE === 'live') return null;

  // Static imports here would bundle the fixtures into the production build — see the note at the
  // top of this file, and `metro.config.js` for how the exclusion is actually enforced.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const mock = require('./mock') as typeof import('./mock');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const scenario = require('./mock/scenario') as typeof import('./mock/scenario');

  return {
    fixtureOtp: mock.FIXTURE_OTP,
    fixtureAccounts: mock.FIXTURE_ACCOUNTS,
    heroScanId: mock.HERO_SCAN_ID,
    scenarios: scenario.SCENARIOS,
    scenarioLabels: scenario.SCENARIO_LABELS,
    getScenario: scenario.getScenario,
    setScenario: scenario.setScenario,
    subscribeToScenario: scenario.subscribeToScenario,
  };
}

/**
 * The bridge, or null in any build that should not have one.
 *
 * Resolved once at module scope rather than per call: `require` is cached anyway, and a function
 * would invite a caller to treat the answer as something that can change between renders.
 */
export const dev: DevBridge | null = load();
