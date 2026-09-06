/**
 * The taxonomy page in every state it can be in.
 *
 * The frame is the assertion: loading, a refusal and a project with no approved terms all
 * keep the `h1` the shell's skip link lands on, and the empty state says what a taxonomy
 * is for rather than only that there is not one.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { TaxonomyPage } from './Taxonomy';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

const INDEX = {
  works: [],
  claims: [],
  questions: [],
  decisions: [],
  anchors: [],
  matrices: [],
  taxonomies: [
    {
      name: 'traffic-shape',
      terms: [
        {
          term: 'padded',
          parent: null,
          definition: 'a flow whose records are padded to a fixed size',
          decision: 'D0004',
        },
      ],
    },
  ],
};

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function indexDaemon(taxonomies: unknown[]): FakeDaemon {
  return fakeDaemon({ capabilities: { 'state.index': { ...INDEX, taxonomies } } });
}

describe('the taxonomy page', () => {
  it('keeps its heading and draws panels while the read is in flight', () => {
    const { container } = renderView(<TaxonomyPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the taxonomies…');
    expect(container.querySelectorAll('.rh-web-skeleton-card').length).toBeGreaterThan(1);
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<TaxonomyPage />, {
      daemon: fakeDaemon({
        capabilities: {
          'state.index': {
            capability: 'state.index',
            ok: false,
            error: { code: 'unavailable', message: REFUSAL },
          },
        },
      }),
    });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a taxonomy is and where one is proposed when there is none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <TaxonomyPage />
      </ProjectPathProvider>,
      {
        daemon: indexDaemon([]),
        route: '/projects/prj_abc/taxonomy',
        path: '/projects/prj_abc/taxonomy',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('No taxonomy has been approved yet')).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeInTheDocument();
    expect(screen.getByText(/approved by a Decision/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to propose a term' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
    await expectNoAxeViolations(container);
  });

  it('shows the approved terms and the decision behind each one', async () => {
    renderView(<TaxonomyPage />, { daemon: indexDaemon(INDEX.taxonomies) });

    await waitFor(() => expect(screen.getByText('traffic-shape')).toBeInTheDocument());
    expect(screen.getByText('padded')).toBeInTheDocument();
    expect(screen.getByText('D0004')).toBeInTheDocument();
  });
});
