/**
 * Source beside decision (ROADMAP Task 11.3), and the queue it sits in.
 *
 * Left: the page the span was read off, with the span drawn on it. Right: exactly what is
 * being proposed — the quoted text, the field it answers, its epistemic origin and type,
 * the number with the provenance a number needs, the verifier's verdict and rationale, the
 * competing candidates, and the positions in any conflict. Then the six review actions.
 *
 * The two halves are a `PaneGroup`, so the split is draggable and keyboard-resizable and
 * neither half can push the other off the screen. Below 1100px they stack, and the source
 * is still first.
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
  Switch,
} from '@research-harness/design';
import type { EvidenceModel, ReviewDecision } from '@research-harness/design';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { CandidateView, JsonObject, ReviewItem } from '../api/dto';
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
  const decideRef = useRef<HTMLDivElement | null>(null);

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
        hint: 'Open the next one in the queue’s own order.',
        run: () => openCandidate(next),
      },
      {
        id: 'review:previous',
        label: 'Previous candidate',
        group: 'This candidate',
        shortcut: 'p',
        hint: 'Go back to the one before it.',
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
      title={candidate ? `${candidate.field} · ${candidate.work}` : `Candidate ${candidateId}`}
      description="A staged proposal, beside the page it was read off. Nothing here is accepted state."
      toolbar={
        <>
          <StatusBadge status="candidate" size="md" />
          {item ? (
            <StatusBadge status={item.category} size="md">
              {item.category.replace('_', ' ')}
            </StatusBadge>
          ) : null}
        </>
      }
    >
      {state.loading ? <Loading what={`candidate ${candidateId}`} /> : null}
      {state.error ? <ErrorBox error={state.error} retry={state.reload} /> : null}
      {!state.loading && !state.error && !data ? <Empty>No candidate {candidateId}.</Empty> : null}

      {data && candidate ? (
        <PaneGroup direction="horizontal" defaultSizes={[50, 50]}>
          <Pane minSize={25}>
            <div className="rh-web-review-pane">
              <SourcePane
                artifact={candidate.artifact}
                context={sourceContext(candidate, item)}
                blocks={data.blocks}
                blockId={blockIdOf(candidate)}
              />
            </div>
          </Pane>
          <PaneHandle label="Resize the source pane" />
          <Pane minSize={25}>
            <div className="rh-web-review-pane rh-web-review-pane--end rh-web-stack">
              <Proposal candidate={candidate} item={item} />

              <Panel title="Decide">
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
                  {outcome ? (
                    <p className="rh-web-next__outcome" role="status">
                      Candidate {outcome}.
                    </p>
                  ) : null}
                  <div className="rh-web-next__moves">
                    {previous ? (
                      <Link to={href(`/review/${previous.candidate_id}`)}>
                        Previous: {previous.field} · {previous.work}
                      </Link>
                    ) : null}
                    {next ? (
                      <Link to={href(`/review/${next.candidate_id}`)}>
                        Next: {next.field} · {next.work}
                      </Link>
                    ) : (
                      <span className="rh-text-secondary">Last in the queue.</span>
                    )}
                  </div>
                  <Switch
                    label="Open the next candidate after a decision"
                    checked={autoAdvance}
                    onCheckedChange={(on) => {
                      setAutoAdvance(on);
                      writeAutoAdvance(on);
                    }}
                  />
                </div>
              </Panel>
            </div>
          </Pane>
        </PaneGroup>
      ) : null}
    </FullPageWorkspace>
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
      <EvidenceCard evidence={proposedEvidence(candidate, evidence, content, source)} />

      <Panel title="Proposal">
        <Fields>
          <Field label="Anchor">
            <StatusBadge status={candidate.anchor_status} /> block{' '}
            <code>{String(source.block ?? '?')}</code> · page {String(source.page ?? '?')}
          </Field>
          {item ? <Field label="Why it is here">{item.reasons.join('; ') || 'routine'}</Field> : null}
          <Field label="Work">
            <ObjectRef id={candidate.work} kind="work" to={href(`/corpus/${candidate.work}`)} />
          </Field>
        </Fields>
      </Panel>

      {content.numeric ? <NumericPanel numeric={content.numeric as JsonObject} /> : null}
      {content.negative_state ? (
        <Panel title="Absence">
          <Fields>
            <Field label="State">{String(content.negative_state)}</Field>
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
            <Field label="Verdict">{candidate.verdict ?? 'unverified'}</Field>
            <Field label="Verifier">{candidate.verifier ?? 'none'}</Field>
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
                    <td>
                      <code>{JSON.stringify(position.decision)}</code>
                    </td>
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
    field: candidate.field,
    evidenceType: String(evidence.evidence_type ?? ''),
    strength: String(evidence.strength ?? ''),
    origin: String(evidence.origin ?? ''),
    authority: 'candidate',
    anchor: {
      artifactId: candidate.artifact,
      stale: candidate.anchor_status !== 'valid',
      ...(typeof source.page === 'number' ? { page: source.page } : {}),
      ...(typeof source.block === 'string' ? { block: source.block } : {}),
    },
  };
}

function NumericPanel({ numeric }: { numeric: JsonObject }) {
  return (
    <Panel title="Number">
      <Fields>
        <Field label="Value">{String(numeric.raw ?? '')}</Field>
        <Field label="Metric">{String(numeric.metric ?? '—')}</Field>
        <Field label="Unit">{String(numeric.unit ?? '—')}</Field>
        <Field label="Dataset">{String(numeric.dataset ?? '—')}</Field>
        <Field label="Condition">{JSON.stringify(numeric.condition ?? {})}</Field>
        <Field label="Table">
          {String(numeric.source_table ?? '—')} · row {String(numeric.source_row ?? '—')} · column{' '}
          {String(numeric.source_column ?? '—')}
        </Field>
      </Fields>
    </Panel>
  );
}

/** The diff PRODUCT §25 asks for: what accepting each side would change. */
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
          <td>{String(change.field ?? '')}</td>
          <td>{String(change.from ?? '—')}</td>
          <td>{String(change.to ?? '—')}</td>
        </tr>
      ))}
    </DataTable>
  );
}

export type { ReviewItem };
