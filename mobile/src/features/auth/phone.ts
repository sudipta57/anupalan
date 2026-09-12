/**
 * Phone number handling for the OTP flow.
 *
 * One canonical form goes to the API — E.164, `+91` followed by ten digits — because the backend
 * looks a user up by it and `98000 00001`, `098000-00001` and `+91 9800000001` are the same
 * person. Normalising at the edge means no endpoint ever has to guess.
 *
 * Indian mobile numbers are ten digits beginning 6, 7, 8 or 9. Landlines and short codes cannot
 * receive an SMS OTP, so they are rejected here rather than failing at the SMS gateway.
 */

const COUNTRY_CODE = '91';

/** Ten digits starting 6-9. */
const MOBILE = /^[6-9]\d{9}$/;

/**
 * Reduce any of the forms a user might type to `+91XXXXXXXXXX`, or null if it is not a valid
 * Indian mobile number.
 */
export function normalisePhone(input: string): string | null {
  const digits = input.replace(/\D/g, '');

  // Strip a country code or a trunk prefix, leaving the ten-digit subscriber number.
  const local = digits.startsWith(COUNTRY_CODE)
    ? digits.slice(COUNTRY_CODE.length)
    : digits.startsWith('0')
      ? digits.slice(1)
      : digits;

  return MOBILE.test(local) ? `+${COUNTRY_CODE}${local}` : null;
}

/**
 * Group an E.164 number for display: `+91 98000 00001`.
 *
 * Read back to a user who is checking they typed their own number, so grouping matters more than
 * compactness. Anything unexpected is returned unchanged rather than mangled.
 */
export function formatPhone(phone: string): string {
  const match = /^\+(\d{2})(\d{5})(\d{5})$/.exec(phone);
  return match ? `+${match[1]} ${match[2]} ${match[3]}` : phone;
}

/** Six digits. The code length the backend issues (TRD §5). */
export const OTP_LENGTH = 6;

export function isCompleteOtp(input: string): boolean {
  return new RegExp(`^\\d{${OTP_LENGTH}}$`).test(input.trim());
}
