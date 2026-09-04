/**
 * Conflicts (PRODUCT §25): the disagreements, every side kept and none preferred.
 *
 * The open conflict records come from `GET /overview` — the daemon materialises them under
 * `.research/staging/conflicts` and reports them with the attention surfaces. Resolving one
 * is a researcher act and happens on the candidate's own review screen, where the source is
 * visible: accepting, rejecting, or deferring a conflicted proposal there goes through
 * `review.resolve_conflict`, which closes the record with the reason that was given.
 *
 * The Design System's `ConflictNotice` is deliberately *not* used here. Its view model has
 * two named sides — accepted state, and what a conversation remembered — and this record
 * has neither: a provider disagreement is N symmetric positions, none of them accepted.
 * Rendering one through the other would print "Accepted — sent to the model" over a
 * position nobody has accepted, which is the one thing this screen must never do.
 */
import { Link } from 'react-router-dom';
import { Badge, FullPageWorkspace } from '@research-harness/design';
import { DataTable, Empty, ErrorBox, Loading, Panel } from '../components/Feedback';
import { ProposedChanges } from './EvidenceReview';
import type { JsonObject } from '../api/dto';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';

export function ConflictsPage() {
  const { overview, loading, error, refresh } = useSession();
  const { href } = useProjectPaths();

  if (loading) return <Loading what="the conflict store" />;
  if (error) return <ErrorBox error={error} retry={refresh} />;
  if (!overview || overview.conflicts.length === 0) {
    return <Empty>No open conflicts.</Empty>;
  }

  return (
    <FullPageWorkspace
      title="Conflicts"
      description={
        `${overview.conflicts.length} open. A conflict is a question for a researcher; ` +
        'nothing below picks a winner.'
      }
    >
      <div className="rh-web-stack">
        {overview.conflicts.map((conflict) => (
          <Panel
            key={conflict.conflict_id}
            title={conflict.subject}
            action={
              <Badge status="contested" size="sm">
                {conflict.kind.replace(/_/g, ' ')}
              </Badge>
            }
          >
            <p>{conflict.summary}</p>
            <p className="rh-text-secondary">
              Disagrees on: {conflict.differing_fields.join(', ') || 'unrecorded'} · tier{' '}
              {conflict.tier}
            </p>
            <DataTable
              label={`Positions in ${conflict.conflict_id}`}
              head={
                <tr>
                  <th scope="col">Position</th>
                  <th scope="col">Decision</th>
                  <th scope="col">Rationale</th>
                </tr>
              }
            >
              {conflict.positions.map((position) => (
                <tr key={position.label}>
                  <th scope="row">{position.label}</th>
                  <td>
                    <code>{JSON.stringify(position.decision)}</code>
                  </td>
                  <td>{position.rationale ?? '—'}</td>
                </tr>
              ))}
            </DataTable>
            <ProposedChanges changes={conflict.proposed_changes as JsonObject[]} />
            {conflict.subject.startsWith('cand_') ? (
              <Link to={href(`/review/${conflict.subject}`)}>Review it beside the source</Link>
            ) : null}
          </Panel>
        ))}
      </div>
    </FullPageWorkspace>
  );
}
