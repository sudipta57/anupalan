/**
 * Authentication — phone OTP over JWT access/refresh (docs/01-architecture.md §14).
 *
 * The flow is two screens and two endpoints: request a code for a phone number, verify the code
 * to get a session. The session carries the user, their role and their **org**, and the org's
 * mode is what decides which app shell they see (`src/features/navigation`).
 *
 * Where the pieces live:
 * - tokens and identity: `src/store/session.ts`, read synchronously from MMKV at startup
 * - refresh on 401: `src/api/live-transport.ts`, single-flight, invisible to screens
 * - the seam between those two: `src/api/auth-bridge.ts`
 */

export { clearCacheOnOrgChange, useClearCacheOnOrgChange } from './cache';
export { InvalidPhoneError, useRequestOtp, useSignOut, useVerifyOtp } from './hooks';
export type { OtpRequest } from './hooks';
export { OTP_LENGTH, formatPhone, isCompleteOtp, normalisePhone } from './phone';
