/**
 * The questions page in every state it can be in.
 *
 * The project-scoped links this page draws are covered in `Corpus.test.tsx`, beside the
 * other screens where a Claim id becomes a link. What is asserted here is the frame — the
 * `h1` survives loading and refusal, and the empty state teaches what a question is — and
 * the reading order the Overview proved: the page opens with what is still open, in the
 * daemon's own words and the daemon's own order, and never with the size of the list.
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
  bearing: [],
  remaining_uncertainty: null,
  stale: 'fresh',
  opened: '2026-03-12',
};

const CLAIM = {
  id: 'C0001',
  title: 'Byte-level tokenization improves recall on short encrypted flows.',
};

const OLDER = {
  id: 'RQ0002',
  question: 'Which metrics are comparable across captures?',
  status: 'blocked',
  claims: [CLAIM.id],
  // The daemon carries the statement beside the id: the Claims page's own name for C0001.
  bearing: [CLAIM],
  remaining_uncertainty: 'the two captures use different samplers',
  stale: 'fresh',
  opened: '2026-01-04',
};

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

/**
 * `question.list` as the daemon answers it: the rows, the grouping it composed around them,
 * and the sentence it wrote about what is still open. A test that supplied only the rows
 * would be testing a client that groups them itself, which is the thing this page stopped
 * doing.
 */
function questionsDaemon(
  questions: { id: string; status: string }[],
  summary?: string,
): FakeDaemon {
  const waiting = questions.filter((question) => question.status !== 'answered');
  const answered = questions.filter((question) => question.status === 'answered');
  const groups = [
    ...(waiting.length
      ? [
          {
            kind: 'unanswered',
            label: waiting.length === 1 ? '1 question is still open' : `${waiting.length} questions are still open`,
            count: waiting.length,
            surface: 'waiting',
            // The one status this group's own line already states (`QuestionGroup.status`).
            status: 'open',
            questions: waiting.map((question) => question.id),
          },
        ]
      : []),
    ...(answered.length
      ? [
          {
            kind: 'answered',
            label: answered.length === 1 ? '1 question has been answered' : `${answered.length} questions have been answered`,
            count: answered.length,
            surface: 'settled',
            status: 'answered',
            questions: answered.map((question) => question.id),
          },
        ]
      : []),
  ];
  return fakeDaemon({
    capabilities: {
      'question.list': {
        count: questions.length,
        questions,
        groups,
        summary:
          summary ??
          (questions.length === 0
            ? 'This project has registered no questions yet.'
            : `${groups[0]?.label ?? ''}.`),
      },
    },
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
    const partly = { ...QUESTION, id: 'RQ0009', status: 'partially_answered' };
    const { container } = renderView(<QuestionsPage />, {
      daemon: questionsDaemon([partly]),
    });

    await waitFor(() => expect(screen.getByText('Partially answered')).toBeInTheDocument());
    expect(container.textContent).not.toContain('partially_answered');
  });

  /**
   * A status is badged where it is the subject, and the group's own line is already the
   * subject of every row under it: "1 question is still open" says `open` about all of
   * them. The row that has something to add is the one the line does not describe.
   */
  it('badges a status only where the group’s own line does not already state it', async () => {
    const partly = {
      ...QUESTION,
      id: 'RQ0009',
      question: 'Which captures re-encrypt a flow?',
      status: 'partially_answered',
    };
    renderView(<QuestionsPage />, { daemon: questionsDaemon([QUESTION, partly]) });

    await waitFor(() => expect(screen.getByText(QUESTION.question)).toBeInTheDocument());
    expect(screen.getByText('Partially answered')).toBeInTheDocument();
    expect(screen.queryByText('Open')).not.toBeInTheDocument();
  });

  it('keeps the stale badge, because staleness is never the group', async () => {
    const decayed = { ...QUESTION, id: 'RQ0010', stale: 'stale' };
    renderView(<QuestionsPage />, { daemon: questionsDaemon([decayed]) });

    await waitFor(() => expect(screen.getByText(QUESTION.question)).toBeInTheDocument());
    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.queryByText('Open')).not.toBeInTheDocument();
  });

  /**
   * The count the page used to lead with — "3 registered." — was the size of the list, and
   * the Overview's proof is that the first screenful names work instead. The daemon writes
   * that sentence, so this asserts the page reads it rather than assembling its own.
   */
  it('opens with the daemon’s sentence about what is still open, not with a total', async () => {
    const { container } = renderView(<QuestionsPage />, {
      daemon: questionsDaemon([QUESTION, OLDER]),
    });

    await waitFor(() => expect(screen.getByText(QUESTION.question)).toBeInTheDocument());
    expect(screen.getByText('2 questions are still open.')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d+ registered/);
  });

  it('reads the groups the daemon composed, in the order the daemon put them in', async () => {
    const answered = { ...OLDER, id: 'RQ0003', status: 'answered' };
    const { container } = renderView(<QuestionsPage />, {
      daemon: questionsDaemon([QUESTION, answered]),
    });

    await waitFor(() => expect(screen.getByText('1 question is still open')).toBeInTheDocument());
    expect(screen.getByText('1 question has been answered')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Still open' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Answered' })).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it('says how long a question has waited, and what bears on it', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <QuestionsPage />
      </ProjectPathProvider>,
      {
        daemon: questionsDaemon([OLDER]),
        route: '/projects/prj_abc/questions',
        path: '/projects/prj_abc/questions',
      },
    );

    await waitFor(() => expect(screen.getByText(OLDER.question)).toBeInTheDocument());
    expect(screen.getByText(/Registered 4 January 2026/)).toBeInTheDocument();
    expect(
      screen.getByText(/the two captures use different samplers/),
    ).toBeInTheDocument();
    // The claim is named by what it asserts; the id stays inside the reference chip.
    expect(screen.getByRole('link', { name: `C0001 ${CLAIM.title}` })).toHaveAttribute(
      'href',
      '/projects/prj_abc/claims/C0001',
    );
  });

  it('teaches both halves of the page when only one of them is empty', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <QuestionsPage />
      </ProjectPathProvider>,
      {
        daemon: questionsDaemon([QUESTION]),
        route: '/projects/prj_abc/questions',
        path: '/projects/prj_abc/questions',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('No question has been answered yet')).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('link', { name: 'See the claims that could answer one' }),
    ).toHaveAttribute('href', '/projects/prj_abc/claims');
  });
});
