/**
 * Fixture accounts, one per org mode.
 *
 * The phone number selects the account, exactly as a real backend would look a user up by it.
 * That keeps the mock honest: the dev panel's "switch account" runs the real OTP request/verify
 * path rather than writing into the session store behind its back, so the thing being
 * demonstrated is the thing that will ship.
 *
 * Deleted with the rest of `src/api/mock/` at Stage 13.
 */

import type { Org, OrgMode, User } from '@/domain';

import { BRAND_ANALYST, ENFORCEMENT_ORG, INDUSTRY_ORG, INSPECTOR } from './fixtures/orgs';

export interface FixtureAccount {
  mode: OrgMode;
  /** E.164, as `normalisePhone` produces. */
  phone: string;
  user: User;
  org: Org;
}

export const FIXTURE_ACCOUNTS: readonly FixtureAccount[] = [
  {
    mode: 'enforcement',
    phone: INSPECTOR.phone,
    user: INSPECTOR,
    org: ENFORCEMENT_ORG,
  },
  {
    mode: 'industry',
    phone: BRAND_ANALYST.phone,
    user: BRAND_ANALYST,
    org: INDUSTRY_ORG,
  },
];

/** The code the mock accepts. A real backend sends one by SMS; this one is printed on screen. */
export const FIXTURE_OTP = '000000';

export function accountForMode(mode: OrgMode): FixtureAccount {
  const account = FIXTURE_ACCOUNTS.find((a) => a.mode === mode);
  if (!account) throw new Error(`No fixture account for mode ${mode}`);
  return account;
}

/**
 * Resolve a phone to an account.
 *
 * An unrecognised number signs in as the industry analyst rather than failing, so the app can be
 * demonstrated with the tester's own number. A real backend will reject an unregistered phone —
 * the mock does not model registration, and nothing in the app should assume it does.
 */
export function accountForPhone(phone: string): FixtureAccount {
  return FIXTURE_ACCOUNTS.find((a) => a.phone === phone) ?? accountForMode('industry');
}
