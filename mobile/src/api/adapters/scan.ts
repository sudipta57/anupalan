/**
 * Scan wire shapes and their mapping — `POST /v1/scans`, `GET /v1/scans`, `GET /v1/scans/{id}`.
 *
 * Three translations here are decisions rather than renames, and each is written down because the
 * wrong one is invisible:
 *
 * **The status vocabularies differ, and `no_marker` is the one that bites.** The server has
 * `created` and `no_marker`; the app has the offline queue's local `captured` and `uploading`, which
 * never come from a server. `no_marker` is mapped to `complete` **plus a `no_marker` issue**, because
 * `01-architecture.md` §11 calls such a run degraded *but final* — it has real findings, with every
 * metric rule already NOT_ASSESSABLE. Leaving it as its own terminal status would strand the queue:
 * `features/queue/runner.ts` moves a row out of `processing` only on `complete` or `failed`, so the
 * scan would sit there for ever and the pending badge would never clear.
 *
 * **The marker names differ and the server's are better.** `aruco_4x4_50` names the ArUco dictionary
 * that `make-marker-sheet.py` and the backend's chart generator must agree on; the 40 mm lives in
 * `markerMm`, where it belongs, because an ID-1 card is a different number. The app renames inward
 * and outward so the wire keeps the precise name.
 *
 * **The profile is flat on the wire and nested in the app.** `net_qty_value` and `net_qty_unit`
 * become one `netQuantity`, because a value without its unit is not half a quantity — it is a
 * number that means nothing, and the rule pack keys Table-I on the pair.
 */

import type {
  AssetKind,
  GeoPoint,
  MarkerType,
  NetQuantityUnit,
  PackType,
  ProductProfile,
  QtyBasis,
  SalesChannel,
  Scan,
  ScanAsset,
  ScanIssue,
  ScanListItem,
  ScanStatus,
  Surface,
} from '@/domain';

import { orNull } from './common';

// ------------------------------------------------------------------ wire shapes

export interface WireProfile {
  is_imported?: boolean;
  surface?: string;
  qty_basis?: string;
  channel?: string;
  net_qty_in_g_or_ml?: number | null;
  pdp_area_cm2?: number | null;
  net_qty_value?: number | null;
  net_qty_unit?: string | null;
  pack_type?: string | null;
  category_code?: string | null;
  name?: string | null;
}

export interface WireGeo {
  latitude: number;
  longitude: number;
  accuracy_m?: number | null;
}

export interface WireAsset {
  asset_id: string;
  kind: AssetKind;
  sha256: string;
  content_type?: string | null;
  width_px?: number | null;
  height_px?: number | null;
  px_per_mm?: number | null;
  url?: string | null;
}

export type WireScanStatus =
  | 'created'
  | 'queued'
  | 'processing'
  | 'needs_confirmation'
  | 'complete'
  | 'failed'
  | 'no_marker';

export type WireMarkerType = 'aruco_4x4_50' | 'id1_card' | 'user_declared';

export interface WireScan {
  scan_id: string;
  org_id: string;
  user_id?: string | null;
  status: WireScanStatus;
  captured_at: string;
  marker_type: WireMarkerType;
  marker_mm: number;
  product_id?: string | null;
  profile: WireProfile;
  geo?: WireGeo | null;
  district?: string | null;
  error?: string | null;
  assets?: WireAsset[];
}

export interface WireScanListItem {
  scan_id: string;
  product_id?: string | null;
  product_name?: string | null;
  status: WireScanStatus;
  captured_at: string;
  district?: string | null;
  thumbnail_url?: string | null;
  summary?: { pass?: number; fail?: number; borderline?: number; na?: number };
}

export interface WireScanPage {
  items?: WireScanListItem[];
  next_cursor?: string | null;
}

export interface WireUploadTarget {
  asset_id: string;
  key: string;
  url: string;
  headers: Record<string, string>;
  max_bytes: number;
  expires_in: number;
}

export interface WireScanCreated {
  scan_id: string;
  status: WireScanStatus;
  uploads: WireUploadTarget[];
}

// ------------------------------------------------------------------ vocabularies

/**
 * Server status to the app's.
 *
 * `created` means the scan exists but was never submitted, which from the phone's point of view is
 * still waiting to go — `queued` is the app's word for that. `no_marker` is handled by the caller,
 * which also raises the issue; mapping it here alone would lose the reason.
 */
const STATUS: Record<WireScanStatus, ScanStatus> = {
  created: 'queued',
  queued: 'queued',
  processing: 'processing',
  // Not `processing`: the server has finished and is waiting on a person. Mapping it to
  // `processing` would leave the queue polling forever for a change only the user can make.
  needs_confirmation: 'needs_confirmation',
  complete: 'complete',
  failed: 'failed',
  no_marker: 'complete',
};

const MARKER_IN: Record<WireMarkerType, MarkerType> = {
  aruco_4x4_50: 'aruco_40mm',
  id1_card: 'id1_card',
  user_declared: 'user_dimension',
};

const MARKER_OUT: Record<MarkerType, WireMarkerType> = {
  aruco_40mm: 'aruco_4x4_50',
  id1_card: 'id1_card',
  user_dimension: 'user_declared',
};

export function toMarkerType(wire: WireMarkerType): MarkerType {
  return MARKER_IN[wire];
}

export function fromMarkerType(marker: MarkerType): WireMarkerType {
  return MARKER_OUT[marker];
}

export function toScanStatus(wire: WireScanStatus): ScanStatus {
  return STATUS[wire];
}

/**
 * What the scan alone says went wrong.
 *
 * Only `no_marker` is knowable from a scan. `reduced_extraction` and `low_confidence_fields` live in
 * the findings, and `features/processing/degradation.ts` merges them in where both are to hand —
 * rather than this function guessing at data it has not been given.
 */
export function issuesOf(wire: Pick<WireScan, 'status'>): ScanIssue[] {
  return wire.status === 'no_marker' ? ['no_marker'] : [];
}

// ------------------------------------------------------------------ profile

export function toProfile(wire: WireProfile): ProductProfile {
  return {
    name: wire.name ?? '',
    categoryCode: wire.category_code ?? '',
    packType: (wire.pack_type ?? 'other') as PackType,
    surface: (wire.surface ?? 'printed') as Surface,
    isImported: wire.is_imported ?? false,
    qtyBasis: (wire.qty_basis ?? 'weight_or_volume') as QtyBasis,
    netQuantity: {
      // Zero is the app's own "not stated" for a quantity, and `context`'s form is what stops a
      // scan reaching the server without one. Never read it as a declared quantity of nothing.
      value: wire.net_qty_value ?? 0,
      unit: (wire.net_qty_unit ?? 'g') as NetQuantityUnit,
    },
    channel: (wire.channel ?? 'retail') as SalesChannel,
    pdpAreaCm2: orNull(wire.pdp_area_cm2),
  };
}

export function fromProfile(profile: ProductProfile): WireProfile {
  return {
    is_imported: profile.isImported,
    surface: profile.surface,
    qty_basis: profile.qtyBasis,
    channel: profile.channel,
    // The rule pack keys Table-I on this, and it is the *normalised* figure rather than whatever
    // unit the operator typed — `features/context` does the conversion, not this function.
    net_qty_in_g_or_ml: normaliseToGramsOrMillilitres(profile),
    pdp_area_cm2: profile.pdpAreaCm2,
    net_qty_value: profile.netQuantity.value,
    net_qty_unit: profile.netQuantity.unit,
    pack_type: profile.packType,
    category_code: profile.categoryCode,
    name: profile.name,
  };
}

/** Multipliers to grams or millilitres. Mass and volume only — Table-I keys on nothing else. */
const TO_BASE: Partial<Record<NetQuantityUnit, number>> = {
  g: 1,
  kg: 1000,
  ml: 1,
  l: 1000,
  L: 1000,
};

/**
 * The Table-I key, or null.
 *
 * Null for a pack measured in length, area or number: Rule 9's Table-I does not key on those, and
 * sending a zero would look like a declared quantity of nothing rather than an inapplicable table.
 */
export function normaliseToGramsOrMillilitres(profile: ProductProfile): number | null {
  const factor = TO_BASE[profile.netQuantity.unit];
  if (factor === undefined) return null;
  return profile.netQuantity.value * factor;
}

// ------------------------------------------------------------------ scans

export function toGeo(wire: WireGeo | null | undefined): GeoPoint | null {
  if (!wire) return null;
  return {
    latitude: wire.latitude,
    longitude: wire.longitude,
    // The app's type wants a number; an unknown radius is reported as 0, which `capture` already
    // treats as "no accuracy stated" when it decides whether to show a precision warning.
    accuracyM: wire.accuracy_m ?? 0,
  };
}

export function toAsset(wire: WireAsset, scanId: string): ScanAsset {
  return {
    id: wire.asset_id,
    scanId,
    kind: wire.kind,
    // A private bucket means the only read path is a presigned URL, and it can be absent when
    // storage is unreachable. An empty string is the app's "nothing to show here".
    uri: wire.url ?? '',
    // Zero, which `features/findings/viewport.ts` already treats as unmeasurable: `fitScale`
    // returns 0 and the scale bar disappears rather than being drawn at a made-up size.
    widthPx: wire.width_px ?? 0,
    heightPx: wire.height_px ?? 0,
    pxPerMm: orNull(wire.px_per_mm),
    sha256: orNull(wire.sha256),
  };
}

export function toScan(wire: WireScan): Scan {
  return {
    id: wire.scan_id,
    orgId: wire.org_id,
    productId: orNull(wire.product_id),
    userId: wire.user_id ?? '',
    status: toScanStatus(wire.status),
    // The server publishes no pipeline stage, and the progress screen renders null as "the server
    // has not said" rather than guessing one from elapsed time (flag 19).
    pipelineStage: null,
    profile: toProfile(wire.profile),
    markerType: toMarkerType(wire.marker_type),
    markerMm: wire.marker_mm,
    capturedAt: wire.captured_at,
    geo: toGeo(wire.geo),
    district: orNull(wire.district),
    // Set once the reports endpoint can say so; until then no report locks editing (flag 22).
    reportIssuedAt: null,
    issues: issuesOf(wire),
    assets: (wire.assets ?? []).map((asset) => toAsset(asset, wire.scan_id)),
  };
}

export function toScanListItem(wire: WireScanListItem): ScanListItem {
  const summary = wire.summary ?? {};
  return {
    id: wire.scan_id,
    orgId: '',
    productId: orNull(wire.product_id),
    productName: wire.product_name ?? '',
    status: toScanStatus(wire.status),
    capturedAt: wire.captured_at,
    district: orNull(wire.district),
    summary: {
      pass: summary.pass ?? 0,
      fail: summary.fail ?? 0,
      borderline: summary.borderline ?? 0,
      // The one rename in the summary: the server's fourth bucket is `na`.
      notAssessable: summary.na ?? 0,
    },
    thumbnailUri: orNull(wire.thumbnail_url),
  };
}
