/**
 * Evidence: everything this project has accepted, and what about it needs a researcher.
 *
 * The product's largest body of accepted state had no page of its own — `routes.tsx`
 * defined `evidence/:evidenceId` and no index — so "what have I accepted from this corpus?"
 * had no answer surface and the review queue was a one-way valve (critique 2026-09-08, P1).
 * PRODUCT §26 lists Evidence between Corpus and Claims; this is that page.
 *
 * ## It answers questions; it does not display records
 *
 * The questions a researcher brings here are six, and the page is built around those and
 * nothing else: what have I accepted, from which work; what has decayed under me; what does
 * no claim rest on; what is derived rather than read directly from a source; what may only
 * a researcher accept; what came in since I last looked. So each piece of evidence is a row
 * read across shared columns that answer them — what it is and where it came from, its
 * type, its strength, its origin, what cites it, when it was accepted — and the questions
 * themselves are the controls that narrow the list.
 *
 * The narrowing is a request, not a `filter()`. Which readings went stale when their
 * sources changed, and which no Claim rests on, are judgements over canonical state
 * (PRODUCT §37, §20.4), and P10 leaves those where they are made: `evidence.list` takes a
 * `question`, answers with the rows that answer it, and composes the sentence the narrowed
 * list is read under. What stays in the browser is the find, because "which one was that
 * quote in" is a question about the text on screen rather than about the science.
 *
 * ## What is not here, and why
 *
 * No confidence number — the daemon reports none (§43) and there is nowhere on this page
 * for one to come from. No sort: the order is the daemon's, and a find only ever hides. No
 * Accept, Reject or Defer: acceptance happened in the review queue, beside the source, and
 * there is no undo capability (§24.3), so this page is the record of that decision rather
 * than a second place to take it. Its one action is to open a reading at its source.
 *
 * Scientific status colour is used on scientific state only. A row's status badge appears
 * when the status is something other than plain acceptance, because every row on this page
 * is accepted state and a column of two hundred identical green words says nothing; type,
 * strength and origin are text, since a colour that said "derived" would be the page
 * grading the reading.
 *
 * The list is windowed. `evidence.list` answers the whole record in one read — the daemon
 * imposes no page size and P10 forbids the cockpit inventing one — and this list is longer
 * than the corpus by construction (§26's own example: 42 works, 186 accepted evidence). So
 * `VirtualList` keeps only what is near the viewport in the DOM, the page carries a find of
 * its own over the whole list rather than over the window, and it says how much of the
 * record it is showing. The browser's own Ctrl/Cmd+F is deliberately not intercepted.
 *
 * The frame is mounted before the read resolves: the heading, the description and the
 * toolbar survive loading, a refusal, and a project with nothing accepted in it.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  FullPageWorkspace,
  Input,
  VirtualList,
  humaniseResearchTokens,
  researchLabel,
  useId,
} from '@research-harness/design';
import type {
  EvidenceAttentionGroup,
  EvidenceAttentionItem,
  EvidenceList,
  EvidenceQuestion,
  EvidenceSummary,
} from '../api/dto';
import { Empty, ErrorBox, Loading, Panel, StatusBadge } from '../components/Feedback';
import { ObjectRef } from '../components/ObjectRef';
import { useDaemonOutage } from '../app/daemonStatus';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './evidence.css';

/**
 * About how tall one reading's row is before it has been measured, in CSS pixels.
 *
 * Two lines of identity — what it answers and where it came from, then the quoted span —
 * which is what a row is on this page. The measurement is the real answer; this is only
 * what the window places rows by until it has one.
 */
const EVIDENCE_ROW_HEIGHT = 76;

/**
 * The columns the accepted record is read across.
 *
 * `head` is what the strip above the list says; `label` is what one cell says on its own,
 * to a screen reader and — once the pane is too narrow for columns — to everyone. They
 * differ because a column header is read once with five others beside it and a cell label
 * is read alone.
 *
 * The set is the questions of the page's opening comment, in the order a researcher asks
 * them: what is this and where is it from, what kind of statement it carries, how directly
 * the source supports it, where it came from epistemically, what rests on it, when it
 * entered the record.
 */
const COLUMNS = [
  { key: 'evidence', head: 'Evidence', label: 'Evidence' },
  { key: 'type', head: 'Type', label: 'Evidence type' },
  { key: 'strength', head: 'Strength', label: 'Strength' },
  { key: 'origin', head: 'Origin', label: 'Epistemic origin' },
  { key: 'claims', head: 'Cited by', label: 'Claims citing it' },
  { key: 'accepted', head: 'Accepted', label: 'Accepted' },
] as const;

/**
 * Whether one reading answers what was typed into the page's find field.
 *
 * Every term has to match somewhere, and a term may match anywhere: the evidence id, the
 * work's id or title, the field it answers, or the quoted span itself. It only ever *hides*
 * — the record is the daemon's list in the daemon's order, and a find that reordered it
 * would be the cockpit deciding what a researcher should read first (PRODUCT §5 P10).
 */
export function matchesEvidence(item: EvidenceSummary, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = [item.id, item.work, item.work_title, item.field ?? '', item.exact_text]
    .join(' ')
    .toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

/**
 * What one reading is called: the field it answers, and the source it was read from.
 *
 * The same two halves, in the same order and the same words, that `evidence.list` composes
 * for a reading it names in the page's lead — the field through the vocabulary every other
 * cockpit surface spells it with, and the Work's own title.
 */
export function evidenceName(item: EvidenceSummary): string {
  const source = item.work_title || item.work;
  return item.field ? `${researchLabel('candidateField', item.field)} · ${source}` : source;
}

export function EvidenceIndexPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  // Which question the record is being asked, or "" for the whole of it. It goes to the
  // daemon rather than into a `filter()`: which readings decayed and which no claim rests
  // on are judgements about scientific state, and P10 leaves those where they are made.
  const [question, setQuestion] = useState('');
  const state = useAsync(
    () => client.evidenceList(question ? { question } : {}),
    [client, question],
  );
  const [query, setQuery] = useState('');
  const outage = useDaemonOutage();
  // The rows are a region of their own, named by their own heading, so a screen-reader user
  // can jump past the lead straight into the list — and so the live count below is reachable
  // as part of something rather than as one more announcement on the page.
  const rowsHeading = useId(undefined, 'rh-web-evidence-rows');

  // The last record the daemon actually sent.
  //
  // Silence is not an answer. A refusal is the daemon speaking and its answer replaces what
  // came before, but a daemon that has gone quiet has said nothing about the record — what
  // is on screen is still true of the last moment it spoke. So the answer is kept whole,
  // groups and all, and labelled for what it is.
  const kept = useRef<EvidenceList | null>(null);
  if (state.data !== null) kept.current = state.data;
  const answer = state.data ?? kept.current;
  const evidence = answer?.evidence ?? [];
  const attention = answer?.attention ?? [];
  const questions = answer?.questions ?? [];
  // How much the record holds, whatever this answer was narrowed to.
  const total = answer?.total ?? evidence.length;
  // The question these rows actually answer, taken from the answer that produced them
  // rather than from the request: while a new one is in flight the sentence beside the list
  // has to describe what is on the screen.
  const asked = questions.find((item) => item.kind === (answer?.question ?? '')) ?? null;
  const stale = outage !== null && evidence.length > 0;

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
    () => evidence.filter((item) => matchesEvidence(item, query)),
    [evidence, query],
  );
  const failed = state.error !== null && !stale;
  // The skeleton is for a page that has nothing yet. Once the record is on screen, asking
  // it another question keeps it there: replacing two hundred rows with a placeholder for
  // the seconds a re-read takes loses the reader's place to say nothing they did not know.
  const arriving = state.loading && answer === null;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Evidence"
      description="Everything this project has accepted from its sources, and what rests on each."
      toolbar={
        evidence.length > 0 || question !== '' ? (
          <Input
            label="Find evidence by quote, field, work or id"
            hideLabel
            size="sm"
            type="search"
            iconStart="search"
            placeholder="Quote, field, work or id"
            fieldClassName="rh-web-evidence__find"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        ) : (
          <></>
        )
      }
    >
      {arriving ? (
        <Loading what="the accepted evidence" shape="cards" />
      ) : failed ? (
        <ErrorBox error={state.error as string} retry={state.reload} />
      ) : total === 0 ? (
        <Empty
          description="Evidence is accepted one candidate at a time, beside the exact page it was read off, and only a researcher's decision creates it. Nothing in this project has been through that yet, so there is nothing to browse."
          action={<Link to={href('/review')}>Open the review inbox</Link>}
        >
          Nothing has been accepted in this project yet
        </Empty>
      ) : (
        <div className="rh-web-evidence">
          <Panel title="Evidence that needs a researcher">
            {attention.length > 0 ? (
              <ul className="rh-web-list rh-web-evidence__attention">
                {attention.map((group) => (
                  <NeedsAResearcher key={group.kind} group={group} href={href} />
                ))}
              </ul>
            ) : (
              <Empty
                flat
                description="A reading waits for a researcher once its source has changed under it, once a later reading has superseded it, once a verifier reports that it did not support what was accepted, or while no claim rests on it. None of that is true of this record."
                action={<Link to={href('/claims')}>Open the claims this evidence carries</Link>}
              >
                Nothing in this record needs a researcher
              </Empty>
            )}
          </Panel>

          <section className="rh-web-evidence__rows" aria-labelledby={rowsHeading}>
            <h2 className="rh-text-h3" id={rowsHeading}>
              Everything this project has accepted
            </h2>
            <Questions
              questions={questions}
              chosen={question}
              total={total}
              onChoose={setQuestion}
            />
            <p className="rh-text-secondary" role="status">
              {stale
                ? `The last record the daemon sent: ${counted(evidence.length, 'piece')} of evidence. It has not answered since.`
                : asked
                  ? query
                    ? `${asked.summary} Showing ${shown.length} of them.`
                    : asked.summary
                  : query
                    ? `Showing ${shown.length} of ${counted(total, 'piece')} of evidence.`
                    : `${counted(total, 'piece')} of evidence.`}
            </p>
            {evidence.length === 0 ? (
              <Empty
                description="Everything the daemon counted under this question is still in the record; this list is only what it named. The record itself is unchanged underneath it."
                action={
                  <Button size="sm" variant="secondary" onClick={() => setQuestion('')}>
                    Show everything accepted
                  </Button>
                }
              >
                Nothing answers this question
              </Empty>
            ) : shown.length === 0 ? (
              <Empty
                description="The find only hides. Everything the daemon listed is still in the record underneath it."
                action={
                  <Button size="sm" variant="secondary" onClick={() => setQuery('')}>
                    Clear the find
                  </Button>
                }
              >
                Nothing matches this find
              </Empty>
            ) : (
              <>
                {/* The column names, once, above the window. They are the visible half of
                    the labels each cell carries for a screen reader, which is why they are
                    hidden from one: read together they would say every column name twice. */}
                <div className="rh-web-evidence__head" aria-hidden="true">
                  {COLUMNS.map((column) => (
                    <span key={column.key} className="rh-web-evidence__column">
                      {column.head}
                    </span>
                  ))}
                </div>
                <VirtualList
                  className="rh-web-evidence__list"
                  label="Accepted evidence"
                  items={shown}
                  itemKey={(item) => item.id}
                  estimatedItemHeight={EVIDENCE_ROW_HEIGHT}
                  renderItem={(item) => <EvidenceRow item={item} href={href} />}
                />
              </>
            )}
          </section>
        </div>
      )}
    </FullPageWorkspace>
  );
}

/** `1 piece` / `2 pieces` — a count is only ever read inside the thing it counts. */
function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * What this record can be asked, as the controls that ask it.
 *
 * Every one of them is the daemon's: the question, the words on it, and how many readings
 * answer it. The cockpit contributes one control the daemon has no opinion about — the way
 * back to the whole record — and the press that sends the next `evidence.list`.
 *
 * Toggles rather than a select, for the reason the corpus gives: a researcher should be
 * able to see what the record can be asked without opening anything, and a record in good
 * order offers few of them.
 */
function Questions({
  questions,
  chosen,
  total,
  onChoose,
}: {
  questions: EvidenceQuestion[];
  chosen: string;
  total: number;
  onChoose: (kind: string) => void;
}) {
  if (questions.length === 0) return null;
  return (
    <div className="rh-web-evidence__questions" role="group" aria-label="Ask the record a question">
      <Button size="sm" variant="secondary" aria-pressed={chosen === ''} onClick={() => onChoose('')}>
        {`Everything accepted (${total})`}
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
 * One reason a piece of accepted evidence needs a researcher.
 *
 * The line is the daemon's whole sentence, count and all, because deciding which readings
 * belong in this group and deciding how to say so are one judgement (P10). Under it are the
 * first few of them, indented, each a link to the reading itself — and, where the daemon
 * had something to add about that one reading rather than about all of them, what it added.
 *
 * `more` is what the cap left out, in the daemon's words. It exists because the group is a
 * lead rather than a second list: the readings it counts are all in the list underneath it.
 */
function NeedsAResearcher({
  group,
  href,
}: {
  group: EvidenceAttentionGroup;
  href: (path: string) => string;
}) {
  return (
    <li>
      <p className="rh-web-evidence__group">{humaniseResearchTokens(group.label)}</p>
      {group.items.length > 0 ? (
        <ul className="rh-web-list rh-web-list--tight rh-web-evidence__group-items">
          {group.items.map((item) => (
            <li key={item.id}>
              <EvidenceLink item={item} href={href} />
              {item.detail ? (
                <span className="rh-text-secondary"> — {humaniseResearchTokens(item.detail)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {group.more ? <p className="rh-web-evidence__more">{group.more}</p> : null}
    </li>
  );
}

/**
 * One reading in a lead group, pointed at itself where the daemon gave it a page.
 *
 * A reading with no route of its own is not linked back to this index: the reader is
 * already on it, and a link to the page under their feet is not a next step.
 */
function EvidenceLink({
  item,
  href,
}: {
  item: EvidenceAttentionItem;
  href: (path: string) => string;
}) {
  if (!item.route) return <>{item.label}</>;
  return <Link to={href(item.route)}>{item.label}</Link>;
}

/** One cell's own name, for a screen reader and for a pane too narrow to hold columns. */
function CellLabel({ children }: { children: string }) {
  return <span className="rh-web-evidence__label">{children}</span>;
}

/**
 * One accepted reading, read across the columns the page is asked about.
 *
 * The name opens the evidence at its exact span; the id beside it is the reference a
 * researcher works with and opens the same page. The quoted span is on the row rather than
 * a press away, because it is what a reading *is* — an index of two hundred rows of
 * metadata with the sentences hidden would be a catalogue of the record rather than the
 * record.
 *
 * A status badge appears only where the status is something other than plain acceptance:
 * every row here is accepted state, so a column of identical green words would carry no
 * information, while a stale or superseded reading is exactly the row that has something to
 * say.
 */
function EvidenceRow({
  item,
  href,
}: {
  item: EvidenceSummary;
  href: (path: string) => string;
}) {
  const to = href(`/evidence/${item.id}`);
  const decayed = item.status !== 'accepted' || item.stale === 'stale';
  return (
    <div className="rh-web-evidence__row">
      <div className="rh-web-evidence__cells">
        <div className="rh-web-evidence__cell rh-web-evidence__cell--evidence">
          <Link className="rh-web-evidence__name" to={to}>
            {evidenceName(item)}
          </Link>
          {/* One line under the name: the reference a researcher writes down, and the state
              of the reading when it is not simply accepted. */}
          <div className="rh-web-evidence__meta">
            <ObjectRef id={item.id} kind="evidence" to={to} />
            {decayed ? (
              <StatusBadge
                status={item.stale === 'stale' ? 'stale' : item.status}
                vocabulary={item.stale === 'stale' ? 'staleState' : 'evidenceStatus'}
              />
            ) : null}
          </div>
          {/* The span itself, as the source wrote it. Quoted, because the product never
              paraphrases a source and the quotation rule is how the cockpit says so. */}
          <blockquote className="rh-web-evidence__quote">{item.exact_text}</blockquote>
        </div>
        <div className="rh-web-evidence__cell">
          <CellLabel>Evidence type</CellLabel>
          {researchLabel('evidenceType', item.evidence_type)}
        </div>
        <div className="rh-web-evidence__cell">
          <CellLabel>Strength</CellLabel>
          {researchLabel('evidenceStrength', item.strength)}
        </div>
        <div className="rh-web-evidence__cell">
          <CellLabel>Epistemic origin</CellLabel>
          {researchLabel('evidenceOrigin', item.origin)}
        </div>
        <div className="rh-web-evidence__cell rh-web-evidence__cell--claims">
          <CellLabel>Claims citing it</CellLabel>
          <CitingClaims claims={item.claims} href={href} />
        </div>
        <div className="rh-web-evidence__cell">
          <CellLabel>Accepted</CellLabel>
          {item.accepted_at ? <time dateTime={item.accepted_at}>{item.accepted}</time> : '—'}
        </div>
      </div>
    </div>
  );
}

/**
 * What rests on one reading: the Claims that cite it, by the statement each is read as.
 *
 * The daemon inverts the edge and carries the statement with the id, so a row says which
 * claim rather than how many. "Nothing yet" is a claim about the record and is the true one
 * — the alternative, a bare zero, is the figure this page was built to avoid.
 */
function CitingClaims({
  claims,
  href,
}: {
  claims: EvidenceSummary['claims'];
  href: (path: string) => string;
}) {
  if (claims.length === 0) return <span className="rh-text-secondary">Nothing yet</span>;
  return (
    <ul className="rh-web-list rh-web-list--tight">
      {claims.map((claim) => (
        <li key={claim.id}>
          <Link to={href(`/claims/${claim.id}`)}>{claim.title || claim.id}</Link>
        </li>
      ))}
    </ul>
  );
}
