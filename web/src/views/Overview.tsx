/**
 * The Overview: the research state that matters today, and the pattern the other research
 * pages follow.
 *
 * PRODUCT §26 asks this page to emphasise next actions rather than vanity metrics, and it
 * used to open with a row of large numbers — the stat tile the design critique named. The
 * reading order now is what a researcher actually needs on opening a project: what is
 * waiting for a decision, what has gone stale, what changed since they last worked, then
 * claim health and the open questions. What the project *holds* is still stated, once, in
 * the footer, as a sentence whose counts lead to the pages that hold them.
 *
 * Everything here is read from `GET /overview`: the order of the attention groups, their
 * labels, which of them are decisions and which are decay, the window "since your last
 * session" covers, and the sentence describing it. There is no model-confidence number on
 * this page and there is nowhere for one to come from — the daemon does not report one
 * (§43). A client displays this; it never recomputes it (principle P10).
 *
 * The frame is mounted before the read resolves, so the project's name, the description and
 * the toolbar are on screen while the report is arriving and after a refusal.
 */
import { Fragment, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Button,
  ChangeList,
  FullPageWorkspace,
  humaniseResearchTokens,
  humaniseTerm,
} from '@research-harness/design';
import type { ChangeListEntry } from '@research-harness/design';
import type {
  AttentionGroup,
  AttentionItem,
  OverviewCounts,
  OverviewReport,
} from '../api/dto';
import {
  AttentionName,
  Empty,
  ErrorBox,
  Loading,
  Panel,
  StatusBadge,
  clockTime,
} from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import './overview.css';

/** What the daemon reports when a project has recorded nothing yet. */
const NO_CHANGES: NonNullable<OverviewReport['since_last_session']> = {
  basis: 'no_history',
  since: '',
  summary: 'No research activity has been recorded in this project yet.',
  more: '',
  entries: [],
  total: 0,
};

/** `1 work` / `4 works` — a count is only ever read inside the thing it counts. */
function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

export function OverviewPage() {
  const { overview, error, loading, refresh, readAt } = useSession();
  /*
   * Whether the read-at line is a live region yet.
   *
   * A page that announced every read would talk over the work: the automatic first read is
   * quiet text. Pressing "Look again" is a question — is this still current? — so the press
   * arms the region *before* the answer lands, which is the only ordering a polite live
   * region is actually announced in, and it stays armed because every later read is one the
   * researcher asked for too.
   */
  const [announceRead, setAnnounceRead] = useState(false);
  const lookAgain = (): void => {
    setAnnounceRead(true);
    refresh();
  };
  // `attention[].route` and `since_last_session[].route` are the daemon's own workspace
  // paths (`/review`, `/claims/C0001`). They stay that way in the DTO and are pointed at
  // this project only as they are rendered.
  const { href } = useProjectPaths();
  const navigate = useNavigate();

  const waiting = (overview?.attention ?? []).filter((group) => group.surface !== 'stale');
  // A surface with nothing waiting on it is not work, so it is not a row in a list of work
  // (third critique, minor: "0 unsupported manuscript claims — nothing waiting here" states
  // a zero and then states it again). The ones that are clear are named once, below.
  const working = waiting.filter((group) => group.count > 0);
  const clear = waiting.filter((group) => group.count === 0);
  const stale = (overview?.attention ?? []).find((group) => group.surface === 'stale');
  const changes = overview?.since_last_session ?? NO_CHANGES;

  return (
    <FullPageWorkspace
      busy={loading}
      // The project's own name once the daemon has said it; until then, the page's name.
      title={overview?.project ?? 'Overview'}
      description={
        overview?.attention_summary ??
        'What needs a researcher next, and what changed since you last worked.'
      }
      toolbar={
        <>
          <LastRead at={readAt} announce={announceRead} />
          <Button size="sm" variant="secondary" iconStart="refresh-cw" onClick={lookAgain}>
            Look again
          </Button>
        </>
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
            <Button size="sm" variant="secondary" iconStart="refresh-cw" onClick={lookAgain}>
              Look again
            </Button>
          }
        >
          No workspace is being served
        </Empty>
      ) : (
        <div className="rh-web-stack">
          <Panel title="Waiting for a decision">
            {working.length > 0 ? (
              <>
                <ul className="rh-web-list rh-web-attention">
                  {working.map((group) => (
                    <WaitingGroup key={group.kind} group={group} />
                  ))}
                </ul>
                <Clear groups={clear} />
              </>
            ) : (
              <Empty
                flat
                description="A candidate reaches the queue when a run stages it from a source, and a conflict opens when two readings of the same span disagree. Nothing becomes accepted state without a researcher, so an empty queue means there is nothing to accept."
                action={<Link to={href('/review')}>Open the review inbox</Link>}
              >
                Nothing is waiting for a decision
              </Empty>
            )}
          </Panel>

          <Panel
            title="Gone stale"
            action={<StatusBadge status="stale" vocabulary="staleState" describe />}
          >
            {stale && stale.count > 0 ? (
              <div className="rh-web-overview__group">
                <p className="rh-web-row">
                  <Link to={href(stale.route)}>{stale.label}</Link>
                </p>
                <ul className="rh-web-list rh-web-list--tight rh-web-overview__stale">
                  {stale.items.map((item) => (
                    <li key={item.id}>
                      <ItemLink item={item} fallback={stale.route}>
                        <AttentionName item={item} />
                      </ItemLink>{' '}
                      <span className="rh-text-secondary">
                        — {humaniseResearchTokens(item.detail)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <Empty
                flat
                description="An object goes stale when a source it rests on gains a new version, or a re-parse moves the span an anchor names. Nothing is ever re-anchored silently, so this is work to do rather than damage — and today there is none."
                action={<Link to={href('/corpus')}>Open the corpus this project rests on</Link>}
              >
                Nothing is stale
              </Empty>
            )}
          </Panel>

          <Panel title="Since your last session">
            {changes.entries.length > 0 ? (
              <>
                <p className="rh-web-overview__window">{changes.summary}</p>
                <ChangeList
                  label="What changed since your last session"
                  entries={changes.entries.map(
                    (entry): ChangeListEntry => ({
                      id: entry.id,
                      kind: entry.kind,
                      label: humaniseResearchTokens(entry.label),
                      at: entry.at,
                      when: entry.when,
                      // Who the daemon says did it, when it says. An entry the record
                      // attributes to nobody carries nothing rather than a guess.
                      ...(entry.by ? { by: entry.by } : {}),
                      ...(entry.route ? { href: href(entry.route) } : {}),
                    }),
                  )}
                  onOpen={(entry) => {
                    if (entry.href) navigate(entry.href);
                  }}
                />
                {changes.more ? (
                  <p className="rh-web-overview__window">{changes.more}</p>
                ) : null}
              </>
            ) : (
              <Empty
                flat
                description="Works added, evidence accepted, claims promoted and decisions taken all appear here, newest first, so a session can start where the last one stopped."
                action={
                  <Link to={href('/')}>Open the conversation to start the next piece of work</Link>
                }
              >
                {changes.summary}
              </Empty>
            )}
          </Panel>

          <Panel title="Claim health">
            {overview.claim_health.length ? (
              <ul className="rh-web-list rh-web-list--tight rh-web-overview__health">
                {overview.claim_health.map((entry) => (
                  <li key={entry.key}>
                    <Link to={href('/claims')}>
                      {`${counted(entry.count, 'claim')} ${entry.count === 1 ? 'is' : 'are'}`}
                    </Link>{' '}
                    <StatusBadge status={entry.key} vocabulary="claimStatus" describe />
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
              <ul className="rh-web-list rh-web-list--tight rh-web-overview__questions">
                {overview.open_questions.map((question) => (
                  <li key={question.id}>
                    <Link to={href('/questions')}>{question.label}</Link>{' '}
                    <StatusBadge status={question.detail} vocabulary="questionStatus" />
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

          <Holdings overview={overview} />
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * When what is on screen was read, next to the button that reads again.
 *
 * The critique's finding was that "Look again" never says when it last looked, which leaves
 * a returning researcher unable to tell a project with nothing happening from a page that
 * stopped listening. The instant is the transport's own stamp for the round trip that
 * answered — one clock for the whole window — and it is the time of day, not a date,
 * because it answers "how old is this?" over a sitting rather than over a week.
 *
 * Nothing is shown before the first answer: a page that has read nothing has no time to
 * report, and inventing one would be the opposite of the point.
 */
function LastRead({ at, announce }: { at: string | null; announce: boolean }) {
  if (at === null) return null;
  return (
    <span className="rh-web-overview__read" {...(announce ? { role: 'status' } : {})}>
      Read at {clockTime(at)}
    </span>
  );
}

/**
 * The surfaces with nothing waiting on them, named once, under the ones that have work.
 *
 * Each of them used to be a row of its own reading "0 conflicts — nothing waiting here":
 * the fact stated as a number and then stated again as a phrase, on a line that looked
 * exactly like work. One line for all of them says the same thing once, and keeps every
 * route the daemon gave, so nothing on this page becomes unreachable by being clear.
 *
 * The noun is the daemon's own `kind` read as words — the same token the label counts —
 * because a client that invented a second name for a surface would give the cockpit two
 * words for one page.
 */
function Clear({ groups }: { groups: AttentionGroup[] }) {
  const { href } = useProjectPaths();
  if (groups.length === 0) return null;
  return (
    <p className="rh-web-overview__clear">
      Nothing is waiting in{' '}
      {groups.map((group, index) => (
        <Fragment key={group.kind}>
          {index === 0 ? '' : index === groups.length - 1 ? ' or ' : ', '}
          <Link to={href(group.route)}>{humaniseTerm(group.kind).toLowerCase()}</Link>
        </Fragment>
      ))}
      .
    </p>
  );
}

/**
 * One surface that is waiting: the daemon's own count in words, and its first few items.
 *
 * The count is in the label the daemon composed — "2 review items" — so a `waiting` chip
 * beside it repeated the card's own title. Only groups that have work reach this component;
 * `data-work` stays because the stylesheet reads the group's state from it.
 */
function WaitingGroup({ group }: { group: AttentionGroup }) {
  const { href } = useProjectPaths();
  return (
    <li data-work="">
      <p className="rh-web-row">
        <Link to={href(group.route)}>{group.label}</Link>
      </p>
      {group.items.length > 0 ? (
        <ul className="rh-web-list rh-web-list--tight rh-web-attention__items">
          {group.items.map((item) => (
            <li key={`${group.kind}:${item.id}`}>
              <ItemLink item={item} fallback={group.route}>
                <span className="rh-web-attention__item">{humaniseResearchTokens(item.label)}</span>
              </ItemLink>
              {item.detail ? (
                <span className="rh-text-secondary">
                  {' '}
                  — {humaniseResearchTokens(item.detail)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * One waiting item, pointed at itself where the daemon said it has a screen of its own.
 *
 * An item with no route of its own is *not* linked to its group: the group's own line is
 * already that link, and a second copy of it under every item would be five links to one
 * place. The item is text, and the reader reaches it through the group.
 */
function ItemLink({
  item,
  fallback,
  children,
}: {
  item: AttentionItem;
  fallback: string;
  children: ReactNode;
}) {
  const { href } = useProjectPaths();
  if (!item.route) return <>{children}</>;
  return <Link to={href(item.route || fallback)}>{children}</Link>;
}

/**
 * What the project holds, said once, at the end.
 *
 * PRODUCT §26 states the size of the project on this page and the brief forbids vanity
 * metrics; both hold when the counts are a sentence that leads to the pages that hold
 * them, and neither does when they are a row of large numbers above the work.
 *
 * It is the last thing in the page's own column rather than a footer bar, because a bar
 * pinned to the bottom of every screen would put the size of the project permanently in
 * front of the work — which is the placement the brief rules out, only smaller.
 */
function Holdings({ overview }: { overview: OverviewReport }) {
  const { href } = useProjectPaths();
  // `counts` carries a default on the wire, so a report that omits it still reads as a
  // project holding nothing rather than as a page that cannot render.
  const counts: Partial<OverviewCounts> = overview.counts ?? {};
  return (
    <p className="rh-web-overview__holdings">
      This project holds <Link to={href('/corpus')}>{counted(counts.works ?? 0, 'work')}</Link> with{' '}
      {counted(counts.accepted_evidence ?? 0, 'piece', 'pieces')} of accepted evidence,{' '}
      <Link to={href('/claims')}>{counted(counts.claims ?? 0, 'claim')}</Link> and{' '}
      <Link to={href('/questions')}>{counted(counts.questions ?? 0, 'question')}</Link>. Review policy:{' '}
      {humaniseTerm(overview.review_policy).toLowerCase()}. The next decision this project
      records will be <code>{overview.next_decision_id}</code>.
    </p>
  );
}