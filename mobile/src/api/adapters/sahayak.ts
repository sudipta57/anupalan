/**
 * Sahayak and BIS wire shapes — `POST /v1/sahayak/ask`, `POST /v1/bis/applicability`.
 *
 * **The outcome is derived here, and getting it wrong would defeat the design.** The server reports
 * `refused` plus a reason; the app has a three-valued `outcome` because its screen behaves
 * differently for each. The mapping is deliberate:
 *
 * - `refused` → `refused_priced_content`. The technical content of an Indian Standard is copyrighted
 *   and sold by BIS, and the refusal is a feature (CLAUDE.md §3.5).
 * - answered **with no citation left standing** → `not_found`. Not `answered`. An answer with no
 *   supporting source is exactly what a fabricated citation looks like after the client's host
 *   allow-list has done its work, and presenting its prose would be presenting an unsourced claim
 *   about the law.
 * - otherwise → `answered`.
 *
 * `qco_applicable` carries `unclear` on the wire, which answers flag 27: the three-stance design
 * survives the trip. It must never be collapsed to `no`, because `no` renders as "certification is
 * not required" — a clearance — and an unresolved lookup is not a clearance.
 */

import type {
  AnswerOutcome,
  BisApplicability,
  BisScheme,
  Citation,
  ProductProfile,
  QcoApplicable,
  SahayakAnswer,
  SourceType,
} from '@/domain';

import { orNull } from './common';
import { toProfile, type WireProfile } from './scan';

export interface WireCitation {
  chunk_id: string;
  document_id: string;
  title: string;
  url: string;
  section?: string | null;
  published_at?: string | null;
  source_type?: string | null;
}

export interface WireSource {
  title: string;
  url: string;
}

export interface WireAnswer {
  answer: string;
  citations?: WireCitation[];
  confidence?: number | null;
  as_of?: string | null;
  refused?: boolean;
  refusal_reason?: string | null;
  sources?: WireSource[];
  disclaimer: string;
}

export interface WireApplicability {
  qco_applicable: QcoApplicable;
  scheme: BisScheme;
  candidate_is_numbers?: string[];
  next_steps?: string[];
  sources?: WireCitation[];
  matched_entry_id?: string | null;
  matched_on?: string;
  order?: string | null;
  notes?: string | null;
  forthcoming?: string[];
  lists_version: string;
  as_of?: string | null;
  disclaimer: string;
}

/**
 * What kind of official document a citation is.
 *
 * The server does not classify its corpus in the response, so this reads the URL — the same
 * evidence the client's host allow-list already relies on. `catalogue_metadata` is the fallback
 * because it is the weakest claim of the eight: describing a document rather than quoting one.
 */
export function sourceTypeOf(url: string, declared?: string | null): SourceType {
  if (declared) return declared as SourceType;

  const lower = url.toLowerCase();
  if (lower.includes('egazette') || lower.includes('qco')) return 'qco_gazette';
  if (lower.includes('crs') || lower.includes('registration')) return 'crs_product_list';
  if (lower.includes('hallmark')) return 'hallmarking';
  if (lower.includes('lab')) return 'lab_directory';
  if (lower.includes('faq')) return 'faq';
  if (lower.includes('isi') || lower.includes('mandatory')) return 'isi_product_list';
  if (lower.includes('scheme') || lower.includes('guide')) return 'scheme_guide';
  return 'catalogue_metadata';
}

export function toCitation(wire: WireCitation): Citation {
  return {
    id: wire.chunk_id,
    title: wire.title,
    url: wire.url,
    sourceType: sourceTypeOf(wire.url, wire.source_type),
    section: orNull(wire.section),
    publishedAt: orNull(wire.published_at),
  };
}

/**
 * The server's refusal reasons, and which of the app's three outcomes each is.
 *
 * Read from `refusal_reason`, not from whether any citation came back. A not-found answer *does*
 * carry a link — the official page to go and read — so counting citations would classify it as
 * answered and publish prose that no source supports as though it were sourced.
 *
 * Only `priced_standard_content` is the copyright refusal. The other four are all "we could not
 * stand this up", which the app presents as not-found: the honest thing to show is the official
 * page, not an explanation of which internal check declined.
 */
const REFUSAL_OUTCOME: Record<string, AnswerOutcome> = {
  priced_standard_content: 'refused_priced_content',
  no_supporting_source: 'not_found',
  unsupported_claim: 'not_found',
  fabricated_citation: 'not_found',
  assistant_unavailable: 'not_found',
};

export function outcomeOf(wire: WireAnswer): AnswerOutcome {
  if (!wire.refused) return 'answered';
  // An unrecognised reason is still a refusal. Falling through to `answered` would publish the
  // refusal text as though it were an answer.
  return REFUSAL_OUTCOME[wire.refusal_reason ?? ''] ?? 'not_found';
}

/**
 * The official pages offered alongside a refusal, as citations.
 *
 * The server keeps them apart — `citations` support a claim, `sources` are places to look — and the
 * app shows one list. They are kept distinguishable by construction: a source has no chunk to point
 * at, so its id is derived from its URL.
 */
function sourcesAsCitations(wire: WireAnswer): Citation[] {
  return (wire.sources ?? []).map((source) => ({
    id: `src:${source.url}`,
    title: source.title,
    url: source.url,
    sourceType: sourceTypeOf(source.url),
    section: null,
    publishedAt: null,
  }));
}

export function toAnswer(wire: WireAnswer, question: string, id: string): SahayakAnswer {
  return {
    id,
    question,
    outcome: outcomeOf(wire),
    answer: wire.answer,
    // Both lists, because the screen shows one. A refusal's official pages are the only thing it
    // has to offer, and dropping them would leave a not-found answer with nowhere to go.
    citations: [...(wire.citations ?? []).map(toCitation), ...sourcesAsCitations(wire)],
    confidence: wire.confidence ?? 0,
    // An answer states how fresh its sources are, because QCOs are amended constantly. An empty
    // string is the app's "the server did not say", which the freshness tier renders as unknown
    // rather than falling through to fresh.
    asOf: wire.as_of ?? '',
  };
}

export function toApplicability(
  wire: WireApplicability,
  profile: ProductProfile | WireProfile
): BisApplicability {
  return {
    profile:
      'name' in profile && typeof profile.name === 'string' && 'netQuantity' in profile
        ? (profile as ProductProfile)
        : toProfile(profile as WireProfile),
    // Never collapsed. `unclear` is its own stance and renders as "we could not determine", not as
    // the negative one.
    qcoApplicable: wire.qco_applicable,
    scheme: wire.scheme,
    candidateIsNumbers: wire.candidate_is_numbers ?? [],
    nextSteps: wire.next_steps ?? [],
    sources: (wire.sources ?? []).map(toCitation),
    asOf: wire.as_of ?? '',
  };
}
