/**
 * The findings viewer — FR-05.
 *
 * *Accept: every FAIL and BORDERLINE finding has a bounding box that highlights on tap; the citation
 * text is visible without leaving the screen.*
 *
 * The layout is three fixed zones rather than one long scroll, and that is the acceptance test's
 * doing. "Without leaving the screen" is not satisfied by a detail panel that has scrolled out of
 * sight: tap a box at the top of the label and the citation has to be *there*. So the label stays
 * pinned at the top, the selected finding sits directly beneath it, and only the grouped list
 * scrolls.
 *
 * What this screen refuses to do:
 *
 * - **It does not merge the four groups.** Failures, Borderline, Not assessable and Passed each get a
 *   heading, and an empty one still gets its heading and the word "none". A list that hides empty
 *   groups teaches its reader that the groups shown are the only ones there are, and the first
 *   casualty is BORDERLINE (CLAUDE.md §3.4).
 * - **It does not show a BORDERLINE without its band.** `2.05 mm, band 1.80–2.30` is a measurement
 *   that could not be told apart from the threshold. A bare "Borderline" is the accusation with the
 *   reason deleted.
 * - **It does not present verdicts as settled while a field is unconfirmed.** Same reasoning as the
 *   scan screen, and more urgent here, because this is where the verdicts are actually read.
 * - **It does not draw a millimetre scale bar on an image with no known scale.** `pxPerMm` is null
 *   when nothing was rectified against a marker, and a ruler over an unscaled image would assert the
 *   one thing the product refuses to guess (CLAUDE.md §3.3).
 *
 * Every piece of arithmetic is in `features/findings/viewport.ts`, including the inverse transform
 * that turns a tap back into an image pixel. The rule is that the outline and the tap come from one
 * transform: two near-identical sets of sums would look right and open the wrong rule.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { memo, useCallback, useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  type ImageSourcePropType,
} from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';

import { imageSourceFor, useFindings, useScan } from '@/api';
import {
  AdvisoryDisclaimer,
  Banner,
  Button,
  Card,
  Chip,
  FindingsOverlay,
  Screen,
  Skeleton,
  Text,
  VerdictBadge,
} from '@/components';
import type { BBox, Finding, FindingsResult, OrgMode, Scan, Verdict } from '@/domain';
import {
  GROUP_TITLE_KEYS,
  IDENTITY_VIEW,
  SEVERITY_KEYS,
  anchoredFindings,
  canvasSize,
  detailFor,
  editingLocked,
  evidenceFor,
  findingsInDisplayOrder,
  findingsMissingAnchor,
  fitScale,
  focusOn,
  groupFindings,
  hashGroups,
  hitTest,
  panBy,
  pinchAt,
  scaleBarLength,
  showsEvidence,
  slopInImagePx,
  viewportToImage,
  type ViewTransform,
} from '@/features/findings';
import {
  fieldsNeedingConfirmation,
  verdictsAreProvisional,
  type ImageSize,
  type Viewport,
} from '@/features/processing';
import { formatGeo } from '@/features/scan-context';
import { useT } from '@/i18n';
import { useOrgMode } from '@/store/session';
import { radius, spacing, useTheme } from '@/theme';

/**
 * Height of the label pane, in logical units.
 *
 * Fixed rather than a fraction of the screen so the three zones are predictable: the pane, the
 * selected finding and the list all have to fit a phone at once, and a pane sized as a percentage
 * gets squeezed to nothing on a short screen exactly when the list grows.
 */
const PANE_HEIGHT = 300;

/** How tall the selected-finding panel may grow before it scrolls inside itself. */
const DETAIL_MAX_HEIGHT = 208;

/** Length of the scale bar. 10 mm is the unit the rules are written in. */
const SCALE_BAR_MM = 10;

function toneFor(verdict: Verdict): 'pass' | 'fail' | 'borderline' | 'notAssessable' {
  switch (verdict) {
    case 'PASS':
      return 'pass';
    case 'FAIL':
      return 'fail';
    case 'BORDERLINE':
      return 'borderline';
    case 'NOT_ASSESSABLE':
      return 'notAssessable';
  }
}

/* -------------------------------------------------------------------------- */
/*  The label pane                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Pan and zoom state for the pane.
 *
 * Held here rather than inside `LabelPane` because two things move the view: a gesture on the image,
 * and a tap on a row in the list below it. Owning it where both can reach means the list calls
 * `focusBox` directly, instead of poking the pane through a prop and an effect that has to be made to
 * re-fire when the same row is tapped twice.
 *
 * **Every continuous gesture goes through a functional update.** A pan delivers a dozen changes before
 * React re-renders, and each has to be applied to the result of the last rather than to the state as
 * it stood when the finger went down — so the updater receives the live value instead of a closure's
 * copy. A ref mirror would do the same job and was the first attempt here; the compiler's `refs` rule
 * correctly objected, and the updater is the better answer anyway because there is then only one
 * place the transform lives.
 *
 * A tap needs no such care. Taps race the pan rather than interleaving with it, so by the time one
 * fires the view has been committed and `view` from render is the current one.
 */
function useLabelView(image: ImageSize) {
  const [viewport, setViewport] = useState<Viewport>({ width: 0, height: 0 });
  const [view, setView] = useState<ViewTransform>(IDENTITY_VIEW);

  const fit = fitScale(image, viewport);

  const measure = useCallback(
    (width: number, height: number) => {
      if (viewport.width === width && viewport.height === height) return;

      setViewport({ width, height });
      // A resize or rotation invalidates the clamped offsets. Re-fitting is predictable; carrying a
      // stale offset across leaves the label pressed off one edge with no obvious way back.
      setView(IDENTITY_VIEW);
    },
    [viewport]
  );

  return {
    viewport,
    view,
    fit,
    canvas: canvasSize(image, fit),

    drag: useCallback(
      (dx: number, dy: number) =>
        setView((current) => panBy(current, dx, dy, image, viewport, fit)),
      [fit, image, viewport]
    ),

    pinch: useCallback(
      (scaleChange: number, focal: { x: number; y: number }) =>
        setView((current) => pinchAt(current, scaleChange, focal, image, viewport, fit)),
      [fit, image, viewport]
    ),

    /** Move the view so one box is centred and readable. */
    focusBox: useCallback(
      (box: BBox) => setView(focusOn(box, image, viewport, fit)),
      [fit, image, viewport]
    ),

    reset: useCallback(() => setView(IDENTITY_VIEW), []),
    measure,
  };
}

type LabelView = ReturnType<typeof useLabelView>;

function LabelPane({
  image,
  source,
  pxPerMm,
  findings,
  selectedId,
  onSelect,
  labelView,
}: {
  image: ImageSize;
  source: ImageSourcePropType;
  pxPerMm: number | null;
  findings: readonly Finding[];
  selectedId: string | null;
  onSelect: (finding: Finding | null) => void;
  labelView: LabelView;
}) {
  const t = useT();
  const { colors } = useTheme();

  const { viewport, view, fit, canvas, drag, pinch, reset, measure } = labelView;

  // Candidate order decides an exact tie, and this order puts FAIL before PASS — so a tap on the MRP
  // box, which carries both, opens the failure.
  const candidates = findingsInDisplayOrder(findings);
  const anchored = anchoredFindings(findings);

  const tapAt = useCallback(
    (x: number, y: number) => {
      const point = viewportToImage({ x, y }, view, image, viewport, fit);
      if (!point) return;

      // A tap on bare label clears the selection rather than leaving a stale highlight.
      onSelect(hitTest(point, candidates, slopInImagePx(fit, view.zoom)));
    },
    [candidates, fit, image, onSelect, view, viewport]
  );

  const gesture = Gesture.Race(
    // `runOnJS` throughout: every decision lives in the pure module, and a worklet cannot call a
    // function that was not compiled as one. The cost is that the transform is applied on the JS
    // thread; the benefit is one tested copy of the arithmetic rather than one per thread — and the
    // overlay is memoised on the canvas, so a drag restyles one view rather than thirteen rectangles.
    Gesture.Tap()
      .runOnJS(true)
      .maxDuration(260)
      .onEnd((event) => tapAt(event.x, event.y)),
    Gesture.Simultaneous(
      Gesture.Pan()
        .runOnJS(true)
        .averageTouches(true)
        .onChange((event) => drag(event.changeX, event.changeY)),
      Gesture.Pinch()
        .runOnJS(true)
        .onChange((event) => pinch(event.scaleChange, { x: event.focalX, y: event.focalY }))
    )
  );

  const bar = scaleBarLength(pxPerMm, SCALE_BAR_MM, fit, view.zoom);
  const moved = view.zoom !== 1 || view.offsetX !== 0 || view.offsetY !== 0;

  return (
    <View
      style={[styles.pane, { backgroundColor: colors.surfaceAlt }]}
      onLayout={(event) => measure(event.nativeEvent.layout.width, event.nativeEvent.layout.height)}
    >
      <GestureDetector gesture={gesture}>
        <View style={styles.paneInner}>
          {fit > 0 ? (
            <View
              style={{
                width: canvas.width,
                height: canvas.height,
                // Translate then scale: React Native composes this so the translation stays in
                // viewport units, which is the convention `viewport.ts` inverts.
                transform: [
                  { translateX: view.offsetX },
                  { translateY: view.offsetY },
                  { scale: view.zoom },
                ],
              }}
            >
              <Image
                source={source}
                style={{ width: canvas.width, height: canvas.height }}
                // The size above is already the aspect-correct size; `contain` would letterbox
                // inside it and every box would sit off the text it names.
                resizeMode="stretch"
                accessibilityLabel={t('findings.imageLabel')}
              />
              <FindingsOverlay
                findings={anchored}
                selectedId={selectedId}
                width={canvas.width}
                height={canvas.height}
                fit={fit}
                zoom={view.zoom}
              />
            </View>
          ) : null}
        </View>
      </GestureDetector>

      {/* Chrome, outside the transform so it keeps its size as the label zooms. */}
      <View style={styles.paneChrome} pointerEvents="box-none">
        <Chip label={t('findings.zoom', { percent: Math.round(view.zoom * 100) })} />
        {moved ? <Button label={t('findings.fit')} variant="ghost" onPress={reset} /> : null}
      </View>

      {/* No bar at all when `pxPerMm` is null: a ruler over an image of unknown scale would assert
          the one thing the product refuses to guess (CLAUDE.md §3.3). */}
      {bar !== null ? (
        <View style={styles.scaleBar} pointerEvents="none">
          <View style={[styles.scaleBarRule, { width: bar, backgroundColor: colors.text }]} />
          <Text variant="mono" tone="muted">
            {t('findings.scaleBar', { mm: SCALE_BAR_MM })}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function NoImagePane() {
  const t = useT();
  const { colors } = useTheme();

  return (
    <View style={[styles.pane, styles.paneEmpty, { backgroundColor: colors.surfaceAlt }]}>
      <Text variant="bodyStrong">{t('findings.noImage')}</Text>
      <Text variant="caption" tone="muted" style={styles.centred}>
        {t('findings.noImageBody')}
      </Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  The selected finding                                                       */
/* -------------------------------------------------------------------------- */

function Detail({
  finding,
  rulepackVersion,
  mode,
}: {
  finding: Finding;
  rulepackVersion: string;
  /** Passed in rather than read here, so one place on this screen decides which shell it is. */
  mode: OrgMode | null;
}) {
  const t = useT();
  const { colors } = useTheme();

  const detail = detailFor(finding, mode);

  return (
    <View style={[styles.detail, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <ScrollView contentContainerStyle={styles.detailBody}>
        <View style={styles.detailHead}>
          <VerdictBadge verdict={finding.verdict} />
          <Chip label={t(SEVERITY_KEYS[finding.severity])} tone={toneFor(finding.verdict)} />
          <Text variant="mono" tone="subtle">
            {finding.ruleId}
          </Text>
        </View>

        <Text variant="body">{finding.message}</Text>

        <View style={styles.rows}>
          {detail.required !== null ? (
            <Row label={t('findings.required')} value={detail.required} />
          ) : null}
          {detail.observed !== null ? (
            <Row label={t('findings.observed')} value={detail.observed} />
          ) : null}

          {/* A BORDERLINE says why it is borderline. When the band did not arrive, it says what the
              verdict means instead of printing an empty line. */}
          {finding.verdict === 'BORDERLINE' ? (
            <Row
              label={t('findings.band')}
              value={detail.band ?? t(detail.bandFallbackKey)}
              tone={detail.bandMissing ? 'subtle' : 'default'}
            />
          ) : null}
        </View>

        {/* Verbatim from the rule pack, in its own block. This is the sentence someone reads out in
            a dispute; it is never shortened, reworded or turned into a link. */}
        <View style={[styles.citation, { borderLeftColor: colors.brand }]}>
          <Text variant="label" tone="muted">
            {t('findings.citation')}
          </Text>
          <Text variant="body">{detail.citation}</Text>
          <Text variant="mono" tone="subtle">
            {t('disclaimer.rulepack', { version: rulepackVersion })}
          </Text>
        </View>

        {detail.remediation !== null ? (
          <View style={styles.rows}>
            <Text variant="label" tone="muted">
              {t('findings.remediation')}
            </Text>
            <Text variant="body">{detail.remediation}</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

function Row({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string;
  tone?: 'default' | 'subtle';
}) {
  return (
    <View style={styles.row}>
      <Text variant="label" tone="muted">
        {label}
      </Text>
      <Text variant="bodyStrong" tone={tone}>
        {value}
      </Text>
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  The grouped list                                                           */
/* -------------------------------------------------------------------------- */

const FindingRow = memo(function FindingRow({
  finding,
  selected,
  onPress,
}: {
  finding: Finding;
  selected: boolean;
  onPress: () => void;
}) {
  const t = useT();
  const { colors } = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={[
        styles.findingRow,
        { borderColor: selected ? colors.brand : colors.border },
        selected && { backgroundColor: colors.brandSoft },
      ]}
    >
      <View style={styles.findingHead}>
        <VerdictBadge verdict={finding.verdict} />
        <Text variant="mono" tone="subtle">
          {finding.ruleId}
        </Text>
      </View>
      <Text variant="body" numberOfLines={2}>
        {finding.message}
      </Text>
      {finding.bbox === null ? (
        <Text variant="caption" tone="subtle">
          {t('findings.noRegion')}
        </Text>
      ) : null}
    </Pressable>
  );
});

function Group({
  verdict,
  findings,
  selectedId,
  onSelect,
}: {
  verdict: Verdict;
  findings: Finding[];
  selectedId: string | null;
  onSelect: (finding: Finding) => void;
}) {
  const t = useT();

  return (
    <View style={styles.group}>
      <View style={styles.groupHead}>
        <Text variant="heading">{t(GROUP_TITLE_KEYS[verdict])}</Text>
        <Chip label={String(findings.length)} tone={toneFor(verdict)} selected />
      </View>

      {/* An empty group keeps its heading. Four verdicts exist on every scan whether or not this
          pack produced one of each. */}
      {findings.length === 0 ? (
        <Text variant="caption" tone="subtle">
          {t('findings.groupEmpty')}
        </Text>
      ) : (
        findings.map((finding) => (
          <FindingRow
            key={finding.id}
            finding={finding}
            selected={finding.id === selectedId}
            onPress={() => onSelect(finding)}
          />
        ))
      )}
    </View>
  );
}

/* -------------------------------------------------------------------------- */
/*  Mode A's evidence panel                                                    */
/* -------------------------------------------------------------------------- */

function EvidencePanel({ scan, result }: { scan: Scan; result: FindingsResult }) {
  const t = useT();

  const evidence = evidenceFor(scan, result);

  return (
    <Card>
      <Text variant="heading">{t('evidence.title')}</Text>
      <Text variant="caption" tone="muted">
        {t('evidence.body')}
      </Text>

      <View style={styles.rows}>
        <Text variant="label" tone="muted">
          {t('evidence.imageHash')}
        </Text>
        {/* The raw upload's hash, never the rectified image's: the rectified image is derived, so
            its hash verifies a computation rather than a photograph (`evidence.ts`). */}
        <Text variant="mono" tone={evidence.imageSha256 ? 'default' : 'subtle'}>
          {evidence.imageSha256 ? hashGroups(evidence.imageSha256) : t('evidence.imageHashMissing')}
        </Text>

        <Text variant="label" tone="muted">
          {t('evidence.findingsHash')}
        </Text>
        <Text variant="mono">{hashGroups(evidence.findingsSha256)}</Text>

        <Row label={t('evidence.capturedAt')} value={evidence.capturedAt} />
        <Row
          label={t('evidence.location')}
          value={
            evidence.geo
              ? `${formatGeo(evidence.geo)} ${t('evidence.accuracy', {
                  metres: Math.round(evidence.geo.accuracyM),
                })}`
              : t('evidence.locationNone')
          }
          tone={evidence.geo ? 'default' : 'subtle'}
        />
        <Row
          label={t('evidence.district')}
          value={evidence.district ?? t('evidence.districtNone')}
          tone={evidence.district ? 'default' : 'subtle'}
        />
        <Row
          label={t('evidence.issuedAt')}
          value={evidence.reportIssuedAt ?? t('evidence.notIssued')}
          tone={evidence.reportIssuedAt ? 'default' : 'subtle'}
        />
      </View>

      <Banner tone="info" title={t('evidence.pendingTitle')} body={t('evidence.pendingBody')} />
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/*  The screen                                                                 */
/* -------------------------------------------------------------------------- */

function Loaded({ scan, result }: { scan: Scan; result: FindingsResult }) {
  const t = useT();
  const mode = useOrgMode();

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Bounding boxes are in the rectified image's coordinate space (`src/domain/common.ts`), so there
  // is nothing to draw them on without that asset.
  const rectified = scan.assets.find((asset) => asset.kind === 'rectified') ?? null;
  const source = imageSourceFor(rectified?.uri);
  const image: ImageSize = rectified
    ? { widthPx: rectified.widthPx, heightPx: rectified.heightPx }
    : { widthPx: 0, heightPx: 0 };

  const labelView = useLabelView(image);

  const groups = groupFindings(result.findings);
  const missingAnchor = findingsMissingAnchor(result.findings);
  const unconfirmed = fieldsNeedingConfirmation(result);
  const provisional = verdictsAreProvisional(result);
  const locked = editingLocked(mode, scan);

  const selected = result.findings.find((finding) => finding.id === selectedId) ?? null;

  const { focusBox } = labelView;

  /**
   * A tap on a list row selects the finding **and moves the view to its box.**
   *
   * Moving the view is the highlight. An outline drawn around text five units high is a smudge, and
   * someone who tapped a row does not yet know where on the pack the rule applies.
   */
  const selectFromList = useCallback(
    (finding: Finding) => {
      setSelectedId(finding.id);
      if (finding.bbox) focusBox(finding.bbox);
    },
    [focusBox]
  );

  /**
   * A tap on the label selects and **leaves the view where it is.**
   *
   * The asymmetry with the list is deliberate: someone who tapped a box already knows where it is, and
   * jumping the zoom under their finger is disorienting.
   */
  const selectFromImage = useCallback((finding: Finding | null) => {
    setSelectedId(finding?.id ?? null);
  }, []);

  return (
    <Screen bleed contentStyle={styles.screen}>
      {rectified && source ? (
        <LabelPane
          image={image}
          source={source}
          pxPerMm={rectified.pxPerMm}
          findings={result.findings}
          selectedId={selectedId}
          onSelect={selectFromImage}
          labelView={labelView}
        />
      ) : (
        <NoImagePane />
      )}

      {selected ? (
        <Detail finding={selected} rulepackVersion={result.rulepackVersion} mode={mode} />
      ) : (
        <View style={styles.hint}>
          <Text variant="caption" tone="muted">
            {t('findings.selectHint')}
          </Text>
          <Text variant="caption" tone="subtle">
            {t('findings.imageHint')}
          </Text>
        </View>
      )}

      <ScrollView contentContainerStyle={styles.list}>
        {/* Above the groups, because it is about how to read every verdict in them. */}
        {provisional ? (
          <Card>
            <Banner
              tone="warning"
              title={t('processing.provisionalTitle')}
              body={
                unconfirmed.length === 1
                  ? t('processing.provisionalBody', { count: unconfirmed.length })
                  : t('processing.provisionalBodyPlural', { count: unconfirmed.length })
              }
            />
            <Button
              label={
                unconfirmed.length === 1
                  ? t('processing.confirmCta', { count: unconfirmed.length })
                  : t('processing.confirmCtaPlural', { count: unconfirmed.length })
              }
              disabled={locked}
              onPress={() => router.push(`/scan/${scan.id}/confirm`)}
            />
            {locked ? (
              <Text variant="caption" tone="subtle">
                {t('findings.lockedBody')}
              </Text>
            ) : null}
          </Card>
        ) : null}

        {/* A FAIL or BORDERLINE with no box would be listed here and invisible on the label, which
            is a contract violation rather than a cosmetic gap (FR-05's acceptance). */}
        {missingAnchor.length > 0 ? (
          <Banner
            tone="warning"
            title={
              missingAnchor.length === 1
                ? t('findings.noBoxTitle', { count: missingAnchor.length })
                : t('findings.noBoxTitlePlural', { count: missingAnchor.length })
            }
            body={t('findings.noBoxBody')}
          />
        ) : null}

        {groups.map((group) => (
          <Group
            key={group.verdict}
            verdict={group.verdict}
            findings={group.findings}
            selectedId={selectedId}
            onSelect={selectFromList}
          />
        ))}

        {locked ? (
          <Banner tone="info" title={t('findings.lockedTitle')} body={t('findings.lockedBody')} />
        ) : null}

        {showsEvidence(mode) ? <EvidencePanel scan={scan} result={result} /> : null}

        <AdvisoryDisclaimer detailed />
      </ScrollView>
    </Screen>
  );
}

export default function FindingsScreen() {
  const t = useT();
  const { id } = useLocalSearchParams<{ id: string }>();

  const scan = useScan(id);
  const findings = useFindings(scan.data?.status === 'complete' ? id : undefined);

  if (scan.isPending) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={24} />
          <Skeleton height={PANE_HEIGHT} />
        </Card>
      </Screen>
    );
  }

  if (!scan.data) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('processing.notFound')}</Text>
          <Text variant="body" tone="muted">
            {t('processing.notFoundBody')}
          </Text>
          <Button label={t('errors.goHome')} onPress={() => router.dismissTo('/(tabs)')} />
        </Card>
      </Screen>
    );
  }

  if (scan.data.status !== 'complete') {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('findings.notComplete')}</Text>
          <Text variant="body" tone="muted">
            {t('findings.notCompleteBody')}
          </Text>
          <Button label={t('findings.openScan')} onPress={() => router.replace(`/scan/${id}`)} />
        </Card>
      </Screen>
    );
  }

  if (!findings.data) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={24} />
          <Skeleton height={PANE_HEIGHT} />
        </Card>
      </Screen>
    );
  }

  return <Loaded scan={scan.data} result={findings.data} />;
}

const styles = StyleSheet.create({
  centred: { textAlign: 'center' },
  citation: {
    borderLeftWidth: 3,
    gap: spacing.xs,
    paddingLeft: spacing.sm,
  },
  detail: {
    borderTopWidth: 1,
    borderBottomWidth: 1,
    maxHeight: DETAIL_MAX_HEIGHT,
  },
  detailBody: { gap: spacing.sm, padding: spacing.lg },
  detailHead: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  findingHead: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  findingRow: {
    borderRadius: radius.md,
    borderWidth: 1,
    gap: spacing.xs,
    padding: spacing.md,
  },
  group: { gap: spacing.sm },
  groupHead: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  hint: { gap: 2, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  list: { gap: spacing.lg, paddingBottom: spacing.xl, paddingHorizontal: spacing.lg },
  pane: { height: PANE_HEIGHT, overflow: 'hidden', width: '100%' },
  paneChrome: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    position: 'absolute',
    right: spacing.sm,
    top: spacing.sm,
  },
  paneEmpty: {
    alignItems: 'center',
    gap: spacing.xs,
    justifyContent: 'center',
    padding: spacing.lg,
  },
  paneInner: { alignItems: 'center', flex: 1, justifyContent: 'center', overflow: 'hidden' },
  row: { gap: 2 },
  rows: { gap: spacing.sm },
  scaleBar: {
    alignItems: 'flex-start',
    bottom: spacing.sm,
    gap: 2,
    left: spacing.sm,
    position: 'absolute',
  },
  scaleBarRule: { borderRadius: 1, height: 3 },
  screen: { gap: 0, paddingTop: 0 },
});
