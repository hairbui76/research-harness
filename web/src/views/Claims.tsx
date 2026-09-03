/**
 * The Claim explorer (ROADMAP Task 11.4).
 *
 * The list shows what each claim asks for and what the audit allows — the two numbers that
 * matter, side by side, because the failure this product is built against is a claim that
 * quietly says more than its evidence supports (Product 10.2, 42 G).
 *
 * The detail page adds the evidence behind it (each link opening the span it was accepted
 * from), the coverage the audit recorded, the maximum defensible wording, the decision
 * history, and what has gone stale under it. Audit and Override are capability calls; the
 * ceiling they produce is the daemon's, never this page's.
 */
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { ClaimSummary, JsonObject } from '../api/dto';
import { Empty, ErrorBox, Field, Loading, Panel, Tag } from '../components/Feedback';
import { useSession } from '../app/session';
import { useAsync } from '../app/useAsync';

const CLAIM_STATUSES = [
  'unverified',
  'supported',
  'qualified',
  'contested',
  'unsupported',
] as const;

const SCOPES = [
  'individual',
  'observed_subset',
  'corpus_pattern',
  'field_generalization',
  'universal_or_absence',
] as const;

export function ClaimsPage() {
  const { client } = useSession();
  // `claim.list` rather than the whole index: this view needs one list, and the capability
  // is the surface every host shares (it returns the same `ClaimSummary` objects).
  const state = useAsync(() => client.claims(), [client]);

  if (state.loading) return <Loading what="the claims" />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data || state.data.length === 0) return <Empty>No claims registered.</Empty>;

  return (
    <div className="claims">
      <h1>Claims</h1>
      <Panel title={`${state.data.length} registered`}>
        <table>
          <thead>
            <tr>
              <th>Claim</th>
              <th>Status</th>
              <th>Requested</th>
              <th>Allowed</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {state.data.map((claim: ClaimSummary) => (
              <tr key={claim.id}>
                <td>
                  <Link to={`/claims/${claim.id}`}>{claim.id}</Link>
                  <div className="muted">{claim.statement}</div>
                </td>
                <td>
                  <Tag kind={claim.status}>{claim.status}</Tag>
                  {claim.stale === 'stale' ? <Tag kind="stale">stale</Tag> : null}
                </td>
                <td>{claim.requested_strength}</td>
                <td>{claim.allowed_strength}</td>
                <td className="muted">
                  {claim.supporting} supporting · {claim.qualifying} qualifying ·{' '}
                  {claim.contradicting} contradicting
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

export function ClaimDetailPage() {
  const { claimId = '' } = useParams();
  const { client, canMutate, mutationBlockedReason, refresh, overview } = useSession();
  const actor = overview?.actor ?? null;
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const state = useAsync(
    async () => {
      const [object, support, decisions, anchors] = await Promise.all([
        client.object(claimId),
        client.claimSupport(claimId),
        // `decision.list` filters server-side; `anchor.list` has no claim filter, so the
        // one narrowing this view does itself is a comparison, not a judgement.
        client.decisions(claimId),
        client.anchors(),
      ]);
      return { object, support, decisions, anchors };
    },
    [client, claimId],
  );

  if (state.loading) return <Loading what={`claim ${claimId}`} />;
  if (state.error) return <ErrorBox error={state.error} retry={state.reload} />;
  if (!state.data) return <Empty>No claim {claimId}.</Empty>;

  const claim = state.data.object.object as JsonObject;
  const assessment = (claim.assessment ?? {}) as JsonObject;
  const coverage = (claim.coverage ?? {}) as JsonObject;
  const support = state.data.support;
  const decisions = state.data.decisions;
  const anchors = state.data.anchors.filter((anchor) => anchor.claim === claimId);

  async function run(what: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setNotice(what);
      state.reload();
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="claim-detail">
      <h1>{claimId}</h1>
      <p className="statement">{String(claim.statement ?? '')}</p>

      <Panel title="Scope">
        <Field label="Status">{String(assessment.status ?? '')}</Field>
        <Field label="Requested strength">{String(assessment.requested_strength ?? '')}</Field>
        <Field label="Allowed strength">{String(assessment.allowed_strength ?? '')}</Field>
        <Field label="Maximum defensible wording">
          {String(assessment.maximum_defensible_wording ?? '— not audited yet')}
        </Field>
        {/*
          The funnel `claim.update_coverage` recorded and `claim.audit` reads, rendered as
          it was written. Nothing here is recomputed: coverage is what separates "we found
          no work that…" from "no work exists" (Product 18), and only a recorded search run
          can say which one this is.
        */}
        <Field label="Coverage">
          {String(coverage.examined_works ?? 0)} of {String(coverage.relevant_works ?? 0)} relevant
          works examined
          {coverage.unresolved_works ? ` · ${String(coverage.unresolved_works)} unresolved` : ''}
          {` · overturn risk ${String(coverage.overturn_risk ?? 'unknown')}`}
        </Field>
        <Field label="Search runs">
          {(coverage.search_runs as string[] | undefined)?.join(', ') || '— none recorded'}
          {coverage.cutoff ? ` · up to ${String(coverage.cutoff)}` : ''}
        </Field>
        <Field label="Freshness">{String(claim.stale ?? 'fresh')}</Field>
      </Panel>

      <Panel title="Evidence">
        <RelationList title="Supporting" links={support.supporting} />
        <RelationList title="Qualifying" links={support.qualifying} />
        <RelationList title="Contradicting" links={support.contradicting} />
        {support.other.length ? <RelationList title="Context" links={support.other} /> : null}
      </Panel>

      <Panel title="Decision history">
        {decisions.length ? (
          <ul>
            {decisions.map((decision) => (
              <li key={decision.id}>
                <strong>{decision.id}</strong> · {decision.type} · {decision.status}
                <div className="muted">{decision.rationale}</div>
                {decision.auditor_recommendation ? (
                  <div className="muted">
                    auditor said {decision.auditor_recommendation}; researcher chose{' '}
                    {decision.researcher_selected}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No decision has been recorded against this claim.</Empty>
        )}
      </Panel>

      <Panel title="Manuscript">
        {anchors.length ? (
          <ul>
            {anchors.map((anchor) => (
              <li key={`${anchor.file}:${anchor.line_start}`}>
                <code>
                  {anchor.file}:{anchor.line_start}
                </code>{' '}
                <Tag kind={anchor.status}>{anchor.status}</Tag>
                <div className="muted">{anchor.sentence}</div>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No manuscript sentence rests on this claim.</Empty>
        )}
      </Panel>

      <Panel title="Act">
        {notice ? <p className="notice">{notice}</p> : null}
        {!canMutate ? <p className="muted">{mutationBlockedReason}</p> : null}
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        <AuditForm
          disabled={!canMutate || busy}
          current={{
            status: String(assessment.status ?? 'unverified'),
            allowed: String(assessment.allowed_strength ?? 'individual'),
            wording: String(assessment.maximum_defensible_wording ?? ''),
          }}
          onSubmit={(audit) =>
            run('Audit recorded.', () => client.auditClaim(claimId, audit))
          }
        />
        <OverrideForm
          disabled={!canMutate || busy}
          recommendation={String(assessment.allowed_strength ?? 'individual')}
          onSubmit={(override) =>
            run('Override accepted and applied.', () =>
              client.overrideClaimStrength(claimId, { ...override, actor: actor ?? undefined }),
            )
          }
        />
        <RelateForm
          disabled={!canMutate || busy}
          onSubmit={(evidence, relation) =>
            run('Evidence related.', () => client.relateEvidence(claimId, evidence, relation))
          }
        />
      </Panel>
    </div>
  );
}

function RelationList({
  title,
  links,
}: {
  title: string;
  links: { evidence: string; exact_text: string | null; work: string | null; note: string | null }[];
}) {
  return (
    <div className="relations">
      <h3>
        {title} ({links.length})
      </h3>
      {links.length === 0 ? (
        <Empty>None.</Empty>
      ) : (
        <ul>
          {links.map((link) => (
            <li key={`${title}:${link.evidence}`}>
              <Link to={`/evidence/${link.evidence}`}>{link.evidence}</Link>
              {link.work ? <span className="muted"> · {link.work}</span> : null}
              {link.exact_text ? <blockquote>{link.exact_text}</blockquote> : null}
              {link.note ? <p className="muted">{link.note}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AuditForm({
  disabled,
  current,
  onSubmit,
}: {
  disabled: boolean;
  current: { status: string; allowed: string; wording: string };
  onSubmit: (audit: { status: string; allowedStrength: string; wording?: string }) => void;
}) {
  const [status, setStatus] = useState(current.status);
  const [allowed, setAllowed] = useState(current.allowed);
  const [wording, setWording] = useState(current.wording);
  return (
    <form
      className="prompt"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ status, allowedStrength: allowed, wording: wording || undefined });
      }}
    >
      <h3>Audit</h3>
      <label htmlFor="audit-status">Status the evidence supports</label>
      <select id="audit-status" value={status} onChange={(e) => setStatus(e.target.value)}>
        {CLAIM_STATUSES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <label htmlFor="audit-allowed">Allowed strength</label>
      <select id="audit-allowed" value={allowed} onChange={(e) => setAllowed(e.target.value)}>
        {SCOPES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <label htmlFor="audit-wording">Maximum defensible wording</label>
      <input
        id="audit-wording"
        value={wording}
        onChange={(e) => setWording(e.target.value)}
        placeholder="what this claim may say, at most"
      />
      <button type="submit" disabled={disabled}>
        Record the audit
      </button>
    </form>
  );
}

function OverrideForm({
  disabled,
  recommendation,
  onSubmit,
}: {
  disabled: boolean;
  recommendation: string;
  onSubmit: (override: {
    selected: string;
    auditorRecommendation: string;
    rationale: string;
  }) => void;
}) {
  const [selected, setSelected] = useState(recommendation);
  const [rationale, setRationale] = useState('');
  return (
    <form
      className="prompt"
      onSubmit={(event) => {
        event.preventDefault();
        if (!rationale.trim()) return;
        onSubmit({ selected, auditorRecommendation: recommendation, rationale });
      }}
    >
      <h3>Override the auditor</h3>
      <p className="muted">
        An override is a Decision before it is a claim edit: the recommendation it overrules,
        the scope you chose, and your reason are all recorded (Product 38).
      </p>
      <label htmlFor="override-scope">Scope you are choosing instead of {recommendation}</label>
      <select id="override-scope" value={selected} onChange={(e) => setSelected(e.target.value)}>
        {SCOPES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <label htmlFor="override-rationale">Rationale</label>
      <textarea
        id="override-rationale"
        rows={3}
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
      />
      <button type="submit" disabled={disabled || !rationale.trim()}>
        Accept the override
      </button>
    </form>
  );
}

function RelateForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (evidence: string, relation: string) => void;
}) {
  const [evidence, setEvidence] = useState('');
  const [relation, setRelation] = useState('supports');
  return (
    <form
      className="prompt"
      onSubmit={(event) => {
        event.preventDefault();
        if (!evidence.trim()) return;
        onSubmit(evidence.trim(), relation);
      }}
    >
      <h3>Relate evidence</h3>
      <label htmlFor="relate-evidence">Evidence id</label>
      <input
        id="relate-evidence"
        value={evidence}
        onChange={(e) => setEvidence(e.target.value)}
        placeholder="E0001"
      />
      <label htmlFor="relate-relation">Relation</label>
      <select id="relate-relation" value={relation} onChange={(e) => setRelation(e.target.value)}>
        {[
          'supports',
          'qualifies',
          'contradicts',
          'contextualizes',
          'exemplifies',
          'incomparable_under_current_evidence',
        ].map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
      <button type="submit" disabled={disabled || !evidence.trim()}>
        Relate
      </button>
    </form>
  );
}
