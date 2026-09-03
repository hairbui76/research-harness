"""Claim audit: what the accepted evidence defends, and what would break it (ROADMAP 7.4).

The audit is deterministic first. :func:`audit_claim_locally` reads accepted evidence, the
citation graph, and the recorded search coverage, and answers with the scope ladder
(:mod:`research_harness.claims.strength`), independent-support accounting
(:mod:`research_harness.citations.independence`), and the coverage guards
(:mod:`research_harness.claims.coverage`). No model is needed for any of that, and no model
can change it upwards.

Models are then used the way the product intends: to *falsify*. The Skeptic looks for what
would make the claim wrong, narrower, or not comparable; the Claim Auditor reports the
strongest wording it can defend. Their outputs are proposals, and they move in one
direction only — a model may lower the recommended scope, add a qualifier, or offer a
counter candidate, and a model that recommends a *higher* scope than the deterministic
engine is ignored with a warning. An auditor that maximizes support is not an auditor.

Three refusals are structural rather than advisory:

* **Differing outcomes are not contradictions.** A result measured on another dataset, with
  another metric, or under another condition is `incomparable_under_current_evidence`, and
  the audit says so as a *proposal*. It never rewrites the claim's relations: reclassifying
  a relation is a researcher act (Product 10.4, ADR-007).
* **Counter-evidence search returns candidates, never Evidence.** A retrieval hit is a
  :class:`RetrievalCandidate` with no anchor, no acceptance, and no authority (ADR-003,
  ADR-006).
* **Strength cannot escalate silently.** :func:`to_assessment` caps the allowed scope at the
  requested scope *and* at the engine's ceiling, and :func:`apply_audit` delegates to
  :func:`research_harness.domain.transitions.audit_claim`, which refuses anything above the
  request. Going higher needs an accepted `epistemic_override` Decision (Product 38, 42.G).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from research_harness.citations.graph import CitationGraph
from research_harness.citations.independence import IndependenceReport, independent_support
from research_harness.claims.coverage import absence_permitted
from research_harness.claims.strength import (
    QUALIFYING_RELATIONS,
    StrengthAssessment,
    StrengthInput,
    assess_strength,
    build_facts,
    wording_for,
)
from research_harness.domain import transitions
from research_harness.domain.base import DomainModel, utc_now
from research_harness.domain.claim import Claim, ClaimAssessment
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceStatus,
    StaleState,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ClaimId, EvidenceId, WorkId
from research_harness.domain.research import SearchRun
from research_harness.domain.work import Work
from research_harness.providers.models import describe_backend
from research_harness.providers.models.base import ModelProvider, ModelRequest, TraceSink
from research_harness.providers.models.cross_verify import (
    DEFAULT_POLICY,
    CrossVerification,
    CrossVerificationGate,
    CrossVerifyPolicy,
    Eligibility,
    ProviderCandidate,
    ProviderConflict,
    cross_verify,
    effective_scope,
    is_eligible,
)
from research_harness.providers.models.router import ModelRouter
from research_harness.roles.auditor import CLAIM_AUDITOR
from research_harness.roles.contracts import (
    InputKind,
    RoleContract,
    RoleInput,
    RoleRequest,
    WriteScope,
    assert_can_write,
    build_request,
)
from research_harness.roles.schemas import ClaimAuditOutput, EvidenceCandidateOutput, SkepticOutput
from research_harness.roles.skeptic import SKEPTIC

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_DECISION_FIELDS",
    "DEFAULT_COUNTER_LIMIT",
    "GATE_ORDER",
    "SKEPTIC_SOURCE",
    "ClaimAuditInput",
    "ClaimAuditResult",
    "CounterEvidenceFinder",
    "ModelJudgement",
    "ProposedRelationChange",
    "RetrievalCandidate",
    "apply_audit",
    "apply_auditor",
    "apply_cross_verification",
    "apply_skeptic",
    "audit_claim",
    "audit_claim_locally",
    "available_providers",
    "backend_label",
    "build_auditor_request",
    "build_skeptic_request",
    "claim_payload",
    "comparison_differences",
    "coverage_state",
    "evidence_payload",
    "select_cross_verify_gate",
    "to_assessment",
    "trace_sink_for",
]

DEFAULT_COUNTER_LIMIT = 5
"""Counter-evidence candidates asked of the retrieval engine; proposals, not a corpus."""

AUDIT_DECISION_FIELDS: tuple[str, ...] = ("recommended_scope",)
"""The claim-audit fields two providers are compared on.

`coverage_state`, `maximum_defensible_wording`, and `rationale` are prose: two models
wording the same judgement differently is not a scientific disagreement, and comparing
free text would manufacture conflicts (Product 20.4, 25).
"""

SKEPTIC_SOURCE = "skeptic"
"""`RetrievalCandidate.source` for a counter candidate the Skeptic proposed."""

GATE_ORDER: tuple[CrossVerificationGate, ...] = (
    CrossVerificationGate.ABSENCE_CLAIM,
    CrossVerificationGate.NUMERIC_HIGH_IMPACT,
    CrossVerificationGate.COUNTER_EVIDENCE_INTERPRETATION,
    CrossVerificationGate.SUBMISSION_FIELD_CLAIM,
    CrossVerificationGate.MANUSCRIPT_HIGH_CONSEQUENCE,
)
"""Order gates are tried in; the first that applies is the one the audit cross-verifies."""

_COUNTING_STATUS = EvidenceStatus.ACCEPTED
_ModelClient = ModelProvider | ModelRouter


# ------------------------------------------------------------------------------- objects


class RetrievalCandidate(DomainModel):
    """One retrieval hit offered as possible counter-evidence. Never Evidence.

    A candidate has no source anchor, no acceptance, and no authority: it names where to
    look. Turning one into Evidence is extraction followed by human review (ADR-003).
    """

    ref: str = Field(min_length=1)
    """Evidence id or block reference the hit points at."""

    work: WorkId | None = None
    text: str = ""
    score: float = 0.0
    source: str = ""
    """Which retrieval path produced it, e.g. an index name or `skeptic`."""

    location: str = ""
    """Where in the work it sits, in plain words, e.g. ``block B0081, page 8``."""


@runtime_checkable
class CounterEvidenceFinder(Protocol):
    """Retrieval that looks for what would break a claim (implemented by Task 15.x).

    The audit calls it and reports what comes back as proposals; it never promotes a hit.
    """

    def find_counter_evidence(
        self, claim: Claim, *, limit: int
    ) -> Sequence[RetrievalCandidate]: ...


class ProposedRelationChange(DomainModel):
    """A claim-evidence relation the audit believes is mislabelled, offered for review.

    Proposing is all it does. The claim's relations are canonical state and are changed
    only by a researcher through the capability layer (ADR-003, ADR-007).
    """

    evidence: EvidenceId
    current: ClaimEvidenceRelationType
    proposed: ClaimEvidenceRelationType
    note: str = Field(min_length=1)


class ModelJudgement(DomainModel):
    """One model's answer, kept with the reproducibility metadata Product 20.5 requires."""

    role: str
    provider: str
    model: str
    output: ClaimAuditOutput | SkepticOutput
    request_fingerprint: str

    @property
    def label(self) -> str:
        """``provider/model``, the actor form used in provenance."""
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True)
class ClaimAuditInput:
    """Everything one claim audit may read, plus the optional helpers it may call.

    The mappings are read-only views of accepted state; nothing here is written. The
    providers are optional because the deterministic audit is the audit: a workspace with
    no model configured still gets a scope ceiling, independence warnings, and coverage.
    """

    claim: Claim
    evidence: Mapping[EvidenceId, Evidence]
    works: Mapping[WorkId, Work]
    search_runs: Sequence[SearchRun]
    citation_graph: CitationGraph | None = None
    counter_finder: CounterEvidenceFinder | None = None
    skeptic: _ModelClient | None = None
    auditor: _ModelClient | None = None
    counter_limit: int = DEFAULT_COUNTER_LIMIT
    manuscript_attached: bool = False
    """True when this claim carries manuscript text; raises the cross-verification stakes."""

    submission_ready: bool = False
    """True when the manuscript is being prepared for submission (Product 20.4)."""

    cross_verify_providers: tuple[ProviderCandidate, ...] = ()
    """Explicit providers for cross-verification; derived from the clients when empty."""

    @property
    def graph(self) -> CitationGraph:
        """The citation graph, or an empty one: no graph means no citation chains, not error."""
        return self.citation_graph if self.citation_graph is not None else CitationGraph()

    def accepted(self, evidence_id: EvidenceId) -> Evidence | None:
        """The evidence behind an id when it is accepted and fresh, else ``None``."""
        item = self.evidence.get(evidence_id)
        if (
            item is None
            or item.status is not _COUNTING_STATUS
            or item.stale is not StaleState.FRESH
        ):
            return None
        return item


class ClaimAuditResult(DomainModel):
    """What the audit found: the ceiling, the doubts, and every proposal for review.

    Nothing here is accepted state. `recommended_scope` is the highest scope the evidence
    defends, `incomparable` and `counter_candidates` are proposals, and `conflict` is a
    provider disagreement a researcher resolves.
    """

    claim: ClaimId
    assessment: StrengthAssessment
    independence: IndependenceReport
    support: tuple[EvidenceId, ...] = ()
    counter_evidence: tuple[EvidenceId, ...] = ()
    qualifiers: tuple[EvidenceId, ...] = ()
    qualifier_notes: tuple[str, ...] = ()
    """Conditions that narrow the claim, in plain words, deterministic and model-proposed."""

    incomparable: tuple[ProposedRelationChange, ...] = ()
    """Relations the audit proposes reclassifying; the claim itself is untouched."""

    counter_candidates: tuple[RetrievalCandidate, ...] = ()
    coverage_state: str = ""
    maximum_defensible_wording: str = ""
    """The deterministic ceiling sentence: what the evidence lets the claim say."""
    proposed_wording: str = ""
    """The sentence the claim auditor proposed, at or below that ceiling (dogfood F15).

    `ClaimAuditOutput.maximum_defensible_wording` is a required field on the auditor's
    reply and used to be computed and thrown away, so the one sentence a writer actually
    wants -- the ceiling said in this claim's own terms -- never left the model call. It is
    advice and nothing more: it never changes `recommended_scope`, and an audit with no
    auditor leaves it empty.
    """
    recommended_scope: ClaimScope = ClaimScope.INDIVIDUAL
    warnings: tuple[str, ...] = ()
    model_judgements: tuple[ModelJudgement, ...] = ()
    cross_verification: CrossVerification | None = None
    conflict: ProviderConflict | None = None
    escalation_prevented: bool = False
    """True when the researcher asked for more scope than the evidence defends."""

    @property
    def status(self) -> ClaimStatus:
        """The claim status this audit records.

        The engine's status, except that a claim whose scope had to be capped below the
        requested one is `qualified` rather than `supported`: the evidence supports
        something, but not what was asked for (Product 10.3, 42.G).
        """
        if self.assessment.status is ClaimStatus.SUPPORTED and self.escalation_prevented:
            return ClaimStatus.QUALIFIED
        return self.assessment.status

    @property
    def proposed_relation_changes(self) -> tuple[ProposedRelationChange, ...]:
        """The relation reclassifications proposed for review; same tuple as `incomparable`."""
        return self.incomparable

    @property
    def has_conflict(self) -> bool:
        """True when two providers disagreed and a researcher has to resolve it."""
        return self.conflict is not None


# --------------------------------------------------------------------- deterministic audit


def comparison_differences(left: Evidence, right: Evidence) -> tuple[str, ...]:
    """The axes on which two evidence objects are not measuring the same thing.

    Two numbers compare only when metric, dataset, and experimental condition all match
    (Product 12); a number and a prose statement do not compare at all; and two statements
    compare only when they are the same kind of statement. An empty result means the two
    are commensurable, which is the precondition for calling one a contradiction of the
    other (Product 10.4, ROADMAP 7.4).
    """
    differences: list[str] = []
    if left.evidence_type is not right.evidence_type:
        differences.append("evidence_type")
    first, second = left.content.numeric, right.content.numeric
    if (first is None) != (second is None):
        differences.append("measurement")
    elif first is not None and second is not None:
        if first.metric != second.metric:
            differences.append("metric")
        if (first.dataset or "") != (second.dataset or ""):
            differences.append("dataset")
        if first.condition != second.condition:
            differences.append("condition")
    return tuple(differences)


def coverage_state(claim: Claim, search_runs: Sequence[SearchRun]) -> tuple[str, tuple[str, ...]]:
    """A plain-words account of the search behind the claim, and why absence is refused.

    The reasons are non-empty only for absence-shaped claims whose recorded coverage does
    not support one: coverage, not silence, is what licenses "we identified no work that"
    (Product 18, 42.F).
    """
    coverage = claim.coverage
    runs = max(len(coverage.search_runs), len(search_runs))
    text = (
        f"{coverage.examined_works} of {coverage.relevant_works} relevant works examined, "
        f"{coverage.unresolved_works} unresolved; estimated overturn risk "
        f"{coverage.overturn_risk.value}; {runs} recorded search run(s)"
    )
    if not _is_absence_shaped(claim):
        return text, ()
    permitted, reasons = absence_permitted(coverage, search_runs)
    if permitted:
        return f"{text}; the recorded coverage permits an absence claim", ()
    return f"{text}; the recorded coverage does not permit an absence claim", reasons


def audit_claim_locally(audit_input: ClaimAuditInput) -> ClaimAuditResult:
    """Audit one claim without any model: scope ceiling, independence, coverage, proposals.

    The ladder is evaluated on *independent* support rather than on the number of
    supporting objects, so two versions of one paper, one group reporting twice, or a
    derivative citation chain cannot inflate a corpus-level claim (Product 17). The
    independence count can only lower the engine's own count, never raise it.
    """
    claim = audit_input.claim
    warnings: list[str] = []

    independence = independent_support(
        claim, audit_input.evidence, audit_input.works, audit_input.graph
    )
    warnings.extend(f"independence: {reason}" for reason in independence.warnings)
    warnings.extend(_missing_evidence_warnings(audit_input))

    recorded_runs = len(audit_input.search_runs) or None
    base = StrengthInput.from_claim(claim, audit_input.evidence, search_runs_recorded=recorded_runs)
    counted = build_facts(base).independent_support
    effective = min(counted, independence.effective_support)
    if effective < counted:
        warnings.append(
            f"independence accounting reduces {counted} supporting works to {effective}; "
            "the scope ladder was evaluated on the smaller number (Product 17)"
        )
    assessment = assess_strength(base.touch(independent_works=effective))

    proposals, relation_warnings = _review_contradictions(audit_input)
    warnings.extend(relation_warnings)

    state, absence_reasons = coverage_state(claim, audit_input.search_runs)
    recommended = assessment.allowed
    if absence_reasons and recommended is ClaimScope.UNIVERSAL_OR_ABSENCE:
        recommended = ClaimScope.FIELD_GENERALIZATION
        warnings.extend(f"absence: {reason}" for reason in absence_reasons)
    wording = (
        assessment.wording
        if recommended is assessment.allowed
        else wording_for(recommended, claim.type, claim.coverage, assessment.support_ratio)
    )

    return ClaimAuditResult(
        claim=claim.id,
        assessment=assessment,
        independence=independence,
        support=claim.supporting,
        counter_evidence=claim.contradicting,
        qualifiers=_qualifying(claim),
        incomparable=proposals,
        counter_candidates=_find_counter_candidates(audit_input),
        coverage_state=state,
        maximum_defensible_wording=wording,
        recommended_scope=recommended,
        warnings=tuple(warnings),
        escalation_prevented=recommended < claim.assessment.requested_strength,
    )


def _is_absence_shaped(claim: Claim) -> bool:
    """True when the claim is an absence claim or reaches universal wording (Product 10.5)."""
    return (
        claim.type is ClaimType.ABSENCE or effective_scope(claim) is ClaimScope.UNIVERSAL_OR_ABSENCE
    )


def _qualifying(claim: Claim) -> tuple[EvidenceId, ...]:
    """Evidence that narrows the claim: `qualifies` plus anything already incomparable."""
    return tuple(link.evidence for link in claim.relations if link.relation in QUALIFYING_RELATIONS)


def _missing_evidence_warnings(audit_input: ClaimAuditInput) -> list[str]:
    """Relations whose evidence was not supplied; an unresolvable id decides nothing."""
    return [
        f"{link.evidence} is linked to {audit_input.claim.id} as {link.relation.value} but was "
        "not supplied, so it was not audited"
        for link in audit_input.claim.relations
        if link.evidence not in audit_input.evidence
    ]


def _review_contradictions(
    audit_input: ClaimAuditInput,
) -> tuple[tuple[ProposedRelationChange, ...], list[str]]:
    """Propose reclassifying every contradiction that is not measuring the same thing.

    A contradiction is a contradiction only against support it is commensurable with. When
    no accepted supporting evidence shares its metric, dataset, condition, and kind, the
    honest label is `incomparable_under_current_evidence` and the audit proposes it,
    naming the axes and the closest support so a reviewer can check the reasoning.
    """
    claim = audit_input.claim
    supports = [
        item
        for evidence_id in claim.supporting
        for item in (audit_input.accepted(evidence_id),)
        if item is not None
    ]
    proposals: list[ProposedRelationChange] = []
    warnings: list[str] = []
    for link in claim.relations:
        if link.relation is not ClaimEvidenceRelationType.CONTRADICTS:
            continue
        item = audit_input.evidence.get(link.evidence)
        if item is None:
            continue
        if not supports:
            warnings.append(
                f"{item.id} contradicts {claim.id} but there is no accepted supporting "
                "evidence to compare it against, so comparability could not be judged"
            )
            continue
        closest = min(supports, key=lambda support: len(comparison_differences(item, support)))
        differences = comparison_differences(item, closest)
        if not differences:
            continue
        proposals.append(
            ProposedRelationChange(
                evidence=item.id,
                current=link.relation,
                proposed=ClaimEvidenceRelationType.INCOMPARABLE_UNDER_CURRENT_EVIDENCE,
                note=(
                    f"{item.id} differs from every accepted support in "
                    f"{', '.join(differences)} (closest: {closest.id}); a result measured "
                    "differently is incomparable under the current evidence, not a direct "
                    "contradiction. This is a proposal: the claim's relations are unchanged "
                    "until a researcher accepts it."
                ),
            )
        )
    return tuple(proposals), warnings


def _find_counter_candidates(audit_input: ClaimAuditInput) -> tuple[RetrievalCandidate, ...]:
    """Ask the retrieval engine what would break the claim; refuse anything but candidates."""
    finder = audit_input.counter_finder
    if finder is None:
        return ()
    found = finder.find_counter_evidence(audit_input.claim, limit=audit_input.counter_limit)
    for item in found:
        if not isinstance(item, RetrievalCandidate):
            raise DomainValidationError(
                "counter-evidence retrieval returns RetrievalCandidate proposals, never "
                f"Evidence; got {type(item).__name__} (ADR-003, ADR-006)"
            )
    return tuple(found)


# ----------------------------------------------------------------------------- role inputs


def claim_payload(claim: Claim) -> dict[str, Any]:
    """What a role learns about the claim: the proposition and its corpus, never the ask.

    `assessment` and the scope ladder level are withheld on purpose. A role told that the
    researcher wants a field-level statement is being invited to agree with it, and the
    Skeptic's and Auditor's job is to bound the claim, not to ratify it (ROADMAP 7.4).
    """
    return {
        "id": str(claim.id),
        "statement": claim.statement,
        "type": claim.type.value,
        "semantics": claim.semantics.model_dump(mode="json"),
        "corpus": claim.scope.corpus,
        "publication_until": claim.scope.publication_until,
        "coverage": claim.coverage.model_dump(mode="json"),
    }


def evidence_payload(
    item: Evidence, relation: ClaimEvidenceRelationType | None = None
) -> dict[str, Any]:
    """One accepted evidence object as a role may read it.

    The verifier's rationale and the extractor's judgement are left out: a later role must
    not treat an earlier one's deliberation as a source fact (Product 43, ADR-003).
    """
    payload: dict[str, Any] = {
        "id": str(item.id),
        "work": str(item.source.work),
        "version": str(item.source.version),
        "block": str(item.source.block),
        "page": item.source.page,
        "section_path": list(item.source.section_path),
        "origin": item.origin.value,
        "evidence_type": item.evidence_type.value,
        "strength": item.strength.value,
        "exact_text": item.content.exact_text,
    }
    if relation is not None:
        payload["relation"] = relation.value
    if item.content.numeric is not None:
        payload["numeric"] = item.content.numeric.model_dump(mode="json")
    if item.content.negative_state is not None:
        payload["negative_state"] = item.content.negative_state.value
    if item.qualification:
        payload["qualification"] = item.qualification
    return payload


def _accepted_evidence_inputs(audit_input: ClaimAuditInput) -> list[RoleInput]:
    """Every accepted, fresh evidence object the claim links to, one envelope each."""
    inputs: list[RoleInput] = []
    for link in audit_input.claim.relations:
        item = audit_input.accepted(link.evidence)
        if item is None:
            continue
        inputs.append(
            RoleInput(
                kind=InputKind.ACCEPTED_EVIDENCE,
                object_id=str(item.id),
                content=evidence_payload(item, link.relation),
            )
        )
    return inputs


def _search_run_inputs(search_runs: Sequence[SearchRun]) -> list[RoleInput]:
    """The recorded search behind the coverage, including what it could not finish."""
    return [
        RoleInput(
            kind=InputKind.SEARCH_RUN,
            object_id=str(run.id),
            content={
                "id": str(run.id),
                "question": run.question,
                "sources": list(run.sources),
                "queries": list(run.queries),
                "results": run.results.model_dump(mode="json"),
                "cutoff": None if run.cutoff is None else run.cutoff.isoformat(),
                "failures": [failure.model_dump(mode="json") for failure in run.failures],
                "unresolved_identities": list(run.unresolved_identities),
            },
        )
        for run in search_runs
    ]


def _candidate_inputs(candidates: Sequence[RetrievalCandidate]) -> list[RoleInput]:
    """Counter candidates as retrieval results: hints to check, never evidence."""
    if not candidates:
        return []
    return [
        RoleInput(
            kind=InputKind.RETRIEVAL_RESULTS,
            object_id=None,
            content={
                "note": "retrieval candidates; they are not evidence and are not accepted",
                "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            },
        )
    ]


def build_skeptic_request(
    audit_input: ClaimAuditInput, result: ClaimAuditResult
) -> RoleRequest[BaseModel]:
    """The Skeptic's whole world: the proposition, the accepted evidence, and what was searched.

    It never sees the requested strength, so "the researcher wants this to be strong" is
    not an input to the search for what would make it wrong.
    """
    inputs = [
        RoleInput(
            kind=InputKind.ACCEPTED_CLAIMS,
            object_id=str(audit_input.claim.id),
            content=claim_payload(audit_input.claim),
        ),
        *_accepted_evidence_inputs(audit_input),
        *_candidate_inputs(result.counter_candidates),
        *_search_run_inputs(audit_input.search_runs),
    ]
    return build_request(SKEPTIC, inputs)


def build_auditor_request(
    audit_input: ClaimAuditInput, result: ClaimAuditResult
) -> RoleRequest[BaseModel]:
    """The Claim Auditor's request, built only from state every provider would see.

    It depends on the claim, its accepted evidence, the counter candidates on the table,
    and the search record — never on an earlier provider's answer. That is what lets the
    same request be replayed on a second provider and the two be compared (Product 20.4).
    """
    inputs = [
        RoleInput(
            kind=InputKind.ACCEPTED_CLAIMS,
            object_id=str(audit_input.claim.id),
            content=claim_payload(audit_input.claim),
        ),
        *_accepted_evidence_inputs(audit_input),
        *_candidate_inputs(result.counter_candidates),
        *_search_run_inputs(audit_input.search_runs),
    ]
    return build_request(CLAIM_AUDITOR, inputs)


# ---------------------------------------------------------------------------- model passes


def apply_skeptic(result: ClaimAuditResult, audit_input: ClaimAuditInput) -> ClaimAuditResult:
    """Run the Skeptic and record what it found as proposals; returns the result unchanged
    when no skeptic provider is configured."""
    client = audit_input.skeptic
    if client is None:
        return result
    assert_can_write(SKEPTIC, WriteScope.AUDIT_RESULT)
    built = build_skeptic_request(audit_input, result)
    _log_stripped(SKEPTIC.name, built)
    response = client.complete(built.request)
    output = response.parsed
    if not isinstance(output, SkepticOutput):  # pragma: no cover - the schema is fixed
        raise TypeError(f"skeptic returned {type(output).__name__}, not SkepticOutput")

    candidates = [_candidate_from_output(item) for item in output.counter_candidates]
    notes = [_qualifier_note(item.text, item.evidence_refs) for item in output.qualifiers]
    warnings = [f"skeptic: {note}" for note in output.incomparability_notes]
    return result.touch(
        counter_candidates=(*result.counter_candidates, *candidates),
        qualifier_notes=(*result.qualifier_notes, *notes),
        warnings=(*result.warnings, *warnings),
        model_judgements=(
            *result.model_judgements,
            ModelJudgement(
                role=SKEPTIC.name,
                provider=response.provider,
                model=response.model,
                output=output,
                request_fingerprint=response.request_fingerprint,
            ),
        ),
    )


def apply_auditor(
    result: ClaimAuditResult,
    audit_input: ClaimAuditInput,
    *,
    request: ModelRequest[BaseModel] | None = None,
) -> ClaimAuditResult:
    """Run the Claim Auditor; its answer may only narrow what the engine already allows.

    A recommended scope below the deterministic ceiling is adopted, together with any
    qualifier or counter-evidence it names. A recommended scope *above* the ceiling is
    ignored with a warning: an auditor exists to falsify a claim, not to maximize support
    for it (ROADMAP 7.4, Product 42.G).

    Its proposed wording is kept beside the deterministic ceiling as `proposed_wording`,
    never in place of it: the model may not raise the ceiling, but it can phrase what sits
    under it, and that sentence used to be computed and discarded (dogfood F15).
    """
    client = audit_input.auditor
    if client is None:
        return result
    assert_can_write(CLAIM_AUDITOR, WriteScope.AUDIT_RESULT)
    if request is None:
        built = build_auditor_request(audit_input, result)
        _log_stripped(CLAIM_AUDITOR.name, built)
        request = built.request
    response = client.complete(request)
    output = response.parsed
    if not isinstance(output, ClaimAuditOutput):  # pragma: no cover - the schema is fixed
        raise TypeError(f"claim auditor returned {type(output).__name__}, not ClaimAuditOutput")

    warnings = [f"auditor: {note}" for note in output.independence_warnings]
    scope = result.recommended_scope
    wording = result.maximum_defensible_wording
    if output.recommended_scope > result.recommended_scope:
        warnings.append(
            f"the claim auditor recommended {output.recommended_scope.label} above the "
            f"{result.recommended_scope.label} the evidence defends; it was ignored, because "
            "an auditor tries to falsify a claim, not to maximize support for it"
        )
    elif output.recommended_scope < result.recommended_scope:
        scope = output.recommended_scope
        wording = wording_for(
            scope,
            audit_input.claim.type,
            audit_input.claim.coverage,
            result.assessment.support_ratio,
        )
        warnings.append(
            f"the claim auditor lowered the recommended scope from "
            f"{result.recommended_scope.label} to {scope.label}"
        )

    counter, unknown = _known_evidence(
        output.counter_evidence, audit_input, result.counter_evidence
    )
    warnings.extend(
        f"the claim auditor named counter-evidence that was not supplied: {name}"
        for name in unknown
    )
    warnings.extend(
        f"the claim auditor named support the claim does not record: {name}; a model never "
        "adds support to a claim"
        for name in output.support
        if EvidenceId(name) not in result.support
    )
    return result.touch(
        counter_evidence=(*result.counter_evidence, *counter),
        qualifier_notes=(*result.qualifier_notes, *output.qualifiers),
        recommended_scope=scope,
        maximum_defensible_wording=wording,
        proposed_wording=output.maximum_defensible_wording,
        escalation_prevented=scope < audit_input.claim.assessment.requested_strength,
        warnings=(*result.warnings, *warnings),
        model_judgements=(
            *result.model_judgements,
            ModelJudgement(
                role=CLAIM_AUDITOR.name,
                provider=response.provider,
                model=response.model,
                output=output,
                request_fingerprint=response.request_fingerprint,
            ),
        ),
    )


def select_cross_verify_gate(
    audit_input: ClaimAuditInput, policy: CrossVerifyPolicy = DEFAULT_POLICY
) -> Eligibility | None:
    """The first enabled gate that applies to this claim, or ``None`` when none does.

    Returning ``None`` is the common case and the intended one: routine audits are not
    cross-verified (Product 20.4).
    """
    numeric = _numeric_evidence(audit_input)
    for gate in GATE_ORDER:
        verdict = is_eligible(
            policy,
            gate,
            claim=audit_input.claim,
            evidence=numeric,
            manuscript_attached=audit_input.manuscript_attached,
            submission_ready=audit_input.submission_ready,
        )
        if verdict.eligible:
            return verdict
    return None


def available_providers(audit_input: ClaimAuditInput) -> tuple[ProviderCandidate, ...]:
    """Providers a cross-verification may use: the declared ones, else the configured clients.

    A router contributes every entry that may answer for the claim auditor, so a workspace
    with two configured vendors can cross-verify without naming them a second time.
    """
    if audit_input.cross_verify_providers:
        return audit_input.cross_verify_providers
    found: list[ProviderCandidate] = []
    seen: set[tuple[str, str]] = set()
    for client in (audit_input.auditor, audit_input.skeptic):
        if client is None:
            continue
        for provider, model in _pairs_of(client):
            if (provider.name, model) in seen:
                continue
            seen.add((provider.name, model))
            found.append((provider, model))
    return tuple(found)


def trace_sink_for(audit_input: ClaimAuditInput) -> TraceSink | None:
    """The disposable trace sink the audit's own clients write to, if any.

    :func:`available_providers` pulls individual providers *out* of a router, so the
    router's `complete` -- the thing that attaches its sink -- is never called for a
    cross-verification. Recovering the sink here is what keeps the second opinion in
    `.research/traces/` beside the first (Product 19.3).
    """
    from research_harness.privacy.traces import sink_of

    for client in (audit_input.auditor, audit_input.skeptic):
        sink = sink_of(client)
        if sink is not None:
            return sink
    return None


def apply_cross_verification(
    result: ClaimAuditResult,
    audit_input: ClaimAuditInput,
    *,
    request: ModelRequest[BaseModel] | None = None,
    policy: CrossVerifyPolicy | None = None,
) -> ClaimAuditResult:
    """Cross-verify the audit at a high-value gate and attach any provider disagreement.

    A conflict is attached, never resolved: no provider's answer overwrites another and
    none of them changes the recommended scope. Agreement is recorded and accepts nothing
    (ADR-007, ROADMAP Task 13.2).
    """
    active = policy if policy is not None else DEFAULT_POLICY
    eligibility = select_cross_verify_gate(audit_input, active)
    if eligibility is None:
        return result
    if request is None:
        request = build_auditor_request(audit_input, result).request
    verification = cross_verify(
        request,
        available_providers(audit_input),
        gate=eligibility.gate,
        policy=active,
        eligibility=eligibility,
        decision_fields=AUDIT_DECISION_FIELDS,
        subject=str(audit_input.claim.id),
        trace=trace_sink_for(audit_input),
    )
    warnings = list(result.warnings)
    if verification.conflict is not None:
        warnings.append(f"cross-verification: {verification.conflict.summary}")
    elif verification.skipped_reason:
        warnings.append(
            f"cross-verification at gate {eligibility.gate.value} did not complete: "
            f"{verification.skipped_reason}"
        )
    return result.touch(
        cross_verification=verification,
        conflict=verification.conflict,
        warnings=tuple(warnings),
    )


def audit_claim(
    audit_input: ClaimAuditInput, *, cross_verify_policy: CrossVerifyPolicy | None = None
) -> ClaimAuditResult:
    """The whole audit: deterministic first, then the Skeptic, the Auditor, and any gate.

    Every model step can only narrow the result. The order matters: the ceiling exists
    before any model is asked, so there is always something for a model recommendation to
    be compared against rather than to define.
    """
    result = audit_claim_locally(audit_input)
    result = apply_skeptic(result, audit_input)
    request = build_auditor_request(audit_input, result).request
    result = apply_auditor(result, audit_input, request=request)
    return apply_cross_verification(
        result, audit_input, request=request, policy=cross_verify_policy
    )


# -------------------------------------------------------------------------------- outcome


def to_assessment(result: ClaimAuditResult, claim: Claim) -> ClaimAssessment:
    """The `ClaimAssessment` this audit writes: the ask untouched, the ceiling enforced.

    `allowed_strength` is the lowest of the requested scope, the recommended scope, and the
    deterministic engine's own ceiling. Applying the engine's ceiling a second time is
    deliberate: a result whose `recommended_scope` was raised by hand still cannot escalate
    a claim (Product 42.G). The status is the audit's, so a claim capped below its request
    is recorded as `qualified`.
    """
    allowed = min(
        claim.assessment.requested_strength, result.recommended_scope, result.assessment.allowed
    )
    return claim.assessment.touch(
        status=result.status,
        allowed_strength=allowed,
        maximum_defensible_wording=result.maximum_defensible_wording,
        audited_at=utc_now(),
    )


def apply_audit(claim: Claim, result: ClaimAuditResult, *, actor: str) -> Claim:
    """Record the audit on the claim through the domain transition; never escalates.

    Raising strength above the auditor's recommendation is not reachable from here at all:
    it requires an accepted `epistemic_override` Decision and
    :func:`research_harness.domain.transitions.override_claim_strength` (Product 38,
    ROADMAP Task 7.5). A re-audit that confirms the current status is an ordinary
    transition: `CLAIM_TRANSITIONS` carries a self-edge for every audited status.
    """
    assessment = to_assessment(result, claim)
    return transitions.audit_claim(
        claim,
        status=assessment.status,
        allowed_strength=assessment.allowed_strength,
        actor=actor,
        maximum_defensible_wording=assessment.maximum_defensible_wording,
    )


# ------------------------------------------------------------------------------- internals


def _numeric_evidence(audit_input: ClaimAuditInput) -> Evidence | None:
    """The first accepted supporting evidence carrying a measured value, if any."""
    for evidence_id in audit_input.claim.supporting:
        item = audit_input.accepted(evidence_id)
        if item is not None and item.content.numeric is not None:
            return item
    return None


def backend_label(client: _ModelClient | None, contract: RoleContract) -> str | None:
    """``provider/model`` a role's request would go to, without sending it.

    A stage fingerprint has to name the model that produced an answer, so re-running an
    audit on another provider recomputes that stage and nothing before it (Product 19.1).
    ``None`` means no model pass runs at all: the deterministic audit names no backend
    rather than naming a fictional one. `providers.models.describe_backend` decides the
    rest, so this and `evidence.extraction.resolve_backend` cannot answer differently.
    """
    if client is None:
        return None
    return describe_backend(client, contract).label


def _pairs_of(client: _ModelClient) -> list[tuple[ModelProvider, str]]:
    """The provider/model pairs behind a client; a router contributes every capable entry."""
    if isinstance(client, ModelRouter):
        return [
            (entry.provider, entry.model)
            for entry in client.entries
            if entry.roles is None or CLAIM_AUDITOR.name in entry.roles
        ]
    return [(client, _model_of(client))]


def _model_of(provider: ModelProvider) -> str:
    """The model identifier an adapter was configured with, for reproducibility metadata.

    The contract is only consulted for a router; a bare adapter answers with the model it
    was configured with, whichever role is asking.
    """
    return describe_backend(provider, CLAIM_AUDITOR).model


def _candidate_from_output(candidate: EvidenceCandidateOutput) -> RetrievalCandidate:
    """A Skeptic proposal as a retrieval candidate; it is not evidence and is not anchored."""
    location = f"block {candidate.block}"
    if candidate.page is not None:
        location = f"{location}, page {candidate.page}"
    if candidate.char_start is not None and candidate.char_end is not None:
        location = f"{location}, chars {candidate.char_start}-{candidate.char_end}"
    return RetrievalCandidate(
        ref=candidate.block,
        text=candidate.exact_text,
        source=SKEPTIC_SOURCE,
        location=location,
    )


def _qualifier_note(text: str, refs: Sequence[str]) -> str:
    """A qualifier plus the evidence it rests on, so a reviewer can check it."""
    return f"{text} ({', '.join(refs)})" if refs else text


def _known_evidence(
    named: Iterable[str], audit_input: ClaimAuditInput, already: Sequence[EvidenceId]
) -> tuple[tuple[EvidenceId, ...], tuple[str, ...]]:
    """Split model-named evidence ids into the ones that were supplied and the rest."""
    known: list[EvidenceId] = []
    unknown: list[str] = []
    for name in named:
        evidence_id = EvidenceId(name)
        if evidence_id not in audit_input.evidence:
            unknown.append(name)
        elif evidence_id not in already and evidence_id not in known:
            known.append(evidence_id)
    return tuple(known), tuple(unknown)


def _log_stripped(role: str, built: RoleRequest[BaseModel]) -> None:
    """Say when a caller handed an earlier role's deliberation forward; it was dropped."""
    if built.stripped_fields:  # pragma: no cover - audit payloads carry no reasoning fields
        logger.warning(
            "dropped hidden-reasoning fields from a %s request: %s",
            role,
            ", ".join(built.stripped_fields),
        )
