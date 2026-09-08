/**
 * An address with no page behind it.
 *
 * The route table used to answer `/*` with the Overview, so a stale bookmark showed a
 * plausible wrong page and said nothing about it. What is asserted here is the opposite of
 * that: the frame stays, the page says nothing is served at this address, the address is
 * quoted back so a typo can be seen, and the one way on is the Overview inside whichever
 * project the reader is in.
 */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { NotFoundPage } from './NotFound';
import { OVERVIEW_PATH } from '../app/routes';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';

describe('an address the cockpit serves no page at', () => {
  it('says so inside the frame, and quotes the address back', async () => {
    const { container } = renderView(<NotFoundPage overview={OVERVIEW_PATH} />, {
      daemon: fakeDaemon(),
      route: '/corpuss',
      path: '*',
    });

    expect(
      screen.getByRole('heading', { level: 1, name: 'There is no page at this address' }),
    ).toBeInTheDocument();
    // The address a researcher typed or followed, so a typo is corrected by seeing it —
    // and it is the half the heading above does not say, rather than the same sentence twice.
    expect(screen.getByText('Nothing is served at /corpuss')).toBeInTheDocument();
    // No claim about the project: only the address is wrong.
    expect(screen.getByText(/Nothing about the project has changed/)).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it('offers the Overview of the project the reader is standing in', () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <NotFoundPage overview={OVERVIEW_PATH} />
      </ProjectPathProvider>,
      { daemon: fakeDaemon(), route: '/projects/prj_abc/nowhere', path: '*' },
    );

    expect(screen.getByRole('link', { name: 'Go to the Overview' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/overview',
    );
  });
});
