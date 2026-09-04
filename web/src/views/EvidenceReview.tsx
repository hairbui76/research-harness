/**
 * Source beside decision (ROADMAP Task 11.3).
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
 * Nothing on this screen is computed here. The category, the reasons, the verdict, and the
 * eligibility all come from the daemon; the page renders them.
 */
import { useState } from 'react';
import {
  EvidenceCard,
  FullPageWorkspace,
  Pane,
  PaneGroup,
  PaneHandle,
} from '@research-harness/design';
import type { EvidenceModel } from '@research-harness/design';
import { useParams } from 'react-router-dom';
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
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';

export function EvidenceReviewPage() {
  const { href } = useProjectPaths();
  const { candidateId = '' } = useParams();
  const { client } = useSession();
  const [outcome, setOutcome] = useState<string | null>(null);

  const state = useAsync(
    async () => {
      const [candidate, inbox] = await Promise.all([
        client.candidate(candidateId),
        client.reviewInbox(),
      ]);
      const item = inbox.items.find((entry) => entry.candidate_id === candidateId) ?? null;
      const blocks = await client.blocks(candidate.artifact);
      return { candidate, item, blocks };
    },
    [client, candidateId],
  );

  if (state.loading) return <Loading what={`candidate ${candidateId}`} />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data) return <Empty>No candidate {candidateId}.</Empty>;

  const { candidate, item, blocks } = state.data;
  const evidence = candidate.evidence as JsonObject;
  const source = (evidence.source ?? {}) as JsonObject;
  const content = (evidence.content ?? {}) as JsonObject;
  const blockId = (source.block as string) ?? null;
  const context = item?.source_context ?? {
    page: (source.page as number | null) ?? null,
    section_path: (source.section_path as string[]) ?? [],
    block_text: String(content.exact_text ?? ''),
    exact_text: String(content.exact_text ?? ''),
    bbox: null,
    neighbors: [],
  };

  return (
    <FullPageWorkspace
      className="rh-web-review"
      title={`${candidate.field} · ${candidate.work}`}
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
      <PaneGroup direction="horizontal" defaultSizes={[50, 50]}>
        <Pane minSize={25}>
          <div className="rh-web-review-pane">
            <SourcePane
              artifact={candidate.artifact}
              context={context}
              blocks={blocks}
              blockId={blockId}
            />
          </div>
        </Pane>
        <PaneHandle label="Resize the source pane" />
        <Pane minSize={25}>
          <div className="rh-web-review-pane rh-web-review-pane--end rh-web-stack">
            <EvidenceCard evidence={proposedEvidence(candidate, evidence, content, source)} />

            <Panel title="Proposal">
              <Fields>
                <Field label="Anchor">
                  <StatusBadge status={candidate.anchor_status} /> block{' '}
                  <code>{String(source.block ?? '?')}</code> · page {String(source.page ?? '?')}
                </Field>
                {item ? (
                  <Field label="Why it is here">{item.reasons.join('; ') || 'routine'}</Field>
                ) : null}
                <Field label="Work">
                  <ObjectRef
                    id={candidate.work}
                    kind="work"
                    to={href(`/corpus/${candidate.work}`)}
                  />
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
                  Absence is a state, not a finding: only an audited decision turns
                  `not_reported` into `absent` (PRODUCT §11).
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
                      <ObjectRef
                        id={id}
                        kind="evidence"
                        to={href(`/review/${id}`)}
                        authority="candidate"
                      />
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

            <Panel title="Decide">
              {outcome ? <p className="rh-text-secondary">Candidate {outcome}.</p> : null}
              <ReviewActions
                candidate={candidate}
                hasOpenConflict={(item?.conflicts.length ?? 0) > 0}
                onReviewed={(what) => setOutcome(what)}
              />
            </Panel>
          </div>
        </Pane>
      </PaneGroup>
    </FullPageWorkspace>
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
