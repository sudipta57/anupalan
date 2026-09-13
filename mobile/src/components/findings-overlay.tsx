/**
 * The bounding boxes drawn over the rectified label — FR-05.
 *
 * Purely presentational, and that is the point: it decides nothing. The rectangles come from
 * `boxOnCanvas` and a tap is resolved by `hitTest`, both in `features/findings/viewport.ts`, so there
 * is no second copy of the geometry here to drift out of step with the one that answers taps.
 *
 * Visual weight follows the verdict rather than treating every box the same. Thirteen outlines on one
 * label is a thicket, and the first thing lost in a thicket is the two boxes someone needs to look at:
 *
 * | Verdict | Stroke |
 * |---|---|
 * | FAIL, BORDERLINE | solid, full weight, their own colour |
 * | NOT_ASSESSABLE | dashed — nothing was measured here, and a solid box would imply something was |
 * | PASS | thin and half-transparent, present and tappable without competing |
 *
 * The selected box gains weight and a soft fill. All four keep their own colour from the verdict
 * palette, so the overlay and the list below it agree without anyone matching them up by eye.
 */

import { memo } from 'react';
import { StyleSheet } from 'react-native';
import Svg, { Circle, G, Rect, Text as SvgText } from 'react-native-svg';

import type { Verdict } from '@/domain';
import { boxOnCanvas, strokeWidthFor, type AnchoredFinding } from '@/features/findings';
import { useTheme } from '@/theme';

export interface FindingsOverlayProps {
  /** Anchored findings, largest box first — `anchoredFindings` supplies that order. */
  findings: readonly AnchoredFinding[];
  selectedId: string | null;
  /** Canvas size, matching the `<Image>` this is drawn over. */
  width: number;
  height: number;
  /** View units per image pixel, before zoom. */
  fit: number;
  /**
   * Current zoom, used only to keep the outlines a constant thickness on screen.
   *
   * Quantised by `strokeWidthFor`, so a pinch re-renders this a handful of times rather than once a
   * frame to restate a hairline.
   */
  zoom: number;
  /**
   * The same number a finding's row shows in the list below, so a reader can match a box on the
   * pack to its card without guessing. Findings with no entry here draw no badge — every id in this
   * map must also be in `findings`.
   */
  numbering?: ReadonlyMap<string, number>;
}

/** Base outline weight in canvas units, before the zoom is divided back out. */
const STROKE = 2.5;
/** Base radius of the numbered index badge, before the zoom is divided back out. */
const BADGE_RADIUS = 9;

function FindingsOverlayImpl({
  findings,
  selectedId,
  width,
  height,
  fit,
  zoom,
  numbering,
}: FindingsOverlayProps) {
  const { colors } = useTheme();

  const stroke = strokeWidthFor(zoom, STROKE);
  const badgeRadius = strokeWidthFor(zoom, BADGE_RADIUS);

  const colourFor: Record<Verdict, string> = {
    PASS: colors.pass,
    FAIL: colors.fail,
    BORDERLINE: colors.borderline,
    NOT_ASSESSABLE: colors.notAssessable,
  };

  return (
    <Svg
      style={StyleSheet.absoluteFill}
      width={width}
      height={height}
      pointerEvents="none"
      accessibilityElementsHidden
    >
      {findings.map((finding) => {
        const box = boxOnCanvas(finding.bbox, fit);
        const selected = finding.id === selectedId;
        const colour = colourFor[finding.verdict];
        const quiet = finding.verdict === 'PASS';

        return (
          <Rect
            key={finding.id}
            x={box.x}
            y={box.y}
            width={box.width}
            height={box.height}
            stroke={colour}
            strokeWidth={selected ? stroke * 2 : quiet ? stroke * 0.6 : stroke}
            strokeOpacity={selected ? 1 : quiet ? 0.45 : 0.9}
            // Dashes say "nothing was measured inside this" without a second colour to learn.
            strokeDasharray={
              finding.verdict === 'NOT_ASSESSABLE' ? [stroke * 3, stroke * 2] : undefined
            }
            fill={selected ? colour : 'none'}
            fillOpacity={selected ? 0.14 : 0}
            rx={stroke}
          />
        );
      })}

      {/* A second pass, so every badge paints above every box regardless of draw order. */}
      {numbering
        ? findings.map((finding) => {
            const number = numbering.get(finding.id);
            if (number === undefined) return null;

            const box = boxOnCanvas(finding.bbox, fit);
            const colour = colourFor[finding.verdict];

            return (
              <G key={`badge-${finding.id}`}>
                <Circle
                  cx={box.x}
                  cy={box.y}
                  r={badgeRadius}
                  fill={colour}
                  stroke={colors.surface}
                  strokeWidth={badgeRadius * 0.2}
                />
                <SvgText
                  x={box.x}
                  y={box.y}
                  fill={colors.onBrand}
                  fontSize={badgeRadius * 1.15}
                  fontWeight="bold"
                  textAnchor="middle"
                  // SVG has no vertical-centre primitive; `dy` nudges the baseline down by roughly
                  // a third of the cap height, which centres single- and double-digit numbers alike.
                  dy={badgeRadius * 0.35}
                >
                  {number}
                </SvgText>
              </G>
            );
          })
        : null}
    </Svg>
  );
}

/**
 * Memoised because panning changes nothing here.
 *
 * A drag updates only the canvas's transform; the rectangles are in canvas coordinates and do not
 * move relative to the image. Without this the whole overlay re-renders on every frame of a pan for
 * no visible difference.
 */
export const FindingsOverlay = memo(FindingsOverlayImpl);
