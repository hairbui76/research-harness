/**
 * Stale: what went out of date, why, and what it costs — highest scientific impact first.
 *
 * A stale object is accepted state that something underneath it moved: a source gained a
 * version, a re-parse moved a span, a taxonomy Decision was revised. Nothing is ever
 * re-anchored silently (ADR-008), so this page is a list of work rather than a report of
 * damage, and every sentence on it is the daemon's. Staleness is decay the daemon declares;
 * this page has no way to compute one and does not try (Product 37, principle P10).
 *
 * It used to be a table of four columns, one of which mapped a priority integer to a word
 * in React. The tiers are the daemon's judgement about scientific impact, so they come from
 * `GET /stale` as groups now, and each row is a sentence: the object, the daemon's reason,
 * and a link to the object when the daemon gave it a screen of its own. The reasons are the
 * same items the Overview's "Gone stale" group carries — one account of one decay, in one
 * set of words, on both pages.
 *
 * The frame is mounted before the read resolves, so the heading and this page's shape
 * survive loading, a refusal and a project where nothing is stale.
 */
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { FullPageWorkspace, humaniseResearchTokens } from '@research-harness/design';
import type { AttentionItem, ResearchGroup } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel, StatusBadge } from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './stale.css';

export function StalePage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(() => client.staleOverview(), [client]);

  const report = state.data;
  const groups = report?.groups ?? [];
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Stale objects"
      // The part that is true before the read answers; the daemon's own line after it.
      description={report?.summary ?? 'What went out of date, and what it rests on.'}
    >
      {state.loading ? (
        <Loading what="the stale set" shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : groups.length === 0 ? (
        <Empty
          // Word for word the sentence the Overview's "Gone stale" group teaches with: two
          // pages describing one rule differently would be two rules to a reader.
          description="An object goes stale when a source it rests on gains a new version, or a re-parse moves the span an anchor names. Nothing is ever re-anchored silently, so this is work to do rather than damage — and today there is none."
          action={<Link to={href('/corpus')}>Open the corpus this project rests on</Link>}
        >
          Nothing is stale
        </Empty>
      ) : (
        <div className="rh-web-stack">
          {groups.map((group, index) => (
            <Panel
              key={group.key}
              title={group.title}
              // Every object on this page is stale, so the word and its meaning are placed
              // once rather than beside each of them.
              action={index === 0 ? <StatusBadge status="stale" vocabulary="staleState" describe /> : null}
            >
              <StaleGroup group={group} />
            </Panel>
          ))}
          {report?.more ? <p className="rh-web-stale__more">{report.more}</p> : null}
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * One tier of scientific impact: what it costs, then the objects in it.
 *
 * The group's own line states its size inside a sentence and leads to the page those
 * objects live on, where the daemon named one. A tier with no page of its own — the index
 * projection — states the same sentence and links nowhere, because a link to this page
 * from this page is not a next step.
 */
function StaleGroup({ group }: { group: ResearchGroup }) {
  const { href } = useProjectPaths();
  return (
    <div className="rh-web-stale__group">
      <p className="rh-web-row">
        {group.route ? <Link to={href(group.route)}>{group.summary}</Link> : group.summary}
      </p>
      <p className="rh-web-stale__detail">{group.detail}</p>
      <ul className="rh-web-list rh-web-list--tight rh-web-stale__items">
        {group.items.map((item) => (
          <li key={`${group.key}:${item.id}`}>
            <StaleItem item={item}>
              <code>{item.label}</code>
            </StaleItem>{' '}
            <span className="rh-text-secondary">— {humaniseResearchTokens(item.detail)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * One stale object, pointed at itself where the daemon said it has a screen of its own.
 *
 * An object with no route is text, exactly as it is on the Overview: linking it to its own
 * group's page would be a second copy of the link the group's line already is.
 */
function StaleItem({ item, children }: { item: AttentionItem; children: ReactNode }) {
  const { href } = useProjectPaths();
  if (!item.route) return <>{children}</>;
  return <Link to={href(item.route)}>{children}</Link>;
}
