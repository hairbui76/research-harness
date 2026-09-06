/**
 * Questions (PRODUCT §31): what is still open, and what currently bears on it.
 *
 * A question is research state, not a to-do list entry: it carries the claims that answer
 * it and the uncertainty that remains, and it stays open until a researcher resolves it.
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and an empty project.
 */
import { Link } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import { Empty, ErrorBox, Field, Fields, Loading, Panel, StatusBadge } from '../components/Feedback';
import { ObjectRef } from '../components/ObjectRef';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';

export function QuestionsPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  // `question.list`: one list, through the capability every host shares.
  const state = useAsync(() => client.questions(), [client]);

  const questions = state.data ?? [];
  const settled = !state.loading && !state.error;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Questions"
      description={
        // The count is only true once it has arrived; the sentence beside it always is.
        settled
          ? `${questions.length} registered. A question stays open until a researcher resolves it.`
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
          {questions.map((question) => (
            <Panel
              key={question.id}
              title={question.question}
              action={<StatusBadge status={question.status} />}
            >
              <Fields>
                <Field label="Id">
                  <code>{question.id}</code>
                </Field>
                <Field label="Claims">
                  {question.claims.length ? (
                    <span className="rh-web-row">
                      {question.claims.map((claim) => (
                        <ObjectRef
                          key={claim}
                          id={claim}
                          kind="claim"
                          to={href(`/claims/${claim}`)}
                        />
                      ))}
                    </span>
                  ) : (
                    <span className="rh-text-muted">none linked</span>
                  )}
                </Field>
                <Field label="Remaining uncertainty">
                  {question.remaining_uncertainty ?? '— not recorded'}
                </Field>
              </Fields>
            </Panel>
          ))}
        </div>
      )}
    </FullPageWorkspace>
  );
}
