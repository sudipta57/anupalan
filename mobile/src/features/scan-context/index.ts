/**
 * Product context — **TRD FR-03**.
 *
 * The form between a photograph and a scan. Three of its fields decide which rules run at all, so
 * FR-03's acceptance is that net quantity, the imported flag and the surface type are present on
 * every completed scan — see `profile.ts` for the table of what each one changes, and
 * `assertRuleRelevantFields` for the runtime guard that refuses a scan without them.
 *
 * The module is almost entirely pure:
 *
 * | File | What it decides |
 * |---|---|
 * | `units.ts` | What a typed unit means, and which Rule 9 table it implies. |
 * | `categories.ts` | The coded category list — the hinge between Legal Metrology and BIS. |
 * | `profile.ts` | Form values in, `ProductProfile` out, plus the FR-03 choke point. |
 * | `prefill.ts` | What a read label may fill in, and what it may never fill in. |
 * | `use-prefill.ts` | The only file that talks to `expo-image-manipulator`. |
 * | `geo.ts` | Whether this org's mode collects location. Mode B never does. |
 * | `use-location.ts` | The only file that talks to `expo-location`. |
 *
 * `app/scan-context.tsx` is a thin layer over these, which is what lets the rule-relevant logic be
 * tested without rendering a screen.
 */

export { CATEGORIES, CATEGORIES_BY_CODE, categoryFor, searchCategories } from './categories';
export type { Category } from './categories';

export {
  GEO_ACCURACY_WARN_M,
  collectsLocation,
  districtForScan,
  formatGeo,
  geoForScan,
  isLooseFix,
  toGeoPoint,
} from './geo';
export type { PositionLike } from './geo';

export {
  RULE_RELEVANT,
  UNSURE_BELOW,
  anyFilled,
  applySuggestions,
  suggestCategory,
  unconfirmedRuleFields,
} from './prefill';
export type { AppliedPrefill, PrefillResult, PrefillStatus, Suggestion } from './prefill';

export {
  COMPRESS,
  MAX_EDGE_PX,
  MAX_PREFILL_IMAGES,
  TIMEOUT_BASE_MS,
  TIMEOUT_CEILING_MS,
  TIMEOUT_PER_IMAGE_MS,
  downscaleForPrefill,
  photographsToRead,
  timeoutFor,
  useLabelPrefill,
} from './use-prefill';
export type { PrefillState } from './use-prefill';

export {
  CHANNELS,
  IncompleteProfileError,
  MAX_NAME_LENGTH,
  MAX_PDP_AREA_CM2,
  MAX_QUANTITY_VALUE,
  PACK_TYPES,
  SURFACES,
  assertRuleRelevantFields,
  buildProfile,
  buildQuantity,
  defaultContextValues,
  isValidName,
  isValidPdpArea,
  isValidQuantityValue,
  parseDecimal,
  pdpAreaRequired,
} from './profile';
export type { BuiltQuantity, ContextFormValues, Option } from './profile';

export {
  LENGTH_AREA_OR_NUMBER_UNITS,
  NET_QUANTITY_UNITS,
  WEIGHT_OR_VOLUME_UNITS,
  basisForUnit,
  formatQuantity,
  normaliseUnit,
  requiresPdpArea,
  wasRewritten,
} from './units';

export { useScanLocation } from './use-location';
export type { LocationState, ScanLocation } from './use-location';
