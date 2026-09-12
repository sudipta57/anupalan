/**
 * The history list and its filters — FR-09.
 *
 * *Accept: filtering 200 seeded scans by `verdict=FAIL` returns only scans with ≥1 FAIL, within
 * 500 ms.*
 *
 * One component, rendered by two screens. Mode A reaches it through **Inspections** and Mode B through
 * **History**; they are the same list of past scans with different framing and one real difference —
 * the district filter, which Mode B is not offered because Mode B collects no location at all
 * (`01-architecture.md` §10). Building it twice would have meant two places to forget that.
 *
 * Three things make the acceptance criterion hold rather than hoping it does:
 *
 * - **`FlatList` with `getItemLayout`.** The row height is a constant exported by `ScanRow`, so the
 *   list can place any row without measuring it. Without that, two hundred rows are measured on every
 *   scroll and the stutter is impossible to attribute afterwards.
 * - **Filtering happens server-side**, through `toQuery`. The client never holds all 220 rows and
 *   never filters them in JS, so the cost does not grow with the archive.
 * - **A filter is never silently partial.** The bar always states how many filters are narrowing the
 *   list, because a list showing a fraction of the data and looking like all of it is how someone
 *   concludes a scan was lost and re-photographs a pack.
 *
 * It lives in `features/` rather than `components/` because it owns queries and filter state;
 * `ScanRow` is the presentational half and lives with the other components.
 */

import { router } from 'expo-router';
import { useCallback, useState } from 'react';
import { FlatList, StyleSheet, View } from 'react-native';

import { useProducts, useScans } from '@/api';
import {
  Banner,
  Button,
  Card,
  Chip,
  EmptyState,
  Field,
  ScanRow,
  Screen,
  Skeleton,
  Text,
} from '@/components';
import { SCAN_ROW_HEIGHT } from '@/components/scan-row';
import { VERDICT_DISPLAY_ORDER, type ScanListItem, type ScanStatus, type Verdict } from '@/domain';
import { useT, type TranslationKey } from '@/i18n';
import { useOrgMode } from '@/store/session';
import { spacing } from '@/theme';

import {
  NO_FILTERS,
  activeCount,
  isFiltered,
  showsDistrictFilter,
  toQuery,
  toggleDistrict,
  toggleProduct,
  toggleVerdict,
  type HistoryFilters,
} from './filters';
import { PRESET_LABEL_KEYS, RANGE_PRESETS, dayLabel, presetFor, rangeFor } from './presets';

/** Districts the enforcement org covers. A real deployment reads these from the org. */
const DISTRICTS = ['Nadia', 'North 24 Parganas', 'Hooghly', 'Kolkata', 'Howrah'];

const VERDICT_LABEL_KEYS: Record<Verdict, TranslationKey> = {
  PASS: 'verdict.pass',
  FAIL: 'verdict.fail',
  BORDERLINE: 'verdict.borderline',
  NOT_ASSESSABLE: 'verdict.notAssessable',
};

/** Only unfinished states are labelled. A complete scan's row is about its verdicts, not its status. */
const STATUS_LABEL_KEYS: Partial<Record<ScanStatus, TranslationKey>> = {
  captured: 'queue.statusCaptured',
  queued: 'queue.statusQueued',
  uploading: 'queue.statusUploading',
  processing: 'queue.statusProcessing',
  failed: 'queue.statusFailed',
};

export interface ScanListProps {
  /** Copy for the screen this is embedded in — the framing differs by mode, the list does not. */
  subtitleKey: TranslationKey;
  emptyKey: TranslationKey;
  emptyBodyKey: TranslationKey;
}

export function ScanList({ subtitleKey, emptyKey, emptyBodyKey }: ScanListProps) {
  const t = useT();
  const mode = useOrgMode();

  const [filters, setFilters] = useState<HistoryFilters>(NO_FILTERS);
  const [open, setOpen] = useState(false);

  // Read once per mount rather than from a ticking clock. "Today" changing under a scrolled list at
  // midnight would be a stranger bug than a label that is one render stale.
  const [now] = useState(() => Date.now());

  const scans = useScans(toQuery(filters, mode));
  const products = useProducts();

  const items: ScanListItem[] = scans.data?.pages.flatMap((page) => page.items) ?? [];
  const count = activeCount(filters, mode);
  const preset = presetFor(filters, now);

  const renderItem = useCallback(
    ({ item }: { item: ScanListItem }) => {
      const label = dayLabel(item.capturedAt, now);
      const statusKey = STATUS_LABEL_KEYS[item.status];

      return (
        <ScanRow
          item={item}
          dateLabel={
            label.kind === 'date'
              ? label.value
              : label.kind === 'today'
                ? t('history.today')
                : t('history.yesterday')
          }
          statusLabel={statusKey ? t(statusKey) : null}
          onPress={() => router.push(`/scan/${item.id}`)}
        />
      );
    },
    [now, t]
  );

  return (
    <Screen>
      <FlatList
        data={items}
        renderItem={renderItem}
        keyExtractor={(item) => item.id}
        // Fixed-height rows, so the list never measures one. This is what keeps 220 rows smooth.
        getItemLayout={(_data, index) => ({
          length: SCAN_ROW_HEIGHT,
          offset: SCAN_ROW_HEIGHT * index,
          index,
        })}
        initialNumToRender={10}
        windowSize={7}
        removeClippedSubviews
        onEndReachedThreshold={0.6}
        onEndReached={() => {
          if (scans.hasNextPage && !scans.isFetchingNextPage) void scans.fetchNextPage();
        }}
        contentContainerStyle={styles.content}
        ListHeaderComponent={
          <View style={styles.header}>
            <Text variant="body" tone="muted">
              {t(subtitleKey)}
            </Text>

            <Field
              label={t('history.search')}
              value={filters.query}
              onChangeText={(query) => setFilters((current) => ({ ...current, query }))}
              placeholder={t('history.searchPlaceholder')}
              autoCapitalize="none"
            />

            <View style={styles.barRow}>
              <Button
                label={count > 0 ? t('history.filtersActive', { count }) : t('history.filters')}
                variant="secondary"
                onPress={() => setOpen((value) => !value)}
              />
              {isFiltered(filters, mode) ? (
                <Button
                  label={t('history.clear')}
                  variant="ghost"
                  onPress={() => setFilters(NO_FILTERS)}
                />
              ) : null}
            </View>

            {open ? (
              <Card>
                <Text variant="label" tone="muted">
                  {t('history.filterVerdict')}
                </Text>
                {/* One verdict at a time. A multi-select here would let someone ask for
                    "FAIL and BORDERLINE" and read the answer as a count of problems, which is
                    exactly the collapse CLAUDE.md §3.4 forbids. */}
                <View style={styles.chips}>
                  {VERDICT_DISPLAY_ORDER.map((verdict) => (
                    <Chip
                      key={verdict}
                      label={t(VERDICT_LABEL_KEYS[verdict])}
                      tone={filters.verdict === verdict ? 'brand' : 'neutral'}
                      selected={filters.verdict === verdict}
                      onPress={() => setFilters((current) => toggleVerdict(current, verdict))}
                    />
                  ))}
                </View>
                <Text variant="caption" tone="subtle">
                  {t('history.filterVerdictHint')}
                </Text>

                <Text variant="label" tone="muted">
                  {t('history.filterRange')}
                </Text>
                <View style={styles.chips}>
                  {RANGE_PRESETS.map((value) => (
                    <Chip
                      key={value}
                      label={t(PRESET_LABEL_KEYS[value])}
                      tone={preset === value ? 'brand' : 'neutral'}
                      selected={preset === value}
                      onPress={() =>
                        setFilters((current) => ({ ...current, ...rangeFor(value, now) }))
                      }
                    />
                  ))}
                </View>

                <Text variant="label" tone="muted">
                  {t('history.filterProduct')}
                </Text>
                <View style={styles.chips}>
                  {(products.data?.items ?? []).map((product) => (
                    <Chip
                      key={product.id}
                      label={product.profile.name}
                      tone={filters.productId === product.id ? 'brand' : 'neutral'}
                      selected={filters.productId === product.id}
                      onPress={() => setFilters((current) => toggleProduct(current, product.id))}
                    />
                  ))}
                </View>

                {/* Mode A only. Mode B collects no location, so a district filter there would return
                    nothing for every value and read as a broken search. */}
                {showsDistrictFilter(mode) ? (
                  <>
                    <Text variant="label" tone="muted">
                      {t('history.filterDistrict')}
                    </Text>
                    <View style={styles.chips}>
                      {DISTRICTS.map((district) => (
                        <Chip
                          key={district}
                          label={district}
                          tone={filters.district === district ? 'brand' : 'neutral'}
                          selected={filters.district === district}
                          onPress={() => setFilters((current) => toggleDistrict(current, district))}
                        />
                      ))}
                    </View>
                  </>
                ) : null}
              </Card>
            ) : null}

            {scans.isError ? <Banner tone="error" title={t('errors.generic')} /> : null}
          </View>
        }
        ListEmptyComponent={
          scans.isPending ? (
            <View style={styles.header}>
              <Skeleton height={SCAN_ROW_HEIGHT} />
              <Skeleton height={SCAN_ROW_HEIGHT} />
              <Skeleton height={SCAN_ROW_HEIGHT} />
            </View>
          ) : (
            // Two different empty states: nothing recorded yet, versus nothing matching. They look
            // the same and mean opposite things, and only one of them has an action.
            <EmptyState
              title={count > 0 ? t('history.noMatches') : t(emptyKey)}
              body={count > 0 ? t('history.noMatchesBody') : t(emptyBodyKey)}
              action={
                count > 0 ? (
                  <Button label={t('history.clear')} onPress={() => setFilters(NO_FILTERS)} />
                ) : undefined
              }
            />
          )
        }
        ListFooterComponent={
          scans.isFetchingNextPage ? <Skeleton height={SCAN_ROW_HEIGHT} /> : null
        }
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  barRow: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  content: { gap: 0, paddingBottom: spacing.xl },
  header: { gap: spacing.md, paddingBottom: spacing.md },
});
