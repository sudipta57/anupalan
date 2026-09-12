/**
 * Where a captured frame goes.
 *
 * The **document** directory, not the cache: FR-04 requires a queued scan to survive a force-close,
 * and the system deletes cache directories under storage pressure — which is precisely the state a
 * phone is in after an inspector has taken forty photographs in a market.
 *
 * `SavablePhoto` is a structural type rather than vision-camera's `Photo` on purpose. It keeps a
 * Nitro module out of this file's import graph, so the save path is testable with a stub, and it
 * documents exactly how little of the camera API this depends on.
 */

import { Directory, File, Paths } from 'expo-file-system';

import type { IsoDateTime } from '@/domain';

/** The part of vision-camera's `Photo` that saving actually needs. */
export interface SavablePhoto {
  readonly width: number;
  readonly height: number;
  /** Wants a filesystem path, not a `file://` URL, and the file must not already exist. */
  saveToFileAsync(path: string): Promise<void>;
}

export interface CapturedPhoto {
  /** `file://` URI, for `<Image>` and for the upload step. */
  uri: string;
  widthPx: number;
  heightPx: number;
  capturedAt: IsoDateTime;
}

const CAPTURES_DIR = 'captures';

/**
 * Strip the scheme from a `file://` URI.
 *
 * `saveToFileAsync` documents that it wants a filesystem path, and handing it a URL fails at
 * runtime on the device — somewhere I cannot reach from a test. Percent-decoding matters because
 * an Android app-private path can contain an encoded character and the native side does not decode.
 */
export function filesystemPathFromUri(uri: string): string {
  const withoutScheme = uri.startsWith('file://') ? uri.slice('file://'.length) : uri;

  try {
    return decodeURI(withoutScheme);
  } catch {
    // A malformed escape is not worth failing a capture over; the raw path is the better guess.
    return withoutScheme;
  }
}

function capturesDirectory(): Directory {
  const directory = new Directory(Paths.document, CAPTURES_DIR);
  if (!directory.exists) directory.create({ intermediates: true });
  return directory;
}

let sequence = 0;

/** Timestamped and sequenced, because `saveToFileAsync` rejects a path that already exists. */
export function nextCaptureFilename(now: number = Date.now()): string {
  sequence += 1;
  return `cap_${now}_${sequence}.jpg`;
}

export async function saveCapture(photo: SavablePhoto): Promise<CapturedPhoto> {
  const directory = capturesDirectory();
  const file = new File(directory, nextCaptureFilename());

  await photo.saveToFileAsync(filesystemPathFromUri(file.uri));

  return {
    uri: file.uri,
    widthPx: photo.width,
    heightPx: photo.height,
    capturedAt: new Date().toISOString(),
  };
}

export function deleteCapture(uri: string): void {
  const file = new File(uri);
  if (file.exists) file.delete();
}

/**
 * Every capture currently on disk.
 *
 * Stage 6 owns the lifecycle: the offline queue adopts these into scan records and deletes what it
 * has uploaded. Until then a capture abandoned by leaving this screen stays on disk rather than
 * being silently discarded — losing an inspector's photograph is the worse of the two failures.
 */
export function listCaptures(): string[] {
  const directory = new Directory(Paths.document, CAPTURES_DIR);
  if (!directory.exists) return [];

  return directory
    .list()
    .filter((entry): entry is File => entry instanceof File)
    .map((file) => file.uri);
}
