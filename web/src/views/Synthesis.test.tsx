/**
 * The synthesis page in every state it can be in.
 *
 * This page has three empties that mean different things, and none of them may read the
 * same: no matrix has ever been built, every reading a matrix declares has been recorded,
 * and a field was compared and nothing was recorded under it. The last is where absence is
 * most easily misread as evidence, so it says in words that a gap in the record is not a
 * statement about the works.
 *
 * The rest asserts what wave 3 changed. The page leads with what the matrices *cannot* say
 * — the daemon's own gap sentences — before it shows what they hold, and no count on it
 * stands as a number on its own.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { SynthesisPage } from './Synthesis';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

const MATRIX = {
  id: 'S0001',
  name: 'Traffic shape',
  taxonomy: 'traffic-shape',
  stale: 'fresh',
  works: 2,
  fields: ['tokenization', 'dataset'],
  cells: 2,
  recorded: 2,
  shape: '2 works read for 2 fields',
  coverage: '2 of 4 readings recorded',
};

const REPORT = {
  summary: '2 readings these matrices declare have not been recorded yet.',
  count: 1,
  missing: 2,
  gaps: [
    {
      key: 'S0001',
      title: 'Traffic shape',
      summary: '2 readings this matrix declares have not been recorded',
      detail:
        'A matrix reads one property across works, from accepted evidence. A reading nobody has recorded is a gap in the record: it never means the work lacks the property, and nothing is proposed for it here.',
      count: 2,
      route: '',
      items: [
        { id: 'S0001:dataset', label: 'dataset', detail: 'no work in this matrix has been read for it yet', priority: 2, route: '' },
        { id: 'S0001:W0003', label: 'W0003', detail: 'this matrix has no row for it', priority: 0, route: '/corpus/W0003' },
      ],
    },
  ],
  matrices: [MATRIX],
};

const NO_MATRIX = {
  summary: 'No matrix has been built yet, so nothing reads a property across this corpus.',
  count: 0,
  missing: 0,
  gaps: [],
  matrices: [],
};

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function synthesisDaemon(report: unknown, extra: Record<string, unknown> = {}): FakeDaemon {
  return fakeDaemon({ gets: { '/synthesis': report }, capabilities: extra });
}

describe('the synthesis page', () => {
  it('keeps its heading and its compare form while the read is in flight', () => {
    const { container } = renderView(<SynthesisPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the synthesis matrices…');
    // Comparing a field does not depend on the matrix list, so the form stays usable.
    expect(screen.getByLabelText('Field')).toBeInTheDocument();
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<SynthesisPage />, {
      daemon: {
        fetch: (async () => new Response(REFUSAL, { status: 503 })) as unknown as typeof fetch,
        calls: [],
        capabilityCalls: () => [],
      },
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
      { daemon: synthesisDaemon(NO_MATRIX), route: '/projects/prj_abc/synthesis', path: '/projects/prj_abc/synthesis' },
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

  it('leads with what the matrices cannot say yet, before what they hold', async () => {
    const { container } = renderView(<SynthesisPage />, { daemon: synthesisDaemon(REPORT) });

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 2, name: 'What these matrices cannot say yet' }),
      ).toBeInTheDocument(),
    );
    const headings = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(headings).toEqual([
      'What these matrices cannot say yet',
      'Traffic shape',
      'Compare a field',
    ]);
    expect(container.querySelector('.rh-full-page__description')).toHaveTextContent(REPORT.summary);
  });

  it('names an unread column once, with the daemon’s reason and no claim about a work', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <SynthesisPage />
      </ProjectPathProvider>,
      { daemon: synthesisDaemon(REPORT), route: '/projects/prj_abc/synthesis', path: '/projects/prj_abc/synthesis' },
    );

    await waitFor(() => expect(screen.getByText('Dataset')).toBeInTheDocument());
    expect(
      screen.getByText('— no work in this matrix has been read for it yet'),
    ).toBeInTheDocument();
    // The rule the product exists to protect, said once where the gaps are explained.
    expect(screen.getByText(/never means the work lacks the property/)).toBeInTheDocument();
    // A work the matrix has no row for links to the work, which the corpus does hold.
    expect(screen.getByRole('link', { name: 'W0003' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/corpus/W0003',
    );
  });

  it('states each matrix in sentences rather than as a row of counts', async () => {
    const { container } = renderView(<SynthesisPage />, { daemon: synthesisDaemon(REPORT) });

    await waitFor(() => expect(screen.getByText('2 works read for 2 fields')).toBeInTheDocument());
    expect(screen.getByText('2 of 4 readings recorded')).toBeInTheDocument();
    for (const node of Array.from(container.querySelectorAll('*'))) {
      if (node.children.length === 0) {
        expect((node.textContent ?? '').trim()).not.toMatch(/^\d+$/);
      }
    }
    await expectNoAxeViolations(container);
  });

  it('says so when there is nothing left unrecorded, without saying anything about the works', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <SynthesisPage />
      </ProjectPathProvider>,
      {
        daemon: synthesisDaemon({ ...REPORT, missing: 0, gaps: [] }),
        route: '/projects/prj_abc/synthesis',
        path: '/projects/prj_abc/synthesis',
      },
    );

    await waitFor(() =>
      expect(
        screen.getByText('Every reading these matrices declare has been recorded'),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('link', { name: 'See the works these matrices read' }),
    ).toHaveAttribute('href', '/projects/prj_abc/corpus');
  });

  it('reads a recorded cell out rather than printing its JSON', async () => {
    const { container } = renderView(<SynthesisPage />, {
      daemon: synthesisDaemon(REPORT, {
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
      daemon: synthesisDaemon(NO_MATRIX, {
        'synthesis.compare': { field: 'tokenization', rows: [] },
      }),
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
