/**
 * Findings wire shapes and their mapping — `GET /v1/scans/{id}/findings` and confirm-fields.
 *
 * **`confidence` and `source` are passed through untouched, and that is the point of this file.**
 * The app reads exactly those two to decide which fields FR-06 must put in front of a human, and
 * whether a report may be generated at all (FR-08). Rounding, defaulting or dropping either moves a
 * safety decision into a mapping function, where nothing would fail and a PDF would go out over a
 * 0.41-confidence reading.
 *
 * **The summary's fourth bucket is renamed, and the fifth is kept.** The server counts
 * `pass/fail/borderline/na/not_applicable`; the app's summary has four, because there are four
 * verdicts. `not_applicable` is not a verdict — it is the *absence* of a finding for a rule that did
 * not apply — so it travels separately as `notApplicableRuleIds`, which is what lets a screen say
 * "this does not apply to you" rather than leaving a reader to wonder what is missing.
 */

import type {
  Extraction,
  ExtractionSource,
  FieldCode,
  Finding,
  FindingsResult,
  FindingsSummary,
  Measurement,
  MeasurementMethod,
  Severity,
  Verdict,
} from '@/domain';

import { orNull, toBBox, type WireBBox } from './common';

export interface WireFinding {
  finding_id?: string | null;
  rule_id: string;
  verdict: Verdict;
  severity: string;
  citation: string;
  message?: string;
  observed?: string | null;
  required?: string | null;
  band?: string | null;
  field_codes?: string[];
  bbox?: WireBBox | null;
  confidence?: number | null;
}

export interface WireExtraction {
  extraction_id: string;
  field_code: string;
  value_raw: string;
  value_norm?: string | null;
  source: ExtractionSource;
  confidence: number;
  bbox?: WireBBox | null;
  source_span?: [number, number] | null;
}

export interface WireMeasurement {
  measurement_id: string;
  field_code: string;
  glyph?: string | null;
  height_mm?: number | null;
  width_mm?: number | null;
  uncertainty_mm?: number | null;
  clear_space_mm?: number | null;
  is_numeral?: boolean;
  is_mark?: boolean;
  method?: string;
}

export interface WireFindingsSummary {
  pass?: number;
  fail?: number;
  borderline?: number;
  na?: number;
  not_applicable?: number;
}

export interface WireFindings {
  scan_id: string;
  rulepack_version: string;
  revision: number;
  evaluated_at?: string | null;
  as_of?: string | null;
  reduced_extraction?: boolean;
  findings_sha256: string;
  summary: WireFindingsSummary;
  findings?: WireFinding[];
  not_applicable_rule_ids?: string[];
  extractions?: WireExtraction[];
  measurements?: WireMeasurement[];
}

export function toSummary(wire: WireFindingsSummary): FindingsSummary {
  return {
    pass: wire.pass ?? 0,
    fail: wire.fail ?? 0,
    borderline: wire.borderline ?? 0,
    notAssessable: wire.na ?? 0,
  };
}

export function toFinding(wire: WireFinding, scanId: string, rulepackVersion: string): Finding {
  return {
    // A finding computed rather than stored — the bulk listing check — has no row to name. Falling
    // back to the rule id keeps React keys stable without pretending there is an evidence row.
    id: wire.finding_id ?? `${scanId}:${wire.rule_id}`,
    scanId,
    ruleId: wire.rule_id,
    // Stamped from the envelope. Every finding in one evaluation was judged under one pack, and the
    // server states it once rather than on every row (CLAUDE.md §3.6).
    rulepackVersion,
    verdict: wire.verdict,
    severity: wire.severity as Severity,
    required: orNull(wire.required),
    observed: orNull(wire.observed),
    band: orNull(wire.band),
    citation: wire.citation,
    message: wire.message ?? '',
    bbox: toBBox(wire.bbox),
    // Not yet served: `remediation` is neither a column nor a rule-pack field. Null renders as no
    // guidance rather than as empty guidance.
    remediation: null,
    confidence: wire.confidence ?? 0,
  };
}

export function toExtraction(wire: WireExtraction, scanId: string): Extraction {
  return {
    id: wire.extraction_id,
    scanId,
    fieldCode: wire.field_code as FieldCode,
    valueRaw: wire.value_raw,
    valueNorm: orNull(wire.value_norm),
    source: wire.source,
    // Untouched. See this module's docstring — this number gates FR-06 and FR-08.
    confidence: wire.confidence,
    bbox: toBBox(wire.bbox),
  };
}

export function toMeasurement(wire: WireMeasurement, scanId: string): Measurement {
  return {
    id: wire.measurement_id,
    scanId,
    fieldCode: wire.field_code as FieldCode,
    glyph: orNull(wire.glyph),
    heightMm: orNull(wire.height_mm),
    widthMm: orNull(wire.width_mm),
    // Null means the band could not be established. It stays null: a zero would be a claim of
    // perfect measurement and would make a reading that should read BORDERLINE look decided.
    uncertaintyMm: orNull(wire.uncertainty_mm),
    method: (wire.method || 'unavailable') as MeasurementMethod,
  };
}

export function toFindingsResult(wire: WireFindings): FindingsResult {
  const scanId = wire.scan_id;
  return {
    scanId,
    rulepackVersion: wire.rulepack_version,
    findingsSha256: wire.findings_sha256,
    reducedExtraction: wire.reduced_extraction ?? false,
    summary: toSummary(wire.summary),
    findings: (wire.findings ?? []).map((f) => toFinding(f, scanId, wire.rulepack_version)),
    notApplicableRuleIds: wire.not_applicable_rule_ids ?? [],
    extractions: (wire.extractions ?? []).map((e) => toExtraction(e, scanId)),
    measurements: (wire.measurements ?? []).map((m) => toMeasurement(m, scanId)),
  };
}
