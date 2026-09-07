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
 *
 * Its *control* sits in the toolbar beside the filters, because it acts on the queue rather
 * than on anything in it, and a control that had to be reached by scrolling past every card
 * was a control that arrived after the work it was meant to save. Nothing else moved: the
 * page still opens on the group the daemon ranked first, the restatement only exists once a
 * preview has been asked for, and the report outlives the queue it emptied.
 *
 * Every row carries its own decisions (`QueueDecision`), and the tier decides which. Refusing
 * a proposal and putting one aside write no evidence, and the page a span was read off would
 * settle neither, so they are offered wherever the row is; an acceptance writes authority and
 * Product 26 puts the source beside that, so Accept stays on the row only where the daemon
 * has already filed the candidate as routine — verified, supported, tier 0 or 1, validly
 * anchored — and every other row says where its acceptance is taken instead. The ceremony is
 * the review screen's throughout: the restatement before an acceptance, the daemon's sentence
 * before a rejection or a deferral, and nothing that fakes an undo.
 *
 * A decision that empties a row hands the keyboard on rather than dropping it at the top of
 * the document: the focus lands on the next candidate in the queue's own order, which is the
 * rule decide-and-next already follows on the review screen.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  DescribedTerm,
  FullPageWorkspace,
  Input,
  REVIEW_DECISION_META,
  Select,
  SourceAnchor,
  humaniseResearchTokens,
  researchLabel,
  researchMeaning,
} from '@research-harness/design';
import type { BatchAcceptResponse, ReviewItem } from '../api/dto';
import {
  Empty,
  ErrorBox,
  Loading,
  Panel,
  StatusBadge,
  candidateName,
  fieldLabel,
} from '../components/Feedback';
import { QueueDecision } from '../components/QueueDecision';
import { useRegisterCommands } from '../app/commands';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './review.css';

/**
 * Which key presses which row decision.
 *
 * The same three letters the review screen binds, and for the same reason: a key presses the
 * row's own button rather than calling a capability of its own, so it can never record
 * something the control on screen would not have. A row that offers no Accept has no button
 * for `a` to press, and the key does nothing rather than inventing a second path.
 */
const ROW_DECISION_KEYS = { accept: 'a', defer: 'd', reject: 'r' } as const;

/**
 * What each key does to the row in focus, for the help sheet and the palette.
 *
 * `REVIEW_DECISION_META` owns the labels and the general descriptions; these say the part
 * that is true *here* — which row it lands on, and what the row will ask for first.
 */
const ROW_DECISION_HINTS: { decision: keyof typeof ROW_DECISION_KEYS; hint: string }[] = [
  {
    decision: 'accept',
    hint:
      'Restate what accepting the row in focus writes, where the daemon filed it as ' +
      'routine. A deeper review is accepted beside its source.',
  },
  {
    decision: 'defer',
    hint: 'Put the row in focus aside, with the note it stays in the queue with.',
  },
  {
    decision: 'reject',
    hint: 'Refuse the row in focus, with the reason it is recorded with.',
  },
];

/** The queue order itself; an item's category is the server's own word for why it is here. */
export const CATEGORY_ORDER = ['conflict', 'high_risk', 'stale', 'ambiguous', 'routine'] as const;

/** The product's own name for one category. The vocabulary owns the words. */
export const categoryLabel = (category: string): string =>
  researchLabel('reviewCategory', category);

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
  // Both the word on screen and the daemon's own identifier match, so typing what the row
  // says finds it and so does typing what a `--field` flag would take.
  const haystack = [
    item.field,
    fieldLabel(item.field),
    item.work,
    item.exact_text,
    ...item.reasons,
    ...item.reasons.map(humaniseResearchTokens),
  ]
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
  const listRef = useRef<HTMLDivElement | null>(null);

  const items = useMemo(() => state.data?.items ?? [], [state.data]);
  const reread = () => {
    state.reload();
    refresh();
  };
  const batch = useBatchAccept(items, reread);
  const groups = useMemo(() => inboxGroups(items, filters), [items, filters]);
  const showing = groups.reduce((total, [, group]) => total + group.length, 0);
  const filtered = filters.text !== '' || filters.category !== '' || filters.verdict !== '';

  /** The rows as they are drawn: the daemon's order, minus whatever the filters hide. */
  const onScreen = useMemo(
    () => groups.flatMap(([, group]) => group.map((item) => item.candidate_id)),
    [groups],
  );

  /**
   * Where the keyboard goes when the row it was on is decided.
   *
   * A decision re-reads the queue, and a candidate that left it takes its controls — and
   * whatever had the focus — out of the document with it. Dropping the researcher at the top
   * of the page after every decision is the cost of getting through a queue by keyboard, so
   * the focus is handed on the way decide-and-next hands it on the review screen: to the next
   * candidate in the queue's own order, and to the one before it when there is no next. The
   * target is chosen before the re-read, from the order that was on screen at the time.
   */
  const landing = useRef<string | null>(null);
  const decided = (candidateId: string): void => {
    const index = onScreen.indexOf(candidateId);
    landing.current = onScreen[index + 1] ?? onScreen[index - 1] ?? null;
    reread();
  };

  useEffect(() => {
    const target = landing.current;
    if (target === null) return;
    landing.current = null;
    const list = listRef.current;
    if (list === null) return;
    // A deferred candidate stays in the queue and a rejected one does not, so the row that
    // was chosen may itself have moved; the first row is the honest fallback, and an emptied
    // queue has none, which is what the empty state is for.
    const next =
      list.querySelector<HTMLAnchorElement>(
        `a[data-review-row="${CSS.escape(target)}"]`,
      ) ?? list.querySelector<HTMLAnchorElement>('a[data-review-row]');
    next?.focus();
  }, [items]);

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

  /**
   * Press the focused row's own decision button.
   *
   * "The row in focus" is wherever the caret is inside the list: the row's link after `j`,
   * or a control inside the decision it opened. Nothing is pressed when the focus is outside
   * the queue, and nothing is pressed on a row that does not offer that decision.
   */
  const pressRowDecision = (decision: keyof typeof ROW_DECISION_KEYS): void => {
    const focused = document.activeElement;
    if (!(focused instanceof HTMLElement)) return;
    const row = focused.closest('li');
    if (row === null || listRef.current?.contains(row) !== true) return;
    const button = row.querySelector<HTMLButtonElement>(`button[data-decision="${decision}"]`);
    if (button && !button.disabled) button.click();
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
      ...ROW_DECISION_HINTS.map((entry) => ({
        id: `inbox:${entry.decision}`,
        label: REVIEW_DECISION_META[entry.decision].label,
        group: 'The row in focus',
        shortcut: ROW_DECISION_KEYS[entry.decision],
        hint: entry.hint,
        run: () => pressRowDecision(entry.decision),
      })),
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
          <>
            <InboxFilterBar items={items} filters={filters} onChange={setFilters} />
            {/* The one control that acts on the queue rather than on a candidate in it,
                beside the two that narrow it. It is offered only to a window that may
                accept, and the policy gate is still the daemon's. */}
            {canMutate ? <BatchAcceptControls batch={batch} items={items} /> : null}
          </>
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

          {/* What the batch would write, and afterwards what it wrote. It exists only once
              a preview has been asked for, so the page still opens on the group the daemon
              put first — and it appears where the control that opened it is, because a
              restatement nobody can see is not a restatement. It outlives the queue on
              purpose: a batch that accepted everything empties the list it reported on, and
              the receipt for a write of accepted state must not disappear with it. */}
          {canMutate && (batch.result !== null || batch.refusal !== null) ? (
            <BatchAcceptReport batch={batch} />
          ) : null}

          {items.length === 0 ? (
            <Empty
              description={
                'This queue holds the proposals a run staged and nobody has decided yet. ' +
                'Candidates come from interrogating a work, and none of them is accepted ' +
                'state until it is decided here.'
              }
              action={<Link to={href('/corpus')}>Open the corpus to interrogate a work</Link>}
            >
              Nothing is waiting for review
            </Empty>
          ) : showing === 0 ? (
            <Empty
              description="Nothing has left the queue. The filters only hide, and the daemon’s order is unchanged underneath them."
              action={
                <Button size="sm" variant="secondary" onClick={() => setFilters(NO_FILTERS)}>
                  Clear the filters
                </Button>
              }
            >
              No candidate matches these filters
            </Empty>
          ) : (
            groups.map(([category, group]) => (
              <Panel
                key={category}
                title={`${categoryLabel(category)} (${group.length})`}
              >
                <ul className="rh-web-list rh-web-list--rules">
                  {group.map((item) => (
                    <ReviewRow key={item.candidate_id} item={item} onDecided={decided} />
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
            {categoryLabel(category)}
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
            {researchLabel('verdict', verdict)}
          </option>
        ))}
      </Select>
    </div>
  );
}

type BatchStage = 'idle' | 'previewing' | 'preview' | 'running' | 'done';

/**
 * The Product 24.4 batch, with the ceremony a write of accepted state has to carry.
 *
 * Two presses, and the first one writes nothing: it asks the daemon what it *would* accept,
 * which is the only honest preview, since the conditions are re-checked at the moment of
 * the call. Between them sits the restatement — how many candidates become accepted
 * Evidence, and whose verification that will be recorded as.
 *
 * The state lives in the page rather than in either half of the presentation, because the
 * control sits in the toolbar and the restatement it opens sits over the queue, and they
 * are one act: pressing the button in one place has to be answered in the other.
 */
interface Batch {
  stage: BatchStage;
  scope: string;
  works: string[];
  setScope: (work: string) => void;
  result: BatchAcceptResponse | null;
  refusal: string | null;
  /** What a candidate the daemon named is called, resolved when the answer arrived. */
  label: (candidateId: string) => string;
  run: (dryRun: boolean) => void;
  cancel: () => void;
}

function useBatchAccept(items: ReviewItem[], onAccepted: () => void): Batch {
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
        return [candidateId, item ? candidateName(item.field, item.work) : candidateId];
      }),
    );
  }

  async function call(dryRun: boolean): Promise<void> {
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

  return {
    stage,
    scope,
    works,
    setScope: (work: string) => {
      setScope(work);
      setStage('idle');
      setResult(null);
    },
    result,
    refusal,
    label: (candidateId: string) => names[candidateId] ?? candidateId,
    run: (dryRun: boolean) => void call(dryRun),
    cancel: () => setStage('idle'),
  };
}

/** The batch's scope and its first press, in the toolbar beside the filters. */
function BatchAcceptControls({ batch, items }: { batch: Batch; items: ReviewItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rh-web-row rh-web-inbox-batch">
      <Select
        label="Batch scope"
        hideLabel
        size="sm"
        value={batch.scope}
        onChange={(event) => batch.setScope(event.target.value)}
      >
        <option value="">The whole queue</option>
        {batch.works.map((work) => (
          <option key={work} value={work}>
            {work}
          </option>
        ))}
      </Select>
      <Button
        size="sm"
        variant="secondary"
        loading={batch.stage === 'previewing'}
        loadingLabel="Asking the daemon what it would accept"
        onClick={() => batch.run(true)}
      >
        Accept the routine candidates…
      </Button>
    </div>
  );
}

/** What the batch would write, what it wrote, and what it left behind. */
function BatchAcceptReport({ batch }: { batch: Batch }) {
  const { result, stage, refusal, label } = batch;
  const accepted = result?.accepted ?? [];
  const skipped = Object.entries(result?.skipped ?? {});

  return (
    <Panel title="Batch accept">
      <p className="rh-text-secondary rh-web-batch__note">
        Only the candidates that meet every one of the daemon’s deterministic conditions, and
        only where this project’s policy allows a batch at all. How sure a model was is never
        one of them.
      </p>

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
                  onClick={() => batch.run(false)}
                >
                  {accepted.length === 1
                    ? 'Accept 1 candidate'
                    : `Accept ${accepted.length} candidates`}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={stage === 'running'}
                  onClick={batch.cancel}
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
              <h3 className="rh-text-h4">Left in the queue</h3>
              <ul
                className="rh-web-list rh-web-list--tight"
                aria-label="Candidates the batch would leave in the queue"
              >
                {skipped.map(([candidateId, reason]) => (
                  <li key={candidateId}>
                    <span className="rh-web-queue__field">{label(candidateId)}</span>{' '}
                    <span className="rh-text-secondary">— {humaniseResearchTokens(reason)}</span>
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

export function ReviewRow({
  item,
  onDecided = () => {},
}: {
  item: ReviewItem;
  /** Re-read the queue after a decision on this row, and say which row it was. */
  onDecided?: (candidateId: string) => void;
}) {
  const { href } = useProjectPaths();
  return (
    <li className="rh-web-stack rh-web-stack--tight">
      <p className="rh-web-row">
        <Link to={href(`/review/${item.candidate_id}`)} data-review-row={item.candidate_id}>
          <span className="rh-web-queue__field">{fieldLabel(item.field)}</span>
          <span className="rh-text-secondary"> · {item.work}</span>
        </Link>
        {/* Why it is waiting and what the verifier said are the two states this row is
            about, so both carry the sentence that says what they mean. The tier is a
            property of the question rather than of this answer, so it stays plain text —
            but "Tier 2 — deep review" is no more self-explaining than the two badges are,
            so it carries its sentence in the same shape and by the same gesture. */}
        <StatusBadge status={item.category} vocabulary="reviewCategory" describe />
        <StatusBadge status={item.verdict ?? 'unverified'} vocabulary="verdict" describe />
        <TierName tier={item.tier} />
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
      {/* The queue's own sentences, with the identifiers inside them read out in the same
          words the badges above use. The sentence stays the daemon's. */}
      <p className="rh-text-secondary">{humaniseResearchTokens(item.reasons.join('; '))}</p>
      {/* Every candidate can be refused or put aside where it is read; only one the daemon
          filed as routine can be accepted there, and the rest say where that happens. */}
      <QueueDecision item={item} onDecided={onDecided} />
    </li>
  );
}

/**
 * How much reading this question needs, in the product's words and with its meaning.
 *
 * Secondary ink and no badge: the tier belongs to the question the candidate answers, and
 * a third badge on the row would put it beside the two states this row actually reports.
 * The meaning is reachable all the same, because `Tier 2 — deep review` is exactly the
 * kind of phrase that means nothing on a first visit.
 */
function TierName({ tier }: { tier: number }) {
  const value = String(tier);
  const meaning = researchMeaning('reviewTier', value);
  const name = researchLabel('reviewTier', value);
  if (meaning === undefined) return <span className="rh-text-secondary">{name}</span>;
  return (
    <DescribedTerm className="rh-text-secondary" description={meaning}>
      {name}
    </DescribedTerm>
  );
}
