/**
 * The Review Inbox (ROADMAP Task 11.2): the queue in Product 24.2 order, grouped by the
 * reason each item is waiting — conflict, high risk, stale, ambiguous, routine.
 *
 * The order and the grouping are the server's: `review.inbox` returns items already sorted
 * and already labelled with a category and the reasons behind it. This view groups by that
 * label and never reorders, because deciding what a researcher should look at first is a
 * scientific judgement, not a presentation one (Product 5 P8).
 */
import { Link } from 'react-router-dom';
import type { ReviewItem } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel, Tag } from '../components/Feedback';
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
    <div className="inbox">
      <h1>Review inbox</h1>
      <p className="muted">{state.data.count} waiting, in the order Product 24.2 asks for.</p>
      {groups.map(([category, items]) => (
        <Panel key={category} title={`${CATEGORY_LABELS[category] ?? category} (${items.length})`}>
          <ul className="queue">
            {items.map((item) => (
              <ReviewRow key={item.candidate_id} item={item} />
            ))}
          </ul>
        </Panel>
      ))}
    </div>
  );
}

export function ReviewRow({ item }: { item: ReviewItem }) {
  return (
    <li className="queue-row">
      <Link to={`/review/${item.candidate_id}`}>
        <span className="field-name">{item.field}</span>
        <span className="muted"> · {item.work}</span>
      </Link>
      <Tag kind={item.category}>{item.category.replace('_', ' ')}</Tag>
      <span className="muted">tier {item.tier}</span>
      <span className="muted">{item.verdict ?? 'unverified'}</span>
      <blockquote>{item.exact_text}</blockquote>
      <p className="muted">{item.reasons.join('; ')}</p>
    </li>
  );
}
