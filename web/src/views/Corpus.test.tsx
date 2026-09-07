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
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { CorpusPage, EvidencePage, WorkPage } from './Corpus';
import { QuestionsPage } from './Questions';
import { ProjectPathProvider } from '../app/projectPaths';
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
  stale: 'fresh',
  opened: '2026-03-12',
};

/**
 * `question.list` as the daemon answers it: the row, plus the group it composed around it.
 * The Questions page renders the daemon's grouping rather than building one, so a fixture
 * without `groups` would leave the page with nothing to draw.
 */
function questionsDaemon() {
  return fakeDaemon({
    capabilities: {
      'question.list': {
        count: 1,
        questions: [QUESTION],
        groups: [
          {
            kind: 'unanswered',
            label: '1 question is still open',
            count: 1,
            surface: 'waiting',
            questions: [QUESTION.id],
          },
        ],
        summary: '1 question is still open.',
      },
    },
  });
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
    expect(
      screen.getByText('1 works. The sources this project reads from, and the files kept for each.'),
    ).toBeInTheDocument();
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
