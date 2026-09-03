/**
 * The shell: the rail, the routes it reaches, and the appearance settings.
 *
 * What is asserted here is what W1–W4 build on. The research navigation is one list
 * (`routes.tsx`), the counts on it are the daemon's own (`overview.attention[].route`), the
 * active route carries `aria-current="page"`, a plain click on a rail link is a
 * client-side navigation rather than a page load, and the theme and density toggles write
 * the Design System's `data-theme` / `data-density` onto the document.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Layout } from './Layout';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';

/** `path: '*'` keeps the shell mounted while a rail link changes the route under it. */
function renderShell(daemon = fakeDaemon(), token: string | null = 'local-token') {
  return renderView(<Layout />, { daemon, token, route: '/review', path: '*' });
}

describe('the project rail', () => {
  it('lists the research navigation with the counts the daemon reported', async () => {
    renderShell();

    const rail = await screen.findByRole('navigation', { name: 'Project navigation' });
    const items = Array.from(rail.querySelectorAll('.rh-project-rail__nav-item')).map((node) =>
      node.querySelector('.rh-project-rail__nav-label')?.textContent,
    );
    expect(items).toEqual([
      'Overview',
      'Review inbox',
      'Conflicts',
      'Stale',
      'Corpus',
      'Claims',
      'Questions',
      'Synthesis',
      'Taxonomy',
      'Manuscript',
    ]);

    // `2 review items` on `/review` in the fixture; the groups reporting 0 show no count.
    const review = FIXTURES.overview.attention.find((group) => group.route === '/review');
    expect(screen.getByRole('link', { name: /Review inbox/ }).textContent).toContain(
      String(review?.count),
    );
    expect(screen.getByRole('link', { name: /Conflicts/ }).textContent).not.toMatch(/\d/);
  });

  it('marks the active route with aria-current, and follows a click without reloading', async () => {
    const user = userEvent.setup();
    renderShell();

    const review = await screen.findByRole('link', { name: /Review inbox/ });
    expect(review).toHaveAttribute('aria-current', 'page');

    await user.click(screen.getByRole('link', { name: /Corpus/ }));

    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Corpus/ })).toHaveAttribute('aria-current', 'page'),
    );
    expect(screen.getByRole('link', { name: /Review inbox/ })).not.toHaveAttribute('aria-current');
  });

  it('says which principal the daemon resolved, in words', async () => {
    renderShell(fakeDaemon(), 'local-token');

    await waitFor(() => expect(screen.getByText('Researcher — may accept')).toBeInTheDocument());
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('says an agent host may only read and propose', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    renderShell(fakeDaemon({ gets: { '/overview': asHost } }), null);

    await waitFor(() =>
      expect(screen.getByText('agent_host — reads and proposes only')).toBeInTheDocument(),
    );
    expect(screen.getByText('Degraded')).toBeInTheDocument();
  });
});

describe('the shell', () => {
  it('puts a skip link ahead of the rail, pointing at the main surface', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.tab();
    const skip = screen.getByRole('link', { name: 'Skip to main content' });
    expect(skip).toHaveFocus();
    const main = screen.getByRole('main', { name: 'Research workspace' });
    expect(skip.getAttribute('href')).toBe(`#${main.id}`);
  });

  it('switches the theme and the density from settings, on the document', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.click(await screen.findByRole('button', { name: 'Settings' }));
    await screen.findByRole('dialog', { name: 'Settings' });

    await user.selectOptions(screen.getByLabelText('Theme'), 'light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    await user.selectOptions(screen.getByLabelText('Density'), 'compact');
    expect(document.documentElement.getAttribute('data-density')).toBe('compact');
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderShell();

    await screen.findByRole('navigation', { name: 'Project navigation' });
    await expectNoAxeViolations(container);
  });
});
