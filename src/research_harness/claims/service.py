"""The claim workstation: create a claim, relate evidence to it, audit it, override it.

Everything the researcher does to a Claim happens here, and every mutation goes through the
capability layer (ADR-004). The service adds the three things a handler cannot know on its
own: which evidence, works, and search runs an audit may read; that a new claim's allowed
strength is L0 until an audit earns more; and that an override is a Decision first and a
claim edit second.

Two numbers on a claim are deliberately not the same number (Product 10, 42.G):

* ``requested_strength`` is the researcher's ask. It is set at creation and never moves.
* ``allowed_strength`` is what the audited evidence defends. A new claim starts at
  ``L0 individual`` however ambitious the ask, an audit can only lower it further or raise
  it as far as the evidence goes, and raising it beyond that needs an accepted
  ``epistemic_override`` Decision that stays visible in the record (Product 38, ADR-007).

    claims = ClaimService(ctx)
    claim, _ = claims.create("Existing systems tokenize traffic heterogeneously", ...)
    claims.relate(claim.id, EvidenceId("E0132"), ClaimEvidenceRelationType.SUPPORTS)
    claim, result, _ = claims.audit(claim.id)
    result.maximum_defensible_wording, claim.allowed_strength
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from research_harness.capabilities.claims_ext import (
    RelateClaimEvidenceRequest,
    SupersedeClaimRequest,
    UnrelateClaimEvidenceRequest,
    UpdateClaimCoverageRequest,
    relate_claim_evidence,
    supersede_claim,
    unrelate_claim_evidence,
    update_claim_coverage,
)
from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AuditClaimRequest,
    CreateClaimRequest,
    MutationResult,
    OverrideClaimStrengthRequest,
)
from research_harness.capabilities.handlers import accept_decision, create_claim
from research_harness.capabilities.handlers import audit_claim as record_claim_audit
from research_harness.capabilities.handlers import override_claim_strength as apply_override
from research_harness.capabilities.invalidation import canonical_objects
from research_harness.citations.graph import CitationGraph
from research_harness.claims.audit import (
    DEFAULT_COUNTER_LIMIT,
    ClaimAuditInput,
    ClaimAuditResult,
    CounterEvidenceFinder,
    audit_claim,
    coverage_state,
    to_assessment,
)
from research_harness.claims.coverage import CoverageUniverse
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DecisionStatus,
    DecisionType,
)
from research_harness.domain.errors import (
    AuthorityError,
    CapabilityError,
    DomainValidationError,
    TransitionError,
)
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import (
    ClaimId,
    DecisionId,
    EvidenceId,
    SearchRunId,
    SynthesisId,
    WorkId,
)
from research_harness.domain.research import Decision, ResearchEvent, SearchRun
from research_harness.domain.work import Work
from research_harness.projection.dependencies import DependencyGraph, StaleMark, mark_changed
from research_harness.providers.models.base import ModelProvider
from research_harness.providers.models.cross_verify import CrossVerifyPolicy
from research_harness.providers.models.router import ModelRouter

if TYPE_CHECKING:  # imported lazily in `audit`: `workflows` imports `claims`, not the reverse
    from research_harness.workflows.engine import WorkflowEngine

#: Cutoff used to *measure* a derived funnel when the claim declares none. It never
#: reaches the recorded `Coverage`: a claim with no declared `publication_until` keeps
#: `cutoff = None`, so the L4 requirement for a cutoff stays a researcher's declaration.
_OPEN_CUTOFF = "9999-12"

__all__ = [
    "AUDIT_EVENTS",
    "CLAIM_EVENTS",
    "INITIAL_ALLOWED_STRENGTH",
    "RELATION_EVENT",
    "ClaimService",
    "ClaimView",
    "next_decision_id",
]

ModelClient = ModelProvider | ModelRouter
"""What a role call may be given: one provider, or a router that picks one."""

ClaimList = list[Claim]
SearchRunList = list[SearchRun]
"""Aliases used inside `ClaimService`, whose `list` method shadows the builtin in class scope."""

INITIAL_ALLOWED_STRENGTH = ClaimScope.INDIVIDUAL
"""Where every new claim starts, however strong the ask: scope is earned by audit, not asked
for (Product 10.2, 42.G). The researcher's ask is kept verbatim in ``requested_strength``."""

AUDIT_EVENTS: frozenset[str] = frozenset({"claim.audited", "claim.qualified"})
"""The events a `claim.audit` writes; one of them is what a relation change invalidates."""

RELATION_EVENT = "claim.relation_changed"

#: Event kinds that make up a claim's audit history, newest last.
CLAIM_EVENTS: frozenset[str] = frozenset(
    {
        "claim.created",
        "claim.audited",
        "claim.qualified",
        "claim.overridden",
        "claim.superseded",
        "claim.relation_changed",
        "decision.accepted",
        "state.marked_stale",
    }
)


@dataclass(frozen=True, slots=True)
class ClaimView:
    """One claim as a researcher reads it: relations by kind, decisions, and what depends on it."""

    claim: Claim
    support: tuple[ClaimEvidenceRelation, ...] = ()
    qualifiers: tuple[ClaimEvidenceRelation, ...] = ()
    contradictions: tuple[ClaimEvidenceRelation, ...] = ()
    incomparable: tuple[ClaimEvidenceRelation, ...] = ()
    context: tuple[ClaimEvidenceRelation, ...] = ()
    """`contextualizes` and `exemplifies`: evidence that frames the claim without bearing on it."""

    decisions: tuple[Decision, ...] = ()
    stale: tuple[StaleMark, ...] = ()
    """Objects that depend on this claim and go stale when it changes (ADR-008)."""

    coverage: str = ""
    wording: str = ""
    history: tuple[ResearchEvent, ...] = ()

    @property
    def overrides(self) -> tuple[Decision, ...]:
        """The accepted epistemic overrides on this claim, oldest first."""
        return tuple(
            item for item in self.decisions if item.type is DecisionType.EPISTEMIC_OVERRIDE
        )

    @property
    def audit_is_older_than_relations(self) -> bool:
        """True when a relation changed after the last audit, so the ceiling is out of date.

        Read from the event log rather than from ``updated_at``, which every mutation bumps:
        an override moves the claim without touching a single relation.
        """
        audited = _last_index(self.history, AUDIT_EVENTS)
        changed = _last_index(self.history, {RELATION_EVENT})
        return audited is not None and changed is not None and changed > audited

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for transports and `--json` output."""
        return {
            "claim": self.claim.model_dump(mode="json"),
            "status": self.claim.status.value,
            "requested_strength": self.claim.requested_strength.value,
            "allowed_strength": self.claim.allowed_strength.value,
            "wording": self.wording,
            "coverage": self.coverage,
            "support": [_relation_dict(link) for link in self.support],
            "qualifiers": [_relation_dict(link) for link in self.qualifiers],
            "contradictions": [_relation_dict(link) for link in self.contradictions],
            "incomparable": [_relation_dict(link) for link in self.incomparable],
            "context": [_relation_dict(link) for link in self.context],
            "decisions": [item.model_dump(mode="json") for item in self.decisions],
            "stale": [
                {
                    "object_id": mark.object_id,
                    "reason": mark.reason,
                    "priority": int(mark.priority),
                }
                for mark in self.stale
            ],
            "audit_is_older_than_relations": self.audit_is_older_than_relations,
            "history": [event.model_dump(mode="json") for event in self.history],
        }


class ClaimService:
    """Create, relate, audit, override, and retire claims in one workspace."""

    def __init__(
        self,
        ctx: CapabilityContext,
        *,
        counter_finder: CounterEvidenceFinder | None = None,
        graph: CitationGraph | None = None,
    ) -> None:
        self._ctx = ctx
        self._counter_finder = counter_finder
        self._graph = graph

    @property
    def ctx(self) -> CapabilityContext:
        """The capability context every mutation runs through."""
        return self._ctx

    # -- creation ------------------------------------------------------------

    def create(
        self,
        statement: str,
        *,
        # `type` shadows the builtin on purpose: it is the field name in Product 10.1 and
        # keeping the keyword identical to the field is worth more than the shadowing.
        type: ClaimType,
        semantics: ClaimSemantics,
        scope: ClaimScopeSpec,
        requested_strength: ClaimScope,
        relations: Sequence[ClaimEvidenceRelation] = (),
        coverage: Coverage | None = None,
        derived_from: Sequence[SynthesisId] = (),
    ) -> tuple[Claim, MutationResult]:
        """Register a claim as `unverified` at L0, whatever strength was requested.

        ``requested_strength`` records the ask and never moves again; ``allowed_strength``
        starts at :data:`INITIAL_ALLOWED_STRENGTH` because no audit has yet earned anything
        more. Every relation is checked against accepted evidence before the claim exists,
        so a typo never becomes a claim that silently supports itself with nothing.
        """
        links = _checked_relations(relations)
        missing = [link.evidence for link in links if not self._has_evidence(link.evidence)]
        if missing:
            raise CapabilityError(
                "claim.create: no accepted evidence "
                f"{', '.join(sorted(str(item) for item in missing))} in this workspace"
            )
        claim = Claim(
            id=self.next_claim_id(),
            statement=statement,
            type=type,
            semantics=semantics,
            scope=scope,
            relations=links,
            coverage=coverage if coverage is not None else Coverage(),
            assessment=ClaimAssessment(
                requested_strength=requested_strength,
                allowed_strength=INITIAL_ALLOWED_STRENGTH,
                status=ClaimStatus.UNVERIFIED,
            ),
            derived_from=tuple(derived_from),
            provenance=self._ctx.provenance(workflow="claim"),
        )
        result = create_claim(self._ctx, CreateClaimRequest(claim=claim))
        return self.get(claim.id), result

    # -- coverage ------------------------------------------------------------

    def record_coverage(
        self, claim_id: ClaimId, coverage: Coverage
    ) -> tuple[Claim, MutationResult]:
        """Persist a computed `Coverage` onto a Claim (`claim.update_coverage`).

        The write half of the fix for the dogfood's F2: `research coverage` computed a
        proper PRISMA funnel and nothing carried it to the Claim, so `claim audit` read
        zeros and capped every literature-wide claim at L1 for a plumbing reason.
        """
        result = update_claim_coverage(
            self._ctx, UpdateClaimCoverageRequest(claim_id=claim_id, coverage=coverage)
        )
        return self.get(claim_id), result

    def derived_coverage(self, claim: Claim) -> tuple[Coverage, tuple[SearchRunId, ...]] | None:
        """The funnel this claim's recorded SearchRuns support, when it records none itself.

        ``None`` whenever the claim already carries coverage, or when there is no search run
        to read one off: a derived zero is indistinguishable from a recorded zero, and
        neither should be presented as a measurement (Product 18, 42.F).

        A cutoff is *never* invented. Coverage is measured up to the claim's own declared
        `publication_until`, and a claim that declares none gets a coverage record with no
        cutoff - which is exactly what L4 asks for and therefore must not be conjured from
        the date a search happened to run.
        """
        # Deferred: `discovery/` reaches into `capabilities/`, which reaches back here, so a
        # module-scope import makes `import research_harness.discovery` depend on whether
        # `claims` happened to be imported first.
        from research_harness.discovery.absence import coverage_for

        if not _coverage_is_empty(claim.coverage):
            return None
        runs = self._ctx.repo.list_search_runs()
        if not runs:
            return None
        works = {work.id: work for work in self._ctx.repo.list_works()}
        universe = CoverageUniverse(
            definition=claim.scope.corpus or claim.statement,
            cutoff=claim.scope.publication_until or _OPEN_CUTOFF,
        )
        report = coverage_for(claim, runs, universe, works=works, evidence=self._evidence(works))
        coverage = report.coverage
        if claim.scope.publication_until is None:
            coverage = coverage.touch(cutoff=None)
        if _coverage_is_empty(coverage):
            return None
        return coverage, coverage.search_runs

    def with_derived_coverage(self, claim: Claim) -> tuple[Claim, tuple[SearchRunId, ...]]:
        """``claim`` with derived coverage when it records none, and the runs it came from."""
        derived = self.derived_coverage(claim)
        if derived is None:
            return claim, ()
        coverage, runs = derived
        return claim.touch(coverage=coverage), runs

    def next_claim_id(self) -> ClaimId:
        """The id the next `claim.create` will write, ids already on disk included."""
        repo = self._ctx.repo
        on_disk = ClaimId.next(str(claim.id) for claim in repo.list_claims())
        return ClaimId.make(max(on_disk.number, repo.config.counter(ClaimId.prefix) + 1))

    # -- relations -----------------------------------------------------------

    def relate(
        self,
        claim_id: ClaimId,
        evidence_id: EvidenceId,
        relation: ClaimEvidenceRelationType,
        *,
        aspect: str | None = None,
        note: str | None = None,
    ) -> tuple[Claim, MutationResult]:
        """Link one evidence object to a claim (Product 10.4).

        Relations are many-to-many and aspect-scoped: the same paper may support a claim on
        one aspect and qualify it on another, and both edges stand at once. Only the exact
        triple (evidence, relation, aspect) is refused as a duplicate.
        """
        result = relate_claim_evidence(
            self._ctx,
            RelateClaimEvidenceRequest(
                claim_id=claim_id,
                relation=ClaimEvidenceRelation(
                    evidence=evidence_id, relation=relation, aspect=aspect, note=note
                ),
            ),
        )
        return self.get(claim_id), result

    def unrelate(
        self,
        claim_id: ClaimId,
        evidence_id: EvidenceId,
        relation: ClaimEvidenceRelationType,
        *,
        aspect: str | None = None,
    ) -> tuple[Claim, MutationResult]:
        """Remove exactly the edge named; the claim's other edges to the same evidence stay."""
        result = unrelate_claim_evidence(
            self._ctx,
            UnrelateClaimEvidenceRequest(
                claim_id=claim_id, evidence=evidence_id, relation=relation, aspect=aspect
            ),
        )
        return self.get(claim_id), result

    def relations_of(self, claim_id: ClaimId) -> tuple[ClaimEvidenceRelation, ...]:
        """Every claim-evidence edge, in declaration order."""
        return self.get(claim_id).relations

    def evidence_for(
        self, claim_id: ClaimId, relation: ClaimEvidenceRelationType
    ) -> tuple[EvidenceId, ...]:
        """Evidence ids linked under ``relation``, in declaration order and without repeats."""
        seen: dict[EvidenceId, None] = {}
        for link in self.relations_of(claim_id):
            if link.relation is relation:
                seen.setdefault(link.evidence, None)
        return tuple(seen)

    # -- audit ---------------------------------------------------------------

    def audit_input(
        self,
        claim: Claim | ClaimId,
        *,
        skeptic: ModelClient | None = None,
        auditor: ModelClient | None = None,
        counter_limit: int = DEFAULT_COUNTER_LIMIT,
        submission_ready: bool = False,
    ) -> ClaimAuditInput:
        """Everything one audit of ``claim`` may read, assembled from accepted state only."""
        subject = claim if isinstance(claim, Claim) else self.get(claim)
        subject, _ = self.with_derived_coverage(subject)
        repo = self._ctx.repo
        works = {work.id: work for work in repo.list_works()}
        return ClaimAuditInput(
            claim=subject,
            evidence=self._evidence(works),
            works=works,
            search_runs=self._search_runs(subject),
            citation_graph=self._graph,
            counter_finder=self._counter_finder,
            skeptic=skeptic,
            auditor=auditor,
            counter_limit=counter_limit,
            manuscript_attached=self._is_attached(subject.id),
            submission_ready=submission_ready,
        )

    def audit(
        self,
        claim_id: ClaimId,
        *,
        skeptic: ModelClient | None = None,
        auditor: ModelClient | None = None,
        policy: CrossVerifyPolicy | None = None,
        durable: bool = False,
        engine: WorkflowEngine | None = None,
    ) -> tuple[Claim, ClaimAuditResult, MutationResult]:
        """Audit one claim and record what the evidence allows, never what was asked for.

        The deterministic ceiling is computed first and every model step can only narrow it;
        the recorded ``allowed_strength`` is then the lowest of the request, the audit's
        recommendation, and the ladder's own result, so a silent escalation is unreachable
        from this path (Product 42.G). ``durable`` runs the audit as a checkpointed workflow
        so a provider failure can be resumed without paying for the whole audit twice.
        """
        claim = self.get(claim_id)
        if claim.status is ClaimStatus.SUPERSEDED:
            raise TransitionError(f"{claim.id} is superseded; a retired claim is not re-audited")
        subject, derived_from = self.with_derived_coverage(claim)
        audit_input = self.audit_input(subject, skeptic=skeptic, auditor=auditor)
        result = (
            self._durable_audit(audit_input, policy=policy, engine=engine)
            if durable
            else audit_claim(audit_input, cross_verify_policy=policy)
        )
        if derived_from:
            runs = ", ".join(str(run) for run in derived_from)
            result = result.touch(
                warnings=(
                    *result.warnings,
                    f"coverage: {claim.id} records no coverage, so the funnel was derived "
                    f"from the recorded search runs {runs}; persist it with "
                    "`research coverage` so the record and the audit read the same numbers",
                )
            )
        assessment = to_assessment(result, claim)
        mutation = record_claim_audit(
            self._ctx,
            AuditClaimRequest(
                claim_id=claim.id,
                status=assessment.status,
                allowed_strength=assessment.allowed_strength,
                maximum_defensible_wording=assessment.maximum_defensible_wording,
            ),
        )
        return self.get(claim.id), result, mutation

    def _durable_audit(
        self,
        audit_input: ClaimAuditInput,
        *,
        policy: CrossVerifyPolicy | None,
        engine: WorkflowEngine | None,
    ) -> ClaimAuditResult:
        """Run the audit as a resumable workflow, checkpointing every stage under `.research/`."""
        # Local import: `workflows.claim_audit` imports `claims.audit`, so importing it at
        # module scope would make `claims` and `workflows` a circular pair.
        from research_harness.workflows.claim_audit import run_claim_audit
        from research_harness.workflows.engine import WorkflowEngine as Engine
        from research_harness.workspace.runs import RunStore

        research_dir = self._ctx.repo.layout.research_dir
        runner = engine if engine is not None else Engine(RunStore(research_dir))
        _, result = run_claim_audit(
            runner, research_dir, lambda: audit_input, audit_input.claim.id, policy=policy
        )
        return result

    # -- researcher override -------------------------------------------------

    def override(
        self, claim_id: ClaimId, *, selected: ClaimScope, rationale: str
    ) -> tuple[Claim, Decision, MutationResult]:
        """Overrule the auditor's ceiling, visibly (Product 38, ADR-007).

        The override is a Decision before it is a claim edit: the auditor recommendation it
        overrides, the scope the researcher chose instead, and the reason are all recorded
        and accepted first, and only then does the claim move. Downstream objects are marked
        stale rather than rewritten, so the manuscript text resting on the old ceiling shows
        up as work to do (ADR-008).
        """
        if not self._ctx.is_human:
            raise AuthorityError(
                f"claim.override_strength: {self._ctx.actor} is not the researcher; only a "
                "human actor may overrule the claim auditor"
            )
        if not rationale.strip():
            raise DomainValidationError("an epistemic override requires a rationale")
        claim = self.get(claim_id)
        recommendation = claim.allowed_strength
        if selected is recommendation:
            raise TransitionError(
                f"{claim.id} already allows {recommendation.label}; there is nothing to override"
            )
        decision = Decision(
            id=self.next_decision_id(),
            type=DecisionType.EPISTEMIC_OVERRIDE,
            status=DecisionStatus.PROPOSED,
            title=f"epistemic override on {claim.id}",
            rationale=rationale,
            claim=claim.id,
            auditor_recommendation=recommendation,
            researcher_selected=selected,
            provenance=self._ctx.provenance(workflow="claim"),
        )
        accept_decision(self._ctx, AcceptDecisionRequest(decision=decision))
        mutation = apply_override(
            self._ctx,
            OverrideClaimStrengthRequest(claim_id=claim.id, decision_id=decision.id),
        )
        return self.get(claim.id), self._ctx.repo.get_decision(decision.id), mutation

    def override_history(self, claim_id: ClaimId) -> tuple[Decision, ...]:
        """Every epistemic override recorded against this claim, oldest first."""
        return tuple(
            sorted(
                (
                    decision
                    for decision in self._ctx.repo.list_decisions()
                    if decision.type is DecisionType.EPISTEMIC_OVERRIDE
                    and decision.claim == claim_id
                ),
                key=lambda decision: (decision.created_at, str(decision.id)),
            )
        )

    def next_decision_id(self) -> DecisionId:
        """The id the next `decision.accept` will write, ids already on disk included."""
        return next_decision_id(self._ctx)

    # -- lifecycle -----------------------------------------------------------

    def supersede(
        self, claim_id: ClaimId, by: ClaimId | None = None, reason: str = ""
    ) -> tuple[Claim, MutationResult]:
        """Retire a claim, optionally naming the claim that replaces it. Superseded is terminal."""
        result = supersede_claim(
            self._ctx,
            SupersedeClaimRequest(claim_id=claim_id, reason=reason, superseded_by=by),
        )
        return self.get(claim_id), result

    # -- reads ---------------------------------------------------------------

    def get(self, claim_id: ClaimId) -> Claim:
        """The claim with ``claim_id``, read from canonical state."""
        return self._ctx.repo.get_claim(claim_id)

    def list(self, status: ClaimStatus | None = None) -> ClaimList:
        """Claims by id, optionally filtered by status."""
        claims = sorted(self._ctx.repo.list_claims(), key=lambda claim: str(claim.id))
        return [claim for claim in claims if status is None or claim.status is status]

    def show(self, claim_id: ClaimId) -> ClaimView:
        """One claim with its relations split by kind, its decisions, and what depends on it."""
        claim = self.get(claim_id)
        kinds = ClaimEvidenceRelationType
        by_relation = _split_relations(claim.relations)
        state, _ = coverage_state(claim, self._search_runs(claim))
        return ClaimView(
            claim=claim,
            support=by_relation[kinds.SUPPORTS],
            qualifiers=by_relation[kinds.QUALIFIES],
            contradictions=by_relation[kinds.CONTRADICTS],
            incomparable=by_relation[kinds.INCOMPARABLE_UNDER_CURRENT_EVIDENCE],
            context=by_relation[kinds.CONTEXTUALIZES] + by_relation[kinds.EXEMPLIFIES],
            decisions=self._decisions_of(claim),
            stale=self._dependents(claim.id),
            coverage=state,
            wording=claim.assessment.maximum_defensible_wording or "",
            history=self.history(claim.id),
        )

    def history(self, claim_id: ClaimId) -> tuple[ResearchEvent, ...]:
        """Every recorded event that names this claim, oldest first."""
        return tuple(
            event
            for event in self._ctx.repo.iter_events()
            if claim_id in event.subjects and event.event.value in CLAIM_EVENTS
        )

    # -- internals -----------------------------------------------------------

    def _evidence(self, works: Mapping[WorkId, Work]) -> dict[EvidenceId, Evidence]:
        """Every accepted evidence object in the workspace, keyed by id."""
        repo = self._ctx.repo
        return {item.id: item for work in works for item in repo.iter_evidence(work)}

    def _has_evidence(self, evidence_id: EvidenceId) -> bool:
        repo = self._ctx.repo
        return any(
            item.id == evidence_id
            for work in repo.list_works()
            for item in repo.iter_evidence(work.id)
        )

    def _search_runs(self, claim: Claim) -> SearchRunList:
        """The runs behind this claim: the ones its coverage names, else every recorded run.

        A rerun of a named run counts as named too: it is the same search finished, and a
        recorded coverage set that hid it would freeze the funnel at the moment it was first
        written (`discovery.effective_runs` then decides which of the two is of record).
        """
        runs = self._ctx.repo.list_search_runs()
        named = set(claim.coverage.search_runs)
        if not named:
            return runs
        selected = [run for run in runs if run.id in _with_reruns(runs, named)]
        return selected or runs

    def _is_attached(self, claim_id: ClaimId) -> bool:
        """True when manuscript text rests on this claim, which raises the audit's stakes."""
        return any(anchor.claim == claim_id for anchor in self._ctx.repo.iter_anchors())

    def _decisions_of(self, claim: Claim) -> tuple[Decision, ...]:
        """Decisions the claim records, plus any decision that references it, oldest first."""
        recorded = set(claim.decisions)
        found = [
            decision
            for decision in self._ctx.repo.list_decisions()
            if decision.id in recorded or decision.claim == claim.id
        ]
        return tuple(sorted(found, key=lambda decision: (decision.created_at, str(decision.id))))

    def _dependents(self, claim_id: ClaimId) -> tuple[StaleMark, ...]:
        """What a change to this claim invalidates: anchors, questions, and on (ADR-008)."""
        graph = DependencyGraph.from_objects(canonical_objects(self._ctx.repo))
        marks = mark_changed(graph, str(claim_id))
        return tuple(sorted(marks, key=lambda mark: (-int(mark.priority), mark.object_id)))


def _with_reruns(runs: Sequence[SearchRun], named: set[SearchRunId]) -> set[SearchRunId]:
    """``named`` plus every run that reproduces one of them, transitively."""
    selected = set(named)
    changed = True
    while changed:
        changed = False
        for run in runs:
            if run.reproduces in selected and run.id not in selected:
                selected.add(run.id)
                changed = True
    return selected


def _coverage_is_empty(coverage: Coverage) -> bool:
    """True when a coverage record measures nothing: no funnel and no runs behind it."""
    return (
        coverage.relevant_works == 0 and coverage.examined_works == 0 and not coverage.search_runs
    )


def next_decision_id(ctx: CapabilityContext) -> DecisionId:
    """The id the next `decision.accept` will write, ids already on disk included."""
    repo = ctx.repo
    on_disk = DecisionId.next(str(decision.id) for decision in repo.list_decisions())
    return DecisionId.make(max(on_disk.number, repo.config.counter(DecisionId.prefix) + 1))


# -- helpers -----------------------------------------------------------------


def _checked_relations(
    relations: Iterable[ClaimEvidenceRelation],
) -> tuple[ClaimEvidenceRelation, ...]:
    """The relations as a tuple, refusing an exact duplicate (evidence, relation, aspect)."""
    seen: set[tuple[str, str, str | None]] = set()
    links: list[ClaimEvidenceRelation] = []
    for link in relations:
        key = (str(link.evidence), link.relation.value, link.aspect)
        if key in seen:
            raise DomainValidationError(
                f"{link.evidence} is already linked as {link.relation.value}"
                + ("" if link.aspect is None else f" on {link.aspect!r}")
                + "; a repeated edge would count the same evidence twice"
            )
        seen.add(key)
        links.append(link)
    return tuple(links)


def _split_relations(
    relations: Sequence[ClaimEvidenceRelation],
) -> dict[ClaimEvidenceRelationType, tuple[ClaimEvidenceRelation, ...]]:
    """The relation set grouped by kind, in declaration order, with every kind present."""
    grouped: dict[ClaimEvidenceRelationType, list[ClaimEvidenceRelation]] = {
        kind: [] for kind in ClaimEvidenceRelationType
    }
    for link in relations:
        grouped[link.relation].append(link)
    return {kind: tuple(items) for kind, items in grouped.items()}


def _last_index(history: Sequence[ResearchEvent], kinds: Collection[str]) -> int | None:
    """Position of the last event in ``history`` whose kind is in ``kinds``."""
    found = [index for index, event in enumerate(history) if event.event.value in kinds]
    return found[-1] if found else None


def _relation_dict(link: ClaimEvidenceRelation) -> dict[str, Any]:
    return {
        "evidence": str(link.evidence),
        "relation": link.relation.value,
        "aspect": link.aspect,
        "note": link.note,
    }
