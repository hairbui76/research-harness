/**
 * The Overview of PRODUCT §26: next actions first, then claim health and open questions.
 *
 * Everything here is read from `GET /overview`, including the order of the attention
 * groups and the wording of their labels. There is no model-confidence number on this page
 * and there is nowhere for one to come from — the daemon does not report one (§43).
 *
 * The frame is mounted before the read resolves, so the project's name and this page's
 * shape are on screen while the counts are still arriving and after a refusal.
 */
import { Link } from 'react-router-dom';
import { Badge, Button, FullPageWorkspace } from '@research-harness/design';
import type { OverviewCounts } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel } from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';

export function OverviewPage() {
  const { overview, error, loading, refresh } = useSession();
  // `attention[].route` is the daemon's own workspace path (`/review`, `/stale`). It stays
  // that way in the DTO and is pointed at this project only as it is rendered.
  const { href } = useProjectPaths();

  const counts: Partial<OverviewCounts> = overview?.counts ?? {};
  return (
    <FullPageWorkspace
      busy={loading}
      // The project's own name once the daemon has said it; until then, the page's name.
      title={overview?.project ?? 'Overview'}
      description={
        overview
          ? `${counts.works ?? 0} works · ${counts.accepted_evidence ?? 0} accepted evidence · ` +
            `${counts.claims ?? 0} claims · review policy ${overview.review_policy}`
          : 'What needs a researcher next, and what this project currently holds.'
      }
    >
      {loading ? (
        <Loading what="the project overview" shape="cards" />
      ) : error ? (
        <ErrorBox error={error} retry={refresh} />
      ) : !overview ? (
        <Empty
          description="Nothing answered on this connection. The daemon may have stopped, or this window may be pointed at a workspace that is no longer open."
          action={
            <Button size="sm" variant="secondary" iconStart="refresh-cw" onClick={refresh}>
              Look again
            </Button>
          }
        >
          No workspace is being served
        </Empty>
      ) : (
        <div className="rh-web-stack">
          <Panel title="Attention">
            <ul className="rh-web-list rh-web-attention">
              {overview.attention.map((group) => (
                <li key={group.kind} data-work={group.count > 0 ? '' : undefined}>
                  <p className="rh-web-row">
                    <Link to={href(group.route)}>{group.label}</Link>
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
              <Empty
                flat
                description="A claim states what this project asserts, beside the strength its evidence allows. Claims begin as a candidate promoted from a conversation."
                action={<Link to={href('/')}>Open the conversation to promote a claim</Link>}
              >
                No claims registered yet
              </Empty>
            )}
          </Panel>

          <Panel title="Open questions">
            {overview.open_questions.length ? (
              <ul className="rh-web-list rh-web-list--tight">
                {overview.open_questions.map((question) => (
                  <li key={question.id}>
                    <Link to={href('/questions')}>{question.label}</Link>{' '}
                    <span className="rh-text-secondary">({question.detail})</span>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty
                flat
                description="A question records what is still open and what currently bears on it. It stays open until a researcher resolves it."
                action={<Link to={href('/')}>Open the conversation to promote a question</Link>}
              >
                No open questions
              </Empty>
            )}
          </Panel>
        </div>
      )}
    </FullPageWorkspace>
  );
}
