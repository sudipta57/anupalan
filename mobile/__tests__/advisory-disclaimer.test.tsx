/**
 * The advisory disclaimer (CLAUDE.md §3.8).
 *
 * Required on every findings and report surface. Tested here so the component itself cannot
 * regress; Stage 8 and Stage 9 add tests that those screens actually render it.
 */

import { AdvisoryDisclaimer } from '@/components';
import { translate } from '@/i18n';

import { renderWithProviders } from '../test-utils/render';

describe('AdvisoryDisclaimer', () => {
  it('states plainly that this is not a certification', async () => {
    const view = await renderWithProviders(<AdvisoryDisclaimer />);

    expect(view.getByText(translate('en', 'disclaimer.title'))).toBeTruthy();
    expect(view.getByText(translate('en', 'disclaimer.body'))).toBeTruthy();
  });

  it('stamps the rule pack version when a verdict is on screen', async () => {
    const view = await renderWithProviders(<AdvisoryDisclaimer rulepackVersion="LM-2011-v1.0" />);

    // Every finding carries its pack version (CLAUDE.md §3.6) — a report regenerated next year
    // must still be explainable by the rules in force when it was issued.
    expect(view.getByText(/LM-2011-v1\.0/)).toBeTruthy();
  });

  it('adds the pending-legal-review note in detailed form', async () => {
    const view = await renderWithProviders(<AdvisoryDisclaimer detailed />);

    expect(view.getByText(translate('en', 'disclaimer.pending'))).toBeTruthy();
  });

  it('omits the version line when no verdict is shown', async () => {
    const view = await renderWithProviders(<AdvisoryDisclaimer />);

    expect(view.queryByText(/Checked against rule pack/)).toBeNull();
  });
});
