/**
 * Sahayak fixtures (FR-07, FR-29).
 *
 * Three outcomes, because all three have to be visible in the UI before anyone trusts it:
 *
 * - **answered** — a cited answer drawn from public material.
 * - **not_found** — no supporting source, so it says so and links the official page. Never a
 *   fabricated citation.
 * - **refused_priced_content** — the technical content of a standard was asked for. Full IS
 *   texts are copyrighted and sold by BIS, so the answer points at the purchase route. This
 *   refusal is a design feature and should be demoed as one (CLAUDE.md §3.5).
 *
 * Every URL below is a real, public BIS or gazette page.
 */

import type { BisApplicability, Citation, SahayakAnswer } from '@/domain';

import { PRODUCTS_BY_ID } from './products';

const AS_OF = '2026-08-30';

const CRS_LIST: Citation = {
  id: 'doc_crs_list',
  title: 'Compulsory Registration Scheme — list of products under mandatory registration',
  url: 'https://www.bis.gov.in/product-certification/products-under-compulsory-certification/',
  sourceType: 'crs_product_list',
  section: 'Electronics and IT goods',
  publishedAt: '2026-06-12',
};

const SCHEME_GUIDE: Citation = {
  id: 'doc_scheme_guide',
  title: 'BIS Product Certification Scheme — guide for applicants',
  url: 'https://www.bis.gov.in/product-certification/',
  sourceType: 'scheme_guide',
  section: 'Application process',
  publishedAt: '2026-03-04',
};

const HALLMARKING: Citation = {
  id: 'doc_hallmarking',
  title: 'Hallmarking of gold jewellery and artefacts',
  url: 'https://www.bis.gov.in/hallmarking/',
  sourceType: 'hallmarking',
  section: null,
  publishedAt: '2026-05-20',
};

export const SAHAYAK_ANSWERS: SahayakAnswer[] = [
  {
    id: 'ans_crs_applicability',
    question: 'Does a phone charger need BIS registration?',
    outcome: 'answered',
    answer:
      'Yes. Power adaptors for IT equipment fall under the Compulsory Registration Scheme, so the model must be registered with BIS before it is sold in India. Registration is a test-report-based route: testing at a BIS-recognised laboratory, then an online application. It does not involve a factory audit, which is what separates CRS from the ISI mark scheme.',
    citations: [CRS_LIST, SCHEME_GUIDE],
    confidence: 0.88,
    asOf: AS_OF,
  },
  {
    id: 'ans_hallmarking',
    question: 'Which purities can be hallmarked?',
    outcome: 'answered',
    answer:
      'Gold jewellery is hallmarked at the caratages notified by BIS, and each hallmarked article carries the BIS mark, the purity grade and a six-digit alphanumeric HUID. Registration as a jeweller is done online and applies per sales premises.',
    citations: [HALLMARKING],
    confidence: 0.81,
    asOf: AS_OF,
  },
  {
    id: 'ans_not_found',
    question: 'Is there a QCO covering bamboo furniture?',
    outcome: 'not_found',
    answer:
      'Not found in official sources. The Quality Control Orders and product lists available to me do not cover bamboo furniture, and I will not infer one that may not exist. Check the current list of products under compulsory certification directly, since Quality Control Orders are notified and amended frequently.',
    citations: [CRS_LIST],
    confidence: 0.0,
    asOf: AS_OF,
  },
  {
    id: 'ans_refused',
    question: 'What is the tensile strength limit in IS 1786?',
    outcome: 'refused_priced_content',
    answer:
      'I cannot give you the clause content of IS 1786. The full texts of Indian Standards are copyrighted and sold by BIS, so test limits, clause text and tolerance tables are outside what I can quote. I can tell you whether a Quality Control Order makes the standard mandatory, which certification route applies, and where to buy the standard.',
    citations: [SCHEME_GUIDE],
    confidence: 0.0,
    asOf: AS_OF,
  },
];

export const BIS_APPLICABILITY: Record<string, BisApplicability> = {
  prd_atta_1kg: {
    profile: PRODUCTS_BY_ID.prd_atta_1kg.profile,
    qcoApplicable: 'no',
    scheme: 'none',
    candidateIsNumbers: [],
    nextSteps: [
      'No Quality Control Order covers wheat flour, so BIS certification is not mandatory for this product.',
      'Food labelling is governed separately by FSSAI; this tool does not evaluate FSSAI requirements.',
    ],
    sources: [CRS_LIST],
    asOf: AS_OF,
  },
  prd_olive_oil_500ml: {
    profile: PRODUCTS_BY_ID.prd_olive_oil_500ml.profile,
    qcoApplicable: 'unclear',
    scheme: 'none',
    candidateIsNumbers: [],
    nextSteps: [
      'Edible oil coverage depends on the specific commodity and the Quality Control Order in force; the public lists available do not settle it for imported olive oil.',
      'Confirm against the current list of products under compulsory certification before relying on this.',
    ],
    sources: [CRS_LIST],
    asOf: AS_OF,
  },
};
