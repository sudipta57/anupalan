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
 * The scale reference comes from the **open scan row**, not from the marker store — see
 * `src/db/queue-repo.ts` for why reading the live setting at submit time would mislabel the scan.
 *
 * **Submitting does not upload.** It attaches the context and hands the scan to the offline queue
 * (`captured → queued`), which returns immediately and succeeds in airplane mode. That is FR-04's
 * whole point: an inspector in a market with no signal must be able to finish a scan and walk to the
 * next shop. The network is the queue's problem, not this screen's.
 */

import { router } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { StyleSheet, View } from 'react-native';

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
  searchCategories,
  useScanLocation,
  wasRewritten,
  type ContextFormValues,
  type ScanLocation,
} from '@/features/scan-context';
import * as repo from '@/db/queue-repo';
import { kick, useOpenCapture } from '@/features/queue';
import { useT, type TranslationKey } from '@/i18n';
import { useOrgMode } from '@/store/session';
import { spacing, useTheme } from '@/theme';

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
}: {
  value: string;
  onChange: (code: string) => void;
  error?: string;
}) {
  const t = useT();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(value.length === 0);

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
          {chosen.code}
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
  const { colors } = useTheme();

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
          {rows.map((row, index) => (
            <View
              key={row.label}
              style={[
                styles.summaryRow,
                { borderTopColor: index > 0 ? colors.border : 'transparent' },
              ]}
            >
              <Text variant="label" tone="muted">
                {row.label}
              </Text>
              <Text variant="bodyStrong">{row.value}</Text>
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
}: {
  scanId: string;
  photoCount: number;
  reference: MarkerReference;
}) {
  const t = useT();
  const { colors } = useTheme();
  const mode = useOrgMode();

  const location = useScanLocation();

  const [created, setCreated] = useState<{ scanId: string; profile: ProductProfile } | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<ContextFormValues>({
    defaultValues: defaultContextValues(mode),
    mode: 'onTouched',
  });

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

  /**
   * Attach the context and hand the scan to the queue.
   *
   * Local and synchronous: no network call, so it works in airplane mode and cannot fail for want of
   * a signal. `kick()` only wakes the runner early if there happens to be a connection.
   */
  const submit = useCallback(
    (values: ContextFormValues) => {
      setSubmitError(null);

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
    [location.point, mode, reference, scanId, t]
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
                  onChangeText={field.onChange}
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
                onChange={(next) => field.onChange(next === 'imported')}
                accessibilityLabel={t('context.importedLabel')}
              />
              <Text variant="caption" tone="subtle">
                {t('context.importedHint')}
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

export default function ScanContextScreen() {
  const t = useT();
  const open = useOpenCapture();

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

  return (
    <ContextForm
      scanId={open.id}
      photoCount={open.assets.length}
      reference={{ type: open.markerType, mm: open.markerMm }}
    />
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chosenRow: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  footer: { borderTopWidth: 1, paddingTop: spacing.lg },
  intro: { gap: spacing.xs },
  quantityRow: { flexDirection: 'row', gap: spacing.md },
  quantityUnit: { flex: 1 },
  quantityValue: { flex: 2 },
  row: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  stack: { gap: spacing.xs },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    gap: spacing.md,
    paddingVertical: spacing.sm,
  },
});
