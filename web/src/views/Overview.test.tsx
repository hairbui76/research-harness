/**
 * Task 11.2: the Overview leads with next actions, and reports no vanity metric.
 *
 * The order of the attention groups and the wording of their labels come from the daemon,
 * so the assertion is that the page renders them in the order it received — not that it
 * knows the order itself.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { OverviewPage } from './Overview';
import { FIXTURES, fakeDaemon, renderView } from '../test/harness';

describe('the overview', () => {
  it('states the project and its size the way Product 26 asks', async () => {
    renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText(FIXTURES.overview.project)).toBeInTheDocument());
    expect(screen.getByText(/works ·/)).toBeInTheDocument();
  });

  it('renders the attention groups in the order the daemon reported them', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    const rendered = Array.from(container.querySelectorAll('.attention > li > a')).map(
      (node) => node.textContent,
    );
    expect(rendered).toEqual(FIXTURES.overview.attention.map((group) => group.label));
  });

  it('leads with the group that has work in it', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    expect(container.querySelector('.attention > li')?.className).toBe('has-work');
  });

  it('shows claim health as counts and nothing that looks like model confidence', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Claim health')).toBeInTheDocument());
    expect(screen.getByText('supported')).toBeInTheDocument();
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
    expect(container.textContent).not.toMatch(/\d+(\.\d+)?%/);
  });
});
