/**
 * Organisations and users.
 *
 * Mode is an **org-level attribute** (docs/01-architecture.md §3). The same engine ships in two
 * shells: enforcement adds evidence-integrity features and locks editing, industry adds
 * remediation suggestions and bulk import. Rule evaluation is identical in both — a brand's
 * whole reason to pay is that the tool runs the same check an inspector would.
 */

import type { IsoDateTime } from './common';

export type OrgMode = 'enforcement' | 'industry';

export type Role = 'admin' | 'inspector' | 'analyst' | 'viewer';

export interface Org {
  id: string;
  name: string;
  mode: OrgMode;
  /** Indian state the org operates in. Drives the district filters in Mode A. */
  /**
   * The state the org operates in, when it is known.
   *
   * Null because the session endpoint does not publish it — shown beside the org name only when
   * present, rather than rendered as a blank that reads like a failed load.
   */
  state: string | null;
  createdAt: IsoDateTime | null;
}

export interface User {
  id: string;
  orgId: string;
  name: string;
  role: Role;
  phone: string;
  email: string | null;
}

/**
 * A JWT pair. The access token is short-lived and sent on every request; the refresh token buys a
 * new pair when it expires (docs/01-architecture.md §14).
 */
export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

/** What `POST /v1/auth/otp/verify` returns. */
export interface Session extends AuthTokens {
  user: User;
  org: Org;
}
