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
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and a project with nothing in dispute.
 */
import { Link } from 'react-router-dom';
import {
  Badge,
  FullPageWorkspace,
  humaniseResearchTokens,
  researchLabel,
} from '@research-harness/design';
import {
  DataTable,
  Empty,
  ErrorBox,
  Loading,
  Panel,
  fieldLabel,
} from '../components/Feedback';
import { ProposedChanges, readable } from './EvidenceReview';
import type { JsonObject } from '../api/dto';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';

export function ConflictsPage() {
  const { overview, loading, error, refresh } = useSession();
  const { href } = useProjectPaths();

  const conflicts = overview?.conflicts ?? [];
  const settled = !loading && !error;
  return (
    <FullPageWorkspace
      busy={loading}
      title="Conflicts"
      description={
        settled
          ? `${conflicts.length} open. A conflict is a question for a researcher; nothing below picks a winner.`
          : 'A conflict is a question for a researcher; nothing below picks a winner.'
      }
    >
      {loading ? (
        <Loading what="the conflict store" shape="cards" />
      ) : error ? (
        <ErrorBox error={error} retry={refresh} />
      ) : conflicts.length === 0 ? (
        <Empty
          description="A conflict opens when two readings of the same subject disagree — an extractor against a verifier, one provider against another, a candidate against accepted state. Each one is resolved on the candidate's own review screen, beside the source."
          action={<Link to={href('/review')}>Open the review inbox</Link>}
        >
          No open conflicts
        </Empty>
      ) : (
        <div className="rh-web-stack">
          {conflicts.map((conflict) => (
            <Panel
              key={conflict.conflict_id}
              title={conflict.subject}
              action={
                <Badge status="contested" size="sm">
                  {researchLabel('conflictKind', conflict.kind)}
                </Badge>
              }
            >
              <p>{humaniseResearchTokens(conflict.summary)}</p>
              <p className="rh-text-secondary">
                {conflict.differing_fields.length > 0
                  ? `Disagrees on: ${conflict.differing_fields.map(fieldLabel).join(', ')}`
                  : 'The fields it disagrees on were not recorded'}{' '}
                · {researchLabel('reviewTier', String(conflict.tier))}
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
                    <td>{readable(position.decision)}</td>
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
      )}
    </FullPageWorkspace>
  );
}
