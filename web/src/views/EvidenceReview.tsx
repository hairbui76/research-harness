/**
 * Source beside decision (ROADMAP Task 11.3).
 *
 * Left: the page the span was read off, with the span drawn on it. Right: exactly what is
 * being proposed — the quoted text, the field it answers, its epistemic origin and type,
 * the number with the provenance a number needs, the verifier's verdict and rationale, the
 * competing candidates, and the positions in any conflict. Then the six review actions.
 *
 * Nothing on this screen is computed here. The category, the reasons, the verdict, and the
 * eligibility all come from the daemon; the page renders them.
 */
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { JsonObject, ReviewItem } from '../api/dto';
import { Empty, ErrorBox, Field, Loading, Panel, Tag } from '../components/Feedback';
import { ReviewActions } from '../components/ReviewActions';
import { SourcePane } from '../components/SourcePane';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

export function EvidenceReviewPage() {
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
  const context = item?.source_context ?? {
    page: (source.page as number | null) ?? null,
    section_path: (source.section_path as string[]) ?? [],
    block_text: String(content.exact_text ?? ''),
    exact_text: String(content.exact_text ?? ''),
    bbox: null,
    neighbors: [],
  };

  return (
    <div className="review-screen">
      <SourcePane
        artifact={candidate.artifact}
        context={context}
        blocks={blocks}
        blockId={(source.block as string) ?? null}
      />

      <div className="decision-pane">
        <Panel
          title={`${candidate.field} · ${candidate.work}`}
          action={item ? <Tag kind={item.category}>{item.category.replace('_', ' ')}</Tag> : null}
        >
          <blockquote className="exact-text">{String(content.exact_text ?? '')}</blockquote>
          <Field label="Field">{candidate.field}</Field>
          <Field label="Origin">{String(evidence.origin ?? '')}</Field>
          <Field label="Evidence type">{String(evidence.evidence_type ?? '')}</Field>
          <Field label="Strength">{String(evidence.strength ?? '')}</Field>
          <Field label="Anchor">
            {candidate.anchor_status} · block {String(source.block ?? '?')} · page{' '}
            {String(source.page ?? '?')}
          </Field>
          {item ? (
            <Field label="Why it is here">{item.reasons.join('; ') || 'routine'}</Field>
          ) : null}
        </Panel>

        {content.numeric ? <NumericPanel numeric={content.numeric as JsonObject} /> : null}
        {content.negative_state ? (
          <Panel title="Absence">
            <Field label="State">{String(content.negative_state)}</Field>
            <p className="muted">
              Absence is a state, not a finding: only an audited decision turns `not_reported`
              into `absent` (Product 11).
            </p>
          </Panel>
        ) : null}

        <Panel title="Verification">
          {candidate.verification ? (
            <>
              <Field label="Verdict">{candidate.verdict ?? 'unverified'}</Field>
              <Field label="Verifier">{candidate.verifier ?? 'none'}</Field>
              <Field label="Rationale">
                {String((candidate.verification as JsonObject).rationale ?? '')}
              </Field>
              <Field label="Quoted support">
                {String((candidate.verification as JsonObject).quoted_support ?? '—')}
              </Field>
            </>
          ) : (
            <Empty>Not verified yet — accepting it makes you its verifier.</Empty>
          )}
        </Panel>

        {item && item.competing.length > 0 ? (
          <Panel title="Competing candidates">
            <ul>
              {item.competing.map((id) => (
                <li key={id}>
                  <Link to={`/review/${id}`}>{id}</Link>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {item && item.conflicts.length > 0 ? (
          <Panel title="Conflict">
            {item.conflicts.map((conflict) => (
              <div key={conflict.conflict_id} className="conflict">
                <p>{conflict.summary}</p>
                <table>
                  <thead>
                    <tr>
                      <th>Position</th>
                      <th>Decision</th>
                      <th>Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conflict.positions.map((position) => (
                      <tr key={position.label}>
                        <td>{position.label}</td>
                        <td>
                          <code>{JSON.stringify(position.decision)}</code>
                        </td>
                        <td>{position.rationale ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <ProposedChanges changes={conflict.proposed_changes as JsonObject[]} />
              </div>
            ))}
          </Panel>
        ) : null}

        <Panel title="Decide">
          {outcome ? <p className="notice">Candidate {outcome}.</p> : null}
          <ReviewActions
            candidate={candidate}
            hasOpenConflict={(item?.conflicts.length ?? 0) > 0}
            onReviewed={(what) => setOutcome(what)}
          />
        </Panel>
      </div>
    </div>
  );
}

function NumericPanel({ numeric }: { numeric: JsonObject }) {
  return (
    <Panel title="Number">
      <Field label="Value">{String(numeric.raw ?? '')}</Field>
      <Field label="Metric">{String(numeric.metric ?? '—')}</Field>
      <Field label="Unit">{String(numeric.unit ?? '—')}</Field>
      <Field label="Dataset">{String(numeric.dataset ?? '—')}</Field>
      <Field label="Condition">{JSON.stringify(numeric.condition ?? {})}</Field>
      <Field label="Table">
        {String(numeric.source_table ?? '—')} · row {String(numeric.source_row ?? '—')} · column{' '}
        {String(numeric.source_column ?? '—')}
      </Field>
    </Panel>
  );
}

/** The diff Product 25 asks for: what accepting each side would change. */
export function ProposedChanges({ changes }: { changes: JsonObject[] }) {
  if (!changes.length) return null;
  return (
    <table className="diff">
      <thead>
        <tr>
          <th>Position</th>
          <th>Field</th>
          <th>From</th>
          <th>To</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change, index) => (
          <tr key={index}>
            <td>{String(change.position ?? '')}</td>
            <td>{String(change.field ?? '')}</td>
            <td>{String(change.from ?? '—')}</td>
            <td>{String(change.to ?? '—')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export type { ReviewItem };
