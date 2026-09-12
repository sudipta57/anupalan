/**
 * Skeleton placeholder for content that is loading.
 *
 * Pulses, unless the user has asked the system to reduce motion — in which case it holds at a
 * steady mid opacity rather than animating. Accessibility settings are honoured, not detected
 * and ignored.
 */

import { useEffect, useState } from 'react';
import { AccessibilityInfo, Animated, StyleSheet, type ViewStyle } from 'react-native';

import { radius, useTheme } from '@/theme';

export interface SkeletonProps {
  width?: number | `${number}%`;
  height?: number;
  style?: ViewStyle;
}

export function Skeleton({ width = '100%', height = 16, style }: SkeletonProps) {
  const { colors } = useTheme();
  // useState's lazy initialiser, not useRef: reading `.current` during render is a lint
  // error and, more to the point, a ref is not the right home for a value the render uses.
  const [opacity] = useState(() => new Animated.Value(0.55));
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let cancelled = false;

    AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (!cancelled) setReduceMotion(enabled);
      })
      .catch(() => {
        // Not all platforms answer; a static skeleton is the safe default.
      });

    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduceMotion);

    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(0.55);
      return;
    }

    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.9, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.45, duration: 700, useNativeDriver: true }),
      ])
    );

    loop.start();
    return () => loop.stop();
  }, [opacity, reduceMotion]);

  return (
    <Animated.View
      accessibilityRole="progressbar"
      accessibilityLabel="Loading"
      style={[styles.block, { width, height, backgroundColor: colors.surfaceAlt, opacity }, style]}
    />
  );
}

const styles = StyleSheet.create({
  block: { borderRadius: radius.sm },
});
