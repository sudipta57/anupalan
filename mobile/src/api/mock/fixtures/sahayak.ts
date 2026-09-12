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
 * Every URL below is a real, public BIS or gazette page — **except one, on purpose.**
 * `ans_fabricated` claims `answered` and cites a plausible-looking commercial standards reseller.
 * It is the fixture for the failure the client cannot detect any other way: a model that invents a
 * source does not produce a worse answer, it produces a more convincing one. Stage 11's guard
 * (`features/sahayak/citations`) drops the citation and downgrades the answer to not-found, and this
 * is the fixture that proves it rather than asserting it. Do not "fix" the host.
 *
 * Hindi answers are kept beside the English ones rather than on the domain type: the server returns
 * one language per request (`SahayakAskBody.lang`), so a second field on `SahayakAnswer` would model
 * a response shape that never occurs.
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

const ISI_LIST: Citation = {
  id: 'doc_isi_list',
  title: 'Products under mandatory ISI mark certification',
  url: 'https://www.bis.gov.in/product-certification/products-under-compulsory-certification/',
  sourceType: 'isi_product_list',
  section: 'Scheme I — ISI mark',
  publishedAt: '2026-06-12',
};

const CATALOGUE: Citation = {
  id: 'doc_catalogue',
  title: 'Indian Standards catalogue — search by standard number',
  url: 'https://www.manakonline.in/MANAK/home',
  sourceType: 'catalogue_metadata',
  section: null,
  publishedAt: '2026-07-01',
};

/**
 * A source that does not exist.
 *
 * Deliberately plausible: a real-sounding title, a `.com` reseller, https, a section reference. This
 * is what a hallucinated citation looks like, and it is the only kind of bad citation a client can
 * actually catch — the host is not one the BIS corpus is built from, so nothing in it could have been
 * retrieved. `isShowable` rejects it; `isUnsupported` then finds the answer has nothing left.
 */
const FABRICATED: Citation = {
  id: 'doc_fabricated',
  title: 'Indian Standards compliance handbook — packaged goods',
  url: 'https://standards-india-handbook.com/qco/packaged-goods',
  sourceType: 'qco_gazette',
  section: 'Chapter 4',
  publishedAt: '2026-04-18',
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
    citations: [SCHEME_GUIDE, CATALOGUE],
    confidence: 0.0,
    asOf: AS_OF,
  },
  {
    // Claims to be answered, cites nothing traceable. The client must not show this prose.
    id: 'ans_fabricated',
    question: 'Which QCO covers stainless steel cookware?',
    outcome: 'answered',
    answer:
      'Stainless steel cookware is covered by the Packaged Goods Quality Control Order, 2019, which mandates ISI certification against IS 14756 for all utensil-grade stainless steel.',
    citations: [FABRICATED],
    confidence: 0.79,
    asOf: AS_OF,
  },
];

/**
 * Hindi answer bodies, keyed by answer id.
 *
 * Not every answer needs one to prove the path, but the two refusals do: they are the responses whose
 * wording carries the whole value, and a Hindi-speaking user who receives the English refusal has
 * been given the least useful version of the most important answer.
 */
export const SAHAYAK_ANSWERS_HI: Record<string, string> = {
  ans_crs_applicability:
    'हाँ। IT उपकरणों के पावर अडैप्टर अनिवार्य पंजीकरण योजना (CRS) के अंतर्गत आते हैं, इसलिए भारत में बिक्री से पहले मॉडल का BIS पंजीकरण आवश्यक है। यह परीक्षण-रिपोर्ट आधारित मार्ग है: BIS-मान्यता प्राप्त प्रयोगशाला में परीक्षण, फिर ऑनलाइन आवेदन। इसमें कारखाना निरीक्षण नहीं होता, और यही CRS को ISI चिह्न योजना से अलग करता है।',
  ans_hallmarking:
    'सोने के आभूषणों की हॉलमार्किंग BIS द्वारा अधिसूचित कैरेट पर होती है, और प्रत्येक हॉलमार्क वस्तु पर BIS चिह्न, शुद्धता श्रेणी और छह अंकों का HUID अंकित होता है। जौहरी का पंजीकरण ऑनलाइन होता है और प्रत्येक विक्रय परिसर पर अलग से लागू होता है।',
  ans_not_found:
    'आधिकारिक स्रोतों में नहीं मिला। मेरे पास उपलब्ध गुणवत्ता नियंत्रण आदेश और उत्पाद सूचियाँ बाँस के फर्नीचर को कवर नहीं करतीं, और जो आदेश मौजूद न हो उसका अनुमान मैं नहीं लगाऊँगा। अनिवार्य प्रमाणन वाले उत्पादों की वर्तमान सूची सीधे देखें, क्योंकि गुणवत्ता नियंत्रण आदेश बार-बार अधिसूचित और संशोधित होते हैं।',
  ans_refused:
    'मैं IS 1786 के खंड की सामग्री नहीं दे सकता। भारतीय मानकों के पूर्ण पाठ कॉपीराइट के अंतर्गत हैं और BIS द्वारा बेचे जाते हैं, इसलिए परीक्षण सीमाएँ, खंड का पाठ और सह्यता सारणियाँ मेरे उद्धरण के दायरे से बाहर हैं। मैं बता सकता हूँ कि कोई गुणवत्ता नियंत्रण आदेश उस मानक को अनिवार्य बनाता है या नहीं, कौन-सा प्रमाणन मार्ग लागू होता है, और मानक कहाँ से खरीदें।',
};

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
  prd_biscuit_180g: {
    profile: PRODUCTS_BY_ID.prd_biscuit_180g.profile,
    qcoApplicable: 'no',
    scheme: 'none',
    candidateIsNumbers: [],
    nextSteps: [
      'No Quality Control Order covers biscuits, so BIS certification is not mandatory for this product.',
      'Food safety and labelling are governed separately by FSSAI; this tool does not evaluate FSSAI requirements.',
    ],
    sources: [ISI_LIST],
    asOf: AS_OF,
  },
  prd_notebook_200: {
    profile: PRODUCTS_BY_ID.prd_notebook_200.profile,
    qcoApplicable: 'no',
    scheme: 'none',
    candidateIsNumbers: [],
    nextSteps: [
      'Exercise books and notebooks do not appear in the public mandatory-certification lists, so BIS certification is not mandatory for this product.',
      'Legal Metrology declarations still apply — this pack is measured under Table-II, on display-panel area.',
    ],
    sources: [ISI_LIST],
    asOf: AS_OF,
  },
};
