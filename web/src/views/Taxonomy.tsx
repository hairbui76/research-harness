/**
 * Taxonomy: which terms need a researcher, and then the classification itself.
 *
 * A taxonomy is a researcher-approved classification, not a universal fact (PRODUCT §32).
 * The consequence this page now opens with is what that means when it is *not* satisfied: a
 * term no Decision approves, or one whose Decision has been superseded, is classifying works
 * on an authority this project never granted. That is the work, so it is read first; the
 * classification is read after it.
 *
 * The classification itself stays a table, because a table is what it is: every term is
 * compared across the same three columns. What changed is that the table is the tree it
 * describes — the daemon walks the terms and states each one's depth, so a `Parent` column
 * holding an id is replaced by the indentation a person reads a hierarchy from.
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and a project with no approved terms.
 */
import { Link } from 'react-router-dom';
import { FullPageWorkspace } from '@research-harness/design';
import type { ResearchGroup, TaxonomyView } from '../api/dto';
import { DataTable, Empty, ErrorBox, Loading, Panel, StatusBadge } from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './taxonomy.css';

/** How deep the table indents before it stops; deeper terms sit at the last step. */
const MAX_DEPTH = 4;

export function TaxonomyPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(() => client.taxonomy(), [client]);

  const report = state.data;
  const taxonomies = report?.taxonomies ?? [];
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Taxonomy"
      description={
        report?.summary ??
        'Every term is a researcher-approved classification, with the Decision that authorised it.'
      }
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
          <WaitingForADecision group={report?.needs_decision} />
          {taxonomies.map((taxonomy) => (
            <Classification key={taxonomy.name} taxonomy={taxonomy} />
          ))}
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * The terms nothing accepted stands behind, which is the work this page is opened for.
 *
 * Each item is a sentence rather than a row: the term, the taxonomy it belongs to, and the
 * daemon's own account of what is missing — no Decision at all, one that was superseded,
 * one still only proposed, or one this project has no record of. A Decision has no screen
 * of its own in the cockpit, so nothing here is a link to a page that cannot hold it.
 */
function WaitingForADecision({ group }: { group: ResearchGroup | undefined }) {
  const { href } = useProjectPaths();
  // The daemon always sends this group; a report without it is one from a daemon that
  // predates the route, and the page shows the classification rather than an empty frame.
  if (!group) return null;
  return (
    <Panel title={group.title}>
      {group.count > 0 ? (
        <div className="rh-web-taxonomy__group">
          <p className="rh-web-row">{group.summary}</p>
          <p className="rh-web-taxonomy__detail">{group.detail}</p>
          <ul className="rh-web-list rh-web-list--tight rh-web-taxonomy__items">
            {group.items.map((item) => (
              <li key={item.id}>
                <span className="rh-web-taxonomy__term-name">{item.label}</span>{' '}
                <span className="rh-text-secondary">— {item.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <Empty
          flat
          description={group.detail}
          action={<Link to={href('/')}>Open the conversation to propose a term</Link>}
        >
          Every term is approved by an accepted Decision
        </Empty>
      )}
    </Panel>
  );
}

/**
 * One taxonomy, as the tree it is: each term under the one it hangs from.
 *
 * The `Decision` column is where the authority is, so it carries the id and — when the
 * Decision is not an accepted one — the word for what it actually is. That badge is a
 * decision status and wears the vocabulary's own presentation; no scientific status colour
 * is borrowed for it.
 */
function Classification({ taxonomy }: { taxonomy: TaxonomyView }) {
  return (
    <Panel title={taxonomy.name}>
      <p className="rh-web-taxonomy__detail">{taxonomy.summary}</p>
      <DataTable
        label={`${taxonomy.name} terms`}
        head={
          <tr>
            <th scope="col">Term</th>
            <th scope="col">Definition</th>
            <th scope="col">Approved by</th>
          </tr>
        }
      >
        {taxonomy.terms.map((term) => (
          <tr key={term.term}>
            <th
              scope="row"
              className="rh-web-taxonomy__term"
              data-depth={Math.min(term.depth, MAX_DEPTH)}
            >
              <span className="rh-web-taxonomy__term-name">{term.term}</span>
            </th>
            <td>{term.definition || '—'}</td>
            <td>
              {term.decision ? (
                <span className="rh-web-taxonomy__decision">
                  <code>{term.decision}</code>
                  {term.approved ? null : (
                    <StatusBadge status={term.decision_status || 'proposed'} vocabulary="decisionStatus" />
                  )}
                </span>
              ) : (
                'No Decision yet'
              )}
            </td>
          </tr>
        ))}
      </DataTable>
    </Panel>
  );
}
