/**
 * Turning a `ScanAsset.uri` into something `<Image>` can render.
 *
 * This exists so **no screen imports a fixture.** The mock's rectified asset is a bundled PNG behind a
 * `fixture://` URI, and the real one will be a presigned HTTPS URL. A screen that branched on which it
 * was would be a screen that has to be rewritten at Stage 13, which is exactly what the transport seam
 * exists to prevent (`05-frontend-plan.md` §3).
 *
 * At Stage 13 the `fixture://` branch is deleted and the function becomes `({ uri })`. Nothing above it
 * changes.
 */

import type { ImageSourcePropType } from 'react-native';

// Dev-only import, deleted at Stage 13 with the rest of the mock backend.
import { LABEL_IMAGE } from './mock/fixtures/label';

const FIXTURE_PREFIX = 'fixture://';

/** Bundled images the fixtures refer to, keyed by the path after `fixture://`. */
const FIXTURE_IMAGES: Readonly<Record<string, ImageSourcePropType>> = {
  'rectified-label': LABEL_IMAGE,
};

/**
 * A renderable source for an asset URI, or null if there is nothing to show.
 *
 * Null rather than a broken-image placeholder: a screen that knows it has no image can say so, while
 * an `<Image>` pointed at an unresolvable URI renders an empty box that reads as a layout bug.
 */
export function imageSourceFor(uri: string | null | undefined): ImageSourcePropType | null {
  if (!uri) return null;

  if (uri.startsWith(FIXTURE_PREFIX)) {
    return FIXTURE_IMAGES[uri.slice(FIXTURE_PREFIX.length)] ?? null;
  }

  return { uri };
}
