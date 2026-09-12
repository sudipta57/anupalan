/**
 * Stage 11 — Sahayak chat and BIS applicability (FR-07).
 *
 * *Accept: the unanswerable fixture returns the explicit not-found response with an official link,
 * and never a fabricated citation.*
 *
 * Two things get the weight here, and neither is the chat plumbing.
 *
 * **The fabricated citation.** A model that invents a source does not produce a worse answer, it
 * produces a more convincing one, and the citation is the part of a response a reader will not check.
 * The client cannot verify that a page says what an answer claims — only that the page could have
 * come from the corpus at all. So the tests below pin the host check, and then pin the consequence:
 * an `answered` response with nothing traceable behind it is not shown as an answer, and its prose is
 * not rendered.
 *
 * **`unclear` is not `no`.** The BIS half's version of CLAUDE.md §3.4, running in the more dangerous
 * direction. A wrong FAIL gets disputed; a wrong clearance gets believed, because it tells a brand
 * what it hoped to hear. Every affirmative surface on the applicability screen is gated on
 * `isConclusive`, and these tests exist so a later "simplification" to a boolean fails loudly.
 *
 * Whether a source chip actually opens Chrome Custom Tabs is a device question — `openSource` is the
 * one impure module in the feature and is not exercised here. It is item 4 of the Stage 11 device
 * checklist.
 */

import { ApiError, api } from '@/api';
import { setScenario } from '@/api/mock/scenario';
import {
  BIS_APPLICABILITY,
  SAHAYAK_ANSWERS,
  SAHAYAK_ANSWERS_HI,
} from '@/api/mock/fixtures/sahayak';
import type { BisApplicability, Citation, SahayakAnswer } from '@/domain';
import {
  EMPTY_TRANSCRIPT,
  FRESHNESS_AGEING_DAYS,
  FRESHNESS_COPY,
  FRESHNESS_STALE_DAYS,
  MAX_QUESTION_LENGTH,
  OFFICIAL_HOSTS,
  PRESENTATION_COPY,
  SCHEME_BODY_KEYS,
  SCHEME_LABEL_KEYS,
  STANCE_COPY,
  ageInDays,
  appendAnswer,
  appendError,
  appendQuestion,
  canSend,
  charactersRemaining,
  citationRole,
  freshnessFor,
  hostOf,
  isConclusive,
  isEmpty,
  isInconsistent,
  isNumbersAreRequirements,
  isNumbersLabelKey,
  isOfficialHost,
  isOverLength,
  isShowable,
  isUnsupported,
  needsRecheck,
  nextSteps,
  presentationFor,
  questionFor,
  showableCitations,
  showsConfidence,
  showsModelText,
  showsScheme,
  stanceFor,
  wasDowngraded,
  withheldCitations,
} from '@/features/sahayak';
import { translate, type TranslationKey } from '@/i18n';

afterEach(() => setScenario('happy'));

/** A citation on an official host, to vary one field at a time from. */
const GOOD: Citation = {
  id: 'doc_good',
  title: 'Products under compulsory certification',
  url: 'https://www.bis.gov.in/product-certification/',
  sourceType: 'crs_product_list',
  section: null,
  publishedAt: '2026-06-12',
};

function answerWith(citations: Citation[], overrides: Partial<SahayakAnswer> = {}): SahayakAnswer {
  return {
    id: 'ans_test',
    question: 'Does this need BIS registration?',
    outcome: 'answered',
    answer: 'Yes, it does.',
    citations,
    confidence: 0.8,
    asOf: '2026-08-30',
    ...overrides,
  };
}

// ---------------------------------------------------------------- the host guard

describe('hostOf', () => {
  it('reads the host of an https URL', () => {
    expect(hostOf('https://www.bis.gov.in/hallmarking/')).toBe('www.bis.gov.in');
    expect(hostOf('https://bis.gov.in')).toBe('bis.gov.in');
    expect(hostOf('https://bis.gov.in?q=1')).toBe('bis.gov.in');
    expect(hostOf('https://bis.gov.in:443/x')).toBe('bis.gov.in');
  });

  it('lowercases, so a mixed-case host cannot slip past the allowlist', () => {
    expect(hostOf('https://WWW.BIS.GOV.IN/x')).toBe('www.bis.gov.in');
  });

  it('rejects http rather than upgrading it', () => {
    // A citation is evidence. One that arrived over a channel any intermediary could rewrite is not
    // evidence, and silently promoting it would hide that the link was downgraded.
    expect(hostOf('http://www.bis.gov.in/x')).toBeNull();
  });

  it('rejects anything that is not an absolute https URL', () => {
    expect(hostOf('')).toBeNull();
    expect(hostOf('bis.gov.in')).toBeNull();
    expect(hostOf('//bis.gov.in')).toBeNull();
    expect(hostOf('javascript:alert(1)')).toBeNull();
    expect(hostOf('file:///etc/passwd')).toBeNull();
  });
});

describe('isOfficialHost', () => {
  it('accepts every listed host and their subdomains', () => {
    for (const host of OFFICIAL_HOSTS) {
      expect(isOfficialHost(host)).toBe(true);
      expect(isOfficialHost(`www.${host}`)).toBe(true);
    }
  });

  it('rejects a host that merely ends with an official one as a suffix', () => {
    // The check is `endsWith('.' + official)`, not `endsWith(official)`. Without the dot,
    // `notbis.gov.in` would pass — and registering exactly that is the cheapest possible attack on
    // a citation allowlist.
    expect(isOfficialHost('notbis.gov.in')).toBe(false);
    expect(isOfficialHost('bis.gov.in.example.com')).toBe(false);
  });

  it('rejects a plausible commercial lookalike', () => {
    expect(isOfficialHost('standards-india-handbook.com')).toBe(false);
    expect(isOfficialHost('bis-india.org')).toBe(false);
  });

  it('rejects null', () => {
    expect(isOfficialHost(null)).toBe(false);
  });
});

describe('isShowable', () => {
  it('accepts a titled citation on an official host', () => {
    expect(isShowable(GOOD)).toBe(true);
  });

  it('rejects an untitled citation', () => {
    // An empty string is what a dropped field looks like coming through a JSON schema, and a chip
    // with no label is not a source a reader can weigh.
    expect(isShowable({ ...GOOD, title: '' })).toBe(false);
    expect(isShowable({ ...GOOD, title: '   ' })).toBe(false);
  });

  it('rejects a citation on any other host', () => {
    expect(isShowable({ ...GOOD, url: 'https://standards-india-handbook.com/qco' })).toBe(false);
  });
});

describe('partitioning citations', () => {
  it('splits showable from withheld and loses none', () => {
    const bad = { ...GOOD, id: 'doc_bad', url: 'https://example.com/x' };
    const answer = answerWith([GOOD, bad]);

    expect(showableCitations(answer).map((c) => c.id)).toEqual(['doc_good']);
    expect(withheldCitations(answer).map((c) => c.id)).toEqual(['doc_bad']);
    expect(showableCitations(answer).length + withheldCitations(answer).length).toBe(2);
  });
});

// ---------------------------------------------------------------- the downgrade

describe('isUnsupported', () => {
  it('is true for an answered response with nothing traceable behind it', () => {
    expect(isUnsupported(answerWith([{ ...GOOD, url: 'https://example.com/x' }]))).toBe(true);
    expect(isUnsupported(answerWith([]))).toBe(true);
  });

  it('is false when at least one citation survives', () => {
    expect(isUnsupported(answerWith([GOOD]))).toBe(false);
  });

  it('does not fire on a refusal with an unusable signpost', () => {
    // A refusal carries its citations as "where to look", not as support. An uncited refusal is a
    // refusal missing a link, which is a different and much smaller problem than a fabricated answer.
    const refusal = answerWith([], { outcome: 'not_found' });
    const priced = answerWith([], { outcome: 'refused_priced_content' });

    expect(isUnsupported(refusal)).toBe(false);
    expect(isUnsupported(priced)).toBe(false);
  });
});

describe('presentationFor', () => {
  it('passes through a properly cited answer and both refusals', () => {
    expect(presentationFor(answerWith([GOOD]))).toBe('answered');
    expect(presentationFor(answerWith([GOOD], { outcome: 'not_found' }))).toBe('not_found');
    expect(presentationFor(answerWith([GOOD], { outcome: 'refused_priced_content' }))).toBe(
      'refused_priced_content'
    );
  });

  it('downgrades an uncited answer to not-found', () => {
    const fabricated = answerWith([{ ...GOOD, url: 'https://standards-india-handbook.com/x' }]);

    expect(fabricated.outcome).toBe('answered');
    expect(presentationFor(fabricated)).toBe('not_found');
    expect(wasDowngraded(fabricated)).toBe(true);
  });

  it('suppresses the model prose on a downgrade, and only then', () => {
    // The point of the downgrade. Printing an uncited paragraph under a "not found in official
    // sources" heading would be the worst of both — the caveat nobody reads above the answer
    // everybody does.
    expect(showsModelText(answerWith([{ ...GOOD, url: 'https://example.com/x' }]))).toBe(false);
    expect(showsModelText(answerWith([GOOD]))).toBe(true);
    expect(showsModelText(answerWith([GOOD], { outcome: 'not_found' }))).toBe(true);
    expect(showsModelText(answerWith([GOOD], { outcome: 'refused_priced_content' }))).toBe(true);
  });

  it('shows a confidence number only on a genuine answer', () => {
    // Both refusals carry confidence 0, correctly — there is no claim to be confident about. "0%"
    // beside a deliberate, correct refusal reads as a broken answer rather than a held boundary.
    expect(showsConfidence(answerWith([GOOD]))).toBe(true);
    expect(showsConfidence(answerWith([GOOD], { outcome: 'not_found' }))).toBe(false);
    expect(showsConfidence(answerWith([GOOD], { outcome: 'refused_priced_content' }))).toBe(false);
    expect(showsConfidence(answerWith([{ ...GOOD, url: 'https://example.com/x' }]))).toBe(false);
  });
});

describe('citationRole', () => {
  it('calls them sources under an answer and a signpost under a refusal', () => {
    expect(citationRole('answered')).toBe('support');
    expect(citationRole('not_found')).toBe('signpost');
    expect(citationRole('refused_priced_content')).toBe('signpost');
  });
});

// ---------------------------------------------------------------- freshness

describe('freshnessFor', () => {
  const asOf = '2026-08-30';
  const sameDay = Date.parse('2026-08-30T18:00:00Z');

  it('is fresh on the day and just under the ageing threshold', () => {
    expect(freshnessFor(asOf, sameDay)).toBe('fresh');
    expect(freshnessFor(asOf, sameDay + (FRESHNESS_AGEING_DAYS - 1) * 86_400_000)).toBe('fresh');
  });

  it('ages at the threshold and goes stale at a year', () => {
    expect(freshnessFor(asOf, sameDay + FRESHNESS_AGEING_DAYS * 86_400_000)).toBe('ageing');
    expect(freshnessFor(asOf, sameDay + (FRESHNESS_STALE_DAYS - 1) * 86_400_000)).toBe('ageing');
    expect(freshnessFor(asOf, sameDay + FRESHNESS_STALE_DAYS * 86_400_000)).toBe('stale');
  });

  it('reports an unparseable stamp as unknown rather than fresh', () => {
    // `unknown` must not fall through to `fresh`, which is what a `?? 0` would do. An answer with no
    // provenance in time is worse than an old one — an old stamp can be weighed, an absent one cannot.
    expect(freshnessFor('', sameDay)).toBe('unknown');
    expect(freshnessFor('not-a-date', sameDay)).toBe('unknown');
    expect(ageInDays('not-a-date', sameDay)).toBeNull();
  });

  it('reports a future stamp as unknown, not as zero days old', () => {
    // A clock disagreement between the phone and the ingest job. Reading it as "brand new" hides it.
    expect(freshnessFor(asOf, Date.parse('2026-01-01T00:00:00Z'))).toBe('unknown');
  });

  it('asks for a re-check when stale or unknown, and not otherwise', () => {
    expect(needsRecheck('fresh')).toBe(false);
    expect(needsRecheck('ageing')).toBe(false);
    expect(needsRecheck('stale')).toBe(true);
    expect(needsRecheck('unknown')).toBe(true);
  });
});

// ---------------------------------------------------------------- unclear is not no

describe('stanceFor', () => {
  it('maps the three QCO values one to one, without folding unclear into no', () => {
    expect(stanceFor('yes')).toBe('required');
    expect(stanceFor('no')).toBe('not_required');
    expect(stanceFor('unclear')).toBe('undetermined');
  });
});

describe('isConclusive', () => {
  it('is false for unclear', () => {
    // The load-bearing assertion of the BIS half. `unclear` means the public lists do not settle
    // whether certification is needed; presenting that as "not required" tells a brand they may ship
    // uncertified goods on an authority this tool never established.
    expect(isConclusive({ qcoApplicable: 'unclear' })).toBe(false);
  });

  it('is true for both settled answers', () => {
    expect(isConclusive({ qcoApplicable: 'yes' })).toBe(true);
    expect(isConclusive({ qcoApplicable: 'no' })).toBe(true);
  });
});

describe('showsScheme', () => {
  it('hides the route on an undetermined record even when the field says none', () => {
    // `scheme: 'none'` on an unclear record is the absence of a claim, not the claim "no route
    // applies". Rendering the row would answer the question the stance just declined to answer.
    expect(showsScheme({ qcoApplicable: 'unclear', scheme: 'none' })).toBe(false);
    expect(showsScheme({ qcoApplicable: 'unclear', scheme: 'CRS' })).toBe(false);
  });

  it('shows the route once the stance is settled', () => {
    expect(showsScheme({ qcoApplicable: 'no', scheme: 'none' })).toBe(true);
    expect(showsScheme({ qcoApplicable: 'yes', scheme: 'ISI' })).toBe(true);
  });
});

describe('IS numbers', () => {
  it('are requirements only when certification is actually required', () => {
    expect(isNumbersAreRequirements({ qcoApplicable: 'yes' })).toBe(true);
    expect(isNumbersAreRequirements({ qcoApplicable: 'unclear' })).toBe(false);
    expect(isNumbersAreRequirements({ qcoApplicable: 'no' })).toBe(false);
  });

  it('are labelled as candidates when the stance is not settled', () => {
    expect(isNumbersLabelKey({ qcoApplicable: 'yes' })).toBe('bis.isNumbersRequired');
    expect(isNumbersLabelKey({ qcoApplicable: 'unclear' })).toBe('bis.isNumbersCandidate');
  });
});

describe('isInconsistent', () => {
  it('flags a record that mandates certification and names no route', () => {
    expect(isInconsistent({ qcoApplicable: 'yes', scheme: 'none' })).toBe(true);
  });

  it('does not flag an unclear record with no route, which is simply unanswered', () => {
    expect(isInconsistent({ qcoApplicable: 'unclear', scheme: 'none' })).toBe(false);
    expect(isInconsistent({ qcoApplicable: 'no', scheme: 'none' })).toBe(false);
    expect(isInconsistent({ qcoApplicable: 'yes', scheme: 'CRS' })).toBe(false);
  });
});

describe('nextSteps', () => {
  it('drops blank entries rather than rendering empty rows', () => {
    expect(nextSteps({ nextSteps: ['Do this', '', '   ', 'Then this'] })).toEqual([
      'Do this',
      'Then this',
    ]);
  });
});

// ---------------------------------------------------------------- transcript

describe('transcript', () => {
  it('starts empty and appends in order', () => {
    expect(isEmpty(EMPTY_TRANSCRIPT)).toBe(true);

    const withQuestion = appendQuestion(EMPTY_TRANSCRIPT, 't1', '  Does this need BIS?  ', 'now');
    const withAnswer = appendAnswer(withQuestion, 't2', answerWith([GOOD]), 'then');

    expect(isEmpty(withQuestion)).toBe(false);
    expect(withQuestion.turns[0]).toMatchObject({ kind: 'question', text: 'Does this need BIS?' });
    expect(withAnswer.turns.map((turn) => turn.kind)).toEqual(['question', 'answer']);
  });

  it('never mutates the transcript it was given', () => {
    const appended = appendQuestion(EMPTY_TRANSCRIPT, 't1', 'q', 'now');

    expect(EMPTY_TRANSCRIPT.turns).toHaveLength(0);
    expect(appended.turns).toHaveLength(1);
  });

  it('keeps a failed question in the transcript as a failure', () => {
    // A question that vanishes when the network drops looks like one that was never asked, and the
    // user retypes it — which on a flaky link is how one question becomes four billed requests.
    const asked = appendQuestion(EMPTY_TRANSCRIPT, 't1', 'Does this need BIS?', 'now');
    const failed = appendError(asked, 't2', 'Could not reach the server.');

    expect(failed.turns.map((turn) => turn.kind)).toEqual(['question', 'error']);
    expect(questionFor(failed, 1)).toBe('Does this need BIS?');
  });

  it('finds the question an answer belongs under, and nothing before the start', () => {
    const one = appendAnswer(
      appendQuestion(EMPTY_TRANSCRIPT, 't1', 'first', 'now'),
      't2',
      answerWith([GOOD]),
      'then'
    );
    const two = appendAnswer(
      appendQuestion(one, 't3', 'second', 'now'),
      't4',
      answerWith([GOOD]),
      'then'
    );

    expect(questionFor(two, 1)).toBe('first');
    expect(questionFor(two, 3)).toBe('second');
    expect(questionFor(EMPTY_TRANSCRIPT, 0)).toBeNull();
  });
});

describe('canSend', () => {
  it('refuses an empty or whitespace-only draft', () => {
    expect(canSend('', false)).toBe(false);
    expect(canSend('    ', false)).toBe(false);
    expect(canSend('Does this need BIS?', false)).toBe(true);
  });

  it('refuses a second question while one is in flight', () => {
    // Two overlapping asks can complete out of order, and a transcript where the second question's
    // answer sits under the first is worse than a disabled button: nothing on screen reveals it, and
    // the citations under the wrong question still look official.
    expect(canSend('Does this need BIS?', true)).toBe(false);
  });

  it('refuses a draft over the cap', () => {
    expect(canSend('x'.repeat(MAX_QUESTION_LENGTH), false)).toBe(true);
    expect(canSend('x'.repeat(MAX_QUESTION_LENGTH + 1), false)).toBe(false);
    expect(isOverLength('x'.repeat(MAX_QUESTION_LENGTH + 1))).toBe(true);
    expect(charactersRemaining('x'.repeat(MAX_QUESTION_LENGTH))).toBe(0);
  });
});

// ---------------------------------------------------------------- copy completeness

describe('translation keys', () => {
  /** Every key the copy maps point at must resolve, in both locales, to something not the key. */
  function expectResolves(key: TranslationKey) {
    expect(translate('en', key)).not.toBe(key);
    expect(translate('hi', key)).not.toBe(key);
  }

  it('resolves every presentation, freshness, stance and scheme key', () => {
    for (const copy of Object.values(PRESENTATION_COPY)) {
      expectResolves(copy.labelKey);
      expectResolves(copy.bodyKey);
    }
    for (const copy of Object.values(FRESHNESS_COPY)) {
      expectResolves(copy.labelKey);
    }
    for (const copy of Object.values(STANCE_COPY)) {
      expectResolves(copy.titleKey);
      expectResolves(copy.bodyKey);
    }
    for (const key of Object.values(SCHEME_LABEL_KEYS)) expectResolves(key);
    for (const key of Object.values(SCHEME_BODY_KEYS)) expectResolves(key);
  });

  it('translates the two refusals into Hindi rather than falling back', () => {
    // These are the answers whose wording carries the whole value. A Hindi-speaking user who gets the
    // English refusal has been handed the least useful version of the most important response.
    expect(translate('hi', 'sahayak.outcomeNotFound')).not.toBe(
      translate('en', 'sahayak.outcomeNotFound')
    );
    expect(translate('hi', 'sahayak.outcomeRefused')).not.toBe(
      translate('en', 'sahayak.outcomeRefused')
    );
    expect(translate('hi', 'bis.stanceUndetermined')).not.toBe(
      translate('en', 'bis.stanceUndetermined')
    );
  });
});

// ---------------------------------------------------------------- the fixtures and the seam

describe('the ask endpoint', () => {
  it('returns the explicit not-found response for the unanswerable question', async () => {
    // The stage's acceptance criterion.
    const answer = await api.askSahayak({
      question: 'Is there a QCO covering bamboo furniture?',
      lang: 'en',
    });

    expect(answer.outcome).toBe('not_found');
    expect(presentationFor(answer)).toBe('not_found');
    expect(answer.answer.toLowerCase()).toContain('not found in official sources');
  });

  it('gives that not-found response an official link, and no fabricated one', async () => {
    const answer = await api.askSahayak({
      question: 'Is there a QCO covering bamboo furniture?',
      lang: 'en',
    });

    const showable = showableCitations(answer);
    expect(showable.length).toBeGreaterThan(0);
    expect(withheldCitations(answer)).toHaveLength(0);
    for (const citation of showable) {
      expect(isOfficialHost(hostOf(citation.url))).toBe(true);
    }
  });

  it('echoes the question that was asked rather than the fixture phrasing', async () => {
    const asked = 'is there a qco covering BAMBOO furniture, specifically?';
    const answer = await api.askSahayak({ question: asked, lang: 'en' });

    expect(answer.question).toBe(asked);
  });

  it('refuses to quote the content of a standard', async () => {
    const answer = await api.askSahayak({
      question: 'What is the tensile strength limit in IS 1786?',
      lang: 'en',
    });

    expect(answer.outcome).toBe('refused_priced_content');
    // The refusal is shown as itself, not downgraded and not dressed up as an answer.
    expect(presentationFor(answer)).toBe('refused_priced_content');
    expect(showsModelText(answer)).toBe(true);
    expect(showsConfidence(answer)).toBe(false);
  });

  it('answers a covered question with traceable sources', async () => {
    const answer = await api.askSahayak({
      question: 'Does a phone charger need BIS registration?',
      lang: 'en',
    });

    expect(presentationFor(answer)).toBe('answered');
    expect(showableCitations(answer).length).toBeGreaterThan(0);
  });

  it('answers in Hindi when Hindi is asked for', async () => {
    const answer = await api.askSahayak({
      question: 'Does a phone charger need BIS registration?',
      lang: 'hi',
    });

    expect(answer.answer).toBe(SAHAYAK_ANSWERS_HI.ans_crs_applicability);
    expect(answer.answer).not.toBe(
      SAHAYAK_ANSWERS.find((a) => a.id === 'ans_crs_applicability')?.answer
    );
  });

  it('falls back to not-found for a question nothing in the corpus covers', async () => {
    const answer = await api.askSahayak({ question: 'How do I file my income tax?', lang: 'en' });

    expect(answer.outcome).toBe('not_found');
  });

  it('surfaces the fabricated-citation fixture as not-found, with its prose suppressed', async () => {
    // The fixture exists to be caught. If this ever passes as `answered`, the guard has been removed
    // or an unofficial host has been added to the allowlist to make one chip render.
    const answer = await api.askSahayak({
      question: 'Which QCO covers stainless steel cookware?',
      lang: 'en',
    });

    expect(answer.outcome).toBe('answered');
    expect(presentationFor(answer)).toBe('not_found');
    expect(wasDowngraded(answer)).toBe(true);
    expect(showsModelText(answer)).toBe(false);
    expect(showableCitations(answer)).toHaveLength(0);
    expect(withheldCitations(answer).length).toBeGreaterThan(0);
  });
});

describe('every shipped fixture answer', () => {
  it('cites only official hosts, except the one that exists to be caught', () => {
    for (const answer of SAHAYAK_ANSWERS) {
      if (answer.id === 'ans_fabricated') {
        expect(showableCitations(answer)).toHaveLength(0);
        continue;
      }

      expect(withheldCitations(answer)).toHaveLength(0);
      expect(answer.citations.length).toBeGreaterThan(0);
    }
  });

  it('carries a parseable freshness stamp', () => {
    for (const answer of SAHAYAK_ANSWERS) {
      expect(ageInDays(answer.asOf, Date.parse('2026-09-12T00:00:00Z'))).not.toBeNull();
    }
  });
});

describe('the applicability endpoint', () => {
  it('answers for every product in the fixture catalogue', async () => {
    for (const productId of Object.keys(BIS_APPLICABILITY)) {
      const record = await api.bisApplicability({
        productId,
        profile: BIS_APPLICABILITY[productId].profile,
      });

      expect(record.profile.name).toBe(BIS_APPLICABILITY[productId].profile.name);
    }
  });

  it('returns 404 rather than another product’s record when the product is unknown', async () => {
    // This previously defaulted to the atta profile for anything unrecognised, which answered a
    // question about one product with a different product's applicability.
    await expect(
      api.bisApplicability({ profile: BIS_APPLICABILITY.prd_atta_1kg.profile })
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      api.bisApplicability({
        productId: 'prd_not_a_product',
        profile: BIS_APPLICABILITY.prd_atta_1kg.profile,
      })
    ).rejects.toMatchObject({ status: 404 });
  });

  it('never ships a record that claims mandatory certification with no route', () => {
    for (const record of Object.values(BIS_APPLICABILITY) as BisApplicability[]) {
      expect(isInconsistent(record)).toBe(false);
    }
  });

  it('keeps the unclear record unclear', async () => {
    // The imported olive oil: the public lists do not settle edible-oil coverage, and the record says
    // so. If this ever becomes `no`, a brand has been told it may ship without certification.
    const record = await api.bisApplicability({
      productId: 'prd_olive_oil_500ml',
      profile: BIS_APPLICABILITY.prd_olive_oil_500ml.profile,
    });

    expect(record.qcoApplicable).toBe('unclear');
    expect(isConclusive(record)).toBe(false);
    expect(showsScheme(record)).toBe(false);
  });
});
