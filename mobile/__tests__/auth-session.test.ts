/**
 * The session: phone normalisation, what survives a restart, and what a sign-out takes with it.
 *
 * The storage assertions matter more than they look. An inspector's phone is shared, handed over,
 * and re-signed-into; the rules are that a session survives a restart, a sign-out leaves nothing
 * behind, and a malformed stored session signs the user out instead of crashing the app on launch.
 */

import { ENFORCEMENT_ORG, INDUSTRY_ORG, INSPECTOR } from '@/api/mock/fixtures/orgs';
import type { Session } from '@/domain';
import { formatPhone, isCompleteOtp, normalisePhone } from '@/features/auth';
import { authStorage, storage } from '@/lib/storage';
import { SESSION_STORAGE_KEY, parseStoredSession, useSession } from '@/store/session';

const SESSION: Session = {
  accessToken: 'access-1',
  refreshToken: 'refresh-1',
  user: INSPECTOR,
  org: ENFORCEMENT_ORG,
};

afterEach(() => {
  useSession.getState().signOut();
});

describe('normalisePhone', () => {
  it('accepts the forms a person actually types', () => {
    for (const input of [
      '9800000001',
      '+919800000001',
      '+91 98000 00001',
      '09800000001',
      '919800000001',
      '98000-00001',
    ]) {
      expect(normalisePhone(input)).toBe('+919800000001');
    }
  });

  it('rejects what cannot receive an SMS', () => {
    // Too short, too long, a landline STD number, a short code, and empty.
    for (const input of ['980000000', '98000000012', '03312345678', '139', '']) {
      expect(normalisePhone(input)).toBeNull();
    }
  });

  it('rejects numbers not starting 6-9, which are not Indian mobiles', () => {
    expect(normalisePhone('5800000001')).toBeNull();
    expect(normalisePhone('1800000001')).toBeNull();
  });

  it('matches the fixture accounts, so the dev sign-in path resolves', () => {
    expect(normalisePhone(INSPECTOR.phone)).toBe(INSPECTOR.phone);
  });
});

describe('formatPhone', () => {
  it('groups an E.164 number for reading back', () => {
    expect(formatPhone('+919800000001')).toBe('+91 98000 00001');
  });

  it('returns anything unexpected unchanged rather than mangling it', () => {
    expect(formatPhone('not a number')).toBe('not a number');
  });
});

describe('isCompleteOtp', () => {
  it('needs exactly six digits', () => {
    expect(isCompleteOtp('000000')).toBe(true);
    expect(isCompleteOtp('12345')).toBe(false);
    expect(isCompleteOtp('1234567')).toBe(false);
    expect(isCompleteOtp('12345a')).toBe(false);
  });
});

describe('parseStoredSession', () => {
  it('reads back a session it wrote', () => {
    const raw = JSON.stringify({
      tokens: { accessToken: 'a', refreshToken: 'r' },
      user: INSPECTOR,
      org: ENFORCEMENT_ORG,
    });

    expect(parseStoredSession(raw).org?.mode).toBe('enforcement');
  });

  it('treats nothing stored as signed out', () => {
    expect(parseStoredSession(null)).toEqual({ tokens: null, user: null, org: null });
  });

  it('treats unparseable storage as signed out rather than throwing on launch', () => {
    expect(parseStoredSession('{ not json').tokens).toBeNull();
  });

  it('rejects half a session — tokens with no org leaves navigation nothing to compose', () => {
    const raw = JSON.stringify({ tokens: { accessToken: 'a', refreshToken: 'r' } });
    expect(parseStoredSession(raw).tokens).toBeNull();
  });

  it('rejects a token pair missing its refresh token', () => {
    const raw = JSON.stringify({
      tokens: { accessToken: 'a' },
      user: INSPECTOR,
      org: ENFORCEMENT_ORG,
    });
    expect(parseStoredSession(raw).tokens).toBeNull();
  });
});

describe('useSession', () => {
  it('starts signed out', () => {
    expect(useSession.getState().tokens).toBeNull();
  });

  it('signing in exposes the org mode navigation reads', () => {
    useSession.getState().signIn(SESSION);

    expect(useSession.getState().org?.mode).toBe('enforcement');
    expect(useSession.getState().user?.id).toBe(INSPECTOR.id);
  });

  it('persists the session so a restart does not sign the user out', () => {
    useSession.getState().signIn(SESSION);

    const stored = authStorage.getItem(SESSION_STORAGE_KEY);
    expect(stored).not.toBeNull();
    expect(parseStoredSession(stored).tokens).toEqual({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
    });
  });

  it('a refresh replaces the tokens and keeps the identity', () => {
    useSession.getState().signIn(SESSION);
    useSession.getState().setTokens({ accessToken: 'access-2', refreshToken: 'refresh-2' });

    expect(useSession.getState().tokens?.accessToken).toBe('access-2');
    expect(useSession.getState().org?.id).toBe(ENFORCEMENT_ORG.id);
    // And it is durable: the old access token must not come back after a restart.
    expect(parseStoredSession(authStorage.getItem(SESSION_STORAGE_KEY)).tokens?.accessToken).toBe(
      'access-2'
    );
  });

  it('a refresh arriving after sign-out does not resurrect the session', () => {
    useSession.getState().signIn(SESSION);
    useSession.getState().signOut();
    useSession.getState().setTokens({ accessToken: 'late', refreshToken: 'late' });

    expect(useSession.getState().tokens).toBeNull();
    expect(authStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('signing out leaves nothing behind for the next person on this phone', () => {
    useSession.getState().signIn(SESSION);
    useSession.getState().signOut();

    expect(useSession.getState()).toMatchObject({ tokens: null, user: null, org: null });
    expect(authStorage.getItem(SESSION_STORAGE_KEY)).toBeNull();
  });

  it('signing out does not take preferences with it', () => {
    // A user who signs out has not asked to be put back into English.
    storage.setItem('preferences', JSON.stringify({ state: { locale: 'hi' }, version: 1 }));
    useSession.getState().signIn(SESSION);
    useSession.getState().signOut();

    expect(storage.getItem('preferences')).toContain('hi');
  });

  it('signing in as the other org replaces the mode, which is what redraws the tab bar', () => {
    useSession.getState().signIn(SESSION);
    expect(useSession.getState().org?.mode).toBe('enforcement');

    useSession.getState().signIn({ ...SESSION, org: INDUSTRY_ORG });
    expect(useSession.getState().org?.mode).toBe('industry');
  });
});
