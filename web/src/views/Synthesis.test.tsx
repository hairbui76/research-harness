/**
 * The synthesis page in every state it can be in.
 *
 * This page has two empties that mean different things, and they must not read the same:
 * no matrix has ever been built, and a field was compared and nothing was recorded under
 * it. The second one is where absence is most easily misread as evidence, so it says in
 * words that a gap in the record is not a statement about the works.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { SynthesisPage } from './Synthesis';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

const EMPTY_INDEX = {
  works: [],
  claims: [],
  questions: [],
  decisions: [],
  anchors: [],
  matrices: [],
  taxonomies: [],
};

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function synthesisDaemon(extra: Record<string, unknown> = {}): FakeDaemon {
  return fakeDaemon({ capabilities: { 'state.index': EMPTY_INDEX, ...extra } });
}

describe('the synthesis page', () => {
  it('keeps its heading and its compare form while the matrix list is in flight', () => {
    const { container } = renderView(<SynthesisPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the synthesis matrices…');
    // Comparing a field does not depend on the matrix list, so the form stays usable.
    expect(screen.getByLabelText('Field')).toBeInTheDocument();
  });

  it('keeps its heading when the matrix list is refused, and offers the retry', async () => {
    renderView(<SynthesisPage />, {
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
    expect(screen.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a matrix reads, and points at the works it would read', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <SynthesisPage />
      </ProjectPathProvider>,
      {
        daemon: synthesisDaemon(),
        route: '/projects/prj_abc/synthesis',
        path: '/projects/prj_abc/synthesis',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('No synthesis matrix has been built yet')).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'See the works a matrix would read' }),
    ).toHaveAttribute('href', '/projects/prj_abc/corpus');
    await expectNoAxeViolations(container);
  });

  it('reads a recorded cell out rather than printing its JSON', async () => {
    const { container } = renderView(<SynthesisPage />, {
      daemon: synthesisDaemon({
        'synthesis.compare': {
          field: 'metric_result',
          rows: [
            {
              work: 'W0001',
              metric_result: { value: '94.32', unit: 'percent' },
              author_limitation: null,
            },
          ],
        },
      }),
    });

    await waitFor(() => expect(screen.getByLabelText('Field')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Field'), { target: { value: 'metric_result' } });
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));

    await waitFor(() =>
      expect(screen.getByRole('columnheader', { name: 'Metric result' })).toBeInTheDocument(),
    );
    expect(screen.getByText('Value: 94.32 · Unit: percent')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/[{}]/);
    expect(container.textContent).not.toContain('author_limitation');
  });

  it('tells a field with no rows apart from a project with no matrix', async () => {
    renderView(<SynthesisPage />, {
      daemon: synthesisDaemon({ 'synthesis.compare': { field: 'tokenization', rows: [] } }),
    });

    await waitFor(() => expect(screen.getByLabelText('Field')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Field'), { target: { value: 'tokenization' } });
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));

    await waitFor(() =>
      expect(screen.getByText('Nothing recorded under “tokenization”')).toBeInTheDocument(),
    );
    // The distinction this product exists to protect: a gap in the record is not an absence.
    expect(screen.getByText(/not a statement about the works/)).toBeInTheDocument();
    expect(screen.getByText('No synthesis matrix has been built yet')).toBeInTheDocument();
  });
});
