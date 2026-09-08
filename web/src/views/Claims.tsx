/**
 * The Claim explorer (ROADMAP Task 11.4).
 *
 * The list opens with the claims whose evidence cannot carry them, because the failure this
 * product is built against is a claim that quietly says more than its evidence supports
 * (PRODUCT §10.2, §42 G) — and a table sorted by id says nothing about which of its rows is
 * that claim. Which ones they are, and in what order, is `claim.list`'s own grouping; this
 * page renders it and never rebuilds it (principle P10).
 *
 * The table stays underneath, because comparing what several claims ask for against what
 * their evidence allows is exactly the reading a table is for: five shared columns, one row
 * per claim, the eye running down two of them. What the page holds is said there, in the
 * sentence above the table, after the work.
 *
 * The detail page adds the evidence behind it (each relation drawn as the Claim → Evidence
 * → Work chain it is, and each link opening the span it was accepted from), the coverage
 * the audit recorded, the maximum defensible wording, the decision history, and what has
 * gone stale under it. Audit and Override are capability calls; the ceiling they produce is
 * the daemon's, never this page's.
 *
 * Both screens mount their frame before the read resolves: the heading, the toolbar and the
 * page's shape survive loading, a refusal, and a claim that is not there.
 */
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  ClaimCard,
  Combobox,
  EntityRef,
  FullPageWorkspace,
  Input,
  ProvenancePath,
  Select,
  Textarea,
  researchLabel,
  useToast,
} from '@research-harness/design';
import type { ClaimModel, ComboboxItem } from '@research-harness/design';
import type {
  AnchorSummary,
  ClaimGroup,
  ClaimSummary,
  ClaimSupport,
  DecisionSummary,
  EvidenceSummary,
  JsonObject,
  ObjectView,
} from '../api/dto';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  Panel,
  StatusBadge,
  authorityOf,
  fieldLabel,
} from '../components/Feedback';
import { useSession } from '../app/session';
import { useProjectPaths } from '../app/projectPaths';
import { useAsync } from '../app/useAsync';
import './claims.css';

/** The claim statuses an audit may record, in the order the product lists them. */
const CLAIM_STATUSES = [
  'unverified',
  'supported',
  'qualified',
  'contested',
  'unsupported',
] as const;

/** The scope ladder, L0 to L4. The rung a claim may stand on, never how sure anyone is. */
const SCOPES = [
  'individual',
  'observed_subset',
  'corpus_pattern',
  'field_generalization',
  'universal_or_absence',
] as const;

/** How one evidence object may be related to a claim. */
const RELATIONS = [
  'supports',
  'qualifies',
  'contradicts',
  'contextualizes',
  'exemplifies',
  'incomparable_under_current_evidence',
] as const;

/** The rung this claim stands on, as the ladder writes it. */
function scopeOf(scope: JsonObject, assessment: JsonObject): string {
  const level = scope.level ?? assessment.allowed_strength;
  return level === undefined || level === null
    ? '— not recorded'
    : researchLabel('claimScope', String(level));
}

export function ClaimsPage() {
  const { client } = useSession();
  const { href } = useProjectPaths();
  // `claim.list` rather than the whole index: this view needs one list, and the capability
  // is the surface every host shares (it returns the same `ClaimSummary` objects, plus the
  // grouping and the sentence the daemon composed around them).
  const state = useAsync(() => client.claimList(), [client]);

  const list = state.data;
  const claims = list?.claims ?? [];
  // `?? []` because a daemon build older than this grouping still answers `claim.list`,
  // and a cockpit that crashed on a field it did not get would be worse than one that
  // shows the table and says nothing about concerns it was never told about.
  const groups = list?.groups ?? [];
  const settled = !state.loading && !state.error;
  return (
    <FullPageWorkspace
      busy={state.loading}
      title="Claims"
      description={
        // The daemon's own sentence about what needs work here. Until it arrives, the part
        // of it that is true without the data.
        settled && list?.summary
          ? list.summary
          : 'What each claim asks for, beside what its evidence allows.'
      }
    >
      {state.loading ? (
        <Loading what="the claims" shape="table" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : claims.length === 0 ? (
        <Empty
          description="A claim is what this project asserts, registered so that the strength it asks for can be held against the strength its evidence allows. One begins as a candidate promoted from a conversation."
          action={<Link to={href('/')}>Open the conversation to promote a claim</Link>}
        >
          No claims registered yet
        </Empty>
      ) : (
        <div className="rh-web-stack">
          <Panel title="Claims their evidence cannot carry">
            {groups.length > 0 ? (
              <ul className="rh-web-list rh-web-claims">
                {groups.map((group) => (
                  <ConcernGroup key={group.kind} group={group} claims={claims} />
                ))}
              </ul>
            ) : (
              <Empty
                flat
                description="A claim lands here when it asks for a rung of the scope ladder its evidence does not reach, when the evidence points both ways, when nothing carries it, or when something it rests on has changed. An audit is what moves a claim off this list, and new evidence is what makes an audit worth running."
                action={<Link to={href('/review')}>Open the review inbox</Link>}
              >
                Every registered claim stands where its evidence puts it
              </Empty>
            )}
          </Panel>

          <Panel title="Every claim">
            <p className="rh-text-secondary rh-web-claims__holdings">
              This project has registered {counted(claims.length, 'claim')}: what each asks
              for, beside what its evidence allows.
            </p>
            <DataTable
              label="Registered claims"
              head={
                <tr>
                  <th scope="col">Claim</th>
                  <th scope="col">Status</th>
                  <th scope="col">Requested</th>
                  <th scope="col">Allowed</th>
                  <th scope="col">Evidence</th>
                </tr>
              }
            >
              {claims.map((claim: ClaimSummary) => (
                <tr key={claim.id}>
                  {/*
                    The assertion leads. This cell used to open with the id chip and its
                    authority badge and put the sentence under them in secondary ink, so the
                    machine identity outranked the thing the claim actually says (design
                    critique, minor). The id still travels with it — a researcher copies and
                    types it — but it follows the sentence, and it is the identity rather
                    than a second link to the page the sentence already opens.
                  */}
                  <th scope="row" className="rh-web-claims__row">
                    <Link to={href(`/claims/${claim.id}`)}>{claim.statement}</Link>
                    <EntityRef
                      size="sm"
                      describe={false}
                      entity={{
                        id: claim.id,
                        kind: 'claim',
                        resolution: 'resolved',
                        authority: authorityOf(claim.status, claim.stale === 'stale'),
                      }}
                    />
                  </th>
                  <td>
                    {/* A row, so the sentence a badge opens takes a line of its own inside
                        the cell instead of widening the column — and a column belongs to
                        every claim on the page, so one badge explaining itself would
                        otherwise move all of them. */}
                    <span className="rh-web-row">
                      <StatusBadge status={claim.status} vocabulary="claimStatus" describe />
                      {claim.stale === 'stale' ? <StatusBadge status="stale" describe /> : null}
                    </span>
                  </td>
                  <td>{researchLabel('claimScope', claim.requested_strength)}</td>
                  <td>{researchLabel('claimScope', claim.allowed_strength)}</td>
                  <td className="rh-text-secondary">
                    {claim.supporting} supporting · {claim.qualifying} qualifying ·{' '}
                    {claim.contradicting} contradicting
                  </td>
                </tr>
              ))}
            </DataTable>
          </Panel>
        </div>
      )}
    </FullPageWorkspace>
  );
}

/** `1 claim` / `4 claims` — a count is only ever read inside the thing it counts. */
function counted(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/**
 * One concern the daemon grouped claims under, and the claims in it.
 *
 * The line naming the group is the daemon's own sentence, count and all; the claims under
 * it link to themselves, because a claim is the one object on this page that has a screen.
 * A claim whose id the list does not carry is skipped rather than drawn as a blank row: the
 * group and the rows come from the same read, so that can only mean a filtered read.
 */
function ConcernGroup({ group, claims }: { group: ClaimGroup; claims: ClaimSummary[] }) {
  const { href } = useProjectPaths();
  const byId = new Map(claims.map((claim) => [claim.id, claim]));
  return (
    <li>
      <p className="rh-web-claims__concern">{group.label}</p>
      <ul className="rh-web-list rh-web-list--tight rh-web-claims__items">
        {group.claims.map((id) => {
          const claim = byId.get(id);
          if (claim === undefined) return null;
          return (
            <li key={`${group.kind}:${id}`}>
              <p className="rh-web-row">
                <Link to={href(`/claims/${id}`)}>{claim.statement}</Link>
                <StatusBadge status={claim.status} vocabulary="claimStatus" describe />
                {claim.stale === 'stale' ? (
                  <StatusBadge status="stale" vocabulary="staleState" describe />
                ) : null}
              </p>
              <p className="rh-text-secondary">
                Asks for {researchLabel('claimScope', claim.requested_strength)}; its evidence
                allows {researchLabel('claimScope', claim.allowed_strength)}.
              </p>
            </li>
          );
        })}
      </ul>
    </li>
  );
}

export function ClaimDetailPage() {
  const { claimId = '' } = useParams();
  const { client } = useSession();
  const { href } = useProjectPaths();

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

  const loaded = state.data;
  const claim = (loaded?.object.object ?? {}) as JsonObject;
  const assessment = (claim.assessment ?? {}) as JsonObject;

  return (
    <FullPageWorkspace
      busy={state.loading}
      title={claimId}
      description={
        loaded
          ? String(claim.statement ?? '')
          : 'One claim, the evidence behind it, and the strength that evidence allows.'
      }
      {...(loaded
        ? {
            toolbar: (
              <StatusBadge
                status={assessment.status ? String(assessment.status) : 'unverified'}
                vocabulary="claimStatus"
                size="md"
                describe
              />
            ),
          }
        : {})}
    >
      {state.loading ? (
        <Loading what={`claim ${claimId}`} shape="cards" />
      ) : state.error ? (
        <ErrorBox error={state.error} retry={state.reload} />
      ) : !loaded ? (
        <Empty
          description="No claim is registered under that id in this project. A claim that is still a candidate has no id here until it is accepted."
          action={<Link to={href('/claims')}>Back to the claims</Link>}
        >
          {`No claim ${claimId} in this project`}
        </Empty>
      ) : (
        <ClaimDetail claimId={claimId} data={loaded} reload={state.reload} />
      )}
    </FullPageWorkspace>
  );
}

/** What the claim screen's four reads answer with, together. */
interface ClaimDetailData {
  object: ObjectView;
  support: ClaimSupport;
  decisions: DecisionSummary[];
  anchors: AnchorSummary[];
}

/**
 * The claim itself, mounted only once its four reads have all answered.
 *
 * It owns the acting state — which capability call is in flight, and what the last one
 * said — because that state is meaningless without the claim it acts on.
 */
function ClaimDetail({
  claimId,
  data,
  reload,
}: {
  claimId: string;
  data: ClaimDetailData;
  reload: () => void;
}) {
  const { client, canMutate, mutationBlockedReason, refresh, overview } = useSession();
  const { href } = useProjectPaths();
  const { toast } = useToast();
  const actor = overview?.actor ?? null;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const claim = data.object.object as JsonObject;
  const assessment = (claim.assessment ?? {}) as JsonObject;
  const coverage = (claim.coverage ?? {}) as JsonObject;
  const scope = (claim.scope ?? {}) as JsonObject;
  const support = data.support;
  const decisions = data.decisions;
  const anchors = data.anchors.filter((anchor) => anchor.claim === claimId);
  const stale = String(claim.stale ?? 'fresh') === 'stale';

  const model: ClaimModel = {
    id: claimId,
    text: String(claim.statement ?? ''),
    // The card prints these three verbatim, so it is handed the product's word for each.
    claimType: claim.type ? researchLabel('claimType', String(claim.type)) : '— not recorded',
    scope: scopeOf(scope, assessment),
    status: researchLabel('claimStatus', String(assessment.status ?? 'unverified')),
    authority: authorityOf(String(assessment.status ?? 'unverified'), stale),
    stale,
    support: {
      supports: support.supporting.length,
      contradicts: support.contradicting.length,
      qualifies: support.qualifying.length,
    },
    ...(assessment.maximum_defensible_wording
      ? { wordingCeiling: String(assessment.maximum_defensible_wording) }
      : {}),
  };

  async function run(what: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      toast({ tone: 'success', title: what });
      reload();
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rh-web-stack">
      <ClaimCard claim={model} />

      <Panel title="Scope">
        <Fields>
          {/* The status is on the badge in the page header; repeating it here would be the
              same fact twice. What this panel adds is the pair the product exists to keep
              honest: what the claim asks for, beside what its evidence allows. */}
          <Field label="Requested strength">
            {researchLabel('claimScope', String(assessment.requested_strength ?? ''))}
          </Field>
          <Field label="Allowed strength">
            {researchLabel('claimScope', String(assessment.allowed_strength ?? ''))}
          </Field>
          {/*
            The funnel `claim.update_coverage` recorded and `claim.audit` reads, rendered as
            it was written. Nothing here is recomputed: coverage is what separates "we found
            no work that…" from "no work exists" (PRODUCT §18), and only a recorded search
            run can say which one this is.
          */}
          <Field label="Coverage">
            {String(coverage.examined_works ?? 0)} of {String(coverage.relevant_works ?? 0)}{' '}
            relevant works examined
            {coverage.unresolved_works ? ` · ${String(coverage.unresolved_works)} unresolved` : ''}
            {` · overturn risk ${researchLabel('overturnRisk', String(coverage.overturn_risk ?? 'unknown')).toLowerCase()}`}
          </Field>
          <Field label="Search runs">
            {(coverage.search_runs as string[] | undefined)?.join(', ') || '— none recorded'}
            {coverage.cutoff ? ` · up to ${String(coverage.cutoff)}` : ''}
          </Field>
          <Field label="Freshness">
            {researchLabel('staleState', String(claim.stale ?? 'fresh'))}
          </Field>
        </Fields>
      </Panel>

      <Panel title="Evidence">
        <RelationList claimId={claimId} title="Supporting" links={support.supporting} />
        <RelationList claimId={claimId} title="Qualifying" links={support.qualifying} />
        <RelationList claimId={claimId} title="Contradicting" links={support.contradicting} />
        {support.other.length ? (
          <RelationList claimId={claimId} title="Context" links={support.other} />
        ) : null}
      </Panel>

      <Panel title="Decision history">
        {decisions.length ? (
          <ul className="rh-web-list rh-web-list--rules">
            {decisions.map((decision) => (
              <li key={decision.id}>
                <p className="rh-web-row">
                  <code>{decision.id}</code>
                  <StatusBadge status={decision.status} vocabulary="decisionStatus" />
                  <span className="rh-text-secondary">
                    {researchLabel('decisionType', decision.type)}
                  </span>
                </p>
                <p className="rh-text-secondary">{decision.rationale}</p>
                {decision.auditor_recommendation ? (
                  <p className="rh-text-secondary">
                    The auditor recommended{' '}
                    {researchLabel('claimScope', decision.auditor_recommendation)}; the
                    researcher chose{' '}
                    {researchLabel('claimScope', String(decision.researcher_selected ?? ''))}.
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            flat
            description="A Decision records who chose what, and why — an audit, an override, an acceptance. Recording one is the Act panel below."
          >
            No decision has been recorded against this claim
          </Empty>
        )}
      </Panel>

      <Panel title="Manuscript">
        {anchors.length ? (
          <ul className="rh-web-list rh-web-list--rules">
            {anchors.map((anchor) => (
              <li key={`${anchor.file}:${anchor.line_start}`}>
                <p className="rh-web-row">
                  <code>
                    {anchor.file}:{anchor.line_start}
                  </code>
                  <StatusBadge status={anchor.status} vocabulary="anchorStatus" />
                  {anchor.stale === 'stale' ? <StatusBadge status="stale" /> : null}
                </p>
                <p className="rh-text-secondary">{anchor.sentence}</p>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            flat
            description="Nothing written so far cites this claim. A manuscript sentence is bound to a claim in the manuscript itself, and the binding is what the audit later checks."
            action={<Link to={href('/manuscript')}>Open the manuscript</Link>}
          >
            No manuscript sentence rests on this claim
          </Empty>
        )}
      </Panel>

      <Panel title="Act">
        {!canMutate ? <p className="rh-text-secondary">{mutationBlockedReason}</p> : null}
        {error ? <ErrorBox error={error} /> : null}
        <AuditForm
          disabled={!canMutate || busy}
          current={{
            status: String(assessment.status ?? 'unverified'),
            allowed: String(assessment.allowed_strength ?? 'individual'),
            wording: String(assessment.maximum_defensible_wording ?? ''),
          }}
          onSubmit={(audit) => run('Audit recorded.', () => client.auditClaim(claimId, audit))}
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

/**
 * One group of claim–evidence edges, each drawn as the chain it is.
 *
 * `ProvenancePath` is the Claim → Evidence → Work navigation of DS spec §5.2: the edge
 * label between two steps is the daemon's own relation word, and every step opens the
 * object it names. The quote under it is the span the evidence was accepted from.
 */
function RelationList({
  claimId,
  title,
  links,
}: {
  claimId: string;
  title: string;
  links: {
    evidence: string;
    relation?: string;
    exact_text: string | null;
    work: string | null;
    note: string | null;
    status?: string | null;
  }[];
}) {
  const navigate = useNavigate();
  const { href } = useProjectPaths();
  return (
    <section className="rh-web-stack rh-web-stack--tight">
      <h3 className="rh-text-h4">
        {title} ({links.length})
      </h3>
      {links.length === 0 ? (
        // The heading above already carries the count, so this says the one thing it does
        // not: which relation is missing, in the daemon's own word for it.
        <p className="rh-text-secondary">{`No evidence is related to this claim as ${title.toLowerCase()}.`}</p>
      ) : (
        <ul className="rh-web-list rh-web-list--tight">
          {links.map((link) => (
            <li key={`${title}:${link.evidence}`} className="rh-web-stack rh-web-stack--tight">
              <ProvenancePath
                label={`${claimId} ${relationWord(link.relation)} ${link.evidence}`}
                onOpen={(entity) => {
                  if (entity.href) navigate(entity.href);
                }}
                path={{
                  steps: [
                    {
                      ref: {
                        id: claimId,
                        kind: 'claim',
                        resolution: 'resolved',
                        href: href(`/claims/${claimId}`),
                      },
                    },
                    {
                      relation: relationWord(link.relation),
                      // No authority badge on the chip: the relation list already sits
                      // under "Accepted evidence", and a badge inside the link would put
                      // the word into the link's own name.
                      ref: {
                        id: link.evidence,
                        kind: 'evidence',
                        resolution: link.status === null ? 'unresolved' : 'resolved',
                        href: href(`/evidence/${link.evidence}`),
                      },
                    },
                    ...(link.work
                      ? [
                          {
                            relation: 'read from',
                            ref: {
                              id: link.work,
                              kind: 'work' as const,
                              resolution: 'resolved' as const,
                              href: href(`/corpus/${link.work}`),
                            },
                          },
                        ]
                      : []),
                  ],
                }}
              />
              {link.exact_text ? (
                <blockquote className="rh-web-quote">{link.exact_text}</blockquote>
              ) : null}
              {link.note ? <p className="rh-text-secondary">{link.note}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The edge label between two steps of a chain, in the sentence case a chain reads in. */
function relationWord(relation: string | undefined): string {
  if (relation === undefined) return 'is related to';
  return researchLabel('claimRelation', relation).toLowerCase();
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
      className="rh-web-stack rh-web-stack--tight rh-web-prompt"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ status, allowedStrength: allowed, wording: wording || undefined });
      }}
    >
      <h3 className="rh-text-h4">Audit</h3>
      <Select
        id="audit-status"
        label="Status the evidence supports"
        value={status}
        onChange={(event) => setStatus(event.target.value)}
      >
        {CLAIM_STATUSES.map((value) => (
          <option key={value} value={value}>
            {researchLabel('claimStatus', value)}
          </option>
        ))}
      </Select>
      <Select
        id="audit-allowed"
        label="Allowed strength"
        value={allowed}
        onChange={(event) => setAllowed(event.target.value)}
      >
        {SCOPES.map((value) => (
          <option key={value} value={value}>
            {researchLabel('claimScope', value)}
          </option>
        ))}
      </Select>
      <Input
        id="audit-wording"
        label="Maximum defensible wording"
        value={wording}
        placeholder="what this claim may say, at most"
        onChange={(event) => setWording(event.target.value)}
      />
      <div className="rh-web-row">
        <Button type="submit" variant="primary" size="sm" disabled={disabled}>
          Record the audit
        </Button>
      </div>
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
      className="rh-web-stack rh-web-stack--tight rh-web-prompt"
      onSubmit={(event) => {
        event.preventDefault();
        if (!rationale.trim()) return;
        onSubmit({ selected, auditorRecommendation: recommendation, rationale });
      }}
    >
      <h3 className="rh-text-h4">Override the auditor</h3>
      <p className="rh-text-secondary">
        An override is a Decision before it is a claim edit: the recommendation it overrules,
        the scope you chose, and your reason are all recorded.
      </p>
      <Select
        id="override-scope"
        label={`Scope you are choosing instead of ${researchLabel('claimScope', recommendation)}`}
        value={selected}
        onChange={(event) => setSelected(event.target.value)}
      >
        {SCOPES.map((value) => (
          <option key={value} value={value}>
            {researchLabel('claimScope', value)}
          </option>
        ))}
      </Select>
      <Textarea
        id="override-rationale"
        label="Rationale"
        rows={3}
        value={rationale}
        onChange={(event) => setRationale(event.target.value)}
      />
      <div className="rh-web-row">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={disabled || !rationale.trim()}
        >
          Accept the override
        </Button>
      </div>
    </form>
  );
}

/**
 * One accepted Evidence object, as the picker offers it.
 *
 * The id leads, because it is what a researcher who already knows the object types and
 * what the daemon is about to be sent; the field's word and the work say which one it is
 * without opening it; the quoted span underneath is what the relation will rest on.
 */
export function evidenceOptionLabel(entry: EvidenceSummary): string {
  const field = entry.field === null ? 'No field recorded' : fieldLabel(entry.field);
  return `${entry.id} · ${field} · ${entry.work}`;
}

/**
 * The accepted evidence that matches what has been typed so far.
 *
 * Every term has to appear somewhere in the option — its id, its field, its work or its
 * quoted text — so `E0001`, `metric`, `Metric result` and a phrase from the span all find
 * the same object. The `·` of a filled-in option is not a term: selecting one must not
 * empty the list it was selected from.
 */
export function matchingEvidence(
  evidence: readonly EvidenceSummary[],
  query: string,
): EvidenceSummary[] {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .filter((term) => term !== '' && term !== '·');
  if (terms.length === 0) return [...evidence];
  return evidence.filter((entry) => {
    const haystack = `${evidenceOptionLabel(entry)} ${entry.field ?? ''} ${entry.exact_text}`;
    return terms.every((term) => haystack.toLowerCase().includes(term));
  });
}

/** An id a researcher typed in full, for the case where the list could not be read. */
const EVIDENCE_ID = /^E\d+$/;

/**
 * Relate one accepted Evidence object to this claim.
 *
 * The evidence is chosen from the project's own accepted evidence rather than recalled: an
 * id typed from memory is the one input on this screen that a researcher cannot check
 * before pressing the button, and a wrong one records a relation to the wrong span. The id
 * stays visible in every option, so knowing it is still the fastest way to find it — and
 * it remains typable in full when the list itself could not be read.
 */
function RelateForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (evidence: string, relation: string) => void;
}) {
  const { client } = useSession();
  const accepted = useAsync(() => client.evidence(), [client]);
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState<EvidenceSummary | null>(null);
  const [relation, setRelation] = useState('supports');

  const evidence = accepted.data ?? [];
  const matches = matchingEvidence(evidence, query);
  const options: ComboboxItem<EvidenceSummary>[] = matches.map((entry) => ({
    id: entry.id,
    label: evidenceOptionLabel(entry),
    description: entry.exact_text,
    value: entry,
  }));
  const typed = query.trim().toUpperCase();
  const evidenceId = chosen?.id ?? (EVIDENCE_ID.test(typed) ? typed : null);

  return (
    <form
      className="rh-web-stack rh-web-stack--tight rh-web-prompt"
      onSubmit={(event) => {
        event.preventDefault();
        if (evidenceId === null) return;
        onSubmit(evidenceId, relation);
      }}
    >
      <h3 className="rh-text-h4">Relate evidence</h3>
      <div className="rh-web-stack rh-web-stack--tight">
        <label className="rh-field__label" id="relate-evidence-label" htmlFor="relate-evidence">
          Accepted evidence
        </label>
        <Combobox
          id="relate-evidence"
          aria-labelledby="relate-evidence-label"
          label="Accepted evidence"
          placeholder="Search by id, field, work or quoted text"
          items={options}
          openOnFocus
          disabled={disabled}
          loading={accepted.loading}
          loadingMessage="Reading the accepted evidence…"
          emptyMessage={
            evidence.length === 0
              ? 'This project has no accepted evidence yet. A candidate becomes evidence in the review inbox.'
              : 'No accepted evidence matches that.'
          }
          query={query}
          onQueryChange={(next) => {
            setQuery(next);
            // Choosing an option fills the box with that option's own line, which is not a
            // researcher editing the search: only text that no longer names the chosen
            // object un-chooses it.
            setChosen((current) =>
              current !== null && next === evidenceOptionLabel(current) ? current : null,
            );
          }}
          value={chosen?.id ?? null}
          onChange={(item) => setChosen(item?.value ?? null)}
        />
        {accepted.error ? (
          <ErrorBox error={accepted.error} retry={accepted.reload} />
        ) : chosen ? (
          <p className="rh-text-secondary">{chosen.exact_text}</p>
        ) : null}
      </div>
      <Select
        id="relate-relation"
        label="Relation"
        value={relation}
        onChange={(event) => setRelation(event.target.value)}
      >
        {RELATIONS.map((value) => (
          <option key={value} value={value}>
            {researchLabel('claimRelation', value)}
          </option>
        ))}
      </Select>
      <div className="rh-web-row">
        <Button type="submit" variant="primary" size="sm" disabled={disabled || evidenceId === null}>
          Relate
        </Button>
      </div>
    </form>
  );
}
