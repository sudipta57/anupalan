/**
 * Sahayak — the BIS and Indian Standards assistant (SIH26107).
 *
 * Two refusals are designed behaviours, not gaps (CLAUDE.md §3.5):
 *
 * - **No supporting source** → `not_found`, with a link to the relevant official page. Never a
 *   fabricated citation.
 * - **Technical content of a standard asked for** → `refused_priced_content`. Full IS texts are
 *   copyrighted and sold by BIS; the answer points at the purchase route instead.
 */

import type { IsoDate } from './common';
import type { ProductProfile } from './product';

export type SourceType =
  | 'qco_gazette'
  | 'isi_product_list'
  | 'crs_product_list'
  | 'scheme_guide'
  | 'faq'
  | 'hallmarking'
  | 'lab_directory'
  | 'catalogue_metadata';

export interface Citation {
  id: string;
  title: string;
  url: string;
  sourceType: SourceType;
  /** Which part of the document supports the claim. */
  section: string | null;
  publishedAt: IsoDate | null;
}

export type AnswerOutcome = 'answered' | 'not_found' | 'refused_priced_content';

export interface SahayakAnswer {
  id: string;
  question: string;
  outcome: AnswerOutcome;
  answer: string;
  citations: Citation[];
  confidence: number;
  /** QCOs are amended constantly, so an answer states how fresh its sources are. */
  asOf: IsoDate;
}

export type QcoApplicable = 'yes' | 'no' | 'unclear';

/** ISI is the mark scheme, CRS the electronics registration route, FMCS the foreign route. */
export type BisScheme = 'ISI' | 'CRS' | 'FMCS' | 'none';

export interface BisApplicability {
  profile: ProductProfile;
  qcoApplicable: QcoApplicable;
  scheme: BisScheme;
  candidateIsNumbers: string[];
  nextSteps: string[];
  sources: Citation[];
  asOf: IsoDate;
}
