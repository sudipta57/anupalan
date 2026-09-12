/**
 * One org per mode, so both shells are one tap apart in the dev panel.
 *
 * Mode is an org-level attribute (docs/01-architecture.md §3): enforcement adds evidence
 * integrity and locks editing, industry adds remediation and bulk import. Rule evaluation is
 * identical in both.
 */

import type { Org, User } from '@/domain';

export const ENFORCEMENT_ORG: Org = {
  id: 'org_lm_wb',
  name: 'Legal Metrology, Nadia District',
  mode: 'enforcement',
  state: 'West Bengal',
  createdAt: '2026-04-02T04:30:00Z',
};

export const INDUSTRY_ORG: Org = {
  id: 'org_annapurna',
  name: 'Annapurna Foods Pvt Ltd',
  mode: 'industry',
  state: 'Maharashtra',
  createdAt: '2026-05-19T06:15:00Z',
};

export const INSPECTOR: User = {
  id: 'usr_inspector',
  orgId: ENFORCEMENT_ORG.id,
  name: 'S. Ghorami',
  role: 'inspector',
  phone: '+919800000001',
  email: null,
};

export const BRAND_ANALYST: User = {
  id: 'usr_analyst',
  orgId: INDUSTRY_ORG.id,
  name: 'R. Iyer',
  role: 'analyst',
  phone: '+919800000002',
  email: 'r.iyer@example.in',
};

export const ORGS: Org[] = [ENFORCEMENT_ORG, INDUSTRY_ORG];
export const USERS: User[] = [INSPECTOR, BRAND_ANALYST];

/** Districts used by the Mode A history filter. */
export const DISTRICTS = ['Nadia', 'North 24 Parganas', 'Hooghly', 'Kolkata', 'Howrah'] as const;
