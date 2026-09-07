/**
 * The questions page in every state it can be in.
 *
 * The project-scoped links this page draws are covered in `Corpus.test.tsx`, beside the
 * other screens where a Claim id becomes a link. What is asserted here is the frame: the
 * `h1` survives loading and refusal, and the empty state teaches what a question is.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { QuestionsPage } from './Questions';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the workspace lock is held by another process';

const QUESTION = {
  id: 'RQ0001',
  question: 'Does the encoding survive re-encryption?',
  status: 'open',
  claims: [],
  remaining_uncertainty: null,
};

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function questionsDaemon(questions: unknown[]): FakeDaemon {
  return fakeDaemon({
    capabilities: { 'question.list': { count: questions.length, questions } },
  });
}

describe('the questions page', () => {
  it('keeps its heading and draws a list while the read is in flight', () => {
    const { container } = renderView(<QuestionsPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Questions' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the research questions…');
    expect(container.querySelector('.rh-skeleton')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d+ registered/);
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<QuestionsPage />, {
      daemon: fakeDaemon({
        capabilities: {
          'question.list': {
            capability: 'question.list',
            ok: false,
            error: { code: 'unavailable', message: REFUSAL },
          },
        },
      }),
    });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Questions' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a question records and where one is raised when there are none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <QuestionsPage />
      </ProjectPathProvider>,
      {
        daemon: questionsDaemon([]),
        route: '/projects/prj_abc/questions',
        path: '/projects/prj_abc/questions',
      },
    );

    await waitFor(() => expect(screen.getByText('No questions yet')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Questions' })).toBeInTheDocument();
    expect(screen.getByText(/the uncertainty that remains/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to promote a question' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
    await expectNoAxeViolations(container);
  });

  it('says a status in the product’s words rather than as an identifier', async () => {
    const partly = { ...QUESTION, id: 'RQ0002', status: 'partially_answered' };
    const { container } = renderView(<QuestionsPage />, {
      daemon: questionsDaemon([partly]),
    });

    await waitFor(() => expect(screen.getByText('Partially answered')).toBeInTheDocument());
    expect(container.textContent).not.toContain('partially_answered');
  });

  it('counts what arrived once the read has answered', async () => {
    renderView(<QuestionsPage />, { daemon: questionsDaemon([QUESTION]) });

    await waitFor(() => expect(screen.getByText(QUESTION.question)).toBeInTheDocument());
    expect(screen.getByText(/^1 registered\./)).toBeInTheDocument();
  });
});
