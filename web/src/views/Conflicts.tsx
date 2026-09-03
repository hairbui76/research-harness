/**
 * Conflicts (Product 25): the disagreements, every side kept and none preferred.
 *
 * The open conflict records come from `GET /overview` — the daemon materialises them under
 * `.research/staging/conflicts` and reports them with the attention surfaces. Resolving one
 * is a researcher act and happens on the candidate's own review screen, where the source is
 * visible: accepting, rejecting, or deferring a conflicted proposal there goes through
 * `review.resolve_conflict`, which closes the record with the reason that was given.
 */
import { Link } from 'react-router-dom';
import { Empty, ErrorBox, Loading, Panel, Tag } from '../components/Feedback';
import { ProposedChanges } from './EvidenceReview';
import type { JsonObject } from '../api/dto';
import { useSession } from '../app/session';

export function ConflictsPage() {
  const { overview, loading, error, refresh } = useSession();

  if (loading) return <Loading what="the conflict store" />;
  if (error) return <ErrorBox error={error} retry={refresh} />;
  if (!overview || overview.conflicts.length === 0) {
    return <Empty>No open conflicts.</Empty>;
  }

  return (
    <div className="conflicts">
      <h1>Conflicts</h1>
      <p className="muted">
        {overview.conflicts.length} open. A conflict is a question for a researcher; nothing
        below picks a winner.
      </p>
      {overview.conflicts.map((conflict) => (
        <Panel
          key={conflict.conflict_id}
          title={conflict.subject}
          action={<Tag kind="conflict">{conflict.kind.replace(/_/g, ' ')}</Tag>}
        >
          <p>{conflict.summary}</p>
          <p className="muted">
            Disagrees on: {conflict.differing_fields.join(', ') || 'unrecorded'} · tier{' '}
            {conflict.tier}
          </p>
          <table>
            <thead>
              <tr>
                <th>Position</th>
                <th>Decision</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {conflict.positions.map((position) => (
                <tr key={position.label}>
                  <td>{position.label}</td>
                  <td>
                    <code>{JSON.stringify(position.decision)}</code>
                  </td>
                  <td>{position.rationale ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ProposedChanges changes={conflict.proposed_changes as JsonObject[]} />
          {conflict.subject.startsWith('cand_') ? (
            <Link to={`/review/${conflict.subject}`}>Review it beside the source</Link>
          ) : null}
        </Panel>
      ))}
    </div>
  );
}
