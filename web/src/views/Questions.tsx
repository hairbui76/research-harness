/**
 * Questions (PRODUCT §31): what is still open, and what currently bears on it.
 *
 * A question is research state, not a to-do list entry: it carries the claims that answer
 * it and the uncertainty that remains, and it stays open until a researcher resolves it.
 * So the page opens with what is still open, longest-unanswered first, and the questions
 * that have been answered are read after them as the record they are.
 *
 * The grouping and that order are `question.list`'s: which statuses still count as work,
 * and which question has waited longest, are the daemon's judgement and this page renders
 * them (principle P10). A question has no screen of its own, so a row links to nothing but
 * the claims that bear on it — which do.
 *
 * There is no table here. A table earns its place when the reader compares rows across
 * shared columns; these rows share no comparable columns at all — one question's remaining
 * uncertainty is a sentence, its claims are a set, and neither is read against the next
 * question's. Each row carries one fact and one next step, which is a list of sentences.
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and an empty project.
 */
import { Link } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import type { QuestionGroup, QuestionSummary } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel, StatusBadge } from '../components/Feedback';
import { ObjectRef } from '../components/ObjectRef';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './questions.css';

export function QuestionsPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  // `question.list`: one list, through the capability every host shares, with the grouping
  // and the sentence the daemon composed around it.
  const state = useAsync(() => client.questionList(), [client]);

  const list = state.data;
  const questions = list?.questions ?? [];
  // `?? []` because a daemon build older than this grouping still answers `question.list`.
  const groups = list?.groups ?? [];
  const waiting = groups.filter((group) => group.surface === 'waiting');
  const answered = groups.filter((group) => group.surface === 'settled');
  const settled = !state.loading && !state.error;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Questions"
      description={
        // The daemon's own sentence about what is still open. Until it arrives, the part of
        // it that is true without the data.
        settled && list?.summary
          ? list.summary
          : 'A question stays open until a researcher resolves it.'
      }
    >
      {state.loading ? (
        <Loading what="the research questions" shape="list" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : questions.length === 0 ? (
        <Empty
          description="A question records what is still open, the claims that bear on it, and the uncertainty that remains. One is registered by promoting a selection in a conversation."
          action={<Link to={href('/')}>Open the conversation to promote a question</Link>}
        >
          No questions yet
        </Empty>
      ) : (
        <div className="rh-web-stack">
          <Panel title="Still open">
            {waiting.length > 0 ? (
              <ul className="rh-web-list rh-web-questions">
                {waiting.map((group) => (
                  <QuestionGroupList key={group.kind} group={group} questions={questions} />
                ))}
              </ul>
            ) : (
              <Empty
                flat
                description="A question leaves this list when a researcher resolves it, never because a conversation answered it: a transcript is a proposal, and accepted state is what the project stands on."
                action={<Link to={href('/')}>Open the conversation to promote a question</Link>}
              >
                Every question this project registered has been answered
              </Empty>
            )}
          </Panel>

          <Panel title="Answered">
            {answered.length > 0 ? (
              <ul className="rh-web-list rh-web-questions">
                {answered.map((group) => (
                  <QuestionGroupList key={group.kind} group={group} questions={questions} />
                ))}
              </ul>
            ) : (
              <Empty
                flat
                description="Answering a question is a researcher act: the claims that settle it are registered first, and the question is resolved against them. What has been answered is kept here rather than deleted, because the answer is part of the record."
                action={<Link to={href('/claims')}>See the claims that could answer one</Link>}
              >
                No question has been answered yet
              </Empty>
            )}
          </Panel>
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * One group of questions, in the order the daemon put them in: longest unanswered first.
 *
 * The line naming the group is the daemon's own sentence, count and all. A question the
 * list does not carry is skipped rather than drawn blank — the group and the rows come from
 * the same read, so that can only mean a filtered read.
 */
function QuestionGroupList({
  group,
  questions,
}: {
  group: QuestionGroup;
  questions: QuestionSummary[];
}) {
  const byId = new Map(questions.map((question) => [question.id, question]));
  return (
    <li>
      <p className="rh-web-questions__group">{group.label}</p>
      <ul className="rh-web-list rh-web-list--tight rh-web-questions__items">
        {group.questions.map((id) => {
          const question = byId.get(id);
          if (question === undefined) return null;
          return <QuestionRow key={`${group.kind}:${id}`} question={question} group={group} />;
        })}
      </ul>
    </li>
  );
}

/**
 * One question: what it asks, how long it has been on the list, and what bears on it.
 *
 * The claims are the only links here, and they are the next step: a question is answered by
 * registering claims and resolving it against them, so the way out of this row is into a
 * claim. The row itself links nowhere, because the daemon gives a question no route.
 *
 * The status is badged only where it is the subject. Under "1 question is still open" every
 * row is open, and an `Open` badge beside each of them is the group's own name repeated; a
 * partially answered question in that same group is the row that has something to add, and
 * it badges. Which status a group already states is the daemon's (`QuestionGroup.status`).
 * Staleness is not the group in either panel, so it always badges.
 */
function QuestionRow({ question, group }: { question: QuestionSummary; group: QuestionGroup }) {
  const { href } = useProjectPaths();
  return (
    <li>
      <p className="rh-web-row rh-web-questions__question">
        <span>{question.question}</span>
        {question.status === group.status ? null : (
          <StatusBadge status={question.status} vocabulary="questionStatus" describe />
        )}
        {question.stale === 'stale' ? (
          <StatusBadge status="stale" vocabulary="staleState" describe />
        ) : null}
      </p>
      <p className="rh-text-secondary">
        {question.opened ? `Registered ${readableDay(question.opened)}. ` : ''}
        {question.remaining_uncertainty
          ? `Still uncertain: ${question.remaining_uncertainty}`
          : 'No remaining uncertainty has been recorded.'}
      </p>
      <p className="rh-web-row">
        {question.bearing.length > 0 ? (
          <>
            <span className="rh-text-secondary">Bearing on it:</span>
            {/*
              The claim is named by what it asserts, which is what the Claims page calls
              it; the id rides along inside the reference chip, where it has always been.
              `bearing` is the daemon's — a page that looked a statement up itself would be
              a second account of what C0001 says.
            */}
            {question.bearing.map((claim) => (
              <ObjectRef
                key={claim.id}
                id={claim.id}
                kind="claim"
                label={claim.title}
                to={href(`/claims/${claim.id}`)}
              />
            ))}
          </>
        ) : (
          <span className="rh-text-secondary">No claim bears on it yet.</span>
        )}
      </p>
    </li>
  );
}

/**
 * `2026-09-07` as the day a person reads it: `7 September 2026`.
 *
 * Two things are pinned rather than taken from the environment. The date is parsed without
 * a zone designator, because `new Date('2026-09-07')` is UTC midnight and prints as the day
 * before in every negative offset — a question would look a day older west of Greenwich
 * than the daemon said it was. And the format is `en-GB` rather than the viewer's locale,
 * because the daemon already writes every other date in the cockpit this way ("7 September,
 * 11:42" on the Overview's change list), and one surface should not read two ways.
 */
function readableDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? day
    : parsed.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}
