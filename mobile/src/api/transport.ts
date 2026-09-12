/**
 * The seam between the app and its data.
 *
 * Everything above this line — hooks, screens, types — is written as though the API were live.
 * Below it there are two implementations: fixtures today, HTTP once the backend exists. The
 * cutover is an environment variable and deleting a folder, not a rewrite (Stage 13).
 *
 * Keep this interface narrow. Every method added here is a method both implementations must
 * honour, and the mock is the one that will quietly fall behind.
 */

import { API_MODE } from './config';
import { createLiveTransport } from './live-transport';
import { createMockTransport } from './mock';

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

export interface RequestSpec {
  method: HttpMethod;
  /** Path below the version prefix, e.g. `/scans/sc_01/findings`. */
  path: string;
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  /** Honoured on every POST that creates (docs/02-trd.md §5). */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

/**
 * Putting one captured image at a presigned URL.
 *
 * Separate from `request` because it is not a JSON API call: it is a raw `PUT` of file bytes to
 * object storage, at a URL the API handed out, with no envelope and no auth header of ours. Routing
 * it through `request` would mean the JSON transport growing a binary branch, an `Authorization`
 * header leaking to a third-party host, and the mock having to pretend a presigned URL exists.
 */
export interface UploadSpec {
  /** The presigned target from `POST /scans`. */
  url: string;
  headers: Record<string, string>;
  /** `file://` URI of the local image. */
  fileUri: string;
  signal?: AbortSignal;
}

/**
 * Fetching one generated report to local storage.
 *
 * The mirror image of `UploadSpec`, and separate from `request` for the same reasons: it is file
 * bytes rather than a JSON envelope, the URL is presigned by the API and served by object storage,
 * and our `Authorization` header must not travel to a third-party host.
 *
 * It exists at all because a share sheet needs a **file**. Handing Android an https URL produces an
 * intent that most apps cannot open, so the bytes come down first and the share is over a local
 * `file://` URI (FR-08).
 */
export interface DownloadSpec {
  /** The presigned source from the report's `files[].uri`. */
  url: string;
  headers: Record<string, string>;
  /** `file://` destination. Overwritten if it already exists, so a re-share is not an error. */
  fileUri: string;
  signal?: AbortSignal;
}

export interface Transport {
  request<T>(spec: RequestSpec): Promise<T>;
  /** Resolves on success; rejects with an `ApiError` otherwise, so the queue's retry policy sees one shape. */
  upload(spec: UploadSpec): Promise<void>;
  /** Writes the file at `spec.fileUri`. Rejects with an `ApiError` on any non-2xx or transport failure. */
  download(spec: DownloadSpec): Promise<void>;
}

export const transport: Transport =
  API_MODE === 'live' ? createLiveTransport() : createMockTransport();
