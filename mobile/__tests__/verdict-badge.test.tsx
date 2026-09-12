/**
 * VerdictBadge — the §3.4 guarantee, tested.
 *
 * This is the component that could quietly destroy the product's credibility: if BORDERLINE ever
 * renders as FAIL, the app accuses a compliant label. These tests assert on the accessibility
 * label rather than on colour, which is the same guarantee a colour-blind inspector relies on.
 */

import { VerdictBadge } from '@/components';
import { VERDICTS, type Verdict } from '@/domain';
import { translate } from '@/i18n';

import { renderWithProviders } from '../test-utils/render';

const LABELS: Record<Verdict, string> = {
  PASS: translate('en', 'verdict.pass'),
  FAIL: translate('en', 'verdict.fail'),
  BORDERLINE: translate('en', 'verdict.borderline'),
  NOT_ASSESSABLE: translate('en', 'verdict.notAssessable'),
};

describe('VerdictBadge', () => {
  it('has a distinct label for each of the four verdicts', () => {
    expect(new Set(Object.values(LABELS)).size).toBe(4);
  });

  it('labels each badge with its own verdict and with no other', async () => {
    for (const verdict of VERDICTS) {
      const view = await renderWithProviders(<VerdictBadge verdict={verdict} />);

      expect(view.getByLabelText(LABELS[verdict])).toBeTruthy();

      // The load-bearing assertion: a BORDERLINE badge must not be findable as a FAIL.
      for (const other of VERDICTS.filter((v) => v !== verdict)) {
        expect(view.queryByLabelText(LABELS[other])).toBeNull();
      }

      await view.unmount();
    }
  });

  it('exposes the verdict to assistive tech, so colour is not the only signal', async () => {
    const view = await renderWithProviders(<VerdictBadge verdict="PASS" />);

    expect(view.getByLabelText(LABELS.PASS)).toBeTruthy();
  });
});
