/**
 * The SHA-256 a scan declares for each photograph it is about to upload — FR-20, architecture §10.
 *
 * **Why the device hashes, rather than the server hashing what arrives.** The worker checks the
 * stored object against this value before it does anything else, and fails the scan on a mismatch.
 * That check only means something if the hash was taken *before* the bytes travelled: a hash
 * computed by the server after the upload would verify the upload against itself and pass no matter
 * what arrived. Hashing here is what turns the declaration into a **checkable claim** — a truncated
 * upload, a proxy that rewrote the body, a corrupted file on disk, all fail the scan rather than
 * being processed as evidence.
 *
 * It is also what architecture §10 asks for in the first place: the hash of the photograph as it
 * came off the camera, recorded at upload, and embedded in any report issued later. A report that
 * quoted a hash of whatever survived the network would be verifying our own plumbing.
 *
 * **Cost.** A 4 MB JPEG is read into memory and hashed natively. That is the price of the property
 * above, it happens once per photograph while the scan sits in the queue, and it is off the capture
 * screen's critical path — the shutter has long since returned by the time this runs.
 *
 * **Why this file reaches for the native module itself instead of importing `expo-crypto`.**
 * `expo-crypto/build/ExpoCrypto.js` is one line — `requireNativeModule('ExpoCrypto')` at module
 * scope — so importing the package *throws during import* on a build that does not contain the
 * native module. A development client built before this dependency was added is exactly that
 * situation, and because the offline queue is imported by the root layout, that throw took down the
 * whole app at launch.
 *
 * Wrapping the import in `require` and a `try/catch` does not fix it, which is worth writing down
 * because it looks like it should: Metro's `guardedLoadModule` catches anything a module throws
 * while loading, hands it to `ErrorUtils.reportFatalError` and returns `undefined`. The error
 * becomes a fatal error report — a red screen in development — and the `catch` here never runs, so
 * the loader would return `undefined` and the first hash would fail on an unrelated `TypeError`.
 *
 * `requireOptionalNativeModule` is the supported way to ask: it returns `null` for a module the
 * build does not have, throwing nothing, so the failure is ours to describe and it lands where an
 * image is actually hashed rather than on a blank screen at boot.
 *
 * It is **not** a fallback. There is no software digest behind this and there must not be: a scan
 * whose hash could not be computed does not get uploaded with a placeholder, it fails.
 */

import { File } from 'expo-file-system';
import { requireOptionalNativeModule } from 'expo-modules-core';

/** Spelled as the native module spells it, and 32 bytes is the digest length that goes with it. */
const SHA256 = 'SHA-256';
const SHA256_BYTES = 32;

/**
 * The two shapes the native module offers, mirroring what `expo-crypto`'s own `digest()` does.
 *
 * Both are optional because which one exists depends on the platform's module version, and a module
 * that has neither is as unusable as one that is missing.
 */
interface ExpoCryptoModule {
  digestAsync?: (algorithm: string, data: Uint8Array) => Promise<ArrayBuffer>;
  /** Writes the digest into `output` in place; returns nothing. */
  digest?: (algorithm: string, output: Uint8Array, data: Uint8Array) => void;
}

/** Raised when the running build has no crypto module. Rebuilding is the only fix; retrying is not. */
export class HashingUnavailableError extends Error {
  constructor() {
    super(
      'This build cannot hash images: the native crypto module is missing. ' +
        'Rebuild the development client so it includes expo-crypto.'
    );
    this.name = 'HashingUnavailableError';
  }
}

/** Cached after the first successful lookup, so a queue drain resolves the module once. */
let cached: ExpoCryptoModule | null = null;

function loadCrypto(): ExpoCryptoModule {
  cached ??= requireOptionalNativeModule<ExpoCryptoModule>('ExpoCrypto');

  if (!cached) throw new HashingUnavailableError();

  return cached;
}

/** What `POST /v1/scans` must be told about one photograph before it can sign an upload URL. */
export interface AssetDeclaration {
  contentType: string;
  sizeBytes: number;
  /** Lowercase hex, 64 characters — the shape the server's schema enforces. */
  sha256: string;
}

/** JPEG unless the file says otherwise. The capture screen writes `.jpg`; this is the fallback. */
const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
};

export function contentTypeFor(uri: string): string {
  const extension = uri.slice(uri.lastIndexOf('.') + 1).toLowerCase();
  return CONTENT_TYPE_BY_EXTENSION[extension] ?? 'image/jpeg';
}

/** Lowercase hex, because the server's pattern is `^[0-9a-f]{64}$` and an uppercase digest is a 422. */
export function toHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Digest bytes natively.
 *
 * Deliberately not the string API: that would need the file as a string, which means a base64 or
 * UTF-8 round trip through JS for every megabyte, and a base64 digest would hash the *encoding*
 * rather than the bytes the server will store.
 */
async function sha256(bytes: Uint8Array): Promise<Uint8Array> {
  const crypto = loadCrypto();

  if (typeof crypto.digestAsync === 'function') {
    return new Uint8Array(await crypto.digestAsync(SHA256, bytes));
  }

  if (typeof crypto.digest === 'function') {
    const output = new Uint8Array(SHA256_BYTES);
    crypto.digest(SHA256, output, bytes);
    return output;
  }

  throw new HashingUnavailableError();
}

/** Hash one local file. */
export async function hashFile(uri: string): Promise<{ sha256: string; sizeBytes: number }> {
  const file = new File(uri);
  const bytes = await file.bytes();

  return {
    sha256: toHex(await sha256(bytes)),
    // The length actually read, not the stat size. They agree, and if they ever did not, the number
    // the server signs an upload for must be the number of bytes being sent.
    sizeBytes: bytes.byteLength,
  };
}

/**
 * Declare every photograph of a scan, in upload order.
 *
 * Serial rather than parallel: each file is held in memory while it is hashed, and three 4 MB
 * buffers at once on a mid-range phone is how a queue drain turns into an out-of-memory crash.
 */
export async function declareAssets(uris: readonly string[]): Promise<AssetDeclaration[]> {
  const declared: AssetDeclaration[] = [];

  for (const uri of uris) {
    const { sha256: digest, sizeBytes } = await hashFile(uri);
    declared.push({ contentType: contentTypeFor(uri), sizeBytes, sha256: digest });
  }

  return declared;
}
