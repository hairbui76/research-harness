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
import { ProjectPathProvider } from '../app/projectPaths';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';

describe('the overview', () => {
  it('states the project and its size the way Product 26 asks', async () => {
    renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText(FIXTURES.overview.project)).toBeInTheDocument());
    expect(screen.getByText(/works ·/)).toBeInTheDocument();
  });

  it('renders the attention groups in the order the daemon reported them', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    const rendered = Array.from(container.querySelectorAll('.rh-web-attention > li a')).map(
      (node) => node.textContent,
    );
    expect(rendered).toEqual(FIXTURES.overview.attention.map((group) => group.label));
  });

  it('leads with the group that has work in it', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    // "Has work" is an attribute rather than a class since the migration to the Design
    // System: the group's own state, styled from `[data-work]`, and read here the same way.
    expect(container.querySelector('.rh-web-attention > li')?.hasAttribute('data-work')).toBe(true);
  });

  it('shows claim health as counts and nothing that looks like model confidence', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Claim health')).toBeInTheDocument());
    expect(screen.getByText('supported')).toBeInTheDocument();
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
    expect(container.textContent).not.toMatch(/\d+(\.\d+)?%/);
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});

/**
 * The same page under `research app`, where every workspace screen is inside a project.
 *
 * `attention[].route` is the daemon's own workspace path and stays that way in the DTO;
 * what changes is only where the link on screen points, which is what keeps a click on
 * "Evidence waiting for review" inside the project the researcher is reading.
 */
describe('the overview inside a project', () => {
  const renderInProject = () =>
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <OverviewPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon(),
        route: '/projects/prj_abc/overview',
        path: '/projects/prj_abc/overview',
      },
    );

  it('points every attention group at the active project', async () => {
    const { container } = renderInProject();

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    const hrefs = Array.from(container.querySelectorAll('.rh-web-attention > li a')).map((node) =>
      node.getAttribute('href'),
    );
    expect(hrefs.length).toBe(FIXTURES.overview.attention.length);
    expect(hrefs).toEqual(
      FIXTURES.overview.attention.map((group) => `/projects/prj_abc${group.route}`),
    );
  });

  it('points an open question at the project’s own questions screen', async () => {
    // The exported fixture has no open question; the link is what is under test, so one is
    // added to the daemon's own report rather than invented in the view.
    const overview = {
      ...FIXTURES.overview,
      open_questions: [{ id: 'RQ0001', label: 'Does it hold out of distribution?', detail: 'open' }],
    };
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <OverviewPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({ gets: { '/overview': overview } }),
        route: '/projects/prj_abc/overview',
        path: '/projects/prj_abc/overview',
      },
    );

    await waitFor(() => expect(screen.getByText('Open questions')).toBeInTheDocument());
    expect(
      screen.getByRole('link', { name: 'Does it hold out of distribution?' }),
    ).toHaveAttribute('href', '/projects/prj_abc/questions');
  });

  it('leaves the legacy host’s links exactly where they were', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Attention')).toBeInTheDocument());
    const hrefs = Array.from(container.querySelectorAll('.rh-web-attention > li a')).map((node) =>
      node.getAttribute('href'),
    );
    expect(hrefs).toEqual(FIXTURES.overview.attention.map((group) => group.route));
  });
});
