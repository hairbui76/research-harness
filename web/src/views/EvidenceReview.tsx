/**
 * Source beside decision (ROADMAP Task 11.3), and the queue it sits in.
 *
 * Left: the page the span was read off, with the span drawn on it. Right: exactly what is
 * being proposed — the quoted text, the field it answers, its epistemic origin and type,
 * the number with the provenance a number needs, the verifier's verdict and rationale, the
 * competing candidates, and the positions in any conflict. Then the six review actions.
 *
 * The two halves are a `PaneGroup`, so the split is draggable and keyboard-resizable and
 * neither half can push the other off the screen. Once this page's own container is too
 * narrow to hold both — the page, not the window: the rail and the divider take width a
 * viewport query cannot see — they stack, and the source is still first. Stacking alone
 * would put the source above the fold and the decision below it, which is the one
 * arrangement PRODUCT §26 forbids, so the pinned decision carries a strip of the source
 * with it: the quoted span, its page, and the control that opens the page it was read off.
 *
 * Reviewing is a queue, so this screen also knows where it is in one. The order is the
 * server's — the same ranking the inbox draws — read once and remembered, so a candidate
 * leaving the queue behind the researcher does not renumber what "next" means halfway
 * through an afternoon. Moving on is offered as a link and never taken on someone's behalf
 * unless they asked for it: auto-advance is a switch, off until it is turned on.
 *
 * Nothing on this screen is computed here. The category, the reasons, the verdict, and the
 * eligibility all come from the daemon; the page renders them.
 */
import { useEffect, useRef, useState } from 'react';
import {
  EvidenceCard,
  FullPageWorkspace,
  Pane,
  PaneGroup,
  PaneHandle,
  REVIEW_DECISION_META,
  SourceAnchor,
  Switch,
  humaniseResearchTokens,
  humaniseTerm,
  researchLabel,
  researchMeaning,
} from '@research-harness/design';
import type {
  EvidenceFactMeanings,
  EvidenceModel,
  ReviewDecision,
} from '@research-harness/design';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { CandidateView, JsonObject, ReviewItem, SourceContext } from '../api/dto';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
  candidateName,
  fieldLabel,
} from '../components/Feedback';
import { ObjectRef } from '../components/ObjectRef';
import { ReviewActions } from '../components/ReviewActions';
import { SourcePane } from '../components/SourcePane';
import { useRegisterCommands } from '../app/commands';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './review.css';

/** Where the auto-advance preference lives. Losing it costs one switch. */
export const AUTO_ADVANCE_KEY = 'research-harness.review.auto-advance';

/**
 * Which key presses which decision.
 *
 * The keys are here; the labels are not. `REVIEW_DECISION_META` owns the vocabulary, and a
 * shortcut presses the bar's own button rather than calling a capability of its own, so a
 * key can never record something the button on screen would not have.
 */
const DECISION_KEYS: Record<ReviewDecision, string> = {
  accept: 'a',
  qualify: 'q',
  edit: 'e',
  reject: 'r',
  defer: 'd',
  request_more_evidence: 'm',
};

export function readAutoAdvance(): boolean {
  try {
    return window.localStorage.getItem(AUTO_ADVANCE_KEY) === 'true';
  } catch {
    return false;
  }
}

function writeAutoAdvance(on: boolean): void {
  try {
    window.localStorage.setItem(AUTO_ADVANCE_KEY, on ? 'true' : 'false');
  } catch {
    /* storage disabled: the switch simply starts off again next time */
  }
}

/**
 * The panel the pinned decision is standing on, if any.
 *
 * The card is pinned to the foot of its scroller, so at most scroll positions it stands over
 * content the researcher has not read past yet. What the critique caught was the *silence*
 * of that: the card's opaque edge landed inside the `Unit percent` row of the Number panel
 * and said nothing, so the panel appeared to end at a fact that was only half drawn. The
 * edge is soft now — the card's own fade band — and this is what names what is behind it.
 *
 * `panels` are boxes in viewport coordinates, in document order. `edge` is where the card
 * stops being transparent and `floor` is where it ends, so together they are exactly the
 * band the card hides. The first panel that reaches into that band is the one the reader
 * was in the middle of, because a later panel cannot start above an earlier one's end.
 */
export function panelUnder(
  panels: readonly { title: string; top: number; bottom: number }[],
  edge: number,
  floor: number,
): string | null {
  for (const panel of panels) {
    if (panel.bottom > edge && panel.top < floor) return panel.title;
  }
  return null;
}

/** Every titled panel in the decision pane, as boxes, for `panelUnder`. */
function panelBoxes(root: HTMLElement): { title: string; top: number; bottom: number }[] {
  return Array.from(root.querySelectorAll<HTMLElement>('section')).flatMap((section) => {
    const heading = section.querySelector('h2');
    if (heading === null) return [];
    const rect = section.getBoundingClientRect();
    return [{ title: heading.textContent ?? '', top: rect.top, bottom: rect.bottom }];
  });
}

/**
 * How much of the span the pinned strip prints.
 *
 * The strip is a reminder of the source, not a replacement for it: the pane above it holds
 * the block the span sits in and the page it was drawn on, and the strip's own control
 * opens that page. A span longer than this would push the decision off the screen, which is
 * the defect the strip exists to fix, so it ends in an ellipsis and says so by ending in one.
 */
const STRIP_QUOTE_LIMIT = 240;

export function stripQuote(text: string): string {
  const span = text.trim();
  if (span.length <= STRIP_QUOTE_LIMIT) return span;
  return `${span.slice(0, STRIP_QUOTE_LIMIT - 1).trimEnd()}\u2026`;
}

/** The candidates either side of this one, in the queue order the server sent. */
export function neighbours(
  queue: ReviewItem[],
  candidateId: string,
): { previous: ReviewItem | null; next: ReviewItem | null } {
  const index = queue.findIndex((item) => item.candidate_id === candidateId);
  if (index < 0) return { previous: null, next: null };
  return { previous: queue[index - 1] ?? null, next: queue[index + 1] ?? null };
}

export function EvidenceReviewPage() {
  const { href } = useProjectPaths();
  const { candidateId = '' } = useParams();
  const { client } = useSession();
  const navigate = useNavigate();
  const [outcome, setOutcome] = useState<string | null>(null);
  const [autoAdvance, setAutoAdvance] = useState(readAutoAdvance);
  const [covered, setCovered] = useState<string | null>(null);
  const decideRef = useRef<HTMLDivElement | null>(null);
  const sourceRef = useRef<HTMLDivElement | null>(null);
  const proposalRef = useRef<HTMLDivElement | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);

  // The queue order, read once. Re-reading it on every candidate would silently re-target
  // "next" as decided proposals drop out, which is the one thing a queue must not do.
  const queueRef = useRef<ReviewItem[] | null>(null);

  const state = useAsync(async () => {
    const [candidate, inbox] = await Promise.all([
      client.candidate(candidateId),
      client.reviewInbox(),
    ]);
    if (queueRef.current === null) queueRef.current = inbox.items;
    const item = inbox.items.find((entry) => entry.candidate_id === candidateId) ?? null;
    const blocks = await client.blocks(candidate.artifact);
    return { candidate, item, blocks };
  }, [client, candidateId]);

  // An outcome belongs to the candidate that produced it, and to no other.
  useEffect(() => setOutcome(null), [candidateId]);

  /*
   * What the pinned decision is standing on.
   *
   * Reading order puts the proposal, the number and the verdict above the decision, and
   * reach pins the decision to the foot of the scroller, so the two meet: the card covers
   * the tail of whatever is on screen. The fade band makes that a dissolve rather than a
   * cut; this makes it a *named* dissolve, so a panel the card is standing on never reads
   * as a panel that ended. The measurement is the surface's own top — the first opaque row
   * of the card — and it is taken off the layout rather than computed from a breakpoint,
   * because the pane answers its own width. The card's height never depends on the answer
   * (the line's row is reserved either way), so measuring can never move what it measures.
   */
  useEffect(() => {
    const surface = surfaceRef.current;
    const proposal = proposalRef.current;
    if (surface === null || proposal === null) return;
    let frame = 0;
    const measure = (): void => {
      frame = 0;
      const band = surface.getBoundingClientRect();
      setCovered(panelUnder(panelBoxes(proposal), band.top, band.bottom));
    };
    const schedule = (): void => {
      if (frame === 0) frame = window.requestAnimationFrame(measure);
    };
    measure();
    // Scroll does not bubble, so the capture phase is how one listener sees every scroller
    // this screen has: the pane when the panes sit side by side, the page when they stack.
    window.addEventListener('scroll', schedule, true);
    window.addEventListener('resize', schedule);
    // Scrolling is not the only thing that moves a panel under the card. The source page
    // arrives from a PDF engine that decodes it after the screen has drawn, and where the
    // panes stack that lands a thousand pixels of page above the proposal, which moves every
    // panel without any scroll event to say so. Both panes are watched; neither of their
    // heights depends on the answer, so watching them cannot make the answer oscillate.
    // jsdom has neither a layout engine nor a `ResizeObserver`, and with no layout there is
    // nothing to observe: the line stays empty there, which is what it should be.
    const resized =
      typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;
    resized?.observe(proposal);
    if (resized !== null && sourceRef.current !== null) resized.observe(sourceRef.current);
    return () => {
      if (frame !== 0) window.cancelAnimationFrame(frame);
      resized?.disconnect();
      window.removeEventListener('scroll', schedule, true);
      window.removeEventListener('resize', schedule);
    };
  }, [state.data, candidateId]);

  const { previous, next } = neighbours(queueRef.current ?? [], candidateId);
  const openCandidate = (item: ReviewItem | null): void => {
    if (item) navigate(href(`/review/${item.candidate_id}`));
  };

  /** Press the bar's own button for a decision, so the shortcut adds no second path. */
  const pressDecision = (decision: ReviewDecision): void => {
    const button = decideRef.current?.querySelector<HTMLButtonElement>(
      `button[data-decision="${decision}"]`,
    );
    if (button && !button.disabled) button.click();
  };

  useRegisterCommands(
    () => [
      ...(Object.keys(DECISION_KEYS) as ReviewDecision[]).map((decision) => ({
        id: `review:${decision}`,
        label: REVIEW_DECISION_META[decision].label,
        group: 'This candidate',
        shortcut: DECISION_KEYS[decision],
        hint: REVIEW_DECISION_META[decision].description,
        run: () => pressDecision(decision),
      })),
      {
        id: 'review:next',
        label: 'Next candidate',
        group: 'This candidate',
        shortcut: 'n',
        // The palette names the candidate the way the link and the heading do, so a
        // researcher choosing from it knows what they are about to open.
        hint: next
          ? `Open ${candidateName(next.field, next.work)}, next in the queue’s own order.`
          : 'Nothing is after this one in the queue.',
        run: () => openCandidate(next),
      },
      {
        id: 'review:previous',
        label: 'Previous candidate',
        group: 'This candidate',
        shortcut: 'p',
        hint: previous
          ? `Go back to ${candidateName(previous.field, previous.work)}.`
          : 'Nothing is before this one in the queue.',
        run: () => openCandidate(previous),
      },
    ],
    [next, previous, href, navigate],
  );

  const data = state.data;
  const candidate = data?.candidate ?? null;
  const item = data?.item ?? null;

  return (
    <FullPageWorkspace
      className="rh-web-review"
      title={
        candidate
          ? candidateName(candidate.field, candidate.work)
          : `Candidate ${candidateId}`
      }
      description="A staged proposal, beside the page it was read off. Nothing here is accepted state."
      toolbar={
        <>
          {/* The two states this screen is about: what the proposal is, and why the queue
              put it here. Both say what they mean on focus or hover. */}
          <StatusBadge status="candidate" size="md" describe />
          {item ? (
            <StatusBadge status={item.category} vocabulary="reviewCategory" size="md" describe />
          ) : null}
        </>
      }
    >
      {state.loading ? <Loading what={`candidate ${candidateId}`} /> : null}
      {state.error ? <ErrorBox error={state.error} retry={state.reload} /> : null}
      {!state.loading && !state.error && !data ? (
        <Empty
          description="Nothing is staged under that id. A candidate that has been decided leaves the queue and keeps its record on the work it was read from."
          action={<Link to={href('/review')}>Back to the review inbox</Link>}
        >
          {`No candidate ${candidateId} is waiting`}
        </Empty>
      ) : null}

      {data && candidate ? (
        <PaneGroup direction="horizontal" defaultSizes={[50, 50]}>
          <Pane minSize={25}>
            <div className="rh-web-review-pane" ref={sourceRef} tabIndex={-1}>
              {/* A proposal in staging, so the span wears the accent and says so. The
                  accepted tint belongs to a decision, and none has been made here. */}
              <SourcePane
                artifact={candidate.artifact}
                context={sourceContext(candidate, item)}
                authority="candidate"
                blocks={data.blocks}
                blockId={blockIdOf(candidate)}
              />
            </div>
          </Pane>
          <PaneHandle label="Resize the source pane" />
          <Pane minSize={25}>
            <div className="rh-web-review-pane rh-web-review-pane--end rh-web-stack">
              <div className="rh-web-stack" ref={proposalRef}>
                <Proposal candidate={candidate} item={item} />
              </div>

              {/*
                  The decision stays on screen while the source does.

                  Everything above this — the proposal, the number, the verification, the
                  conflict — is what a researcher reads *before* deciding, and on a 1024px
                  window it used to push the six actions past the bottom of the pane, so the
                  one act this screen exists for was the one thing you had to scroll to
                  find. The panel is pinned to the foot of the pane instead: its own surface
                  and hairline over whatever it covers, the outcome and the way forward
                  inside it, and the source still beside it.

                  What it stands on it no longer cuts. The block opens with a fade band, so
                  a fact row passing under the card dissolves instead of meeting an opaque
                  edge mid-word, and the first line of the surface names the panel the edge
                  is standing in. When the panes stack, the same block carries the source
                  with it, above the decision and never under it.
              */}
              <div className="rh-web-decide">
                <div className="rh-web-decide__surface" ref={surfaceRef}>
                  <p className="rh-web-decide__more rh-text-secondary">
                    {covered === null ? null : `${covered} continues under the decision.`}
                  </p>

                  <SourceStrip
                    artifact={candidate.artifact}
                    context={sourceContext(candidate, item)}
                    blockId={blockIdOf(candidate)}
                    onOpenPage={() => {
                      if (sourceRef.current !== null) revealSource(sourceRef.current);
                    }}
                  />

                  <Panel title="Decide">
                    {/*
                        The first row of the decision: what the last one recorded, and
                        whether the queue moves on by itself. Alex's complaint was that the
                        switch sat under six buttons and two links, below the card's own
                        fold, so the one preference a fast reviewer wants was the one thing
                        they had to scroll inside a pinned panel to reach.
                    */}
                    <div className="rh-web-decide__lede">
                      {outcome ? (
                        <p className="rh-web-next__outcome" role="status">
                          Candidate {outcome}.
                        </p>
                      ) : null}
                      <Switch
                        label="Open the next candidate after a decision"
                        checked={autoAdvance}
                        onCheckedChange={(on) => {
                          setAutoAdvance(on);
                          writeAutoAdvance(on);
                        }}
                        fieldClassName="rh-web-decide__advance"
                      />
                    </div>

                    <div ref={decideRef}>
                      <ReviewActions
                        candidate={candidate}
                        hasOpenConflict={(item?.conflicts.length ?? 0) > 0}
                        onReviewed={(what) => {
                          setOutcome(what);
                          if (autoAdvance) openCandidate(next);
                        }}
                      />
                    </div>

                    <div className="rh-web-next">
                      <div className="rh-web-next__moves">
                        {previous ? (
                          <Link to={href(`/review/${previous.candidate_id}`)}>
                            Previous: {candidateName(previous.field, previous.work)}
                          </Link>
                        ) : null}
                        {next ? (
                          <Link to={href(`/review/${next.candidate_id}`)}>
                            Next: {candidateName(next.field, next.work)}
                          </Link>
                        ) : (
                          <span className="rh-text-secondary">Last in the queue.</span>
                        )}
                      </div>
                    </div>
                  </Panel>
                </div>
              </div>
            </div>
          </Pane>
        </PaneGroup>
      ) : null}
    </FullPageWorkspace>
  );
}

/**
 * Put the source page back on screen, under the page header rather than behind it.
 *
 * `scrollIntoView` aligns to the scrollport's own top edge, and this page's header is
 * sticky *inside* that scrollport, so aligning to it hides the first lines of the page the
 * researcher has just asked to see — the section heading the span sits under, which is the
 * part that says what the number is a number of. `--rh-page-header-bottom` is the viewport
 * coordinate `FullPageWorkspace` publishes for that header's bottom edge, so the correction
 * is the difference. Focus follows the scroll, because a screen reader follows the focus.
 */
function revealSource(pane: HTMLElement): void {
  if (typeof pane.scrollIntoView === 'function') pane.scrollIntoView({ block: 'start' });
  const headerBottom = Number.parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--rh-page-header-bottom'),
  );
  const hidden = Number.isFinite(headerBottom)
    ? headerBottom - pane.getBoundingClientRect().top
    : 0;
  if (hidden > 0) scrollBack(pane, hidden);
  pane.focus({ preventScroll: true });
}

/** Give `by` pixels back to whichever ancestor is actually scrolling this pane. */
function scrollBack(from: HTMLElement, by: number): void {
  let node = from.parentElement;
  while (node !== null) {
    const overflow = getComputedStyle(node).overflowY;
    if ((overflow === 'auto' || overflow === 'scroll') && node.scrollHeight > node.clientHeight) {
      node.scrollTop -= by;
      return;
    }
    node = node.parentElement;
  }
  window.scrollBy(0, -by);
}

/**
 * The source, pinned above the decision when the two panes cannot sit side by side.
 *
 * PRODUCT §26 asks for the exact source beside the proposed decision, and stacking is where
 * that promise used to lapse: the pane order stayed right — source first — but a screen
 * narrow enough to stack is a screen where the decision is at the bottom and the page it
 * was read off is a scroll away, so the researcher decided with the source off screen. The
 * strip travels with the pinned decision instead. It carries what a decision is actually
 * checked against — the quoted span, and the anchor that names its page — and its control
 * puts the rendered page back on screen rather than opening anything over it.
 *
 * It is drawn only when the panes stack; a container query in `styles.css` decides that,
 * because the page pane, not the window, is what has to hold two panes. Where they do sit
 * side by side the source pane itself is already beside the decision, and a second copy of
 * the span would be one source too many.
 */
function SourceStrip({
  artifact,
  context,
  blockId,
  onOpenPage,
}: {
  artifact: string;
  context: SourceContext;
  blockId: string | null;
  onOpenPage: () => void;
}) {
  const page = context.page ?? 1;
  return (
    <div className="rh-web-source-strip">
      <p className="rh-web-quote rh-web-source-strip__quote">{stripQuote(context.exact_text)}</p>
      <SourceAnchor
        className="rh-web-source-strip__anchor"
        variant="inline"
        anchor={{ artifactId: artifact, page, ...(blockId ? { block: blockId } : {}) }}
        onOpen={onOpenPage}
        openLabel={`Show page ${page}, with the span drawn on it`}
      />
    </div>
  );
}

/** The block the span sits in, when the candidate names one. */
function blockIdOf(candidate: CandidateView): string | null {
  const evidence = candidate.evidence as JsonObject;
  const source = (evidence.source ?? {}) as JsonObject;
  return (source.block as string) ?? null;
}

/**
 * What the source pane draws. The queue item's context is preferred because it carries the
 * neighbouring blocks and the bounding box; the candidate's own source is the fallback for
 * a proposal that has already left the queue.
 */
function sourceContext(candidate: CandidateView, item: ReviewItem | null) {
  if (item) return item.source_context;
  const evidence = candidate.evidence as JsonObject;
  const source = (evidence.source ?? {}) as JsonObject;
  const content = (evidence.content ?? {}) as JsonObject;
  return {
    page: (source.page as number | null) ?? null,
    section_path: (source.section_path as string[]) ?? [],
    block_text: String(content.exact_text ?? ''),
    exact_text: String(content.exact_text ?? ''),
    bbox: null,
    neighbors: [],
  };
}

/** Everything about the proposal itself: what it says, why it is here, and what disputes it. */
function Proposal({ candidate, item }: { candidate: CandidateView; item: ReviewItem | null }) {
  const { href } = useProjectPaths();
  const evidence = candidate.evidence as JsonObject;
  const source = (evidence.source ?? {}) as JsonObject;
  const content = (evidence.content ?? {}) as JsonObject;

  return (
    <>
      {/* The card is named the way the h1, the queue row, the palette and the
          decide-and-next links name it. A `cand_<hex>` is the daemon's handle for a
          proposal, not a word a researcher reads (2E). */}
      <EvidenceCard
        title={candidateName(candidate.field, candidate.work)}
        evidence={proposedEvidence(candidate, evidence, content, source)}
        meanings={proposedMeanings(candidate, evidence)}
      />

      <Panel title="Proposal">
        <Fields>
          <Field label="Anchor">
            <StatusBadge status={candidate.anchor_status} vocabulary="anchorStatus" describe /> block{' '}
            <code>{String(source.block ?? '?')}</code> · page {String(source.page ?? '?')}
          </Field>
          {item ? (
            <Field label="Why it is here">
              {humaniseResearchTokens(item.reasons.join('; ')) ||
                researchLabel('reviewCategory', 'routine')}
            </Field>
          ) : null}
          <Field label="Work">
            <ObjectRef id={candidate.work} kind="work" to={href(`/corpus/${candidate.work}`)} />
          </Field>
        </Fields>
      </Panel>

      {content.numeric ? <NumericPanel numeric={content.numeric as JsonObject} /> : null}
      {content.negative_state ? (
        <Panel title="Absence">
          <Fields>
            <Field
              label="State"
              vocabulary="negativeState"
              value={String(content.negative_state)}
              describe
            />
          </Fields>
          <p className="rh-text-secondary">
            Absence is a state, not a finding: only an audited decision turns “not reported”
            into “absent”.
          </p>
        </Panel>
      ) : null}

      <Panel title="Verification">
        {candidate.verification ? (
          <Fields>
            <Field label="Verdict">
              <StatusBadge status={candidate.verdict ?? 'unverified'} vocabulary="verdict" describe />
            </Field>
            <Field label="Verifier">{candidate.verifier ?? '— none recorded'}</Field>
            <Field label="Rationale">
              {String((candidate.verification as JsonObject).rationale ?? '')}
            </Field>
            <Field label="Quoted support">
              {String((candidate.verification as JsonObject).quoted_support ?? '—')}
            </Field>
          </Fields>
        ) : (
          <Empty>Not verified yet — accepting it makes you its verifier.</Empty>
        )}
      </Panel>

      {item && item.competing.length > 0 ? (
        <Panel title="Competing candidates">
          <ul className="rh-web-list rh-web-list--tight">
            {item.competing.map((id) => (
              <li key={id}>
                <ObjectRef id={id} kind="evidence" to={href(`/review/${id}`)} authority="candidate" />
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {item && item.conflicts.length > 0 ? (
        <Panel title="Conflict">
          {item.conflicts.map((conflict) => (
            <div key={conflict.conflict_id} className="rh-web-stack rh-web-stack--tight">
              <p>{conflict.summary}</p>
              <DataTable
                label={`Positions in ${conflict.conflict_id}`}
                head={
                  <tr>
                    <th scope="col">Position</th>
                    <th scope="col">Decision</th>
                    <th scope="col">Rationale</th>
                  </tr>
                }
              >
                {conflict.positions.map((position) => (
                  <tr key={position.label}>
                    <th scope="row">{position.label}</th>
                    <td>{readable(position.decision)}</td>
                    <td>{position.rationale ?? '—'}</td>
                  </tr>
                ))}
              </DataTable>
              <ProposedChanges changes={conflict.proposed_changes as JsonObject[]} />
            </div>
          ))}
        </Panel>
      ) : null}
    </>
  );
}

/**
 * The staged candidate as the Design System's evidence view model.
 *
 * `authority` is `candidate` and cannot be anything else here: this object is a proposal
 * in `.research/staging`, and only a review decision moves it into accepted state
 * (ADR-003). The numeric block is deliberately left off the card — the Number panel below
 * carries the metric, unit, dataset, condition and table cell a number must travel with
 * (PRODUCT §12), and a two-field summary beside it would only invite reading the shorter one.
 */
function proposedEvidence(
  candidate: CandidateView,
  evidence: JsonObject,
  content: JsonObject,
  source: JsonObject,
): EvidenceModel {
  return {
    id: candidate.candidate_id,
    workId: candidate.work,
    workLabel: candidate.work,
    quote: String(content.exact_text ?? ''),
    field: fieldLabel(candidate.field),
    // The card prints these three verbatim, so it is given the researcher's word for each
    // rather than the daemon's identifier.
    evidenceType: researchLabel('evidenceType', String(evidence.evidence_type ?? '')),
    strength: researchLabel('evidenceStrength', String(evidence.strength ?? '')),
    origin: researchLabel('evidenceOrigin', String(evidence.origin ?? '')),
    authority: 'candidate',
    anchor: {
      artifactId: candidate.artifact,
      stale: candidate.anchor_status !== 'valid',
      ...(typeof source.page === 'number' ? { page: source.page } : {}),
      ...(typeof source.block === 'string' ? { block: source.block } : {}),
    },
  };
}

/**
 * What the product states about each word the card prints as a fact.
 *
 * The card is handed the researcher's word rather than the daemon's value, so the meaning
 * has to travel with it. `researchMeaning` answers with the value's own sentence where the
 * product writes one — `Source observed`, `Metric result` — and with what the product says
 * about the vocabulary itself where it defines the axis but not its members, which is the
 * case for every evidence type and for `Direct` and `Indirect` (PRODUCT §9.2, §9.3). A
 * word it answers nothing for is left plain: `Work` is an identifier, and a vocabulary the
 * product never defines is not given a definition here.
 */
function proposedMeanings(candidate: CandidateView, evidence: JsonObject): EvidenceFactMeanings {
  const meanings: EvidenceFactMeanings = {};
  const type = researchMeaning('evidenceType', String(evidence.evidence_type ?? ''));
  const strength = researchMeaning('evidenceStrength', String(evidence.strength ?? ''));
  const origin = researchMeaning('evidenceOrigin', String(evidence.origin ?? ''));
  const field = researchMeaning('candidateField', candidate.field);
  if (type !== undefined) meanings.type = type;
  if (strength !== undefined) meanings.strength = strength;
  if (origin !== undefined) meanings.origin = origin;
  if (field !== undefined) meanings.field = field;
  return meanings;
}

function NumericPanel({ numeric }: { numeric: JsonObject }) {
  return (
    <Panel title="Number">
      <Fields>
        <Field label="Value">{String(numeric.raw ?? '')}</Field>
        <Field label="Metric">{String(numeric.metric ?? '—')}</Field>
        <Field label="Unit">{String(numeric.unit ?? '—')}</Field>
        <Field label="Dataset">{String(numeric.dataset ?? '—')}</Field>
        <Field label="Condition">{readable(numeric.condition)}</Field>
        <Field label="Table">
          {String(numeric.source_table ?? '—')} · row {String(numeric.source_row ?? '—')} · column{' '}
          {String(numeric.source_column ?? '—')}
        </Field>
      </Fields>
    </Panel>
  );
}

/**
 * A free-form object the daemon sent, as a line rather than as JSON.
 *
 * A position's decision and a number's condition are open dictionaries — the daemon does
 * not fix their keys, so nothing here can name them in advance. What it can do is stop
 * printing braces and quotation marks at a researcher: each key is humanised, each value
 * is read out in the vocabulary's own words, and an empty one says so.
 */
export function readable(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return value.length === 0 ? '—' : value.map(readable).join(', ');
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return '—';
    return entries.map(([key, item]) => `${humaniseTerm(key)}: ${readable(item)}`).join(' · ');
  }
  return humaniseResearchTokens(String(value));
}

/** The diff of what accepting each side would change (Conflict-first UX). */
export function ProposedChanges({ changes }: { changes: JsonObject[] }) {
  if (!changes.length) return null;
  return (
    <DataTable
      label="What accepting each side would change"
      head={
        <tr>
          <th scope="col">Position</th>
          <th scope="col">Field</th>
          <th scope="col">From</th>
          <th scope="col">To</th>
        </tr>
      }
    >
      {changes.map((change, index) => (
        <tr key={index}>
          <th scope="row">{String(change.position ?? '')}</th>
          <td>{change.field === undefined ? '—' : humaniseTerm(String(change.field))}</td>
          <td>{readable(change.from)}</td>
          <td>{readable(change.to)}</td>
        </tr>
      ))}
    </DataTable>
  );
}

export type { ReviewItem };
