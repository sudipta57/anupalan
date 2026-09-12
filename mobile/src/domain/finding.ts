/**
 * Extractions, measurements and findings — the output of a scan.
 *
 * A finding is one rule's verdict for one scan. Every one of them carries the rule pack version
 * it was evaluated under (CLAUDE.md §3.6), so a report regenerated next year reproduces the
 * verdict issued under the rules in force at scan time.
 */

import type { BBox, Millimetres } from './common';
import type { Severity, Verdict } from './verdict';

/** The fifteen field codes the extractor recognises (TRD FR-24). */
export const FIELD_CODES = [
  'manufacturer_name',
  'manufacturer_address',
  'packer_name',
  'importer_name',
  'importer_address',
  'country_of_origin',
  'common_name',
  'net_quantity',
  'mrp',
  'mfg_month_year',
  'consumer_care_name',
  'consumer_care_phone',
  'consumer_care_email',
  'unit_sale_price',
  'best_before',
] as const;

export type FieldCode = (typeof FIELD_CODES)[number];

/**
 * Where a field value came from.
 *
 * The order is the pipeline order: regex first, LLM for what regex missed, human confirmation
 * for anything below the confidence threshold. The LLM proposes values; it never decides
 * compliance (CLAUDE.md §3.1).
 */
export type ExtractionSource = 'regex' | 'llm' | 'human';

export interface Extraction {
  id: string;
  scanId: string;
  fieldCode: FieldCode;
  /** Exactly as it appeared on the pack. */
  valueRaw: string;
  /** Normalised — units resolved, dates parsed. Null when normalisation failed. */
  valueNorm: string | null;
  source: ExtractionSource;
  /** 0–1. Below 0.75 the field goes to the FR-06 confirmation sheet before any verdict. */
  confidence: number;
  bbox: BBox | null;
}

/**
 * How a measurement was obtained.
 *
 * `connected_components` is the real path: OCR polygons include ascenders, descenders and
 * padding, so they are not glyph heights (CLAUDE.md §8).
 */
export type MeasurementMethod = 'connected_components' | 'assisted' | 'unavailable';

export interface Measurement {
  id: string;
  scanId: string;
  fieldCode: FieldCode;
  /** The glyph measured, where the rule is about one glyph. */
  glyph: string | null;
  heightMm: Millimetres | null;
  widthMm: Millimetres | null;
  /** Half-width of the uncertainty band. A result within this of the threshold is BORDERLINE. */
  uncertaintyMm: Millimetres;
  method: MeasurementMethod;
}

export interface Finding {
  id: string;
  scanId: string;
  /** e.g. `LM-9-2-TABLE1`. Matches an id in the rule pack. */
  ruleId: string;
  /** e.g. `LM-2011-v1.0`. Never absent (CLAUDE.md §3.6). */
  rulepackVersion: string;
  verdict: Verdict;
  severity: Severity;
  /** What the pack requires, already rendered for display — e.g. `4.0 mm`. */
  required: string | null;
  /** What was observed — e.g. `4.60 mm`. Null when NOT_ASSESSABLE. */
  observed: string | null;
  /**
   * The uncertainty band printed alongside a BORDERLINE verdict, e.g. `1.80–2.30 mm`. A
   * BORDERLINE without its band is an unexplained accusation.
   */
  band: string | null;
  /** The legal citation, verbatim from the rule pack. Shown without leaving the screen (FR-05). */
  citation: string;
  /** Plain-language explanation of the verdict. */
  message: string;
  /** Where on the rectified image this finding is. Null for rules with no visual anchor. */
  bbox: BBox | null;
  /** Mode B only: what to change on the artwork to pass. */
  remediation: string | null;
  confidence: number;
}

/** Counts per verdict. Four numbers, because there are four verdicts. */
export interface FindingsSummary {
  pass: number;
  fail: number;
  borderline: number;
  notAssessable: number;
}

export interface FindingsResult {
  scanId: string;
  rulepackVersion: string;
  /**
   * SHA-256 over the findings blob, as embedded in a report (`01-architecture.md` §10).
   *
   * Present on the findings themselves, not only on a generated report, because Mode A's evidence
   * panel has to show it **before** anyone asks for a PDF — that is the point at which an inspector
   * decides whether to issue one. See flag 21 in `docs/05-frontend-plan.md`.
   */
  findingsSha256: string;
  summary: FindingsSummary;
  findings: Finding[];
  extractions: Extraction[];
  measurements: Measurement[];
}
