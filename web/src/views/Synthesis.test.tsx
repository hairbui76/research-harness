/**
 * The synthesis page in every state it can be in.
 *
 * This page has three empties that mean different things, and none of them may read the
 * same: no matrix has ever been built, every reading a matrix declares has been recorded,
 * and one cell of a grid nobody has read. The last is where absence is most easily misread
 * as evidence, so it says in words that a gap in the record is not a statement about a work.
 *
 * The rest asserts what the page is now. It still leads with what the matrices *cannot* say
 * — the daemon's own gap sentences — before what they hold, and no count on it stands as a
 * number on its own. What it holds is now the matrix itself: a grid of the works it declares
 * against the fields it declares, every cell either a recorded reading or the words "Not
 * recorded", every recorded one openable onto the accepted span behind it, and the field to
 * read down its column picked out of the matrix's own columns rather than typed from memory.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SynthesisPage } from './Synthesis';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

const BLANK =
  'No reading has been recorded here yet. A blank cell is a gap in the record, never a reading of the work.';

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
  labels_from: 'Its labels come from the traffic-shape taxonomy.',
  columns: [
    {
      field: 'tokenization',
      recorded: 2,
      coverage: 'All 2 works read for it',
      reading:
        'All 2 works read for it. Recorded: padded (1 work), unpadded (1 work). The works read for it do not all record the same label.',
    },
    {
      field: 'dataset',
      recorded: 0,
      coverage: 'No work in this matrix has been read for it yet',
      reading:
        'No work in this matrix has been read for it yet, so there is nothing to read across it.',
    },
  ],
  rows: [
    {
      work: 'W0001',
      title: 'Padding and flow shape',
      route: '/corpus/W0001',
      summary: '1 of 2 readings recorded',
      cells: [
        {
          work: 'W0001',
          field: 'tokenization',
          recorded: true,
          reading: 'padded',
          measurement: 'F1 94.32 percent',
          detail: 'Read from 1 accepted evidence span.',
          evidence: [
            {
              id: 'E0001',
              title: 'metric_result · Padding and flow shape',
              route: '/evidence/E0001',
              quote: 'each record is padded to a fixed size before the flow is tokenised',
              measurement: 'F1 94.32 percent',
              found: true,
            },
          ],
        },
        {
          work: 'W0001',
          field: 'dataset',
          recorded: false,
          reading: '',
          measurement: '',
          detail: BLANK,
          evidence: [],
        },
      ],
    },
    {
      work: 'W0002',
      title: 'Unpadded capture traces',
      route: '/corpus/W0002',
      summary: '1 of 2 readings recorded',
      cells: [
        {
          work: 'W0002',
          field: 'tokenization',
          recorded: true,
          reading: 'unpadded',
          measurement: '',
          detail: 'No accepted evidence is recorded behind this reading.',
          evidence: [],
        },
        {
          work: 'W0002',
          field: 'dataset',
          recorded: false,
          reading: '',
          measurement: '',
          detail: BLANK,
          evidence: [],
        },
      ],
    },
  ],
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

function synthesisDaemon(report: unknown): FakeDaemon {
  return fakeDaemon({ gets: { '/synthesis': report } });
}

/** The page over a project whose one matrix is half read, at a known project path. */
function renderSynthesis(report: unknown = REPORT) {
  return renderView(
    <ProjectPathProvider projectId="prj_abc">
      <SynthesisPage />
    </ProjectPathProvider>,
    {
      daemon: synthesisDaemon(report),
      route: '/projects/prj_abc/synthesis',
      path: '/projects/prj_abc/synthesis',
    },
  );
}


/**
 * One page of a long matrix's rows, in the matrix's own declared order.
 *
 * Every odd work is read for `tokenization` and none is read for `dataset`, so a window
 * over the page still holds both states of a cell and the grid can be asserted on what a
 * researcher would actually see in it.
 */
function pagedRows(from: number, count: number) {
  return Array.from({ length: count }, (_unused, offset) => {
    const index = from + offset;
    const work = `W${String(index).padStart(4, '0')}`;
    const read = index % 2 === 1;
    return {
      work,
      title: `Synthetic corpus study ${String(index).padStart(4, '0')}`,
      route: `/corpus/${work}`,
      summary: read ? '1 of 2 readings recorded' : 'no reading recorded yet',
      cells: [
        {
          work,
          field: 'tokenization',
          recorded: read,
          reading: read ? 'padded' : '',
          measurement: '',
          detail: read ? 'Read from 1 accepted evidence span.' : BLANK,
          evidence: [],
        },
        { work, field: 'dataset', recorded: false, reading: '', measurement: '', detail: BLANK, evidence: [] },
      ],
    };
  });
}

/** A matrix the daemon answered in pages: a thousand works, three of them sent so far. */
const PAGED = {
  ...MATRIX,
  id: 'S0002',
  name: 'Traffic shape at scale',
  works: 1000,
  shape: '1000 works read for 2 fields',
  coverage: '500 of 2000 readings recorded',
  rows: pagedRows(1, 3),
  paged: true,
  next_row: 'W0003',
};

function pagedReport(matrix: unknown = PAGED) {
  return {
    summary: '1500 readings these matrices declare have not been recorded yet.',
    count: 1,
    missing: 1500,
    gaps: [],
    matrices: [matrix],
  };
}

/**
 * A daemon that answers `/synthesis` whole and `?matrix=&after=` with the next page.
 *
 * `fakeDaemon` keys on the path alone, and paging is entirely in the query, so this one
 * reads the search parameters and records them: what is being asserted is that the page
 * asks for the rows after the cursor it was given, in the matrix's own order.
 */
function pagingDaemon(options: {
  works: number;
  pages: number[];
  stall?: boolean;
}): FakeDaemon & { asked: string[] } {
  const asked: string[] = [];
  const sizes = options.pages;
  let sent = 0;
  const answer = (index: number) => {
    const size = sizes[index] ?? 0;
    const rows = pagedRows(sent + 1, size);
    sent += size;
    return pagedReport({
      ...PAGED,
      works: options.works,
      rows,
      next_row: sent < options.works ? (rows[rows.length - 1]?.work ?? '') : '',
    });
  };
  const first = answer(0);
  let page = 1;
  const fetchImpl = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://daemon.test');
    if (url.pathname !== '/synthesis') return new Response('not found', { status: 404 });
    const after = url.searchParams.get('after') ?? '';
    if (after === '') {
      return new Response(JSON.stringify(first), {
        headers: { 'content-type': 'application/json' },
      });
    }
    asked.push(after);
    if (options.stall) return new Promise<Response>(() => undefined);
    const body = answer(page);
    page += 1;
    return new Response(JSON.stringify(body), {
      headers: { 'content-type': 'application/json' },
    });
  }) as unknown as typeof fetch;
  return { fetch: fetchImpl, calls: [], capabilityCalls: () => [], asked };
}

function renderPaged(daemon: FakeDaemon) {
  return renderView(
    <ProjectPathProvider projectId="prj_abc">
      <SynthesisPage />
    </ProjectPathProvider>,
    { daemon, route: '/projects/prj_abc/synthesis', path: '/projects/prj_abc/synthesis' },
  );
}


describe('the synthesis page', () => {
  it('keeps its heading, and draws the grid that is coming, while the read is in flight', () => {
    const { container } = renderView(<SynthesisPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Synthesis' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the synthesis matrices…');
    // The placeholder is shaped like the grid that is arriving, not like a spinner.
    expect(container.querySelector('.rh-web-skeleton-table')).toBeInTheDocument();
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
    const { container } = renderSynthesis(NO_MATRIX);

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
    const { container } = renderSynthesis();

    await waitFor(() =>
      expect(
        screen.getByRole('heading', { level: 2, name: 'What these matrices cannot say yet' }),
      ).toBeInTheDocument(),
    );
    const headings = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(headings).toEqual(['What these matrices cannot say yet', 'Traffic shape']);
    expect(container.querySelector('.rh-full-page__description')).toHaveTextContent(REPORT.summary);
  });

  it('names an unread column once, with the daemon’s reason and no claim about a work', async () => {
    const { container } = renderSynthesis();

    await waitFor(() =>
      expect(container.querySelectorAll('.rh-web-synthesis__column')).toHaveLength(1),
    );
    // The gap names the column in the vocabulary's word, once, not once per empty cell.
    expect(container.querySelector('.rh-web-synthesis__column')).toHaveTextContent('Dataset');
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
    const { container } = renderSynthesis();

    await waitFor(() =>
      expect(
        screen.getByText('2 works read for 2 fields. 2 of 4 readings recorded.'),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText('Its labels come from the traffic-shape taxonomy.'),
    ).toBeInTheDocument();
    for (const node of Array.from(container.querySelectorAll('*'))) {
      if (node.children.length === 0) {
        expect((node.textContent ?? '').trim()).not.toMatch(/^\d+$/);
      }
    }
    await expectNoAxeViolations(container);
  });

  it('draws the matrix as a grid of its own works against its own fields', async () => {
    const { container } = renderSynthesis();

    await waitFor(() =>
      expect(screen.getByRole('columnheader', { name: 'Work' })).toBeInTheDocument(),
    );
    // The column heads are the vocabulary's words, in the matrix's own declared order.
    const columns = screen
      .getAllByRole('columnheader')
      .map((node) => (node.textContent ?? '').trim());
    expect(columns).toEqual(['Work', 'Tokenization', 'Dataset']);
    // Every declared work is a row, headed by its title with its id beside it.
    const work = screen.getByRole('rowheader', { name: /Padding and flow shape/ });
    expect(work).toHaveTextContent('W0001');
    expect(work).toHaveTextContent('1 of 2 readings recorded');
    expect(screen.getByRole('link', { name: 'Padding and flow shape' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/corpus/W0001',
    );
    // Both recorded readings are on the page, each in its own cell.
    expect(screen.getByText('padded')).toBeInTheDocument();
    expect(screen.getByText('unpadded')).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it('says “not recorded” in words in every cell nobody has read', async () => {
    renderSynthesis();

    await waitFor(() => expect(screen.getAllByText('Not recorded')).toHaveLength(2));
    // The rule, once, under the grid the empty cells are in.
    expect(screen.getByText(/An empty cell means/)).toHaveTextContent(
      'never “absent”',
    );
  });

  it('opens a blank cell onto what a blank means rather than onto a reading', async () => {
    renderSynthesis();

    await waitFor(() => expect(screen.getAllByText('Not recorded')).toHaveLength(2));
    fireEvent.click(screen.getAllByText('Not recorded')[0]!);

    // The distinction this product exists to protect: a gap in the record is not an absence.
    expect(await screen.findByText(BLANK)).toBeInTheDocument();
    expect(screen.queryByRole('blockquote')).not.toBeInTheDocument();
  });

  it('opens a recorded cell onto the accepted span it rests on, read out rather than as JSON', async () => {
    const { container } = renderSynthesis();

    await waitFor(() => expect(screen.getByText('padded')).toBeInTheDocument());
    // The number keeps the metric and the unit it was recorded under (PRODUCT §12).
    expect(screen.getAllByText('F1 94.32 percent').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText('padded'));

    expect(await screen.findByText('Read from 1 accepted evidence span.')).toBeInTheDocument();
    expect(
      screen.getByText('each record is padded to a fixed size before the flow is tokenised'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /metric result · Padding and flow shape/ }),
    ).toHaveAttribute('href', '/projects/prj_abc/evidence/E0001');
    expect(container.textContent).not.toMatch(/[{}]/);
  });

  it('says so when a recorded reading has no accepted evidence behind it', async () => {
    renderSynthesis();

    await waitFor(() => expect(screen.getByText('unpadded')).toBeInTheDocument());
    fireEvent.click(screen.getByText('unpadded'));

    expect(
      await screen.findByText('No accepted evidence is recorded behind this reading.'),
    ).toBeInTheDocument();
  });

  it('labels the field picker in the control role, and once', async () => {
    // DESIGN.md's Inputs section: "Labels are `ui`". The 11px uppercase mono role names a
    // group, a column or a `<dt>`; set above a control it is the kicker the craft floor
    // forbids. The visible label is also the combobox's accessible name, so the control
    // carries one name rather than a visible label the box then overrides with its own.
    renderSynthesis();

    const picker = await screen.findByRole('combobox', {
      name: 'Read a field down its column',
    });
    const label = document.querySelector<HTMLLabelElement>(`label[for="${picker.id}"]`);
    expect(label).not.toBeNull();
    expect(label).toHaveTextContent('Read a field down its column');
    expect(label).not.toHaveClass('rh-text-label');
    expect(label).toHaveClass('rh-field__label');
    expect(picker).not.toHaveAttribute('aria-label');
    expect(picker).toHaveAttribute('aria-labelledby', label!.id);
  });

  it('offers the matrix’s own fields to read down, and never asks for one to be typed', async () => {
    const user = userEvent.setup();
    const { container } = renderSynthesis();

    const picker = await screen.findByRole('combobox', {
      name: 'Read a field down its column',
    });
    expect(picker).toHaveValue('');
    // Every field this matrix declares is offered without a character being typed.
    await user.click(picker);
    const offered = (await screen.findAllByRole('option')).map((node) =>
      (node.textContent ?? '').trim(),
    );
    expect(offered).toEqual([
      'TokenizationAll 2 works read for it',
      'DatasetNo work in this matrix has been read for it yet',
    ]);

    await user.click(screen.getByRole('option', { name: /Dataset/ }));

    // The answer is the column itself, marked in place, and the daemon's sentence about it.
    expect(screen.getByRole('columnheader', { name: 'Dataset' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(
      screen.getByText(
        'Dataset — No work in this matrix has been read for it yet, so there is nothing to read across it.',
      ),
    ).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it('reads a column down by pressing its head, and unmarks it by pressing again', async () => {
    renderSynthesis();

    const head = await screen.findByRole('button', { name: 'Tokenization' });
    fireEvent.click(head);

    expect(head).toHaveAttribute('aria-pressed', 'true');
    expect(
      screen.getByText(/Recorded: padded \(1 work\), unpadded \(1 work\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/do not all record the same label/)).toBeInTheDocument();

    fireEvent.click(head);
    expect(head).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText(/do not all record the same label/)).not.toBeInTheDocument();
  });

  it('leaves a matrix inside the daemon\u2019s page size the table it has always been', async () => {
    // Windowing is a cost a corpus of a few hundred works imposes; a matrix under the
    // threshold arrives whole and is still drawn whole, with no find and no window.
    renderSynthesis();

    await waitFor(() =>
      expect(screen.getByRole('columnheader', { name: 'Work' })).toBeInTheDocument(),
    );
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  });

  it('windows a paged matrix and still states the whole of it to a screen reader', async () => {
    // Only the rows near the viewport exist, so the grid states how many rows the matrix
    // has rather than letting assistive technology count the ones this client has loaded.
    renderPaged(pagingDaemon({ works: 1000, pages: [3], stall: true }));

    const grid = await screen.findByRole('grid', {
      name: 'The Traffic shape at scale matrix',
    });
    expect(grid).toHaveAttribute('aria-rowcount', '1001');
    expect(
      screen.getAllByRole('columnheader').map((node) => (node.textContent ?? '').trim()),
    ).toEqual(['Work', 'Tokenization', 'Dataset']);
    const rows = screen.getAllByRole('row');
    expect(rows[0]).toHaveAttribute('aria-rowindex', '1');
    expect(rows[1]).toHaveAttribute('aria-rowindex', '2');
    expect(rows.length, 'a window, not a thousand rows').toBeLessThan(20);
    expect(
      screen.getByRole('rowheader', { name: /Synthetic corpus study 0001/ }),
    ).toBeInTheDocument();
  });

  it('says how much of the matrix is not loaded, and draws a skeleton row rather than a spinner', async () => {
    const { container } = renderPaged(pagingDaemon({ works: 1000, pages: [3], stall: true }));

    await screen.findByRole('grid', { name: 'The Traffic shape at scale matrix' });
    expect(
      screen.getByText(
        '3 of 1000 works loaded. The rest load as the window reaches them, and the find only reaches the works that are loaded.',
      ),
    ).toBeInTheDocument();
    // The page in flight is a row shaped like the rows around it, never a spinner.
    expect(container.querySelector('.rh-skeleton')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('asks the daemon for the rows after the cursor as the window reaches them', async () => {
    const daemon = pagingDaemon({ works: 6, pages: [3, 3] });
    renderPaged(daemon);

    await screen.findByRole('rowheader', { name: /Synthetic corpus study 0004/ });
    expect(daemon.asked, 'the cursor is the work the last page ended on').toEqual(['W0003']);
    expect(screen.getByText('All 6 works are loaded.')).toBeInTheDocument();
  });

  it('finds a work in what is loaded, and says how far the find reaches', async () => {
    const user = userEvent.setup();
    renderPaged(pagingDaemon({ works: 1000, pages: [3], stall: true }));

    await screen.findByRole('grid', { name: 'The Traffic shape at scale matrix' });
    const find = screen.getByRole('searchbox', { name: 'Find a work in this matrix' });
    await user.type(find, '0002');

    expect(
      screen.getByRole('rowheader', { name: /Synthetic corpus study 0002/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Synthetic corpus study 0001')).not.toBeInTheDocument();
    expect(
      screen.getByText(
        'Showing 1 of the 3 works loaded. 997 more have not been loaded yet, and the find does not reach them.',
      ),
    ).toBeInTheDocument();
  });

  it('opens a cell of a windowed row onto the same evidence a whole matrix opens', async () => {
    renderPaged(pagingDaemon({ works: 1000, pages: [3], stall: true }));

    await screen.findByRole('grid', { name: 'The Traffic shape at scale matrix' });
    fireEvent.click(screen.getAllByText('Not recorded')[0]!);

    expect(await screen.findByText(BLANK)).toBeInTheDocument();
  });

  it('has no accessibility violations while it windows a matrix', async () => {
    const { container } = renderPaged(pagingDaemon({ works: 1000, pages: [3], stall: true }));

    await screen.findByRole('grid', { name: 'The Traffic shape at scale matrix' });
    // With the skeleton row in it: the state a researcher meets while a page is on its way
    // is the one most likely to have an unnamed control or an orphan row in it.
    await waitFor(() => expect(container.querySelector('.rh-skeleton')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });

  it('says so when there is nothing left unrecorded, without saying anything about the works', async () => {
    renderSynthesis({ ...REPORT, missing: 0, gaps: [] });

    await waitFor(() =>
      expect(
        screen.getByText('Every reading these matrices declare has been recorded'),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('link', { name: 'See the works these matrices read' }),
    ).toHaveAttribute('href', '/projects/prj_abc/corpus');
  });
});
