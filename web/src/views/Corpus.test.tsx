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
import { CorpusPage, EvidencePage } from './Corpus';
import { QuestionsPage } from './Questions';
import { ProjectPathProvider } from '../app/projectPaths';
import { FIXTURES, fakeDaemon, renderView } from '../test/harness';

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
