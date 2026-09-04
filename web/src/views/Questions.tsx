/**
 * Questions (PRODUCT §31): what is still open, and what currently bears on it.
 *
 * A question is research state, not a to-do list entry: it carries the claims that answer
 * it and the uncertainty that remains, and it stays open until a researcher resolves it.
 */
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

  if (state.loading) return <Loading what="the research questions" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.length === 0) {
    return <Empty>No research questions registered.</Empty>;
  }

  return (
    <FullPageWorkspace
      title="Questions"
      description={`${state.data.length} registered. A question stays open until a researcher resolves it.`}
    >
      <div className="rh-web-stack">
        {state.data.map((question) => (
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
                      <ObjectRef key={claim} id={claim} kind="claim" to={href(`/claims/${claim}`)} />
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
    </FullPageWorkspace>
  );
}
