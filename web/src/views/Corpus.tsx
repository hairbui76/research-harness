/**
 * Corpus: works, their revisions, their immutable files, and whether each file is parsed.
 *
 * The page opens with what needs a researcher among these sources — a source screened and
 * never included, one with no file behind it, one whose files have no stored parse, one
 * nothing has been accepted from — and only then says how many works the project holds.
 * Which of those a Work belongs in is decided by the daemon and arrives with the list
 * (`work.list`'s `attention`); a cockpit that re-derived it from `screening` and `parsed`
 * would be a second, disagreeing copy of Product 14 and 16 living in React (P10).
 *
 * ## The works answer questions, they do not display records
 *
 * A corpus is not read record by record. It is asked things — which of these thousand works
 * has nothing accepted from it, which cannot be read from yet, which does no claim rest on,
 * which came in while I was away, which one was that fact in — and the page is built around
 * those five and nothing else. So each work is a row read across shared columns that answer
 * them (what it is; whether it has readable text; what has been accepted from it; how many
 * claims cite it; when it came in), and the questions themselves are the controls that
 * narrow the list.
 *
 * The narrowing is a request, not a `filter()`. "Nothing accepted from it" and "cannot be
 * read from yet" are judgements over canonical state, and the same P10 that keeps the lead
 * on the daemon keeps these there: `work.list` takes a `question`, answers with the works
 * that answer it, and composes the sentence the narrowed list is read under. What stays in
 * the browser is the find, because "which one was that fact in" is a question about the
 * text on screen rather than about the science.
 *
 * The row used to be a card of ID / AUTHORS / YEAR / VENUE / ACCEPTED EVIDENCE — the shape
 * a CRM gives a contact, and the shape the second design critique named. Every one of those
 * fields is still on the page; what changed is that they are columns a thousand rows share
 * rather than a stack of labels each row repeats, so a corpus can be scanned instead of
 * read one card at a time.
 *
 * The corpus list is windowed. `work.list` answers the whole corpus in one read — the
 * daemon imposes no page size, and PRODUCT §5 P10 forbids the cockpit inventing one — so a
 * project of a thousand works used to mount a thousand cards, each with its own nested file
 * table, before the first one could be read. `VirtualList` keeps only what is near the
 * viewport in the DOM. The files of one work stay one press away, inside the row, so
 * reaching them never unmounts the list a researcher is standing in.
 *
 * Windowing costs the browser's own find-in-page, and pretending otherwise would be the
 * dishonest part: Ctrl/Cmd+F can only search the works the DOM currently holds. So the page
 * carries a find of its own, over the whole list rather than over the window, and says how
 * many of the corpus it is showing. The browser's shortcut is deliberately not intercepted
 * — taking a key away from the researcher to hide a trade-off is worse than the trade-off.
 *
 * A file with no stored parse cannot have an anchor replayed against it, which is why
 * "readable text" is a column rather than something buried in a nested table: it is the
 * difference between a source you can open at a span and one you cannot (PRODUCT §16, §42
 * D).
 *
 * Not here, and deliberately: the `work.update_metadata` proposals a discovery run turns up
 * (`discovery/search_runs.py::MetadataEnrichment`). Nothing in the capability surface reads
 * a recorded `SearchRun` back — `state.index` does not list runs and there is no
 * `search_run.list` — so the cockpit cannot show a proposal it has no way to fetch. Showing
 * one would mean recomputing the funnel client-side, which is exactly what P10 forbids.
 * A read capability over recorded runs and their enrichments would close it.
 *
 * All three screens mount their frame before the read resolves: the heading, the toolbar
 * and the page's shape survive loading, a refusal, and an object that is not there.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Button,
  EvidenceCard,
  FullPageWorkspace,
  Icon,
  Input,
  Select,
  VirtualList,
  formatFileSize,
  humaniseResearchTokens,
  useId,
} from '@research-harness/design';
import type { EvidenceModel } from '@research-harness/design';
import type {
  CorpusAttentionGroup,
  CorpusAttentionItem,
  CorpusOrder,
  CorpusQuestion,
  EvidenceSummary,
  WorkList,
  WorkSummary,
} from '../api/dto';
import type { HarnessClient } from '../api/client';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
} from '../components/Feedback';
import { ObjectRef } from '../components/ObjectRef';
import { useDaemonOutage } from '../app/daemonStatus';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './corpus.css';

/**
 * About how tall one work's row is before it has been measured, in CSS pixels.
 *
 * Two lines of work identity plus a line of controls, which is what the row is before a
 * researcher opens its files. The measurement is the real answer; this is only what the
 * window places rows by until it has one.
 */
const WORK_ROW_HEIGHT = 68;

/**
 * The columns a corpus is read across.
 *
 * `head` is what the strip above the list says; `label` is what one cell says on its own,
 * to a screen reader and — once the pane is too narrow for columns — to everyone. They
 * differ because a column header is read once with five others beside it and a cell label
 * is read alone: "Accepted" under a heading row is unambiguous, "Accepted 3" in a stack of
 * facts is not.
 *
 * The set is the questions of the page's opening comment, in the order a researcher asks
 * them: what is this, where does it stand, can I read it, what has it given, does anything
 * rest on it, when did it arrive.
 */
interface CorpusColumn {
  key: string;
  head: string;
  label: string;
  /** How the corpus is read when this column is the one it is read by; absent when it is
      not something a thousand works can be put in order of. */
  order?: {
    /** The daemon's own word for this order, sent as `work.list`'s `order`. */
    kind: string;
    /** Which end of the column a researcher wants first: the large counts, the recent
        arrivals, the top of the alphabet. */
    descendingFirst: boolean;
    /** The sentence the count is read with, each way round. */
    ascending: string;
    descending: string;
  };
}

const COLUMNS: readonly CorpusColumn[] = [
  {
    key: 'work',
    head: 'Work',
    label: 'Work',
    order: {
      kind: 'title',
      descendingFirst: false,
      ascending: 'In title order, A to Z.',
      descending: 'In title order, Z to A.',
    },
  },
  { key: 'screening', head: 'Screening', label: 'Screening state' },
  { key: 'readable', head: 'Readable', label: 'Readable text' },
  {
    key: 'evidence',
    head: 'Accepted',
    label: 'Accepted evidence',
    order: {
      kind: 'evidence',
      descendingFirst: true,
      ascending: 'Least accepted evidence first.',
      descending: 'Most accepted evidence first.',
    },
  },
  {
    key: 'claims',
    head: 'Cited by',
    label: 'Claims citing it',
    order: {
      kind: 'claims',
      descendingFirst: true,
      ascending: 'Least cited first.',
      descending: 'Most cited first.',
    },
  },
  {
    key: 'added',
    head: 'Came in',
    label: 'Came into the corpus',
    order: {
      kind: 'added',
      descendingFirst: true,
      ascending: 'Oldest first.',
      descending: 'Newest first.',
    },
  },
];

/**
 * Where the order a corpus is read in is remembered, per project.
 *
 * The same shape and the same reasoning as the conversation's last session and the review
 * screen's auto-advance: a convenience the browser keeps, never research state, so every
 * access is guarded and a browser that refuses site data simply reads the corpus in the
 * daemon's own order. Per project, because two projects are two corpora and the column that
 * matters in one says nothing about the other.
 */
const CORPUS_ORDER = 'research-harness.corpus.order';

export function corpusOrderKey(project: string | null): string {
  return project ? `${CORPUS_ORDER}.${project}` : CORPUS_ORDER;
}

function readCorpusOrder(project: string | null): CorpusOrder | null {
  try {
    const stored = window.localStorage.getItem(corpusOrderKey(project));
    if (stored === null) return null;
    const order = JSON.parse(stored) as Partial<CorpusOrder>;
    // A stored order this build no longer offers is not an order: an older column name
    // would otherwise be sent to the daemon, which would refuse the whole read.
    if (!COLUMNS.some((column) => column.order?.kind === order.field)) return null;
    return { field: String(order.field), descending: order.descending === true };
  } catch {
    return null;
  }
}

function writeCorpusOrder(project: string | null, order: CorpusOrder | null): void {
  try {
    if (order) window.localStorage.setItem(corpusOrderKey(project), JSON.stringify(order));
    else window.localStorage.removeItem(corpusOrderKey(project));
  } catch {
    /* a browser with storage disabled reads the corpus in the daemon's order every time */
  }
}

/**
 * What the next press on one column head asks for.
 *
 * Three states rather than two: the useful end of the column first, then the other end,
 * then the corpus's own order again. A two-state toggle would leave a researcher who
 * sorted a thousand works by accident with no way back to the order the daemon sent
 * except a reload, and the corpus's own order is a real answer rather than a null state.
 */
export function nextCorpusOrder(
  current: CorpusOrder | null,
  column: CorpusColumn,
): CorpusOrder | null {
  const spec = column.order;
  if (spec === undefined) return current;
  if (current === null || current.field !== spec.kind) {
    return { field: spec.kind, descending: spec.descendingFirst };
  }
  if (current.descending === spec.descendingFirst) {
    return { field: spec.kind, descending: !spec.descendingFirst };
  }
  return null;
}

/** How the rows on screen are read, in the words of the column they are read by. */
export function orderSentence(order: string, descending: boolean): string {
  const column = COLUMNS.find((entry) => entry.order?.kind === order);
  if (column?.order === undefined) return '';
  return descending ? column.order.descending : column.order.ascending;
}

/** `1 file` / `2 files` — a count is only ever read inside the thing it counts. */
function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * Whether one work answers what was typed into the page's find field.
 *
 * Every term has to match somewhere, and a term may match anywhere: an id, the title, an
 * author, the venue or the year. It only ever *hides* — the corpus is the daemon's list in
 * the daemon's order, and a find that reordered it would be the cockpit deciding what a
 * researcher should read first (PRODUCT §5 P10).
 */
export function matchesWork(work: WorkSummary, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [work.id, work.title, work.venue ?? '', String(work.year ?? ''), ...work.authors]
    .join(' ')
    .toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

export function CorpusPage() {
  const { client } = useSession();
  const { href, projectId } = useProjectPaths();
  // Which question the corpus is being asked, or "" for the whole of it. It goes to the
  // daemon rather than into a `filter()`: which works have nothing accepted from them is a
  // judgement about scientific state, and P10 leaves those where they are made.
  const [question, setQuestion] = useState('');
  // Which column the corpus is read by, or null for the order the daemon sends it in. It
  // goes to the daemon for a plainer reason than the question does: `work.list` answers the
  // whole corpus in one read and this list is windowed, so a comparator here would order
  // the rows near the viewport and call the result the corpus. Remembered per project,
  // because a researcher who reads their corpus by what has been accepted from it reads it
  // that way tomorrow too.
  const [order, setOrder] = useState<CorpusOrder | null>(() => readCorpusOrder(projectId));
  // `work.list`: the corpus, the daemon's own reading of which of these sources cannot be
  // read from yet, and what this corpus can be asked. This view needs nothing else.
  const state = useAsync(
    () => client.works(null, question || null, order),
    [client, question, order],
  );
  const [query, setQuery] = useState('');
  // The works whose files are open, by id, held by the page rather than by the row: a row
  // scrolled out of the window is unmounted, and a researcher who scrolls back should find
  // what they opened still open.
  const [opened, setOpened] = useState<readonly string[]>([]);
  const outage = useDaemonOutage();
  // The works are a region of their own, named by their own heading, so a screen-reader
  // user can jump past the lead straight into the list — and so the live count below is
  // reachable as part of something rather than as one more announcement on the page.
  const worksHeading = useId(undefined, 'rh-web-corpus-works');

  // The last corpus the daemon actually sent.
  //
  // Silence is not an answer. A refusal is the daemon speaking and its answer replaces what
  // came before, but a daemon that has gone quiet has said nothing about the corpus — the
  // list on screen is still true of the last moment it spoke. So the list is kept and
  // labelled for what it is, rather than thrown away to show an empty page; `state.data`
  // going null on a failed re-read does not take it with it. The whole answer is kept,
  // groups and all: what needed a researcher a minute ago still does.
  const kept = useRef<WorkList | null>(null);
  if (state.data !== null) kept.current = state.data;
  const answer = state.data ?? kept.current;
  const works = answer?.works ?? [];
  const attention = answer?.attention ?? [];
  const questions = answer?.questions ?? [];
  // How many works the corpus holds, whatever this answer was narrowed to. An older daemon
  // answers without it, and then the answer is the whole corpus by definition.
  const total = answer?.total ?? works.length;
  // The question these rows actually answer, taken from the answer that produced them
  // rather than from the request: while a new one is in flight the sentence beside the list
  // has to describe what is on the screen.
  const asked = questions.find((item) => item.kind === (answer?.question ?? '')) ?? null;
  // How the rows on screen are read, taken from the answer that produced them for the same
  // reason the question is: while the next read is in flight the sentence has to describe
  // what a researcher is looking at.
  const reading = orderSentence(answer?.order ?? '', answer?.descending ?? false);
  const stale = outage !== null && works.length > 0;

  // The daemon came back: ask again, so the page catches up without a reload.
  const wasOffline = useRef(false);
  useEffect(() => {
    if (outage !== null) {
      wasOffline.current = true;
      return;
    }
    if (!wasOffline.current) return;
    wasOffline.current = false;
    state.reload();
  }, [outage, state]);

  const shown = useMemo(
    () => works.filter((work) => matchesWork(work, query)),
    [query, works],
  );
  const failed = state.error !== null && !stale;
  // The skeleton is for a page that has nothing yet. Once a corpus is on screen, asking it
  // another question keeps it there and marks the region busy: replacing a thousand rows
  // with a placeholder for the seconds a re-read takes loses the reader's place to say
  // nothing they did not already know.
  const arriving = state.loading && answer === null;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Corpus"
      description="The sources this project reads from, and the files kept for each."
      toolbar={
        works.length > 0 || question !== '' ? (
          <Input
            label="Find a work by title, author, venue, year or id"
            hideLabel
            size="sm"
            type="search"
            iconStart="search"
            placeholder="Title, author, venue, year or id"
            fieldClassName="rh-web-corpus__find"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        ) : (
          <></>
        )
      }
    >
      {arriving ? (
        <Loading what="the corpus" shape="cards" />
      ) : failed ? (
        <ErrorBox error={state.error as string} retry={state.reload} />
      ) : total === 0 ? (
        <Empty
          description="The corpus is the set of sources this project reads from: each work, the files kept for it, and whether a file has a stored parse. A file enters it by being attached to a conversation and saved to the corpus."
          action={<Link to={href('/')}>Open the conversation to attach a source</Link>}
        >
          No works in the corpus yet
        </Empty>
      ) : (
        <div className="rh-web-corpus">
          <Panel title="Sources that need a researcher">
            {attention.length > 0 ? (
              <ul className="rh-web-list rh-web-corpus__attention">
                {attention.map((group) => (
                  <NeedsAResearcher key={group.kind} group={group} href={href} />
                ))}
              </ul>
            ) : (
              <Empty
                flat
                description="A source waits for a researcher while a screening decision has been left half-taken, while no file has been attached to it, while none of its files has a stored parse — nothing can be anchored in a file the project cannot read — or while nothing has been accepted from it yet. None of that is true of this corpus."
                action={
                  <Link to={href('/')}>Open the conversation to attach another source</Link>
                }
              >
                Nothing among these sources needs a researcher
              </Empty>
            )}
          </Panel>

          <section className="rh-web-corpus__works" aria-labelledby={worksHeading}>
            <h2 className="rh-text-h3" id={worksHeading}>
              Every work in the corpus
            </h2>
            <Questions
              questions={questions}
              chosen={question}
              total={total}
              onChoose={setQuestion}
            />
            <p className="rh-text-secondary" role="status">
              {stale
                ? `The last corpus the daemon sent: ${works.length} works. It has not answered since.`
                : asked
                  ? query
                    ? `${asked.summary} Showing ${shown.length} of them.`
                    : asked.summary
                  : query
                    ? `Showing ${shown.length} of ${total} works.`
                    : `${total} works.`}
              {/* And how they are read, when they are read by something other than the
                  corpus's own order. It belongs in this sentence rather than beside the
                  column, because it is a fact about every row on screen. */}
              {reading === '' ? null : ` ${reading}`}
            </p>
            {works.length === 0 ? (
              <Empty
                description="Every work the daemon counted under this question is still in the corpus; this list is only the ones it named. The corpus itself is unchanged underneath it."
                action={
                  <Button size="sm" variant="secondary" onClick={() => setQuestion('')}>
                    Show every work
                  </Button>
                }
              >
                No work answers this question
              </Empty>
            ) : shown.length === 0 ? (
              <Empty
                description="The find only hides. Every work the daemon listed is still in the corpus underneath it."
                action={
                  <Button size="sm" variant="secondary" onClick={() => setQuery('')}>
                    Clear the find
                  </Button>
                }
              >
                No work matches this find
              </Empty>
            ) : (
              <>
                {/* The column names, once, above the window — and, for the four columns a
                    thousand works can be put in order of, the control that asks for that
                    order.

                    It used to be hidden from a screen reader, because every cell carries
                    its own name and reading both says each column twice. It cannot be now:
                    an `aria-hidden` strip with four buttons in it is a control nobody using
                    a screen reader can reach, and `aria-sort` — which is the only way the
                    order reaches one at all — is an attribute of a column header. So the
                    strip says what it is: a row of column headers, named for what it does,
                    holding the orders this corpus can be read in. The works stay a list,
                    because only a window of them exists at any moment and each cell tells
                    a reader which column it belongs to. */}
                <div
                  className="rh-web-corpus__head-table"
                  role="table"
                  aria-label="The corpus’s columns, and the order it is read in"
                >
                  <div className="rh-web-corpus__head" role="row">
                    {COLUMNS.map((column) => (
                      <ColumnHead
                        key={column.key}
                        column={column}
                        order={order}
                        onChoose={() => {
                          const next = nextCorpusOrder(order, column);
                          setOrder(next);
                          writeCorpusOrder(projectId, next);
                        }}
                      />
                    ))}
                  </div>
                </div>
                {/* And the same orders, as the one control that is honest below the
                    stacking breakpoint. Both are always in the DOM and the container query
                    shows exactly one with `display: none`, which takes the other out of the
                    accessibility tree as well — so a screen reader is never offered the
                    corpus's order twice. */}
                <OrderSelect
                  order={order}
                  onChoose={(next) => {
                    setOrder(next);
                    writeCorpusOrder(projectId, next);
                  }}
                />
                <VirtualList
                  className="rh-web-corpus__list"
                  label="Works in the corpus"
                  items={shown}
                  itemKey={(work) => work.id}
                  estimatedItemHeight={WORK_ROW_HEIGHT}
                  renderItem={(work) => (
                    <WorkRow
                      work={work}
                      client={client}
                      href={href}
                      open={opened.includes(work.id)}
                      onToggle={() =>
                        setOpened((current) =>
                          current.includes(work.id)
                            ? current.filter((id) => id !== work.id)
                            : [...current, work.id],
                        )
                      }
                    />
                  )}
                />
              </>
            )}
          </section>
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * One column name, and — where the column is one the corpus can be put in order of — the
 * control that asks the daemon for that order.
 *
 * The arrow marks the column the rows are read by and which way, and it is decorative:
 * `aria-sort` on the header is what says the same thing to a screen reader, and the
 * sentence beside the count says it to everyone. A column that orders nothing is the word
 * alone, with no `aria-sort` at all — "none" would promise a control that is not there.
 */
function ColumnHead({
  column,
  order,
  onChoose,
}: {
  column: CorpusColumn;
  order: CorpusOrder | null;
  onChoose: () => void;
}) {
  if (column.order === undefined) {
    return (
      <span className="rh-web-corpus__column" role="columnheader">
        {column.head}
      </span>
    );
  }
  const chosen = order !== null && order.field === column.order.kind;
  return (
    <span
      className="rh-web-corpus__column"
      role="columnheader"
      aria-sort={chosen ? (order.descending ? 'descending' : 'ascending') : 'none'}
    >
      <button type="button" className="rh-web-corpus__sort" onClick={onChoose}>
        {column.head}
        {chosen ? <Icon name={order.descending ? 'arrow-down' : 'arrow-up'} size={14} /> : null}
      </button>
    </span>
  );
}

/**
 * The orders this corpus can be read in, as one control.
 *
 * Below the stacking breakpoint there are no columns left: the row is a work over labelled
 * pairs, and a strip reading "Work  Accepted ↓  Cited by  Came in" over it is a table head
 * with no table under it — the shape a reader spends a moment decoding before finding that
 * the words are controls. The orders are the half of that strip still worth having there,
 * so they are asked for the way a narrow pane asks for one choice out of eight.
 *
 * It is the same state as the column heads, sent to the same `work.list` and remembered in
 * the same place; nothing here is a second way to sort. Each option is the sentence the
 * count already reads with, so the control and the page say the order in one set of words,
 * and the corpus's own order leads because it is a real answer rather than a null one.
 */
function OrderSelect({
  order,
  onChoose,
}: {
  order: CorpusOrder | null;
  onChoose: (order: CorpusOrder | null) => void;
}) {
  const options = COLUMNS.flatMap((column) =>
    column.order === undefined
      ? []
      : [
          { field: column.order.kind, descending: column.order.descendingFirst },
          { field: column.order.kind, descending: !column.order.descendingFirst },
        ],
  );
  const value = order === null ? '' : `${order.field}:${order.descending ? 'desc' : 'asc'}`;
  return (
    <Select
      label="Order by"
      size="sm"
      fieldClassName="rh-web-corpus__order"
      value={value}
      onChange={(event) => {
        const picked = event.target.value;
        if (picked === '') return onChoose(null);
        const [field = '', direction] = picked.split(':');
        onChoose({ field, descending: direction === 'desc' });
      }}
    >
      <option value="">The corpus’s own order</option>
      {options.map((option) => (
        <option
          key={`${option.field}:${option.descending ? 'desc' : 'asc'}`}
          value={`${option.field}:${option.descending ? 'desc' : 'asc'}`}
        >
          {/* The sentence without its full stop: the count reads it as a sentence, an
              option is read as a name. */}
          {orderSentence(option.field, option.descending).replace(/\.$/, '')}
        </option>
      ))}
    </Select>
  );
}

/**
 * What this corpus can be asked, as the controls that ask it.
 *
 * Every one of them is the daemon's: the question, the words on it, and how many works
 * answer it. The cockpit contributes one control the daemon has no opinion about — the way
 * back to the whole corpus — and the press that sends the next `work.list`.
 *
 * They are toggles rather than a select because there are rarely more than three and a
 * researcher should be able to see what a corpus can be asked without opening anything;
 * a corpus in good order offers none of them, and the row disappears.
 */
function Questions({
  questions,
  chosen,
  total,
  onChoose,
}: {
  questions: CorpusQuestion[];
  chosen: string;
  total: number;
  onChoose: (kind: string) => void;
}) {
  if (questions.length === 0) return null;
  return (
    <div
      className="rh-web-corpus__questions"
      role="group"
      aria-label="Ask the corpus a question"
    >
      <Button
        size="sm"
        variant="secondary"
        aria-pressed={chosen === ''}
        onClick={() => onChoose('')}
      >
        {`Every work (${total})`}
      </Button>
      {questions.map((question) => (
        <Button
          key={question.kind}
          size="sm"
          variant="secondary"
          aria-pressed={chosen === question.kind}
          onClick={() => onChoose(chosen === question.kind ? '' : question.kind)}
        >
          {`${question.label} (${question.count})`}
        </Button>
      ))}
    </div>
  );
}

/**
 * One reason a source is not yet something this project can read from.
 *
 * The line is the daemon's whole sentence, count and all, because deciding which works
 * belong in this group and deciding how to say so are one judgement (P10). Under it are
 * the first few of them, indented, each a link to the work itself — and, where the daemon
 * had something to add about that one work rather than about all of them, what it added.
 *
 * `more` is what the cap left out, in the daemon's words. It exists because the group is a
 * lead rather than a second list: the works it counts are all in the list underneath it.
 */
function NeedsAResearcher({
  group,
  href,
}: {
  group: CorpusAttentionGroup;
  href: (path: string) => string;
}) {
  return (
    <li>
      <p className="rh-web-corpus__group">{humaniseResearchTokens(group.label)}</p>
      {group.items.length > 0 ? (
        <ul className="rh-web-list rh-web-list--tight rh-web-corpus__group-items">
          {group.items.map((item) => (
            <li key={item.id}>
              <WorkLink item={item} href={href} />
              {item.detail ? (
                <span className="rh-text-secondary"> — {humaniseResearchTokens(item.detail)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {group.more ? <p className="rh-web-corpus__more">{group.more}</p> : null}
    </li>
  );
}

/**
 * One work in a lead group, pointed at itself where the daemon gave it a page.
 *
 * A work with no route of its own is not linked back to the corpus: the reader is already
 * on the corpus, and a link to the page under their feet is not a next step.
 */
function WorkLink({
  item,
  href,
}: {
  item: CorpusAttentionItem;
  href: (path: string) => string;
}) {
  if (!item.route) return <>{item.label}</>;
  return <Link to={href(item.route)}>{item.label}</Link>;
}

/** What a work is, in one line under its title: who wrote it, when, and where. */
function byline(work: WorkSummary): string {
  const parts = [
    work.authors.join(', '),
    work.year === null || work.year === undefined ? '' : String(work.year),
    work.venue ?? '',
  ].filter((part) => part !== '');
  // An empty line would read as "no authors", which is a claim about the paper. This is a
  // claim about the record, which is the true one.
  return parts.length === 0 ? 'No authors, year or venue recorded' : parts.join(' · ');
}

/** One cell's own name, for a screen reader and for a pane too narrow to hold columns. */
function CellLabel({ children }: { children: string }) {
  return <span className="rh-web-corpus__label">{children}</span>;
}

/**
 * One work in the corpus list, read across the columns the page is asked about.
 *
 * The title opens the work; the id beside it is the reference a researcher works with and
 * opens the same page. The files are one press away and open *inside* the row, because the
 * list is windowed: sending a reader to another screen to see whether a PDF was parsed
 * would unmount the thousand works they were reading and lose their place in them.
 */
function WorkRow({
  work,
  client,
  href,
  open,
  onToggle,
}: {
  work: WorkSummary;
  client: HarnessClient;
  href: (path: string) => string;
  open: boolean;
  onToggle: () => void;
}) {
  const files = useId(undefined, 'rh-web-corpus-files');
  const to = href(`/corpus/${work.id}`);
  return (
    <div className="rh-web-corpus__row">
      <div className="rh-web-corpus__cells">
        <div className="rh-web-corpus__cell rh-web-corpus__cell--work">
          <Link className="rh-web-corpus__title" to={to}>
            {work.title}
          </Link>
          {/* One line under the title: the reference a researcher writes down, what the
              work is, and the way into its files. Three stacked lines on every row of a
              thousand-row list is a card again. */}
          <div className="rh-web-corpus__meta">
            <ObjectRef id={work.id} kind="work" to={to} />
            <span className="rh-web-corpus__byline">{byline(work)}</span>
            {work.artifacts.length === 0 ? (
              <span className="rh-text-secondary">No file yet</span>
            ) : (
              <button
                type="button"
                className="rh-web-corpus__files"
                aria-expanded={open}
                aria-controls={files}
                onClick={onToggle}
              >
                <Icon name={open ? 'chevron-down' : 'chevron-right'} size={14} />
                {counted(work.artifacts.length, 'file')}
              </button>
            )}
          </div>
        </div>
        <div className="rh-web-corpus__cell">
          <CellLabel>Screening state</CellLabel>
          <StatusBadge status={work.screening} vocabulary="screeningState" />
        </div>
        <div className="rh-web-corpus__cell">
          <CellLabel>Readable text</CellLabel>
          {/* The daemon's own answer over every file of this work: a span can only be
              anchored in a file that has been parsed (PRODUCT §16). */}
          {work.readable ? 'yes' : 'no'}
        </div>
        <div className="rh-web-corpus__cell rh-web-corpus__cell--count">
          <CellLabel>Accepted evidence</CellLabel>
          {work.evidence}
        </div>
        <div className="rh-web-corpus__cell rh-web-corpus__cell--count">
          <CellLabel>Claims citing it</CellLabel>
          {work.claims}
        </div>
        <div className="rh-web-corpus__cell">
          <CellLabel>Came into the corpus</CellLabel>
          {work.added_at ? <time dateTime={work.added_at}>{work.added}</time> : '—'}
        </div>
      </div>
      {open ? (
        <div className="rh-web-corpus__files-open" id={files}>
          <DataTable
            label={`Files of ${work.id}`}
            head={
              <tr>
                <th scope="col">Artifact</th>
                <th scope="col">Version</th>
                <th scope="col">Type</th>
                <th scope="col">Size</th>
                <th scope="col">Parsed</th>
                <th scope="col">Source</th>
              </tr>
            }
          >
            {work.artifacts.map((artifact) => (
              <tr key={artifact.id}>
                <th scope="row">
                  <code>{artifact.id}</code>
                </th>
                <td>{artifact.version}</td>
                <td>{artifact.mime_type}</td>
                {/* The package's own file-size wording, so a file reads the same here
                    as it does in the composer's attachment tray. */}
                <td>{formatFileSize(artifact.size_bytes)}</td>
                <td>
                  <StatusBadge status={artifact.parsed ? 'valid' : 'unverified'}>
                    {artifact.parsed ? 'yes' : 'no parse stored'}
                  </StatusBadge>
                </td>
                <td>
                  <a href={client.artifactBytesUrl(artifact.id)} target="_blank" rel="noreferrer">
                    open the file
                  </a>
                </td>
              </tr>
            ))}
          </DataTable>
        </div>
      ) : null}
    </div>
  );
}

export function WorkPage() {
  const { workId = '' } = useParams();
  const { client } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(
    async () => {
      const [work, evidence] = await Promise.all([
        client.work(workId),
        // `evidence.list` names what was accepted from this Work; the count alone cannot
        // be opened, and staged proposals are deliberately not in it (ADR-003).
        client.evidence(workId),
      ]);
      return { work, evidence };
    },
    [client, workId],
  );

  const work = state.data?.work ?? null;
  const evidence = state.data?.evidence ?? [];
  return (
    <FullPageWorkspace
      busy={state.loading}
      title={work ? work.title : workId}
      description={
        work
          ? `${work.id} · ${work.authors.join(', ') || 'no authors recorded'}`
          : 'One work in the corpus, with its files and what has been accepted from it.'
      }
      {...(work
        ? {
            toolbar: (
              <StatusBadge
                status={work.screening}
                vocabulary="screeningState"
                size="md"
                describe
              />
            ),
          }
        : {})}
    >
      {state.loading ? (
        <Loading what={`work ${workId}`} shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : !work ? (
        <Empty
          description="No work is stored under that id in this project. It may belong to another project, or the link may have outlived it."
          action={<Link to={href('/corpus')}>Back to the corpus</Link>}
        >
          {`No work ${workId} in this corpus`}
        </Empty>
      ) : (
        <div className="rh-web-stack">
          <Panel title="Identity">
            <Fields>
              <Field label="Id">
                <code>{work.id}</code>
              </Field>
              <Field label="Authors">{work.authors.join(', ') || '—'}</Field>
              <Field label="Year">{work.year ?? '—'}</Field>
              <Field label="Venue">{work.venue ?? '—'}</Field>
              {/* The badge in the toolbar is this work's screening state, with its
                  meaning attached; a second copy of the word in the identity list would
                  say the same thing twice. */}
              <Field label="Identifiers">
                <code>{JSON.stringify(work.identifiers)}</code>
              </Field>
            </Fields>
          </Panel>

          <Panel title="Derived">
            <Fields>
              <Field label="Blocks">{work.blocks}</Field>
              <Field label="Accepted evidence">{work.evidence}</Field>
            </Fields>
          </Panel>

          <Panel title="Files">
            <DataTable
              label={`Files of ${work.id}`}
              head={
                <tr>
                  <th scope="col">Artifact</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Filename</th>
                  <th scope="col">File hash</th>
                </tr>
              }
            >
              {work.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <th scope="row">
                    <code>{artifact.id}</code>
                  </th>
                  <td>{artifact.kind}</td>
                  <td>{artifact.original_filename ?? 'unnamed'}</td>
                  <td>
                    <code>{artifact.file_hash}</code>
                  </td>
                </tr>
              ))}
            </DataTable>
          </Panel>

          <Panel title={`Accepted evidence (${evidence.length})`}>
            {evidence.length === 0 ? (
              <Empty
                flat
                description="Evidence is accepted one candidate at a time, beside the page it was read off. Nothing from this work has been through that yet."
                action={<Link to={href('/review')}>Open the review inbox</Link>}
              >
                Nothing has been accepted from this work
              </Empty>
            ) : (
              <ul className="rh-web-list">
                {evidence.map((item) => (
                  <li key={item.id}>
                    <EvidenceCard evidence={acceptedEvidenceModel(item)} />
                    {item.qualification ? (
                      <p className="rh-text-secondary">{item.qualification}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </FullPageWorkspace>
  );
}

/**
 * One accepted `EvidenceSummary` as the Design System's evidence view model.
 *
 * Everything mapped here was decided by the daemon: `accepted` is what `evidence.list`
 * returns (staged proposals are not in it, ADR-003) and `stale` is the mark the staleness
 * pass recorded. Nothing is inferred.
 */
function acceptedEvidenceModel(item: EvidenceSummary): EvidenceModel {
  return {
    id: item.id,
    workId: item.work,
    workLabel: item.work,
    quote: item.exact_text,
    evidenceType: item.evidence_type,
    strength: item.strength,
    origin: item.origin,
    authority: 'accepted',
    stale: item.stale === 'stale',
    anchor: { artifactId: item.artifact, stale: item.stale === 'stale' },
    ...(item.field ? { field: item.field } : {}),
  };
}

/** One accepted Evidence object, opened at the exact span it was accepted from. */
export function EvidencePage() {
  const { evidenceId = '' } = useParams();
  const { client } = useSession();
  const { href } = useProjectPaths();
  const state = useAsync(() => client.object(evidenceId), [client, evidenceId]);

  const evidence = (state.data?.object ?? null) as Record<string, any> | null;
  const source = evidence?.source ?? {};
  const content = evidence?.content ?? {};
  const artifact = String(source.artifact ?? '');
  return (
    <FullPageWorkspace
      busy={state.loading}
      title={evidenceId}
      description="One accepted Evidence object, with the exact span it was accepted from."
      {...(evidence
        ? {
            toolbar: (
              <a
                className="rh-web-row"
                href={client.artifactBytesUrl(artifact)}
                target="_blank"
                rel="noreferrer"
              >
                <Icon name="external-link" size={14} />
                Open the source file
              </a>
            ),
          }
        : {})}
    >
      {state.loading ? (
        <Loading what={`evidence ${evidenceId}`} shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : !evidence ? (
        <Empty
          description="No accepted Evidence is stored under that id in this project. A proposal that is still in review has no Evidence id yet."
          action={<Link to={href('/review')}>Open the review inbox</Link>}
        >
          {`No evidence ${evidenceId} in this project`}
        </Empty>
      ) : (
        <div className="rh-web-stack">
          <blockquote className="rh-web-quote">{String(content.exact_text ?? '')}</blockquote>

          <Panel title="Epistemics">
            <Fields>
              <Field label="Origin">{String(evidence.origin ?? '')}</Field>
              <Field label="Type">{String(evidence.evidence_type ?? '')}</Field>
              <Field label="Strength">{String(evidence.strength ?? '')}</Field>
              <Field label="Status">{String(evidence.verification?.status ?? '')}</Field>
              <Field label="Accepted by">{String(evidence.verification?.accepted_by ?? '—')}</Field>
              <Field label="Review action">
                {String(evidence.verification?.review_action ?? '—')}
              </Field>
              <Field label="Rationale">{String(evidence.verification?.rationale ?? '—')}</Field>
            </Fields>
          </Panel>

          <Panel title="Source">
            <Fields>
              <Field label="Work">
                <ObjectRef
                  id={String(source.work ?? '')}
                  kind="work"
                  to={href(`/corpus/${String(source.work ?? '')}`)}
                />
              </Field>
              <Field label="Artifact">
                <a href={client.artifactBytesUrl(artifact)} target="_blank" rel="noreferrer">
                  {artifact}
                </a>
              </Field>
              <Field label="Page">{String(source.page ?? '—')}</Field>
              <Field label="Block">{String(source.block ?? '')}</Field>
              <Field label="File hash">
                <code>{String(source.file_hash ?? '')}</code>
              </Field>
            </Fields>
          </Panel>
        </div>
      )}
    </FullPageWorkspace>
  );
}
