/**
 * The Review Inbox (ROADMAP Task 11.2): the queue in the priority order of Product 24.2,
 * grouped by the reason each item is waiting — conflict, high risk, stale, ambiguous,
 * routine — and, since the throughput work, something a researcher can get through.
 *
 * The order and the grouping are the server's: `review.inbox` returns items already sorted
 * and already labelled with a category and the reasons behind it. This view groups by that
 * label and never reorders, because deciding what a researcher should look at first is a
 * scientific judgement, not a presentation one (Product 5 P8). Every control on this page
 * therefore only *hides*: searching and filtering take items out of the list, and nothing
 * moves one. The daemon already ranks inside a category — deeper review first, then the
 * older candidate — and a control that re-ranked that would be the cockpit deciding what
 * to look at first.
 *
 * Batch acceptance is the daemon's, end to end. `review.accept_batch` takes a work or the
 * whole queue and nothing finer — there is no per-item selection to offer, because the
 * conditions of Product 24.4 are checked per candidate at the moment of the call and a
 * workspace under the default strict policy refuses the request outright. So the ceremony
 * here is: preview with `dry_run`, restate what the write would do, then write, then render
 * what came back — accepted, skipped with the daemon's reason for each, or the refusal in
 * the daemon's own sentence.
 */
import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, FullPageWorkspace, Input, Select, SourceAnchor } from '@research-harness/design';
import type { BatchAcceptResponse, ReviewItem } from '../api/dto';
import { Empty, ErrorBox, Loading, Panel, StatusBadge } from '../components/Feedback';
import { useRegisterCommands } from '../app/commands';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './review.css';

/** The queue order itself; an item's category is the server's own word for why it is here. */
export const CATEGORY_ORDER = ['conflict', 'high_risk', 'stale', 'ambiguous', 'routine'] as const;

export const CATEGORY_LABELS: Record<string, string> = {
  conflict: 'Conflicts',
  high_risk: 'High-risk scientific claims',
  stale: 'Stale high-impact objects',
  ambiguous: 'Ambiguous extractions',
  routine: 'Routine verified candidates',
};

/** What this page is, said once, in the product's words rather than by citing a document. */
const QUEUE_DESCRIPTION =
  'Conflicts first, then high-risk claims, stale high-impact objects, ambiguous ' +
  'extractions, and routine candidates — the order the daemon ranked them in.';

/** How a researcher may narrow the queue on screen. None of it changes the queue. */
export interface InboxFilters {
  /** Matched against the field, the work, the quoted span and the reasons. */
  text: string;
  /** One of the daemon's category words, or '' for every category. */
  category: string;
  /** One of the verifier's verdicts, or '' for every verdict. */
  verdict: string;
}

export const NO_FILTERS: InboxFilters = { text: '', category: '', verdict: '' };

/** Group the items the server already ordered, keeping its order inside each group. */
export function groupByCategory(items: ReviewItem[]): [string, ReviewItem[]][] {
  return CATEGORY_ORDER.map((category) => [
    category,
    items.filter((item) => item.category === category),
  ]).filter(([, group]) => (group as ReviewItem[]).length > 0) as [string, ReviewItem[]][];
}

/** Whether one item survives the filters. Text matches every term, anywhere in the item. */
export function matchesFilters(item: ReviewItem, filters: InboxFilters): boolean {
  if (filters.category && item.category !== filters.category) return false;
  if (filters.verdict && (item.verdict ?? 'unverified') !== filters.verdict) return false;
  const terms = filters.text.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [item.field, item.work, item.exact_text, ...item.reasons]
    .join(' ')
    .toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

/** The groups to draw: the server's order, minus whatever the filters hide. */
export function inboxGroups(items: ReviewItem[], filters: InboxFilters): [string, ReviewItem[]][] {
  return groupByCategory(items.filter((item) => matchesFilters(item, filters)));
}

export function ReviewInboxPage() {
  const { client, canMutate, refresh } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(() => client.reviewInbox(), [client]);
  const [filters, setFilters] = useState<InboxFilters>(NO_FILTERS);
  /** True once a batch has written something here, so its report survives the reload. */
  const [written, setWritten] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);

  const items = useMemo(() => state.data?.items ?? [], [state.data]);
  const groups = useMemo(() => inboxGroups(items, filters), [items, filters]);
  const showing = groups.reduce((total, [, group]) => total + group.length, 0);
  const filtered = filters.text !== '' || filters.category !== '' || filters.verdict !== '';

  /**
   * Move the focus ring, not a selection of our own. The row's link is what Enter opens, so
   * putting real focus on it is what makes `j` and Enter agree with the mouse and with a
   * screen reader — and it survives a filter that removed the row underneath.
   */
  const moveRow = (delta: number): void => {
    const rows = Array.from(
      listRef.current?.querySelectorAll<HTMLAnchorElement>('a[data-review-row]') ?? [],
    );
    if (rows.length === 0) return;
    const current = rows.findIndex((row) => row === document.activeElement);
    const next = current < 0 ? (delta > 0 ? 0 : rows.length - 1) : current + delta;
    rows[Math.min(Math.max(next, 0), rows.length - 1)]?.focus();
  };

  useRegisterCommands(
    () => [
      {
        id: 'inbox:next',
        label: 'Next candidate',
        group: 'Review inbox',
        shortcut: 'j',
        hint: 'Move down the queue; Enter opens the candidate in focus.',
        run: () => moveRow(1),
      },
      {
        id: 'inbox:previous',
        label: 'Previous candidate',
        group: 'Review inbox',
        shortcut: 'k',
        hint: 'Move back up the queue.',
        run: () => moveRow(-1),
      },
    ],
    [],
  );

  return (
    <FullPageWorkspace
      className="rh-web-inbox"
      title="Review inbox"
      description={QUEUE_DESCRIPTION}
      toolbar={
        items.length > 0 ? (
          <InboxFilterBar items={items} filters={filters} onChange={setFilters} />
        ) : (
          <></>
        )
      }
    >
      {state.loading ? <Loading what="the review queue" /> : null}
      {state.error ? <ErrorBox error={state.error} retry={state.reload} /> : null}

      {!state.loading && !state.error ? (
        <div className="rh-web-stack" ref={listRef}>
          {items.length > 0 ? (
            <p className="rh-text-secondary" role="status">
              {filtered
                ? `Showing ${showing} of ${items.length} waiting.`
                : `${items.length} waiting.`}
            </p>
          ) : null}

          {/* The panel outlives the queue on purpose: a batch that accepted everything
              empties the list it reported on, and the receipt for a write of accepted
              state must not disappear with it. */}
          {canMutate && (items.length > 0 || written) ? (
            <BatchAccept
              items={items}
              onAccepted={() => {
                setWritten(true);
                state.reload();
                refresh();
              }}
            />
          ) : null}

          {items.length === 0 ? (
            <Empty>
              Nothing is waiting for review. Interrogate a work in{' '}
              <Link to={href('/corpus')}>the corpus</Link> to stage new candidates, or ask{' '}
              <Link to={href('/')}>the conversation</Link> what to look at next.
            </Empty>
          ) : showing === 0 ? (
            <Empty>
              No candidate matches these filters. Nothing has left the queue.{' '}
              <Button size="sm" variant="secondary" onClick={() => setFilters(NO_FILTERS)}>
                Clear the filters
              </Button>
            </Empty>
          ) : (
            groups.map(([category, group]) => (
              <Panel
                key={category}
                title={`${CATEGORY_LABELS[category] ?? category} (${group.length})`}
              >
                <ul className="rh-web-list rh-web-list--rules">
                  {group.map((item) => (
                    <ReviewRow key={item.candidate_id} item={item} />
                  ))}
                </ul>
              </Panel>
            ))
          )}
        </div>
      ) : null}
    </FullPageWorkspace>
  );
}

interface FilterBarProps {
  items: ReviewItem[];
  filters: InboxFilters;
  onChange: (filters: InboxFilters) => void;
}

/**
 * The controls that narrow the queue.
 *
 * Every option is a word the daemon used: the categories it labelled the queue with, and
 * the verdicts its verifier actually returned for the items on screen. Nothing here offers
 * a category the queue does not contain, because an empty result is not a filter, and
 * nothing here re-orders: hiding is the only thing a presentation control may do to a
 * scientific ranking.
 */
function InboxFilterBar({ items, filters, onChange }: FilterBarProps) {
  const categories = CATEGORY_ORDER.filter((category) =>
    items.some((item) => item.category === category),
  );
  const verdicts = Array.from(new Set(items.map((item) => item.verdict ?? 'unverified')));

  return (
    <div className="rh-web-row rh-web-inbox-filters">
      <Input
        label="Filter by field, work, quoted span or reason"
        hideLabel
        size="sm"
        iconStart="search"
        placeholder="Field, work, quote or reason"
        fieldClassName="rh-web-inbox-filters__search"
        value={filters.text}
        onChange={(event) => onChange({ ...filters, text: event.target.value })}
      />
      <Select
        label="Category"
        hideLabel
        size="sm"
        value={filters.category}
        onChange={(event) => onChange({ ...filters, category: event.target.value })}
      >
        <option value="">Every category</option>
        {categories.map((category) => (
          <option key={category} value={category}>
            {CATEGORY_LABELS[category] ?? category}
          </option>
        ))}
      </Select>
      <Select
        label="Verdict"
        hideLabel
        size="sm"
        value={filters.verdict}
        onChange={(event) => onChange({ ...filters, verdict: event.target.value })}
      >
        <option value="">Every verdict</option>
        {verdicts.map((verdict) => (
          <option key={verdict} value={verdict}>
            {verdict.replace(/_/g, ' ')}
          </option>
        ))}
      </Select>
    </div>
  );
}

type BatchStage = 'idle' | 'previewing' | 'preview' | 'running' | 'done';

interface BatchAcceptProps {
  items: ReviewItem[];
  onAccepted: () => void;
}

/**
 * The Product 24.4 batch, with the ceremony a write of accepted state has to carry.
 *
 * Two presses, and the first one writes nothing: it asks the daemon what it *would* accept,
 * which is the only honest preview, since the conditions are re-checked at the moment of
 * the call. Between them sits the restatement — how many candidates become accepted
 * Evidence, and whose verification that will be recorded as.
 */
function BatchAccept({ items, onAccepted }: BatchAcceptProps) {
  const { client } = useSession();
  const [stage, setStage] = useState<BatchStage>('idle');
  const [scope, setScope] = useState('');
  const [result, setResult] = useState<BatchAcceptResponse | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [refusal, setRefusal] = useState<string | null>(null);

  const works = Array.from(new Set(items.map((item) => item.work)));

  /**
   * The daemon answers with staging ids; a researcher reads fields and works. The names are
   * resolved against the queue at the moment of the answer and kept, because accepting
   * drains the queue those names came from and a report that decayed into hexadecimal the
   * instant it was true would be no report at all.
   */
  function nameEach(answer: BatchAcceptResponse): Record<string, string> {
    const ids = [...answer.accepted, ...Object.keys(answer.skipped)];
    return Object.fromEntries(
      ids.map((candidateId) => {
        const item = items.find((entry) => entry.candidate_id === candidateId);
        return [candidateId, item ? `${item.field} · ${item.work}` : candidateId];
      }),
    );
  }

  async function run(dryRun: boolean): Promise<void> {
    setStage(dryRun ? 'previewing' : 'running');
    setRefusal(null);
    try {
      const answer = await client.acceptBatch({ dryRun, ...(scope ? { work: scope } : {}) });
      setNames(nameEach(answer));
      setResult(answer);
      setStage(dryRun ? 'preview' : 'done');
      if (!dryRun) onAccepted();
    } catch (cause) {
      setRefusal(cause instanceof Error ? cause.message : String(cause));
      setResult(null);
      setStage('idle');
    }
  }

  const label = (candidateId: string): string => names[candidateId] ?? candidateId;

  const accepted = result?.accepted ?? [];
  const skipped = Object.entries(result?.skipped ?? {});

  return (
    <Panel
      title="Batch accept"
      // Nothing left to accept: the panel stays for its report, without offering a run
      // over an empty queue.
      action={
        items.length === 0 ? undefined : (
        <div className="rh-web-row">
          <Select
            label="Batch scope"
            hideLabel
            size="sm"
            value={scope}
            onChange={(event) => {
              setScope(event.target.value);
              setStage('idle');
              setResult(null);
            }}
          >
            <option value="">The whole queue</option>
            {works.map((work) => (
              <option key={work} value={work}>
                {work}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            variant="secondary"
            loading={stage === 'previewing'}
            loadingLabel="Asking the daemon what it would accept"
            onClick={() => void run(true)}
          >
            Accept the routine candidates…
          </Button>
        </div>
        )
      }
    >
      {items.length > 0 ? (
        <p className="rh-text-secondary rh-web-batch__note">
          Only the candidates that meet every one of the daemon’s deterministic conditions,
          and only where this project’s policy allows a batch at all. How sure a model was is
          never one of them.
        </p>
      ) : null}

      {refusal ? <ErrorBox error={refusal} /> : null}

      {result && stage !== 'idle' ? (
        <div className="rh-web-stack rh-web-stack--tight">
          <p>
            {accepted.length === 1
              ? '1 routine candidate meets the batch conditions.'
              : `${accepted.length} routine candidates meet the batch conditions.`}
          </p>
          {accepted.length > 0 ? (
            <ul
              className="rh-web-list rh-web-list--tight"
              aria-label="Candidates that meet the batch conditions"
            >
              {accepted.map((candidateId) => (
                <li key={candidateId}>{label(candidateId)}</li>
              ))}
            </ul>
          ) : null}

          {(stage === 'preview' || stage === 'running') && accepted.length > 0 ? (
            <div className="rh-web-stack rh-web-stack--tight rh-web-batch__confirm">
              <p>
                {accepted.length === 1
                  ? 'It becomes accepted Evidence, verified by you.'
                  : `They become ${accepted.length} accepted Evidence objects, verified by you.`}{' '}
                The rest stay in the queue.
              </p>
              <div className="rh-web-row">
                <Button
                  size="sm"
                  variant="primary"
                  loading={stage === 'running'}
                  loadingLabel="Writing the accepted Evidence"
                  onClick={() => void run(false)}
                >
                  {accepted.length === 1
                    ? 'Accept 1 candidate'
                    : `Accept ${accepted.length} candidates`}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={stage === 'running'}
                  onClick={() => setStage('idle')}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {stage === 'done' ? (
            <p>
              {accepted.length === 1
                ? '1 candidate is now accepted Evidence.'
                : `${accepted.length} candidates are now accepted Evidence.`}
            </p>
          ) : null}

          {skipped.length > 0 ? (
            <>
              <h3 className="rh-text-label">Left in the queue</h3>
              <ul
                className="rh-web-list rh-web-list--tight"
                aria-label="Candidates the batch would leave in the queue"
              >
                {skipped.map(([candidateId, reason]) => (
                  <li key={candidateId}>
                    <span className="rh-web-queue__field">{label(candidateId)}</span>{' '}
                    <span className="rh-text-secondary">— {reason}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

export function ReviewRow({ item }: { item: ReviewItem }) {
  const { href } = useProjectPaths();
  return (
    <li className="rh-web-stack rh-web-stack--tight">
      <p className="rh-web-row">
        <Link to={href(`/review/${item.candidate_id}`)} data-review-row="">
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
