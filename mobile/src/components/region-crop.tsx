/**
 * One region of a scan's rectified image, cropped to fill a box.
 *
 * A scaled and offset `<Image>` inside an `overflow: hidden` view — the geometry comes from
 * `cropTransform`, which is pure and tested. Nothing is written to disk and nothing is asynchronous,
 * so a sheet listing four low-confidence fields renders four crops in one frame.
 *
 * The highlight outline is drawn on the same transform as the image, so it cannot drift from the text
 * it names. That drift is the bug this shares its arithmetic with Stage 8's overlay to avoid.
 */

import { Image, StyleSheet, View, type ImageSourcePropType } from 'react-native';

import type { BBox } from '@/domain';
import { boxInViewport, cropTransform, type ImageSize } from '@/features/processing/crop';
import { radius, useTheme } from '@/theme';

export interface RegionCropProps {
  source: ImageSourcePropType;
  image: ImageSize;
  box: BBox;
  width: number;
  height: number;
  /** Outline the region. Off for a plain crop where the whole view *is* the region. */
  outline?: boolean;
  accessibilityLabel?: string;
}

export function RegionCrop({
  source,
  image,
  box,
  width,
  height,
  outline = true,
  accessibilityLabel,
}: RegionCropProps) {
  const { colors } = useTheme();

  const transform = cropTransform(image, box, { width, height });
  const highlight = boxInViewport(box, transform);

  return (
    <View
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
      style={[
        styles.frame,
        { width, height, backgroundColor: colors.surfaceAlt, borderColor: colors.border },
      ]}
    >
      <Image
        source={source}
        style={{
          position: 'absolute',
          left: transform.left,
          top: transform.top,
          width: transform.imageWidth,
          height: transform.imageHeight,
        }}
        // `stretch`, because the size above is already the exact aspect-correct size. `contain` would
        // letterbox inside it and the offsets would no longer land on the region.
        resizeMode="stretch"
      />

      {outline ? (
        <View
          pointerEvents="none"
          style={[
            styles.outline,
            {
              left: highlight.left,
              top: highlight.top,
              width: highlight.width,
              height: highlight.height,
              borderColor: colors.brand,
            },
          ]}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    borderRadius: radius.sm,
    borderWidth: 1,
    overflow: 'hidden',
  },
  outline: {
    borderRadius: 2,
    borderWidth: 2,
    position: 'absolute',
  },
});
