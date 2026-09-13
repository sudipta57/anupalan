/**
 * Turning the live preview into something the gate check can measure (FR-01).
 *
 * **Why a preview snapshot and not a frame processor.** The gates were meant to read an on-device
 * ArUco frame processor, which was never written. vision-camera 5 is Nitro-based and has removed
 * the `VisionCameraProxy.initFrameProcessorPlugin` API every existing ArUco plugin targets, and
 * `android/` here is prebuild output that `expo prebuild --clean` discards — so a hand-written
 * native module is a project of its own. `03-implementation-plan.md` §P3.3 sanctions this interim
 * explicitly: *"ship the interim version that uploads a frame every 500 ms for server-side gate
 * checks, and swap later."*
 *
 * `Camera.takeSnapshot()` is Android-only, which is the platform this app ships on. It returns the
 * preview's contents, not the sensor's, and that difference is the one thing to keep in mind here:
 * the frame measured is what the user is looking at, at preview resolution. For marker presence and
 * glare that is the right surface to judge. For blur it is a **weaker** signal than the
 * full-resolution photograph would give, because a downscaled image is inherently smoother — see
 * `gates.ts` for why the threshold is therefore a guide rather than a guarantee.
 *
 * **Failure is silence.** Every way this can fail — a preview that is not ready, a snapshot the
 * platform refuses, a manipulator that throws — resolves to `null`, and `null` means "no reading
 * this tick" rather than "the gate failed". The evaluator holds the previous metrics, so a dropped
 * snapshot does not make the chips flicker.
 */

import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

/** What the gate check is sent. Small enough that ArUco still resolves the tag comfortably. */
const MAX_EDGE_PX = 640;

/** JPEG quality. Marker detection is a threshold operation; it does not need a clean gradient. */
const COMPRESS = 0.6;

/**
 * Anything that can hand over the current preview as a base64 JPEG.
 *
 * An interface rather than the camera ref itself, so the evaluator is testable without a camera —
 * the same reason `GateEvaluator` exists at all.
 */
export type FrameSource = () => Promise<string | null>;

/** The part of vision-camera's `Camera` ref this module needs. */
export interface SnapshotCapable {
  takeSnapshot(): Promise<{ saveToTemporaryFileAsync(format: 'jpg', quality?: number): Promise<string> }>;
}

/**
 * A `FrameSource` reading from whatever the camera currently is.
 *
 * Takes a getter rather than the ref itself, for two reasons. The camera mounts after the first
 * render, so anything resolved at construction time would hold `null` forever; and a function
 * that never touches `.current` during render is one React's rules-of-refs lint can verify rather
 * than have to trust.
 */
export function previewFrameSource(current: () => SnapshotCapable | null): FrameSource {
  return async () => {
    const camera = current();
    if (camera === null) return null;

    try {
      const snapshot = await camera.takeSnapshot();
      const path = await snapshot.saveToTemporaryFileAsync('jpg', 90);

      // Downscaled and re-encoded here rather than at full preview size: the request goes out
      // twice a second, and the server refuses anything over its own ceiling anyway.
      const rendered = await ImageManipulator.manipulate(path)
        .resize({ width: MAX_EDGE_PX })
        .renderAsync();

      const saved = await rendered.saveAsync({
        base64: true,
        compress: COMPRESS,
        format: SaveFormat.JPEG,
      });

      return saved.base64 ?? null;
    } catch {
      return null;
    }
  };
}
