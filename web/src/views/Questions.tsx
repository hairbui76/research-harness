/**
 * Questions (Product 31): what is still open, and what currently bears on it.
 *
 * A question is research state, not a to-do list entry: it carries the claims that answer
 * it and the uncertainty that remains, and it stays open until a researcher resolves it.
 */
import { Link } from 'react-router-dom';
import { Empty, ErrorBox, Field, Loading, Panel, Tag } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

export function QuestionsPage() {
  const { client } = useSession();
  // `question.list`: one list, through the capability every host shares.
  const state = useAsync(() => client.questions(), [client]);

  if (state.loading) return <Loading what="the research questions" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.length === 0) {
    return <Empty>No research questions registered.</Empty>;
  }

  return (
    <div className="questions">
      <h1>Questions</h1>
      {state.data.map((question) => (
        <Panel
          key={question.id}
          title={question.question}
          action={<Tag kind={question.status}>{question.status}</Tag>}
        >
          <Field label="Id">{question.id}</Field>
          <Field label="Claims">
            {question.claims.length ? (
              question.claims.map((claim) => (
                <Link key={claim} to={`/claims/${claim}`}>
                  {claim}{' '}
                </Link>
              ))
            ) : (
              <span className="muted">none linked</span>
            )}
          </Field>
          <Field label="Remaining uncertainty">
            {question.remaining_uncertainty ?? '— not recorded'}
          </Field>
        </Panel>
      ))}
    </div>
  );
}
