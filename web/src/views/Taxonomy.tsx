/**
 * Taxonomy: the project's approved terms, and the Decision behind each one.
 *
 * A taxonomy is a researcher-approved classification, not a universal fact (PRODUCT §32),
 * so every term shows the Decision that authorised it. Revising one marks the matrices and
 * claims that used it stale rather than rewriting them (ADR-008).
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and a project with no approved terms.
 */
import { Link } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import { DataTable, Empty, ErrorBox, Loading, Panel } from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';

export function TaxonomyPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(() => client.index(), [client]);

  const taxonomies = state.data?.taxonomies ?? [];
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Taxonomy"
      description="Every term is a researcher-approved classification, with the Decision that authorised it."
    >
      {state.loading ? (
        <Loading what="the taxonomies" shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : taxonomies.length === 0 ? (
        <Empty
          description="A taxonomy is how this project agrees to classify its works. Each term is approved by a Decision, and revising one marks what used it stale rather than rewriting it."
          action={<Link to={href('/')}>Open the conversation to propose a term</Link>}
        >
          No taxonomy has been approved yet
        </Empty>
      ) : (
        <div className="rh-web-stack">
          {taxonomies.map((taxonomy) => (
            <Panel key={taxonomy.name} title={taxonomy.name}>
              <DataTable
                label={`${taxonomy.name} terms`}
                head={
                  <tr>
                    <th scope="col">Term</th>
                    <th scope="col">Parent</th>
                    <th scope="col">Definition</th>
                    <th scope="col">Decision</th>
                  </tr>
                }
              >
                {taxonomy.terms.map((term) => (
                  <tr key={String(term.term)}>
                    <th scope="row">{String(term.term)}</th>
                    <td>{term.parent ? String(term.parent) : '—'}</td>
                    <td>{term.definition ? String(term.definition) : '—'}</td>
                    <td>{term.decision ? <code>{String(term.decision)}</code> : '—'}</td>
                  </tr>
                ))}
              </DataTable>
            </Panel>
          ))}
        </div>
      )}
    </FullPageWorkspace>
  );
}
