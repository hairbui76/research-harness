/**
 * Conflicts (PRODUCT §25): the disagreements, every side kept and none preferred.
 *
 * The open conflict records come from `GET /overview` — the daemon materialises them under
 * `.research/staging/conflicts` and reports them with the attention surfaces. It also
 * reports the grouping this page reads: PRODUCT §25 lists six kinds of disagreement and
 * treats them as different questions, so which group a record belongs in, in what order,
 * and where that one disagreement is decided are all the daemon's (principle P10). This
 * page used to decide the last of those itself, by testing the subject for a `cand_`
 * prefix in React; it now renders the route the daemon gave, and links nothing when the
 * daemon gave none.
 *
 * Resolving one is a researcher act and happens where the subject lives — for a staged
 * candidate, on its own review screen beside the source, where accepting, rejecting or
 * deferring it goes through `review.resolve_conflict` and closes the record with the reason
 * given.
 *
 * The positions stay a table. They are the one genuinely comparative thing on this page:
 * N sides read against the same three columns, which is the reading a table exists for.
 * What is *not* comparative is the list of conflicts itself — each carries one fact and one
 * next step — so that is a group of sentences rather than a run of cards.
 *
 * The Design System's `ConflictNotice` is deliberately *not* used here. Its view model has
 * two named sides — accepted state, and what a conversation remembered — and this record
 * has neither: a provider disagreement is N symmetric positions, none of them accepted.
 * Rendering one through the other would print "Accepted — sent to the model" over a
 * position nobody has accepted, which is the one thing this screen must never do. For the
 * same reason no scientific status colour appears on this page: an open conflict is a queue
 * state, not a contested claim.
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and a project with nothing in dispute.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { FullPageWorkspace, humaniseResearchTokens, researchLabel } from '@research-harness/design';
import {
  DataTable,
  Empty,
  ErrorBox,
  Loading,
  Panel,
  StatusBadge,
  fieldLabel,
} from '../components/Feedback';
import { ProposedChanges, readable } from './EvidenceReview';
import type { AttentionGroup, AttentionItem, ConflictView, JsonObject } from '../api/dto';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import './conflicts.css';

export function ConflictsPage() {
  const { overview, loading, error, refresh } = useSession();
  const { href } = useProjectPaths();

  const groups = overview?.conflict_groups ?? [];
  const conflicts = new Map(
    (overview?.conflicts ?? []).map((conflict) => [conflict.conflict_id, conflict]),
  );
  const settled = !loading && !error;
  return (
    <FullPageWorkspace
      busy={loading}
      title="Conflicts"
      description={
        // The daemon's own sentence about what is in dispute. Until it arrives, the part of
        // it that is true without the data.
        settled && overview?.conflict_summary
          ? overview.conflict_summary
          : 'A conflict is a question for a researcher; nothing below picks a winner.'
      }
    >
      {loading ? (
        <Loading what="the conflict store" shape="cards" />
      ) : error ? (
        <ErrorBox error={error} retry={refresh} />
      ) : groups.length === 0 ? (
        <Empty
          description="A conflict opens when two readings of the same subject disagree — an extractor against a verifier, one provider against another, a candidate against accepted state. Each one is resolved on the candidate's own review screen, beside the source."
          action={<Link to={href('/review')}>Open the review inbox</Link>}
        >
          No open conflicts
        </Empty>
      ) : (
        <Panel title="Open, and waiting for a researcher">
          <ul className="rh-web-list rh-web-conflicts">
            {groups.map((group) => (
              <ConflictGroup key={group.kind} group={group} conflicts={conflicts} />
            ))}
          </ul>
        </Panel>
      )}
    </FullPageWorkspace>
  );
}

/**
 * One kind of disagreement, and every open record of it.
 *
 * The kind is named in the product's own words (`labels.ts`), and the count beside it is
 * the daemon's own phrase for the size of the group — never a number on its own.
 */
function ConflictGroup({
  group,
  conflicts,
}: {
  group: AttentionGroup;
  conflicts: Map<string, ConflictView>;
}) {
  return (
    <li>
      <p className="rh-web-row rh-web-conflicts__kind">
        <span>{researchLabel('conflictKind', group.kind)}</span>
        <span className="rh-text-secondary">{group.label}</span>
      </p>
      <ul className="rh-web-list rh-web-list--rules rh-web-conflicts__items">
        {group.items.map((item) => {
          const conflict = conflicts.get(item.id);
          if (conflict === undefined) return null;
          return <ConflictRow key={item.id} item={item} conflict={conflict} />;
        })}
      </ul>
    </li>
  );
}

/**
 * One disagreement: what is in dispute, what each side said, and where it is decided.
 *
 * The subject is the link, exactly as a waiting item on the Overview is, and only when the
 * daemon gave the record a route. A subject with no screen of its own stays text: this page
 * is where it is on record, and a link back to this page would be a link to nowhere.
 *
 * What the link says is the daemon's name for the subject — the Claim's own statement, or
 * the field and work a staged candidate is called by everywhere else in the cockpit — and
 * never the id the conflict was recorded against. The id is in the route.
 */
function ConflictRow({ item, conflict }: { item: AttentionItem; conflict: ConflictView }) {
  return (
    <li className="rh-web-stack rh-web-stack--tight">
      <p className="rh-web-row">
        <Subject route={item.route}>{humaniseResearchTokens(item.label)}</Subject>
        <StatusBadge status={String(conflict.tier)} vocabulary="reviewTier" describe />
      </p>
      <p>{humaniseResearchTokens(item.detail)}</p>
      <p className="rh-text-secondary">
        {conflict.differing_fields.length > 0
          ? `Disagrees on: ${conflict.differing_fields.map(fieldLabel).join(', ')}`
          : 'The fields it disagrees on were not recorded'}
      </p>
      {/*
        The sides, compared. A table earns its place here and nowhere else on this page: N
        answers read against the same three columns is the reading a table exists for. A
        record that kept no positions gets the sentence instead — a header row with nothing
        under it is a table pretending to hold a comparison nobody made.
      */}
      {conflict.positions.length > 0 ? (
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
      ) : (
        <p className="rh-text-secondary">
          The record kept no side-by-side answers; what disagreed is in the sentence above.
        </p>
      )}
      <ProposedChanges changes={conflict.proposed_changes as JsonObject[]} />
    </li>
  );
}

/** The subject of a disagreement, pointed at wherever the daemon said it is decided. */
function Subject({ route, children }: { route: string; children: ReactNode }) {
  const { href } = useProjectPaths();
  if (!route) return <>{children}</>;
  return <Link to={href(route)}>{children}</Link>;
}
