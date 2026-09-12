/**
 * English strings. This file is the source of truth for the key set — every other locale is
 * typed as a partial of it, so adding a key here is a compile-time prompt to translate it.
 *
 * Keep the shape shallow-ish and grouped by surface. Values may contain `{placeholders}`.
 */

export const en = {
  common: {
    appName: 'Anupalan',
    cancel: 'Cancel',
    retry: 'Try again',
    close: 'Close',
    done: 'Done',
    next: 'Next',
    back: 'Back',
    save: 'Save',
    loading: 'Loading…',
    search: 'Search',
  },

  tabs: {
    scan: 'Scan',
    inspections: 'Inspections',
    bulk: 'Bulk check',
    history: 'History',
    sahayak: 'Sahayak',
    settings: 'Settings',
  },

  verdict: {
    pass: 'Pass',
    fail: 'Fail',
    borderline: 'Borderline',
    notAssessable: 'Not assessable',
    passDescription: 'Meets the requirement.',
    failDescription: 'Does not meet the requirement.',
    borderlineDescription: 'Within the measurement uncertainty of the threshold.',
    notAssessableDescription: 'Could not be measured from this image.',
  },

  disclaimer: {
    title: 'Advisory only — not a certification',
    body: 'Anupalan gives a pre-audit opinion. It carries no legal force and does not replace a Legal Metrology inspection or professional advice.',
    rulepack: 'Checked against rule pack {version}',
    pending:
      'The rule pack is an engineering transcription of published rules, pending legal review.',
  },

  scan: {
    title: 'Scan a label',
    subtitle: 'Photograph the package with the scale marker in frame.',
    start: 'Start a scan',
    comingSoon: 'Guided capture arrives with the camera gates.',
  },

  history: {
    title: 'History',
    empty: 'No scans yet',
    emptyBody: 'Scans you complete will be listed here, filterable by date, product and verdict.',
  },

  sahayak: {
    title: 'Sahayak',
    subtitle: 'Questions about Indian Standards and BIS certification.',
    empty: 'Ask about a Quality Control Order, a scheme, fees, or which lab to use.',
  },

  auth: {
    phoneTitle: 'Sign in',
    phoneSubtitle: 'We will send a six-digit code to your phone.',
    phoneLabel: 'Mobile number',
    phoneHint: '10-digit Indian mobile number',
    phoneInvalid: 'Enter a 10-digit mobile number starting 6, 7, 8 or 9.',
    sendCode: 'Send code',
    otpTitle: 'Enter the code',
    otpSubtitle: 'Sent to {phone}. It expires in {seconds} seconds.',
    otpLabel: 'Six-digit code',
    otpInvalid: 'Enter the six-digit code.',
    verify: 'Verify and sign in',
    changeNumber: 'Use a different number',
    resend: 'Send a new code',
    signedOut: 'Your session ended. Sign in again to continue.',
    fixtureAccounts: 'Fixture accounts',
    fixtureHint: 'Dev only. Any code works except an obviously wrong one — try 000000.',
  },

  account: {
    title: 'Account',
    signedInAs: 'Signed in as',
    role: 'Role',
    organisation: 'Organisation',
    mode: 'Mode',
    modeEnforcement: 'Enforcement',
    modeIndustry: 'Industry',
    modeEnforcementBody:
      'Field inspection: geo-tagged evidence, an audit trail, and district reporting.',
    modeIndustryBody: 'Pre-print checks, bulk listing checks, and BIS applicability guidance.',
    signOut: 'Sign out',
  },

  roles: {
    admin: 'Administrator',
    inspector: 'Inspector',
    analyst: 'Analyst',
    viewer: 'Viewer',
  },

  inspections: {
    title: 'Inspections',
    subtitle: 'Scans you have recorded, with their evidence trail.',
    empty: 'No inspections yet',
    emptyBody:
      'Completed inspections are listed here with their district, timestamp and evidence hashes.',
  },

  bulk: {
    title: 'Bulk check',
    subtitle: 'Check many marketplace listings at once.',
    empty: 'Nothing checked yet',
    emptyBody:
      'Paste or upload a CSV of listing URLs or listing text. Metric rules stay Not assessable — a listing carries no physical scale.',
  },

  settings: {
    title: 'Settings',
    language: 'Language',
    languageEnglish: 'English',
    languageHindi: 'हिन्दी',
    appearance: 'Appearance',
    appearanceSystem: 'Follow device',
    appearanceLight: 'Light',
    appearanceDark: 'Dark',
    about: 'About',
    version: 'Version {version}',
  },

  errors: {
    title: 'Something went wrong',
    generic:
      'The app hit an unexpected problem. Try again, and if it keeps happening, note what you were doing.',
    offline: 'No connection. Your work is saved and will sync when you are back online.',
    notFound: 'Not found',
    notFoundBody: 'That screen does not exist.',
    goHome: 'Go to Scan',
    goSignIn: 'Go to sign in',
  },
} as const;

export type Translations = typeof en;
