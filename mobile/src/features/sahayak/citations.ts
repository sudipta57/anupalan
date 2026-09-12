/**
 * Source chips, and the guard that decides whether a citation may be shown as support — FR-07.
 *
 * *Accept: the unanswerable fixture returns the explicit not-found response with an official link,
 * and never a fabricated citation.*
 *
 * **A citation is a claim about a document, and the app cannot read the document.** That is the
 * whole problem this module exists for. Everything else on a Sahayak answer is prose the reader can
 * judge for themselves; a chip labelled "Compulsory Registration Scheme — list of products under
 * mandatory registration" is an assertion that such a page exists and says what the answer just
 * said, and it is the part a reader will not check. A model that invents one has not produced a
 * worse answer, it has produced a *more convincing* one.
 *
 * So the client applies the one check it can actually make: **the URL must be on an official host.**
 * It cannot verify that the page says what the answer claims — only the retrieval layer can, and
 * `bis.answer` is prompted to cite only retrieved chunks. What it can refuse is a citation pointing
 * somewhere the corpus could never have come from, which is what a fabricated one looks like: a
 * plausible title over `standards-india.com` or a bare `example.org` placeholder.
 *
 * The consequence is deliberately severe and lives in `outcome.ts`: an answer that claims to be
 * `answered` and has **no** official citation left after this filter is not shown as an answer at
 * all. It is shown as not-found. An uncited answer about whether a product needs BIS registration is
 * indistinguishable from a guess, and this app's entire proposition is that it does not guess.
 *
 * Pure. No `URL`, no fetch, no host resolution — see `hostOf`.
 */

import type { AnswerOutcome, Citation, SahayakAnswer, SourceType } from '@/domain';
import type { TranslationKey } from '@/i18n';

/**
 * Hosts the BIS corpus is built from (`services/bis/ingest.py`).
 *
 * Registrable domains only, matched with their subdomains, so `www.bis.gov.in` and
 * `hallmarking.bis.gov.in` pass without being listed. Kept short on purpose: every entry is a host
 * whose pages the ingest step is allowed to fetch, and a host added here to make one citation render
 * is a host whose content the app is now vouching for.
 *
 * `manakonline.in` and `crsbis.in` are BIS's own portals — the standards catalogue and the CRS
 * registration system. They are not `.gov.in` and they are not mistakes.
 */
export const OFFICIAL_HOSTS: readonly string[] = [
  'bis.gov.in',
  'manakonline.in',
  'crsbis.in',
  'egazette.gov.in',
  'consumeraffairs.nic.in',
  'doca.gov.in',
] as const;

/**
 * The host of an `https` URL, lowercased, or null.
 *
 * A regex rather than `URL`. React Native's `URL` is a partial polyfill whose behaviour has moved
 * between releases, and this decides whether a citation is trustworthy — it should not be the one
 * thing in the app that behaves differently on Hermes than it did in the test runner.
 *
 * **`http` is rejected, not upgraded.** A citation is evidence; one that arrived over a channel any
 * intermediary could have rewritten is not evidence, and silently promoting it to `https` would hide
 * that the answer came with a downgraded link.
 */
export function hostOf(url: string): string | null {
  const match = /^https:\/\/([^/?#:\s]+)(?::\d+)?(?:[/?#]|$)/i.exec(url.trim());
  return match ? match[1].toLowerCase() : null;
}

/** Is this host one of `OFFICIAL_HOSTS`, or a subdomain of one? */
export function isOfficialHost(host: string | null): boolean {
  if (!host) return false;
  return OFFICIAL_HOSTS.some((official) => host === official || host.endsWith(`.${official}`));
}

/**
 * May this citation be put in front of a user?
 *
 * A title is required as well as an official URL. A chip with no label is not a source the reader
 * can weigh, and an empty string is what a dropped field looks like on the way through a JSON
 * schema.
 */
export function isShowable(citation: Citation): boolean {
  return citation.title.trim().length > 0 && isOfficialHost(hostOf(citation.url));
}

/** The citations that may be rendered. */
export function showableCitations(answer: Pick<SahayakAnswer, 'citations'>): Citation[] {
  return answer.citations.filter(isShowable);
}

/**
 * The citations that were withheld.
 *
 * Surfaced rather than silently dropped. A filter that quietly removes two of three chips leaves an
 * answer looking thinner than it claimed to be and gives nobody a reason to investigate the model
 * that produced them — the Sahayak equivalent of `missingFormats` in `features/reports`.
 */
export function withheldCitations(answer: Pick<SahayakAnswer, 'citations'>): Citation[] {
  return answer.citations.filter((citation) => !isShowable(citation));
}

/**
 * An answer claiming to be `answered` with nothing official behind it.
 *
 * The condition `outcome.ts` downgrades on. Only `answered` is checked: a refusal carries its
 * citations as signposts rather than as support, so a refusal whose signpost link is unusable is a
 * refusal with a missing link, not a fabricated answer.
 */
export function isUnsupported(answer: Pick<SahayakAnswer, 'outcome' | 'citations'>): boolean {
  return answer.outcome === 'answered' && showableCitations(answer).length === 0;
}

/**
 * What the chips under an answer are claiming.
 *
 * Not cosmetic. Under an answer, a chip means *this document supports what you just read*. Under a
 * refusal it means *this is where to look instead* — the not-found response's whole value is the
 * official page it points at. Labelling both "Sources" would make the refusal read as a cited
 * finding of absence, which is a stronger claim than "I could not find it" and one this tool has no
 * business making.
 */
export type CitationRole = 'support' | 'signpost';

export function citationRole(outcome: AnswerOutcome): CitationRole {
  return outcome === 'answered' ? 'support' : 'signpost';
}

export const CITATION_ROLE_LABEL_KEYS: Record<CitationRole, TranslationKey> = {
  support: 'sahayak.sourcesSupport',
  signpost: 'sahayak.sourcesSignpost',
};

/** What kind of document a chip points at, so a reader can weigh it before tapping. */
export const SOURCE_TYPE_LABEL_KEYS: Record<SourceType, TranslationKey> = {
  qco_gazette: 'sahayak.sourceQco',
  isi_product_list: 'sahayak.sourceIsiList',
  crs_product_list: 'sahayak.sourceCrsList',
  scheme_guide: 'sahayak.sourceSchemeGuide',
  faq: 'sahayak.sourceFaq',
  hallmarking: 'sahayak.sourceHallmarking',
  lab_directory: 'sahayak.sourceLabDirectory',
  catalogue_metadata: 'sahayak.sourceCatalogue',
};
