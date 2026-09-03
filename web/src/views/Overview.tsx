/**
 * The Overview of Product 26: next actions first, then claim health and open questions.
 *
 * Everything here is read from `GET /overview`, including the order of the attention
 * groups and the wording of their labels. There is no model-confidence number on this page
 * and there is nowhere for one to come from — the daemon does not report one (Product 43).
 */
import { Link } from 'react-router-dom';
import type { OverviewCounts } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel } from '../components/Feedback';
import { useSession } from '../app/session';

export function OverviewPage() {
  const { overview, error, loading, refresh } = useSession();

  if (loading) return <Loading what="the project overview" />;
  if (error) return <ErrorBox error={error} retry={refresh} />;
  if (!overview) return <Empty>No workspace is being served.</Empty>;

  const counts: Partial<OverviewCounts> = overview.counts ?? {};
  return (
    <div className="overview">
      <header className="project">
        <h1>{overview.project}</h1>
        <p className="muted">
          {counts.works ?? 0} works · {counts.accepted_evidence ?? 0} accepted evidence ·{' '}
          {counts.claims ?? 0}{' '}
          claims · review policy {overview.review_policy}
        </p>
      </header>

      <Panel title="Attention">
        <ul className="attention">
          {overview.attention.map((group) => (
            <li key={group.kind} className={group.count > 0 ? 'has-work' : 'clear'}>
              <Link to={group.route}>{group.label}</Link>
              {group.items.length > 0 ? (
                <ul className="attention-items">
                  {group.items.map((item) => (
                    <li key={`${group.kind}:${item.id}`}>
                      <span className="item-label">{item.label}</span>
                      {item.detail ? <span className="muted"> — {item.detail}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Claim health">
        {overview.claim_health.length ? (
          <ul className="tally">
            {overview.claim_health.map((entry) => (
              <li key={entry.key}>
                <span className="count">{entry.count}</span> {entry.key}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No claims registered yet.</Empty>
        )}
      </Panel>

      <Panel title="Open questions">
        {overview.open_questions.length ? (
          <ul>
            {overview.open_questions.map((question) => (
              <li key={question.id}>
                <Link to="/questions">{question.label}</Link>{' '}
                <span className="muted">({question.detail})</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No open questions.</Empty>
        )}
      </Panel>
    </div>
  );
}
