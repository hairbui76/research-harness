/**
 * The Overview of PRODUCT §26: next actions first, then claim health and open questions.
 *
 * Everything here is read from `GET /overview`, including the order of the attention
 * groups and the wording of their labels. There is no model-confidence number on this page
 * and there is nowhere for one to come from — the daemon does not report one (§43).
 */
import { Link } from 'react-router-dom';
import { Badge, FullPageWorkspace } from '@research-harness/design';
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
    <FullPageWorkspace
      title={overview.project}
      description={
        `${counts.works ?? 0} works · ${counts.accepted_evidence ?? 0} accepted evidence · ` +
        `${counts.claims ?? 0} claims · review policy ${overview.review_policy}`
      }
    >
      <div className="rh-web-stack">
        <Panel title="Attention">
          <ul className="rh-web-list rh-web-attention">
            {overview.attention.map((group) => (
              <li key={group.kind} data-work={group.count > 0 ? '' : undefined}>
                <p className="rh-web-row">
                  <Link to={group.route}>{group.label}</Link>
                  {group.count > 0 ? (
                    <Badge tone="warning" size="sm" icon="inbox">
                      {`${group.count} waiting`}
                    </Badge>
                  ) : (
                    <Badge tone="neutral" size="sm" icon="circle-check">
                      clear
                    </Badge>
                  )}
                </p>
                {group.items.length > 0 ? (
                  <ul className="rh-web-list rh-web-list--tight rh-web-attention__items">
                    {group.items.map((item) => (
                      <li key={`${group.kind}:${item.id}`}>
                        <span className="rh-web-attention__item">{item.label}</span>
                        {item.detail ? (
                          <span className="rh-text-secondary"> — {item.detail}</span>
                        ) : null}
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
            <ul className="rh-web-tally">
              {overview.claim_health.map((entry) => (
                <li key={entry.key}>
                  <span className="rh-web-tally__count">{entry.count}</span>
                  <span className="rh-text-secondary">{entry.key}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No claims registered yet.</Empty>
          )}
        </Panel>

        <Panel title="Open questions">
          {overview.open_questions.length ? (
            <ul className="rh-web-list rh-web-list--tight">
              {overview.open_questions.map((question) => (
                <li key={question.id}>
                  <Link to="/questions">{question.label}</Link>{' '}
                  <span className="rh-text-secondary">({question.detail})</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>No open questions.</Empty>
          )}
        </Panel>
      </div>
    </FullPageWorkspace>
  );
}
