/**
 * Taxonomy: the project's approved terms, and the Decision behind each one.
 *
 * A taxonomy is a researcher-approved classification, not a universal fact (PRODUCT §32),
 * so every term shows the Decision that authorised it. Revising one marks the matrices and
 * claims that used it stale rather than rewriting them (ADR-008).
 */
import { FullPageWorkspace } from '@research-harness/design';
import { DataTable, Empty, ErrorBox, Loading, Panel } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

export function TaxonomyPage() {
  const { client } = useSession();
  const state = useAsync(() => client.index(), [client]);

  if (state.loading) return <Loading what="the taxonomies" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.taxonomies.length === 0) {
    return <Empty>No taxonomy has been approved.</Empty>;
  }

  return (
    <FullPageWorkspace
      title="Taxonomy"
      description="Every term is a researcher-approved classification, with the Decision that authorised it."
    >
      <div className="rh-web-stack">
        {state.data.taxonomies.map((taxonomy) => (
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
    </FullPageWorkspace>
  );
}
