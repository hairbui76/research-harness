/**
 * Corpus and Questions links, under both hosts.
 *
 * These two screens are where a Work id becomes a link most often — the corpus list, the
 * evidence page's Source panel, and the claims a question is answered by. Under
 * `research app` every one of them has to land inside the project on screen; under
 * `research serve` every one of them has to be exactly the path it has always been.
 *
 * The byte links beside them are the other half of the same rule and belong to the client,
 * not the view: `client.artifactBytesUrl` is already project-scoped by its base URL
 * (`api/client.test.ts`), so what is asserted here is that this view adds no prefix logic
 * of its own on top of it.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CorpusPage, EvidencePage, WorkPage } from './Corpus';
import { QuestionsPage } from './Questions';
import { ProjectPathProvider } from '../app/projectPaths';
import { daemonReachability } from '../api/client';
import type { WorkSummary } from '../api/dto';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const WORK = FIXTURES.index.works[0]!;
const ARTIFACT = WORK.artifacts[0]!;

function corpusDaemon() {
  return fakeDaemon({
    capabilities: { 'work.list': { count: 1, works: [WORK] } },
  });
}

function evidenceDaemon() {
  return fakeDaemon({
    gets: {
      '/objects/E0001': {
        object: {
          origin: 'source_observed',
          evidence_type: 'measurement',
          strength: 'individual',
          content: { exact_text: 'the accepted span' },
          source: { work: WORK.id, artifact: ARTIFACT.id, page: 3, block: 'B0081' },
        },
      },
    },
  });
}

const QUESTION = {
  id: 'RQ0001',
  question: 'Does the encoding survive re-encryption?',
  status: 'open',
  claims: ['C0001'],
  remaining_uncertainty: null,
};

function questionsDaemon() {
  return fakeDaemon({ capabilities: { 'question.list': { count: 1, questions: [QUESTION] } } });
}

describe('the corpus list', () => {
  it('links a Work to the project’s own corpus page', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <CorpusPage />
      </ProjectPathProvider>,
      { daemon: corpusDaemon(), route: '/projects/prj_abc/corpus', path: '/projects/prj_abc/corpus' },
    );

    await waitFor(() => expect(screen.getByText(WORK.title)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: WORK.id })).toHaveAttribute(
      'href',
      `/projects/prj_abc/corpus/${WORK.id}`,
    );
  });

  it('keeps the bare path when there is no project', async () => {
    renderView(<CorpusPage />, {
      daemon: corpusDaemon(),
      route: '/corpus',
      path: '/corpus',
    });

    await waitFor(() => expect(screen.getByText(WORK.title)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: WORK.id })).toHaveAttribute(
      'href',
      `/corpus/${WORK.id}`,
    );
  });

  it('reads the artifact’s bytes from wherever the client points, with no view logic', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <CorpusPage />
      </ProjectPathProvider>,
      { daemon: corpusDaemon(), route: '/projects/prj_abc/corpus', path: '/projects/prj_abc/corpus' },
    );

    await waitFor(() => expect(screen.getByText(WORK.title)).toBeInTheDocument());
    // The test client is the legacy one, so the byte link is the legacy one: the view has
    // added nothing to it, which is exactly the property under test.
    expect(screen.getByRole('link', { name: 'open the file' })).toHaveAttribute(
      'href',
      `http://daemon.test/artifacts/${ARTIFACT.id}/bytes?token=local-token`,
    );
  });
});

/**
 * What the daemon says needs a researcher among these sources.
 *
 * Shaped exactly as `work.list` answers it: the group's whole line is the daemon's
 * sentence, each item is one Work with the cockpit path the daemon chose for it, and
 * `more` is what the daemon's own cap left out. Nothing here is derived in the view — that
 * is the property the tests below are about.
 */
const NEEDS_A_RESEARCHER = [
  {
    kind: 'unparsed',
    label: '4 works have no readable text yet',
    count: 4,
    items: [
      { id: 'W0002', label: 'Encrypted flow taxonomies', detail: '', route: '/corpus/W0002' },
      {
        id: 'W0003',
        label: 'A tokenizer comparison',
        detail: 'none of its 2 files has a stored parse',
        route: '/corpus/W0003',
      },
      { id: 'W0004', label: 'An unregistered draft', detail: '', route: '' },
    ],
    more: '1 more is in the list below.',
  },
];

function needyCorpusDaemon() {
  return fakeDaemon({
    capabilities: {
      'work.list': { count: 1, works: [WORK], attention: NEEDS_A_RESEARCHER },
    },
  });
}

/**
 * Every number on the page that nothing labels.
 *
 * A `<dd>` answers the `<dt>` beside it and a cell answers its column header, so neither is
 * a number standing on its own — that is the comparative reading a table is for. What the
 * rule forbids is the other thing: a count rendered as a figure with nothing around it,
 * which is the stat tile the Overview was rebuilt to leave behind.
 */
function bareNumbers(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('*'))
    .filter(
      (node) =>
        node.children.length === 0 &&
        !['DD', 'TD', 'TH'].includes(node.tagName) &&
        /^\d+([.,]\d+)?%?$/.test((node.textContent ?? '').trim()),
    )
    .map((node) => node.outerHTML);
}

/**
 * The corpus opens with what needs a researcher.
 *
 * PRODUCT §14 and §16 decide when a source is not yet something a project can read from —
 * a screening decision left half-taken, no file, no stored parse, nothing accepted — and
 * the daemon draws every one of those lines. What is asserted here is that the page reads
 * them in that order: the work first, the size of the corpus after it, and no number
 * standing anywhere on its own.
 */
describe('what needs a researcher among the sources', () => {
  it('names the work before it says how much the project holds', async () => {
    const { container } = renderView(<CorpusPage />, {
      daemon: needyCorpusDaemon(),
      route: '/corpus',
      path: '/corpus',
    });

    await waitFor(() =>
      expect(screen.getByText('4 works have no readable text yet')).toBeInTheDocument(),
    );
    const named = screen.getByText('4 works have no readable text yet');
    expect(
      named.compareDocumentPosition(corpusCount()) & Node.DOCUMENT_POSITION_FOLLOWING,
      'the size of the corpus is read after what needs a researcher',
    ).toBeTruthy();
    expect(corpusCount()).toHaveTextContent('1 works.');
    expect(bareNumbers(container), 'no number stands on its own').toEqual([]);
  });

  it('points a named work at itself, and one the daemon gave no page at nothing', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <CorpusPage />
      </ProjectPathProvider>,
      {
        daemon: needyCorpusDaemon(),
        route: '/projects/prj_abc/corpus',
        path: '/projects/prj_abc/corpus',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('4 works have no readable text yet')).toBeInTheDocument(),
    );
    expect(screen.getByRole('link', { name: 'Encrypted flow taxonomies' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/corpus/W0002',
    );
    // No route, so no link: the reader is already on the corpus, and a link to the page
    // under their feet is not a next step.
    expect(screen.getByText('An unregistered draft')).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'An unregistered draft' }),
    ).not.toBeInTheDocument();
  });

  it('says what the daemon left out of the group, in the daemon’s own words', async () => {
    renderView(<CorpusPage />, {
      daemon: needyCorpusDaemon(),
      route: '/corpus',
      path: '/corpus',
    });

    await waitFor(() =>
      expect(screen.getByText('1 more is in the list below.')).toBeInTheDocument(),
    );
    expect(screen.getByText(/none of its 2 files has a stored parse/)).toBeInTheDocument();
  });

  it('teaches what would put a source here when the daemon names none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <CorpusPage />
      </ProjectPathProvider>,
      {
        daemon: corpusDaemon(),
        route: '/projects/prj_abc/corpus',
        path: '/projects/prj_abc/corpus',
      },
    );

    await waitFor(() =>
      expect(
        screen.getByText('Nothing among these sources needs a researcher'),
      ).toBeInTheDocument(),
    );
    // The page never works a group out for itself: the daemon named none, so there is none.
    expect(screen.queryByText(/no readable text yet/)).not.toBeInTheDocument();
    expect(screen.getByText(/no file has been attached to it/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to attach another source' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
    await expectNoAxeViolations(container);
  });

  it('keeps naming it while the daemon is silent, because it was true when it spoke', async () => {
    const daemon = needyCorpusDaemon();
    renderView(<CorpusPage />, { daemon, route: '/corpus', path: '/corpus' });

    await waitFor(() =>
      expect(screen.getByText('4 works have no readable text yet')).toBeInTheDocument(),
    );
    daemonReachability.unanswered('/capabilities/work.list', 'TypeError: Failed to fetch');
    await waitFor(() => expect(corpusCount()).toHaveTextContent(/has not answered since/));
    expect(screen.getByText('4 works have no readable text yet')).toBeInTheDocument();
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderView(<CorpusPage />, {
      daemon: needyCorpusDaemon(),
      route: '/corpus',
      path: '/corpus',
    });

    await waitFor(() =>
      expect(screen.getByText('4 works have no readable text yet')).toBeInTheDocument(),
    );
    await expectNoAxeViolations(container);
  });
});

describe('one accepted piece of evidence', () => {
  it('links its Work inside the project', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <EvidencePage />
      </ProjectPathProvider>,
      {
        daemon: evidenceDaemon(),
        route: '/projects/prj_abc/evidence/E0001',
        path: '/projects/prj_abc/evidence/:evidenceId',
      },
    );

    await waitFor(() => expect(screen.getByText('the accepted span')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: WORK.id })).toHaveAttribute(
      'href',
      `/projects/prj_abc/corpus/${WORK.id}`,
    );
  });

  it('keeps the bare path when there is no project', async () => {
    renderView(<EvidencePage />, {
      daemon: evidenceDaemon(),
      route: '/evidence/E0001',
      path: '/evidence/:evidenceId',
    });

    await waitFor(() => expect(screen.getByText('the accepted span')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: WORK.id })).toHaveAttribute(
      'href',
      `/corpus/${WORK.id}`,
    );
  });
});

describe('the questions screen', () => {
  it('links the claims that bear on a question inside the project', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <QuestionsPage />
      </ProjectPathProvider>,
      {
        daemon: questionsDaemon(),
        route: '/projects/prj_abc/questions',
        path: '/projects/prj_abc/questions',
      },
    );

    await waitFor(() => expect(screen.getByText(QUESTION.question)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'C0001' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/claims/C0001',
    );
  });

  it('keeps the bare path when there is no project', async () => {
    renderView(<QuestionsPage />, {
      daemon: questionsDaemon(),
      route: '/questions',
      path: '/questions',
    });

    await waitFor(() => expect(screen.getByText(QUESTION.question)).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'C0001' })).toHaveAttribute(
      'href',
      '/claims/C0001',
    );
  });
});

/**
 * The corpus in the three states that are not "here are the works".
 *
 * Returning the state instead of the page used to take the `h1` off the screen with it, so
 * the shell's skip link had nowhere to land and a researcher could not tell which page had
 * failed. The frame is asserted first in each of these, the state second.
 */
/**
 * The live line that counts the corpus.
 *
 * The page has more than one polite live region now: an `Empty` is one, and the lead group
 * shows one whenever nothing among the sources needs a researcher. So the count is asked
 * for by the region it belongs to — the works, named by their own heading — rather than by
 * being the only `status` on the screen. The assertions on it are unchanged.
 */
function corpusCount(): HTMLElement {
  return within(
    screen.getByRole('region', { name: 'Every work in the corpus' }),
  ).getByRole('status');
}

const REFUSAL = 'the workspace lock is held by another process';

/** A daemon that has not answered yet, so the page stays in its loading state. */
function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function refusingDaemon(capability: string): FakeDaemon {
  return fakeDaemon({
    capabilities: {
      [capability]: {
        capability,
        ok: false,
        error: { code: 'unavailable', message: REFUSAL },
      },
    },
  });
}

describe('the corpus before, without, and after its read', () => {
  it('keeps its heading and draws panels while the read is in flight', () => {
    const { container } = renderView(<CorpusPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the corpus…');
    expect(container.querySelectorAll('.rh-web-skeleton-card').length).toBeGreaterThan(1);
    expect(container.textContent).not.toMatch(/\d+ works\./);
  });

  it('describes the page rather than the mechanism behind one of its columns', async () => {
    renderView(<CorpusPage />, { daemon: corpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(screen.getByText(/works\./)).toBeInTheDocument());
    // The count moved out of the description and into a live region beside the list. It
    // had to: the find can now narrow the list, and a count that only says how many the
    // daemon sent would be wrong the moment a researcher typed. The description is what
    // the page is, which does not change while it loads or while it is narrowed.
    expect(
      screen.getByText('The sources this project reads from, and the files kept for each.'),
    ).toBeInTheDocument();
    expect(corpusCount()).toHaveTextContent('1 works.');
    expect(screen.queryByText(/anchor replayed/)).not.toBeInTheDocument();
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<CorpusPage />, { daemon: refusingDaemon('work.list') });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what the corpus is for and how a source enters it when it is empty', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <CorpusPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({ capabilities: { 'work.list': { count: 0, works: [] } } }),
        route: '/projects/prj_abc/corpus',
        path: '/projects/prj_abc/corpus',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('No works in the corpus yet')).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument();
    expect(screen.getByText(/whether a file has a stored parse/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to attach a source' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
    await expectNoAxeViolations(container);
  });

  it('states a file size in the units the rest of the product uses', async () => {
    renderView(<CorpusPage />, { daemon: corpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(screen.getByText(WORK.title)).toBeInTheDocument());
    // `formatFileSize` is the package's own wording, so a file reads the same here as it
    // does in the composer's attachment tray. A raw byte count is not a size a reader has.
    expect(screen.queryByText(`${ARTIFACT.size_bytes} bytes`)).not.toBeInTheDocument();
    expect(screen.getByText(/\d+(\.\d)? (B|kB|MB|GB|TB)$/)).toBeInTheDocument();
  });
});

describe('a work that is not in this corpus', () => {
  it('keeps the page and offers the way back rather than a bare sentence', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'evidence.list': { count: 0, evidence: [] },
        'work.get': {
          capability: 'work.get',
          ok: false,
          error: { code: 'not_found', message: REFUSAL },
        },
      },
    });
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <WorkPage />
      </ProjectPathProvider>,
      {
        daemon,
        route: '/projects/prj_abc/corpus/W9999',
        path: '/projects/prj_abc/corpus/:workId',
      },
    );

    // A refusal is a refusal, not an absence: the page says which one it is.
    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'W9999' })).toBeInTheDocument();
  });
});


/**
 * A corpus far past anything a screen can hold.
 *
 * Shaped exactly like the daemon's own summary — the fixture is a real `work.list` row —
 * so what the window mounts is the card the page really draws, nested file table and all.
 */
function manyWorks(count: number): WorkSummary[] {
  return Array.from({ length: count }, (_unused, index) => {
    const id = `W${String(index + 1).padStart(4, '0')}`;
    return {
      ...WORK,
      id,
      title: `Synthetic corpus study ${String(index + 1).padStart(4, '0')}`,
      artifacts: WORK.artifacts.map((artifact) => ({ ...artifact, id: `A${id.slice(1)}-1` })),
    } as WorkSummary;
  });
}

const THOUSAND = manyWorks(1000);

function largeCorpusDaemon() {
  return fakeDaemon({
    capabilities: { 'work.list': { count: THOUSAND.length, works: THOUSAND } },
  });
}

/**
 * A daemon that is not there at all: every request rejects the way `fetch` does when
 * nothing is listening on the port.
 *
 * This is the shape of `ECONNREFUSED` in a browser — a rejected promise, not a status — and
 * it is what the transport has to recognise, because a daemon that has gone away never gets
 * as far as sending a refusal.
 */
function silentDaemon(): FakeDaemon {
  const fetchImpl = async () => {
    throw new TypeError('Failed to fetch');
  };
  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

/** A daemon behind a proxy with nothing behind it. */
function gatewayDaemon(status: number): FakeDaemon {
  const fetchImpl = async () => new Response('<html>bad gateway</html>', { status });
  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

/**
 * One daemon that answers, then stops, then answers again.
 *
 * `stop()` and `start()` are called from the test rather than from a timer, so the moment
 * the daemon goes quiet is the moment the assertion is about.
 */
function flakyDaemon(works: WorkSummary[]) {
  let live = true;
  const inner = fakeDaemon({ capabilities: { 'work.list': { count: works.length, works } } });
  const daemon: FakeDaemon = {
    fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (!live) throw new TypeError('Failed to fetch');
      return inner.fetch(input, init);
    }) as unknown as typeof fetch,
    calls: inner.calls,
    capabilityCalls: inner.capabilityCalls,
  };
  return {
    daemon,
    stop: () => {
      live = false;
    },
    start: () => {
      live = true;
    },
  };
}

// The transport records one outage per window, so a case that took the daemon away has to
// give it back before the next one runs.
afterEach(() => daemonReachability.reset());

/**
 * The corpus past a few hundred works.
 *
 * `work.list` answers the whole corpus in one read and the daemon imposes no page size, so
 * the only bound on what the page mounts is the one the page puts there. These assert that
 * there is one, that the corpus is still whole underneath it, and that nothing a researcher
 * could reach before is now out of reach.
 */
describe('a corpus of a thousand works', () => {
  it('mounts a window of it, not all of it', async () => {
    renderView(<CorpusPage />, { daemon: largeCorpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    const list = screen.getByRole('list', { name: 'Works in the corpus' });
    const mounted = within(list).getAllByRole('listitem');
    expect(mounted.length).toBeGreaterThan(0);
    // The window plus its overscan. The number is not the contract; that it is bounded, and
    // bounded far below the corpus, is.
    expect(mounted.length).toBeLessThan(40);
    expect(screen.queryByText('Synthetic corpus study 0900')).not.toBeInTheDocument();
  });

  it('says how much of the corpus is on screen, and how much there is', async () => {
    const list = THOUSAND;
    renderView(<CorpusPage />, { daemon: largeCorpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    const item = within(screen.getByRole('list', { name: 'Works in the corpus' })).getAllByRole(
      'listitem',
    )[0]!;
    // Each item states where it sits in the whole corpus, so a screen reader is told the
    // size of the list rather than the size of the window.
    expect(item).toHaveAttribute('aria-setsize', String(list.length));
    expect(item).toHaveAttribute('aria-posinset', '1');
  });

  it('reaches a work far down the corpus without scrolling to it', async () => {
    const user = userEvent.setup();
    renderView(<CorpusPage />, { daemon: largeCorpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    // Windowing costs the browser's own find-in-page, so the page carries a find of its
    // own — over the whole corpus, not over the window.
    await user.type(screen.getByRole('searchbox'), 'study 0987');
    await waitFor(() =>
      expect(screen.getByText('Synthetic corpus study 0987')).toBeInTheDocument(),
    );
    expect(corpusCount()).toHaveTextContent('Showing 1 of 1000 works.');
    expect(screen.getByRole('link', { name: 'W0987' })).toHaveAttribute('href', '/corpus/W0987');
  });

  it('says the find only hides, and offers the way back', async () => {
    const user = userEvent.setup();
    renderView(<CorpusPage />, { daemon: largeCorpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    await user.type(screen.getByRole('searchbox'), 'nothing matches this');
    await waitFor(() =>
      expect(screen.getByText('No work matches this find')).toBeInTheDocument(),
    );
    expect(screen.getByText(/The find only hides/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear the find' }));
    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
  });

  it('keeps the list one named, keyboard-reachable scroll region', async () => {
    renderView(<CorpusPage />, { daemon: largeCorpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    const list = screen.getByRole('list', { name: 'Works in the corpus' });
    expect(list).toHaveAttribute('tabindex', '0');

    // End reaches the end of the corpus from the keyboard, without a mouse and without a
    // scrollbar: the last work in the corpus mounts.
    fireEvent.keyDown(list, { key: 'End' });
    await waitFor(() =>
      expect(screen.getByText('Synthetic corpus study 1000')).toBeInTheDocument(),
    );
    expect(within(list).getAllByRole('listitem').length).toBeLessThan(40);

    fireEvent.keyDown(list, { key: 'Home' });
    await waitFor(() =>
      expect(screen.getByText('Synthetic corpus study 0001')).toBeInTheDocument(),
    );
  });

  it('draws each mounted work exactly as it drew it before', async () => {
    renderView(<CorpusPage />, { daemon: largeCorpusDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    const first = within(screen.getByRole('list', { name: 'Works in the corpus' }))
      .getAllByRole('listitem')[0]!;
    // The card, its fields and its nested file table are the ones the page always drew; the
    // window changed when they mount, not what they are.
    expect(within(first).getByRole('heading', { name: 'Synthetic corpus study 0001' })).toBeInTheDocument();
    expect(within(first).getByRole('link', { name: 'W0001' })).toBeInTheDocument();
    expect(within(first).getByRole('table')).toBeInTheDocument();
    expect(within(first).getByRole('columnheader', { name: 'Parsed' })).toBeInTheDocument();
    expect(first.querySelector('[data-density="compact"]')).not.toBeNull();
    expect(first.querySelector('.rh-web-table')).not.toBeNull();
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderView(<CorpusPage />, {
      daemon: largeCorpusDaemon(),
      route: '/corpus',
      path: '/corpus',
    });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('1000 works.'));
    await expectNoAxeViolations(container);
  });
});

/**
 * The corpus when the daemon stops answering.
 *
 * An outage is not a refusal. A refusal is the daemon speaking, and its answer replaces
 * what came before; silence says nothing about the corpus, so the list a researcher was
 * reading is still true of the last moment the daemon spoke. Throwing it away to show an
 * empty screen loses a page for no gain.
 */
describe('the corpus while the daemon is silent', () => {
  it('keeps the last corpus it was given, and says that is what it is', async () => {
    const flaky = flakyDaemon(manyWorks(3));
    renderView(<CorpusPage />, { daemon: flaky.daemon, route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('3 works.'));

    // The daemon goes away, and something asks it for something. The transport records the
    // silence; the page keeps the list it was given and stops claiming it is live.
    flaky.stop();
    daemonReachability.unanswered('/capabilities/work.list', 'TypeError: Failed to fetch');
    await waitFor(() =>
      expect(corpusCount()).toHaveTextContent(
        'The last corpus the daemon sent: 3 works. It has not answered since.',
      ),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument();
    expect(screen.getByText('Synthetic corpus study 0001')).toBeInTheDocument();
  });

  it('keeps the page frame: the heading, the description and the toolbar', async () => {
    const flaky = flakyDaemon(manyWorks(3));
    const { container } = renderView(<CorpusPage />, {
      daemon: flaky.daemon,
      route: '/corpus',
      path: '/corpus',
    });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('3 works.'));
    flaky.stop();
    daemonReachability.unanswered('/capabilities/work.list', 'TypeError: Failed to fetch');
    await waitFor(() =>
      expect(corpusCount()).toHaveTextContent(/has not answered since/),
    );

    // The frame is what says which screen this is. It survives, so the skip link still
    // lands somewhere and the find still works over the list that is on screen.
    expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument();
    expect(
      screen.getByText('The sources this project reads from, and the files kept for each.'),
    ).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__toolbar')).not.toBeNull();
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('reads the corpus again by itself once the daemon answers', async () => {
    const flaky = flakyDaemon(manyWorks(2));
    renderView(<CorpusPage />, { daemon: flaky.daemon, route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(corpusCount()).toHaveTextContent('2 works.'));
    const before = flaky.daemon.calls.length;
    daemonReachability.unanswered('/capabilities/work.list', 'TypeError: Failed to fetch');
    await waitFor(() =>
      expect(corpusCount()).toHaveTextContent(/has not answered since/),
    );

    daemonReachability.reset();
    // No reload, no button: the page asks again because the daemon came back.
    await waitFor(() => expect(flaky.daemon.calls.length).toBeGreaterThan(before));
    await waitFor(() => expect(corpusCount()).toHaveTextContent('2 works.'));
  });

  it('still shows a refusal as a refusal, because a refusal is the daemon answering', async () => {
    renderView(<CorpusPage />, { daemon: refusingDaemon('work.list') });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.queryByText(/has not answered since/)).not.toBeInTheDocument();
  });
});

/**
 * What the transport notices.
 *
 * The whole offline state hangs off one judgement — did anything answer? — so the two
 * shapes that mean "no" are asserted here rather than inferred from the screen.
 */
describe('what counts as the daemon not answering', () => {
  it('counts a rejected fetch', async () => {
    renderView(<CorpusPage />, { daemon: silentDaemon(), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(daemonReachability.get()).not.toBeNull());
    expect(daemonReachability.get()?.reason).toContain('Failed to fetch');
  });

  it.each([502, 504])('counts a %i, which this daemon never sends itself', async (status) => {
    renderView(<CorpusPage />, { daemon: gatewayDaemon(status), route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(daemonReachability.get()).not.toBeNull());
    expect(daemonReachability.get()?.reason).toContain(String(status));
  });

  it('does not count a 503: that is the daemon saying it cannot open the workspace', async () => {
    // `server/app.py::_open_repo` raises one, with a sentence a researcher can act on.
    // Reading it as silence would replace the only message that says what to do about it.
    const daemon: FakeDaemon = {
      fetch: (async () =>
        new Response('the workspace lock is held by another process', {
          status: 503,
        })) as unknown as typeof fetch,
      calls: [],
      capabilityCalls: () => [],
    };
    renderView(<CorpusPage />, { daemon, route: '/corpus', path: '/corpus' });

    await waitFor(() =>
      expect(screen.getByText('the workspace lock is held by another process')).toBeInTheDocument(),
    );
    expect(daemonReachability.get()).toBeNull();
  });

  it('does not count a 500: that is the daemon answering with a fault', async () => {
    const daemon: FakeDaemon = {
      fetch: (async () => new Response('{"detail":"boom"}', { status: 500 })) as unknown as typeof fetch,
      calls: [],
      capabilityCalls: () => [],
    };
    renderView(<CorpusPage />, { daemon, route: '/corpus', path: '/corpus' });

    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument());
    expect(daemonReachability.get()).toBeNull();
  });
});
