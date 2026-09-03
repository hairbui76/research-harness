/**
 * The Review Inbox (ROADMAP Task 11.2): the queue in PRODUCT §24.2 order, grouped by the
 * reason each item is waiting — conflict, high risk, stale, ambiguous, routine.
 *
 * The order and the grouping are the server's: `review.inbox` returns items already sorted
 * and already labelled with a category and the reasons behind it. This view groups by that
 * label and never reorders, because deciding what a researcher should look at first is a
 * scientific judgement, not a presentation one (PRODUCT §5 P8).
 */
import { Link } from 'react-router-dom';
import { FullPageWorkspace, SourceAnchor } from '@research-harness/design';
import type { ReviewItem } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel, StatusBadge } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

/** The queue order itself; an item's category is the server's own word for why it is here. */
export const CATEGORY_ORDER = ['conflict', 'high_risk', 'stale', 'ambiguous', 'routine'] as const;

export const CATEGORY_LABELS: Record<string, string> = {
  conflict: 'Conflicts',
  high_risk: 'High-risk scientific claims',
  stale: 'Stale high-impact objects',
  ambiguous: 'Ambiguous extractions',
  routine: 'Routine verified candidates',
};

/** Group the items the server already ordered, keeping its order inside each group. */
export function groupByCategory(items: ReviewItem[]): [string, ReviewItem[]][] {
  return CATEGORY_ORDER.map((category) => [
    category,
    items.filter((item) => item.category === category),
  ]).filter(([, group]) => (group as ReviewItem[]).length > 0) as [string, ReviewItem[]][];
}

export function ReviewInboxPage() {
  const { client } = useSession();
  const state = useAsync(() => client.reviewInbox(), [client]);

  if (state.loading) return <Loading what="the review queue" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.count === 0) {
    return <Empty>Nothing is waiting for review.</Empty>;
  }

  const groups = groupByCategory(state.data.items);
  return (
    <FullPageWorkspace
      title="Review inbox"
      description={`${state.data.count} waiting, in the order PRODUCT §24.2 asks for.`}
    >
      <div className="rh-web-stack">
        {groups.map(([category, items]) => (
          <Panel key={category} title={`${CATEGORY_LABELS[category] ?? category} (${items.length})`}>
            <ul className="rh-web-list rh-web-list--rules">
              {items.map((item) => (
                <ReviewRow key={item.candidate_id} item={item} />
              ))}
            </ul>
          </Panel>
        ))}
      </div>
    </FullPageWorkspace>
  );
}

export function ReviewRow({ item }: { item: ReviewItem }) {
  return (
    <li className="rh-web-stack rh-web-stack--tight">
      <p className="rh-web-row">
        <Link to={`/review/${item.candidate_id}`}>
          <span className="rh-web-queue__field">{item.field}</span>
          <span className="rh-text-secondary"> · {item.work}</span>
        </Link>
        <StatusBadge status={item.category}>{item.category.replace('_', ' ')}</StatusBadge>
        <StatusBadge status={item.verdict ?? 'unverified'}>
          {item.verdict ?? 'unverified'}
        </StatusBadge>
        <span className="rh-text-secondary">tier {item.tier}</span>
      </p>
      <SourceAnchor
        variant="inline"
        anchor={{
          artifactId: item.artifact,
          ...(item.source_context.page === null ? {} : { page: item.source_context.page }),
          stale: item.anchor_status !== 'valid',
        }}
      />
      <blockquote className="rh-web-quote">{item.exact_text}</blockquote>
      <p className="rh-text-secondary">{item.reasons.join('; ')}</p>
    </li>
  );
}
