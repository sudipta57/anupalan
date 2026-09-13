/**
 * Product context — FR-03.
 *
 * The step between a photograph and a scan. Three of its fields change which rules run at all, so
 * FR-03's acceptance is that net quantity, the imported flag and the surface type are present on
 * **every** completed scan. Two things enforce that rather than one:
 *
 * - the submit button will not build an incomplete profile (`buildProfile` returns null), and
 * - `assertRuleRelevantFields` throws if one somehow gets through, because the compiler cannot stop
 *   a form producing `NaN` for a quantity.
 *
 * Two things this screen deliberately does not decide:
 *
 * - **Which Rule 9 table applies.** That follows from the unit, so it is derived in `units.ts` and
 *   merely displayed here. Asking the operator as a second question would create a way for the two
 *   answers to disagree, and the rules engine would read the wrong table in silence.
 * - **Whether to collect location.** `geoForScan` decides, and returns null for Mode B whatever it
 *   is handed. A screen-level `if` would be one refactor away from a Mode B scan carrying a
 *   coordinate.
 *
 * **The form fills itself, and a person still confirms it.** After capture the first photograph is
 * downscaled and sent to be read, and the declarations that come back seed the form
 * (`features/scan-context/prefill.ts`). Three things make that safe rather than merely convenient:
 * every filled field shows the text it was read from, the rule-relevant fields hold submission
 * until the user affirms them once, and the surface — which selects a Rule 9 threshold column — is
 * never filled at all.
 *
 * **The screen waits for the read rather than filling in around the user.** `PrefillGate` holds
 * this form until the answer settles, so the fields are *seeded* at mount and never patched
 * afterwards. A form that fills itself a few seconds late rearranges under a thumb already typing,
 * and asks for work the feature exists to remove. The wait is bounded three ways — an answer, a
 * failure, a timeout — and offers a way straight to the blank form on the first tap, which is what
 * keeps the no-signal path (FR-04) working rather than merely intended.
 *
 * The scale reference comes from the **open scan row**, not from the marker store — see
 * `src/db/queue-repo.ts` for why reading the live setting at submit time would mislabel the scan.
 *
 * **Submitting does not upload.** It attaches the context and hands the scan to the offline queue
 * (`captured → queued`), which returns immediately and succeeds in airplane mode. That is FR-04's
 * whole point: an inspector in a market with no signal must be able to finish a scan and walk to the
 * next shop. The network is the queue's problem, not this screen's.
 */

import { router } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import {
  AdvisoryDisclaimer,
  Banner,
  Button,
  Card,
  Chip,
  Field,
  Screen,
  SegmentedControl,
  Text,
  type SegmentedOption,
} from '@/components';
import type { ProductProfile } from '@/domain';
import { markerFieldsForScan, type MarkerReference } from '@/features/capture';
import {
  CHANNELS,
  MAX_NAME_LENGTH,
  MAX_PDP_AREA_CM2,
  NET_QUANTITY_UNITS,
  PACK_TYPES,
  SURFACES,
  UNSURE_BELOW,
  applySuggestions,
  assertRuleRelevantFields,
  basisForUnit,
  buildProfile,
  categoryFor,
  collectsLocation,
  defaultContextValues,
  districtForScan,
  formatGeo,
  geoForScan,
  isLooseFix,
  isValidName,
  isValidPdpArea,
  isValidQuantityValue,
  normaliseUnit,
  pdpAreaRequired,
  photographsToRead,
  searchCategories,
  unconfirmedRuleFields,
  useLabelPrefill,
  useScanLocation,
  wasRewritten,
  type ContextFormValues,
  type ScanLocation,
  type Suggestion,
} from '@/features/scan-context';
import * as repo from '@/db/queue-repo';
import { kick, useOpenCapture } from '@/features/queue';
import { useT, type TranslationKey } from '@/i18n';
import { useOrgMode } from '@/store/session';
import { radius, spacing, useTheme } from '@/theme';

/** Translated options for a `SegmentedControl`, from one of the `Option` lists in `profile.ts`. */
function useOptions<T extends string>(
  options: readonly { value: T; labelKey: TranslationKey }[]
): SegmentedOption<T>[] {
  const t = useT();
  return options.map((option) => ({ value: option.value, label: t(option.labelKey) }));
}

// ------------------------------------------------------------------ category picker

/**
 * Searchable category. Collapses to the chosen label once picked, because the list is 26 long and
 * a scrolling list above eight more fields buries them.
 */
function CategoryPicker({
  value,
  onChange,
  error,
  suggestion,
}: {
  value: string;
  onChange: (code: string) => void;
  error?: string;
  /** Present when the category was matched from a name read off the label, not chosen. */
  suggestion?: Suggestion;
}) {
  const t = useT();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(value.length === 0);

  // A prefill lands *after* this mounts, so the list is open with the matched category highlighted
  // in it. Collapse once, to the chosen-chip view where the provenance line is: a matched category
  // the user can see and change beats a list of twenty-six they have to re-read. Once only —
  // reopening with "Change" must not be undone by this.
  const collapsedForSuggestion = useRef(false);
  useEffect(() => {
    if (collapsedForSuggestion.current || !suggestion || value.length === 0) return;
    collapsedForSuggestion.current = true;
    setOpen(false);
  }, [suggestion, value]);

  const matches = useMemo(() => searchCategories(query, t), [query, t]);
  const chosen = categoryFor(value);

  if (!open && chosen) {
    return (
      <View style={styles.stack}>
        <Text variant="label">{t('context.categoryLabel')}</Text>
        <View style={styles.chosenRow}>
          <Chip label={t(chosen.labelKey)} tone="brand" selected />
          <Button
            label={t('context.categoryChange')}
            variant="ghost"
            onPress={() => {
              setQuery('');
              setOpen(true);
            }}
          />
        </View>
        <Text variant="caption" tone="subtle">
          {suggestion ? hintFor(suggestion, chosen.code, t) : chosen.code}
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.stack}>
      <Field
        label={t('context.categoryLabel')}
        hint={t('context.categoryHint')}
        error={error}
        required
        placeholder={t('context.categorySearch')}
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
        returnKeyType="search"
      />

      {matches.length === 0 ? (
        <Text variant="caption" tone="muted">
          {t('context.categoryNone')}
        </Text>
      ) : (
        <View style={styles.chips}>
          {matches.map((category) => (
            <Chip
              key={category.code}
              label={t(category.labelKey)}
              tone={category.code === value ? 'brand' : 'neutral'}
              selected={category.code === value}
              onPress={() => {
                onChange(category.code);
                setOpen(false);
              }}
            />
          ))}
        </View>
      )}
    </View>
  );
}

// ------------------------------------------------------------------ location (Mode A only)

/**
 * Time and place, with the disclosure before the request.
 *
 * Mounted only in Mode A. That is a presentation decision; the guarantee that Mode B records no
 * coordinate is `geoForScan`, which is applied at submit regardless of what this renders.
 */
function LocationCard({ location }: { location: ScanLocation }) {
  const t = useT();
  const { point, state } = location;

  return (
    <Card>
      <Text variant="heading">{t('context.locationTitle')}</Text>
      <Text variant="body" tone="muted">
        {t('context.locationBody')}
      </Text>

      {point ? (
        <View style={styles.stack}>
          <Text variant="bodyStrong" tone="pass">
            {t('context.locationAttached')}
          </Text>
          <Text variant="mono" tone="muted">
            {formatGeo(point)}
          </Text>
          <Text variant="caption" tone="subtle">
            {t('context.locationAccuracy', { metres: Math.round(point.accuracyM) })}
          </Text>
          {isLooseFix(point) ? <Banner tone="warning" title={t('context.locationLoose')} /> : null}
          <View style={styles.row}>
            <Button
              label={t('context.locationRetake')}
              variant="secondary"
              onPress={() => void location.attach()}
              loading={state === 'working'}
            />
            <Button label={t('context.locationRemove')} variant="ghost" onPress={location.clear} />
          </View>
        </View>
      ) : (
        <View style={styles.stack}>
          {state === 'denied' ? (
            <Banner tone="warning" title={t('context.locationDenied')} />
          ) : null}
          {state === 'unavailable' ? (
            <Banner tone="warning" title={t('context.locationUnavailable')} />
          ) : null}
          <Button
            label={state === 'working' ? t('context.locationWorking') : t('context.locationAttach')}
            variant="secondary"
            loading={state === 'working'}
            onPress={() => void location.attach()}
          />
          <Text variant="caption" tone="subtle">
            {t('context.locationOptional')}
          </Text>
        </View>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ prefill

/**
 * What the label read produced, said once at the top of the form.
 *
 * There is no "working" state to report here any more — the screen does not render this form until
 * the read has settled, so by the time anyone sees it the answer is in. Two things are worth a
 * sentence: it filled something, or it read the photograph and found nothing usable on it. A read
 * that *failed* is *silent*: the user is looking at a form that works, and "we could not read your
 * photograph" is an apology for a thing they never asked for.
 */
function PrefillBanner({
  filledCount,
  readNothing,
}: {
  filledCount: number;
  readNothing: boolean;
}) {
  const t = useT();

  if (filledCount > 0) {
    return (
      <Banner
        tone="info"
        title={
          filledCount === 1
            ? t('context.prefillFilled', { count: filledCount })
            : t('context.prefillFilledPlural', { count: filledCount })
        }
        body={t('context.prefillCheck')}
      />
    );
  }

  if (readNothing) {
    return (
      <Banner
        tone="info"
        title={t('context.prefillNothing')}
        body={t('context.prefillNothingBody')}
      />
    );
  }

  return null;
}

/**
 * What is on screen while the label is being read.
 *
 * The form is deliberately **not** rendered underneath this. Showing an empty form and filling it
 * a few seconds later means a screen that rearranges itself under someone who has already started
 * typing — and it invites exactly the work the feature exists to remove. So the wait is honest and
 * the form arrives finished.
 *
 * **Nobody is ever trapped here.** Three things end the wait: the read finishing, the read failing,
 * and `timeoutFor` in `use-prefill.ts`. On top of those this offers a way out on the first tap,
 * because a user who knows the pack is unreadable — or who has no signal and no patience — should
 * not be made to watch a spinner to reach a form they could have filled by hand. That escape hatch
 * is what keeps this change compatible with FR-04 rather than a network dependency on the capture
 * path.
 */
function PrefillGate({ photoCount, onSkip }: { photoCount: number; onSkip: () => void }) {
  const t = useT();
  const { colors } = useTheme();

  return (
    <Screen>
      <View style={styles.gate}>
        <ActivityIndicator size="large" color={colors.brand} />

        <View style={styles.gateText}>
          <Text variant="display">{t('context.prefillGateTitle')}</Text>
          <Text variant="body" tone="muted" style={styles.gateBody}>
            {t('context.prefillGateBody')}
          </Text>
        </View>

        <Card>
          <Text variant="label" tone="muted">
            {photoCount === 1
              ? t('context.photos', { count: photoCount })
              : t('context.photosPlural', { count: photoCount })}
          </Text>
          <Text variant="caption" tone="subtle">
            {t('context.prefillGateNote')}
          </Text>
        </Card>

        <Button label={t('context.prefillGateSkip')} variant="ghost" onPress={onSkip} />
      </View>
    </Screen>
  );
}

/**
 * The one tap that stands between a machine reading and a profile the rules engine will act on.
 *
 * FR-03's three fields decide which rules run, so a value the user has neither typed nor looked at
 * must not silently become one. This is the "confirmed by the user" half of FR-03 — and it is a
 * single affirmation over all of them rather than a checkbox per field, because a form that asks
 * four times teaches people to tap past it.
 *
 * It disappears once confirmed, and it never appears at all when nothing rule-relevant was filled.
 */
function ConfirmReadCard({
  quantity,
  imported,
  onConfirm,
}: {
  quantity: string | null;
  imported: boolean;
  onConfirm: () => void;
}) {
  const t = useT();

  return (
    <Card>
      <Text variant="heading">{t('context.prefillConfirmTitle')}</Text>
      <Text variant="body" tone="muted">
        {t('context.prefillConfirmBody')}
      </Text>

      <View style={styles.stack}>
        {quantity ? (
          <Text variant="bodyStrong">
            {t('context.prefillConfirmQuantity', { value: quantity })}
          </Text>
        ) : null}
        {imported ? <Text variant="bodyStrong">{t('context.prefillConfirmImported')}</Text> : null}
      </View>

      <Button label={t('context.prefillConfirmAction')} onPress={onConfirm} />
    </Card>
  );
}

/**
 * The hint under a field that a reading filled, or the field's own hint when nothing did.
 *
 * Below FR-06's threshold the wording changes from "read from the label" to "read, but unclear" —
 * the machine saying it does not believe itself, which is the difference between a filled box a
 * person can glance past and one they will actually check.
 */
function hintFor(
  suggestion: Suggestion | undefined,
  fallback: string,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string
): string {
  if (!suggestion) return fallback;
  return suggestion.confidence < UNSURE_BELOW
    ? t('context.prefillUnsure', { text: suggestion.sourceText })
    : t('context.prefillFrom', { text: suggestion.sourceText });
}

// ------------------------------------------------------------------ confirmation

/**
 * What was recorded, in the rules engine's terms rather than the form's.
 *
 * Showing the three rule-changing fields back is not decoration: it is the only point at which an
 * operator can catch "180 g" typed as "180 kg" before a report is built on it.
 */
function CreatedPanel({
  scanId,
  profile,
  photoCount,
}: {
  scanId: string;
  profile: ProductProfile;
  photoCount: number;
}) {
  const t = useT();

  const rows: { label: string; value: string }[] = [
    {
      label: t('context.createdQuantity'),
      value: `${profile.netQuantity.value} ${profile.netQuantity.unit}`,
    },
    {
      label: t('context.createdImported'),
      value: profile.isImported ? t('context.importedYes') : t('context.importedNo'),
    },
    {
      label: t('context.createdSurface'),
      value:
        profile.surface === 'embossed' ? t('context.surfaceEmbossed') : t('context.surfacePrinted'),
    },
    {
      label: t('context.createdBasis'),
      value:
        profile.qtyBasis === 'weight_or_volume'
          ? t('context.basisWeight')
          : t('context.basisCount'),
    },
  ];

  return (
    <Screen scroll>
      <Card>
        <Text variant="display">{t('context.createdTitle')}</Text>
        <Text variant="body" tone="muted">
          {photoCount === 1
            ? t('context.createdBody', { count: photoCount })
            : t('context.createdBodyPlural', { count: photoCount })}
        </Text>
        <Text variant="mono" tone="subtle">
          {scanId}
        </Text>
      </Card>

      <Card>
        <Text variant="heading">{t('context.createdRecorded')}</Text>
        <View style={styles.stack}>
          {rows.map((row) => (
            <View key={row.label} style={styles.summaryRow}>
              <Text variant="label" tone="muted">
                {row.label}
              </Text>
              <Text variant="body">{row.value}</Text>
            </View>
          ))}
        </View>
      </Card>

      <Card>
        <Text variant="body" tone="muted">
          {t('context.createdPending')}
        </Text>
        <Button
          label={t('queue.open')}
          variant="secondary"
          onPress={() => router.dismissTo('/queue')}
        />
      </Card>

      <Button
        label={t('context.createdDone')}
        size="lg"
        onPress={() => router.dismissTo('/(tabs)')}
      />

      <AdvisoryDisclaimer />
    </Screen>
  );
}

// ------------------------------------------------------------------ the form

function ContextForm({
  scanId,
  photoCount,
  reference,
  suggestions,
  readNothing,
}: {
  scanId: string;
  photoCount: number;
  reference: MarkerReference;
  /** What the label proposed. Already settled — the screen waited for it. Empty is normal. */
  suggestions: readonly Suggestion[];
  /** The label was read and had nothing usable on it, as opposed to not having been read. */
  readNothing: boolean;
}) {
  const t = useT();
  const { colors } = useTheme();
  const mode = useOrgMode();

  const location = useScanLocation();

  const [created, setCreated] = useState<{ scanId: string; profile: ProductProfile } | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ---------------------------------------------------------------- prefill
  //
  // The read is already finished by the time this mounts — the screen waits for it
  // (`ScanContextScreen` below) — so the suggestions seed the form's **defaults** rather than
  // being written into it afterwards. That is why there is no effect here: a field is never first
  // empty and then filled, so nothing can land under a thumb already typing, and the "do not
  // overwrite a person" rule is satisfied by construction rather than by a `getValues()` check.
  const seeded = useMemo(() => {
    const base = defaultContextValues(mode);
    const { values, filled } = applySuggestions(base, suggestions, t);
    return { defaults: { ...base, ...values }, filled };
  }, [mode, suggestions, t]);

  const [filled, setFilled] = useState(seeded.filled);
  const [readConfirmed, setReadConfirmed] = useState(false);

  const {
    control,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<ContextFormValues>({
    defaultValues: seeded.defaults,
    mode: 'onTouched',
  });

  /**
   * Forget that a field was prefilled, because the user has just typed in it.
   *
   * Editing *is* confirming: someone who has retyped the quantity has looked at the pack, and
   * asking them to confirm the value they just supplied is asking a question with one answer.
   */
  const clearFilled = useCallback((field: keyof ContextFormValues) => {
    setFilled((current) => {
      if (current[field] === undefined) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }, []);

  const packOptions = useOptions(PACK_TYPES);
  const surfaceOptions = useOptions(SURFACES);
  const channelOptions = useOptions(CHANNELS);

  const importedOptions: SegmentedOption<'domestic' | 'imported'>[] = [
    { value: 'domestic', label: t('context.importedNo') },
    { value: 'imported', label: t('context.importedYes') },
  ];

  // `useWatch` rather than `watch()`: the latter returns a fresh function on every render, which
  // React Compiler cannot memoize, so it skips compiling the whole component (eslint says so).
  const typedUnit = useWatch({ control, name: 'quantityUnit' });
  const typedValue = useWatch({ control, name: 'quantityValue' });
  const normalisedUnit = normaliseUnit(typedUnit);
  const needsPdpArea = pdpAreaRequired(typedUnit);

  // Rule-relevant fields a machine filled that a person has not yet affirmed. While this is
  // non-empty, submit refuses — see the `submit` callback.
  const unconfirmed = unconfirmedRuleFields(filled, readConfirmed);

  /**
   * Attach the context and hand the scan to the queue.
   *
   * Local and synchronous: no network call, so it works in airplane mode and cannot fail for want of
   * a signal. `kick()` only wakes the runner early if there happens to be a connection.
   */
  const submit = useCallback(
    (values: ContextFormValues) => {
      setSubmitError(null);

      // FR-03's second half. The form may be filled by a machine; the profile that reaches the
      // rules engine may not be *affirmed* by one — `isImported` and the net quantity decide which
      // rules run and which threshold row is read, so a value the user has neither typed nor
      // acknowledged must not become one (CLAUDE.md §3.1).
      if (unconfirmed.length > 0) {
        setSubmitError(t('context.prefillUnconfirmed'));
        return;
      }

      const profile = buildProfile(values);

      if (!profile) {
        setSubmitError(t('context.incomplete'));
        return;
      }

      try {
        // Refuses rather than queueing a scan the rules engine would misread.
        assertRuleRelevantFields(profile);
        // The reference the photographs were shot against, not today's setting. Already on the row;
        // called here so a future change cannot quietly drop the FR-02 check.
        markerFieldsForScan(reference);

        repo.completeContext(scanId, {
          profile,
          // Mode B gets null here whatever the form state holds.
          geo: geoForScan(mode, location.point),
          district: districtForScan(mode, values.district),
        });

        kick();
        setCreated({ scanId, profile });
      } catch {
        setSubmitError(t('context.submitFailed'));
      }
    },
    [location.point, mode, reference, scanId, t, unconfirmed]
  );

  if (created) {
    return (
      <CreatedPanel scanId={created.scanId} profile={created.profile} photoCount={photoCount} />
    );
  }

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="body" tone="muted">
          {t('context.subtitle')}
        </Text>
      </View>

      <Card>
        <Text variant="label" tone="muted">
          {photoCount === 1
            ? t('context.photos', { count: photoCount })
            : t('context.photosPlural', { count: photoCount })}
        </Text>
        <Text variant="caption" tone="subtle">
          {t('context.reference', { name: t('marker.title'), mm: String(reference.mm) })}
        </Text>
      </Card>

      <PrefillBanner filledCount={Object.keys(filled).length} readNothing={readNothing} />

      {unconfirmed.length > 0 ? (
        <ConfirmReadCard
          quantity={
            filled.quantityValue || filled.quantityUnit
              ? `${getValues('quantityValue')} ${getValues('quantityUnit')}`.trim()
              : null
          }
          imported={filled.isImported !== undefined}
          onConfirm={() => {
            setReadConfirmed(true);
            setSubmitError(null);
          }}
        />
      ) : null}

      <Card>
        <Text variant="heading">{t('context.whyTitle')}</Text>
        <Text variant="body" tone="muted">
          {t('context.whyBody')}
        </Text>
      </Card>

      <Card>
        <Controller
          control={control}
          name="name"
          rules={{ validate: (value) => isValidName(value) }}
          render={({ field }) => (
            <Field
              label={t('context.nameLabel')}
              hint={t('context.nameHint')}
              error={errors.name ? t('context.nameInvalid', { max: MAX_NAME_LENGTH }) : undefined}
              required
              value={field.value}
              onChangeText={field.onChange}
              onBlur={field.onBlur}
              maxLength={MAX_NAME_LENGTH}
              autoCapitalize="words"
            />
          )}
        />
      </Card>

      <Card>
        <Controller
          control={control}
          name="categoryCode"
          rules={{ validate: (value) => value.trim().length > 0 }}
          render={({ field }) => (
            <CategoryPicker
              value={field.value}
              onChange={field.onChange}
              error={errors.categoryCode ? t('context.categoryRequired') : undefined}
            />
          )}
        />
      </Card>

      {/* The three that change which rules run, together and called out as such. */}
      <Card>
        <Text variant="heading">{t('context.quantityLabel')}</Text>
        <Text variant="body" tone="muted">
          {t('context.quantityHint')}
        </Text>

        <View style={styles.quantityRow}>
          <View style={styles.quantityValue}>
            <Controller
              control={control}
              name="quantityValue"
              rules={{ validate: (value) => isValidQuantityValue(value) }}
              render={({ field }) => (
                <Field
                  label={t('context.quantityValueLabel')}
                  error={errors.quantityValue ? t('context.quantityValueInvalid') : undefined}
                  required
                  placeholder={t('context.quantityValuePlaceholder')}
                  value={field.value}
                  onChangeText={(next) => field.onChange(next.replace(/[^0-9.]/g, ''))}
                  onBlur={field.onBlur}
                  keyboardType="decimal-pad"
                  maxLength={10}
                />
              )}
            />
          </View>

          <View style={styles.quantityUnit}>
            <Controller
              control={control}
              name="quantityUnit"
              rules={{ validate: (value) => normaliseUnit(value) !== null }}
              render={({ field }) => (
                <Field
                  label={t('context.quantityUnitLabel')}
                  error={
                    errors.quantityUnit
                      ? t('context.quantityUnitInvalid', {
                          units: NET_QUANTITY_UNITS.join(', '),
                        })
                      : undefined
                  }
                  required
                  placeholder={t('context.quantityUnitPlaceholder')}
                  value={field.value}
                  onChangeText={(next) => {
                    clearFilled('quantityUnit');
                    field.onChange(next);
                  }}
                  onBlur={field.onBlur}
                  autoCapitalize="none"
                  autoCorrect={false}
                  maxLength={12}
                />
              )}
            />
          </View>
        </View>

        {/* What was typed versus what will be recorded. `gms` is not a unit, and the operator should
            learn that here rather than from a finding later. */}
        {normalisedUnit ? (
          <View style={styles.stack}>
            {wasRewritten(typedUnit, normalisedUnit) ? (
              <Text variant="caption" tone="borderline">
                {t('context.quantityRewritten', { typed: typedUnit.trim(), unit: normalisedUnit })}
              </Text>
            ) : null}
            {isValidQuantityValue(typedValue) ? (
              <Text variant="caption" tone="brand">
                {t('context.quantityReading', { value: typedValue.trim(), unit: normalisedUnit })}
              </Text>
            ) : null}
            <Text variant="caption" tone="subtle">
              {basisForUnit(normalisedUnit) === 'weight_or_volume'
                ? t('context.basisWeight')
                : t('context.basisCount')}
            </Text>
          </View>
        ) : null}
      </Card>

      {needsPdpArea ? (
        <Card>
          <Banner tone="info" title={t('context.pdpLabel')} body={t('context.pdpWhy')} />
          <Controller
            control={control}
            name="pdpAreaCm2"
            rules={{ validate: (value) => !needsPdpArea || isValidPdpArea(value) }}
            render={({ field }) => (
              <Field
                label={t('context.pdpLabel')}
                hint={t('context.pdpHint')}
                error={
                  errors.pdpAreaCm2 ? t('context.pdpInvalid', { max: MAX_PDP_AREA_CM2 }) : undefined
                }
                required
                value={field.value}
                onChangeText={(next) => field.onChange(next.replace(/[^0-9.]/g, ''))}
                onBlur={field.onBlur}
                keyboardType="decimal-pad"
                maxLength={8}
              />
            )}
          />
        </Card>
      ) : null}

      <Card>
        <Controller
          control={control}
          name="surface"
          render={({ field }) => (
            <View style={styles.stack}>
              <Text variant="label">{t('context.surfaceLabel')}</Text>
              <SegmentedControl
                options={surfaceOptions}
                value={field.value}
                onChange={field.onChange}
                accessibilityLabel={t('context.surfaceLabel')}
              />
              <Text variant="caption" tone="subtle">
                {t('context.surfaceHint')}
              </Text>
            </View>
          )}
        />
      </Card>

      <Card>
        <Controller
          control={control}
          name="isImported"
          render={({ field }) => (
            <View style={styles.stack}>
              <Text variant="label">{t('context.importedLabel')}</Text>
              <SegmentedControl
                options={importedOptions}
                value={field.value ? 'imported' : 'domestic'}
                onChange={(next) => {
                  clearFilled('isImported');
                  field.onChange(next === 'imported');
                }}
                accessibilityLabel={t('context.importedLabel')}
              />
              <Text variant="caption" tone="subtle">
                {hintFor(filled.isImported, t('context.importedHint'), t)}
              </Text>
            </View>
          )}
        />
      </Card>

      <Card>
        <Controller
          control={control}
          name="packType"
          render={({ field }) => (
            <View style={styles.stack}>
              <Text variant="label">{t('context.packLabel')}</Text>
              <View style={styles.chips}>
                {packOptions.map((option) => (
                  <Chip
                    key={option.value}
                    label={option.label}
                    tone={option.value === field.value ? 'brand' : 'neutral'}
                    selected={option.value === field.value}
                    onPress={() => field.onChange(option.value)}
                  />
                ))}
              </View>
            </View>
          )}
        />
      </Card>

      <Card>
        <Controller
          control={control}
          name="channel"
          render={({ field }) => (
            <View style={styles.stack}>
              <Text variant="label">{t('context.channelLabel')}</Text>
              <SegmentedControl
                options={channelOptions}
                value={field.value}
                onChange={field.onChange}
                accessibilityLabel={t('context.channelLabel')}
              />
              <Text variant="caption" tone="subtle">
                {t('context.channelHint')}
              </Text>
            </View>
          )}
        />
      </Card>

      {collectsLocation(mode) ? (
        <>
          <LocationCard location={location} />
          <Card>
            <Controller
              control={control}
              name="district"
              render={({ field }) => (
                <Field
                  label={t('context.districtLabel')}
                  hint={t('context.districtHint')}
                  value={field.value}
                  onChangeText={field.onChange}
                  onBlur={field.onBlur}
                  maxLength={60}
                  autoCapitalize="words"
                />
              )}
            />
          </Card>
        </>
      ) : (
        <Card>
          <Text variant="heading">{t('context.noLocationTitle')}</Text>
          <Text variant="body" tone="muted">
            {t('context.noLocationBody')}
          </Text>
        </Card>
      )}

      {submitError ? <Banner tone="error" title={submitError} /> : null}

      <Button label={t('context.submit')} size="lg" onPress={() => void handleSubmit(submit)()} />

      <View style={[styles.footer, { borderTopColor: colors.border }]}>
        <AdvisoryDisclaimer />
      </View>
    </Screen>
  );
}

/**
 * The screen root, and the one place that decides whether to wait.
 *
 * The read happens here rather than inside the form for a structural reason: the form is mounted
 * **once**, with the answer already in hand, so its fields are seeded rather than patched. Holding
 * the hook here is what makes that possible — it survives the gate giving way to the form, so the
 * request is issued once and is not restarted by the transition.
 */
export default function ScanContextScreen() {
  const t = useT();
  const open = useOpenCapture();

  // The photographs the read will use, in capture order. The mandatory declarations are spread
  // across a pack's faces — net quantity and commodity name on the front, importer, country of
  // origin and consumer-care line on the back — so reading only the front panel would propose
  // nothing for most of the fields this form exists to stop people typing. Capped at
  // MAX_PREFILL_IMAGES: past the third, a photograph is another angle on a face already read, and
  // the wait is one somebody is watching.
  const photoUris = useMemo(
    () => photographsToRead((open?.assets ?? []).map((asset) => asset.localUri)),
    [open?.assets]
  );
  const prefill = useLabelPrefill(photoUris);
  const [skipped, setSkipped] = useState(false);

  // Reached directly, or after the scan was handed to the queue and the user navigated back.
  if (!open || open.assets.length === 0) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('context.noDraftTitle')}</Text>
          <Text variant="body" tone="muted">
            {t('context.noDraftBody')}
          </Text>
          <Button label={t('context.noDraftAction')} onPress={() => router.dismissTo('/(tabs)')} />
        </Card>
      </Screen>
    );
  }

  if (prefill.working && !skipped) {
    // The count being *read*, not the count captured — a gate that says five while three are in
    // flight is describing work that is not happening.
    return <PrefillGate photoCount={photoUris.length} onSkip={() => setSkipped(true)} />;
  }

  return (
    <ContextForm
      scanId={open.id}
      photoCount={open.assets.length}
      reference={{ type: open.markerType, mm: open.markerMm }}
      // Skipping past the wait means filling the form by hand, so a read that lands afterwards is
      // deliberately dropped: a form that fills itself under someone who just chose to type is
      // worse than one that never filled at all.
      suggestions={skipped ? [] : prefill.suggestions}
      readNothing={!skipped && prefill.readNothing}
    />
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  gate: { flex: 1, gap: spacing.xl, justifyContent: 'center' },
  gateBody: { textAlign: 'center' },
  gateText: { alignItems: 'center', gap: spacing.sm },
  chosenRow: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  footer: { borderTopWidth: 1, paddingTop: spacing.lg },
  intro: { gap: spacing.xs },
  quantityRow: { flexDirection: 'row', gap: spacing.md },
  quantityUnit: { flex: 1 },
  quantityValue: { flex: 2 },
  row: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  stack: { gap: spacing.xs },
  summaryRow: {
    borderRadius: radius.sm,
    gap: spacing.xs,
    paddingVertical: spacing.xs,
  },
});
