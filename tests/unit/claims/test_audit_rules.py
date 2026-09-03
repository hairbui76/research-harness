"""The rules a claim audit enforces: falsify, never maximize; propose, never rewrite.

ROADMAP Task 7.4: the auditor tries to falsify or qualify a claim rather than maximize
support for it, and results that differ under different metrics, datasets, or conditions
are not labelled direct contradictions merely because their outcomes differ. Product 42.G:
strength cannot escalate silently, so no audit result — hand-built or model-influenced —
can lift a claim above the requested scope or above the deterministic engine's ceiling.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from research_harness.claims.audit import (
    ClaimAuditInput,
    ClaimAuditResult,
    RetrievalCandidate,
    apply_audit,
    apply_auditor,
    audit_claim,
    audit_claim_locally,
    comparison_differences,
    to_assessment,
)
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    Coverage,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    EvidenceStatus,
    EvidenceType,
    OverturnRisk,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import Evidence, EvidenceContent, VerificationRecord
from research_harness.domain.ids import ArtifactId, EvidenceId, VersionId, WorkId
from research_harness.domain.work import Work
from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelProvider,
    ModelRequest,
    ProviderCapabilities,
    RawCompletion,
    Usage,
)
from tests.unit.domain import strategies as sty

ACCEPTED = VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by="human")
DATASET = "CICIDS2017"
OTHER_DATASET = "UNSW-NB15"


# ------------------------------------------------------------------------------- builders


def numeric(dataset: str = DATASET, metric: str = "F1", **overrides: Any) -> Any:
    """A measured value with the provenance Product 12 requires."""
    return sty.make_numeric(dataset=dataset, metric=metric, **overrides)


def evidence(
    number: int,
    work: int,
    version: int = 1,
    *,
    dataset: str | None = DATASET,
    metric: str = "F1",
    evidence_type: EvidenceType = EvidenceType.EXPERIMENTAL_RESULT,
    accepted: bool = True,
) -> Evidence:
    """Accepted, source-observed evidence anchored in one version of one work."""
    return sty.make_evidence(
        id=EvidenceId.make(number),
        source=sty.make_anchor(
            work=WorkId.make(work),
            version=VersionId.make(work, version),
            artifact=ArtifactId.make(work, version),
        ),
        content=EvidenceContent(
            exact_text=f"We report {metric} on {dataset}.",
            numeric=None if dataset is None else numeric(dataset, metric),
        ),
        evidence_type=evidence_type,
        verification=ACCEPTED if accepted else VerificationRecord(),
    )


def work(number: int, *authors: str) -> Work:
    return sty.make_work(id=WorkId.make(number), title=f"Paper {number}", authors=authors)


SUPPORTS = ClaimEvidenceRelationType.SUPPORTS
CONTRADICTS = ClaimEvidenceRelationType.CONTRADICTS


def claim(
    *relations: tuple[EvidenceId, ClaimEvidenceRelationType],
    requested: ClaimScope = ClaimScope.FIELD_GENERALIZATION,
    declared: ClaimScope = ClaimScope.CORPUS_PATTERN,
    claim_type: ClaimType = ClaimType.PREVALENCE,
    coverage: Coverage | None = None,
) -> Claim:
    """A claim deliberately asked to be stronger than its evidence (Gate P7)."""
    return sty.make_claim(
        type=claim_type,
        scope=ClaimScopeSpec(level=declared, corpus="structured-traffic-llm"),
        relations=tuple(
            ClaimEvidenceRelation(evidence=item, relation=relation) for item, relation in relations
        ),
        coverage=coverage
        if coverage is not None
        else Coverage(
            relevant_works=10,
            examined_works=8,
            unresolved_works=0,
            overturn_risk=OverturnRisk.LOW_MODERATE,
            search_runs=(sty.make_search_run().id,),
            cutoff=sty.make_search_run().executed_at.date(),
        ),
        assessment=ClaimAssessment(
            requested_strength=requested, allowed_strength=ClaimScope.INDIVIDUAL
        ),
    )


def corpus() -> tuple[Claim, dict[EvidenceId, Evidence], dict[WorkId, Work]]:
    """Four supports across three works (two of them versions of one), one contradiction.

    The contradiction is measured on another dataset, which is what makes it incomparable
    rather than contradictory.
    """
    items = [
        evidence(1, work=1, version=1),
        evidence(2, work=1, version=2),
        evidence(3, work=2),
        evidence(4, work=3),
        evidence(9, work=4, dataset=OTHER_DATASET),
    ]
    subject = claim(
        (items[0].id, SUPPORTS),
        (items[1].id, SUPPORTS),
        (items[2].id, SUPPORTS),
        (items[3].id, SUPPORTS),
        (items[4].id, CONTRADICTS),
    )
    works = {
        item.id: item
        for item in (
            work(1, "A. First"),
            work(2, "B. Second"),
            work(3, "C. Third"),
            work(4, "D. Fourth"),
        )
    }
    return subject, {item.id: item for item in items}, works


def audit_input(**overrides: Any) -> ClaimAuditInput:
    subject, items, works = corpus()
    fields: dict[str, Any] = {
        "claim": subject,
        "evidence": items,
        "works": works,
        "search_runs": [sty.make_search_run()],
    }
    return ClaimAuditInput(**{**fields, **overrides})


# --------------------------------------------------------------------------- fake provider


class FakeAuditor(ModelProvider):
    """A model that answers with exactly the structured output the test hands it."""

    def __init__(self, name: str, answer: dict[str, Any], *, model: str = "fake-1") -> None:
        self.name = name
        self.model = model
        self._answer = answer
        self.calls: list[ModelRequest[Any]] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            structured_output=True,
            max_context_tokens=1_000_000,
            reasoning_levels={"low", "medium", "high"},
            vision=False,
            egress=EgressDeclaration(
                endpoint_host=f"{self.name}.invalid",
                sends_source_text=False,
                sends_identifiers=False,
                description="fake provider used in tests",
            ),
        )

    def _execute(self, request: ModelRequest[Any], schema_json: dict[str, Any]) -> RawCompletion:
        self.calls.append(request)
        return RawCompletion(
            text=json.dumps(self._answer),
            usage=Usage(input_tokens=1, output_tokens=1),
            model=self.model,
            stop_reason="stop",
        )


def audit_output(scope: ClaimScope, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "support": [],
        "counter_evidence": [],
        "qualifiers": [],
        "independence_warnings": [],
        "coverage_state": "8 of 10 relevant works examined",
        "recommended_scope": scope.value,
        "maximum_defensible_wording": "Most systems in the reviewed corpus tokenize traffic.",
        "rationale": "The corpus supports a pattern, not a field-level generalization.",
    }
    return {**payload, **overrides}


# ------------------------------------------------------------- incomparability, not conflict


def test_a_result_on_another_dataset_is_incomparable_rather_than_contradictory() -> None:
    result = audit_claim_locally(audit_input())

    assert [str(change.evidence) for change in result.incomparable] == ["E0009"]
    change = result.incomparable[0]
    assert change.current is CONTRADICTS
    assert change.proposed is ClaimEvidenceRelationType.INCOMPARABLE_UNDER_CURRENT_EVIDENCE
    assert "dataset" in change.note
    assert "proposal" in change.note
    assert result.proposed_relation_changes == result.incomparable


def test_a_result_measured_the_same_way_stays_a_contradiction() -> None:
    subject, items, works = corpus()
    items[EvidenceId("E0009")] = evidence(9, work=4, dataset=DATASET)
    result = audit_claim_locally(
        ClaimAuditInput(
            claim=subject, evidence=items, works=works, search_runs=[sty.make_search_run()]
        )
    )
    assert result.incomparable == ()
    assert EvidenceId("E0009") in result.counter_evidence


def test_the_audit_proposes_but_never_rewrites_a_relation() -> None:
    data = audit_input()
    before = data.claim.relations
    result = audit_claim_locally(data)
    audited = apply_audit(data.claim, result, actor="human:alice")

    assert data.claim.relations == before
    assert audited.relations == before
    assert audited.contradicting == (EvidenceId("E0009"),)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (evidence(1, work=1), evidence(2, work=2), ()),
        (evidence(1, work=1), evidence(2, work=2, dataset=OTHER_DATASET), ("dataset",)),
        (evidence(1, work=1), evidence(2, work=2, metric="accuracy"), ("metric",)),
        (
            evidence(1, work=1),
            evidence(2, work=2, dataset=None),
            ("measurement",),
        ),
        (
            evidence(1, work=1),
            evidence(2, work=2, evidence_type=EvidenceType.LIMITATION),
            ("evidence_type",),
        ),
    ],
    ids=["same", "dataset", "metric", "number-vs-prose", "kind"],
)
def test_comparison_differences_names_every_axis(
    left: Evidence, right: Evidence, expected: tuple[str, ...]
) -> None:
    assert comparison_differences(left, right) == expected


# --------------------------------------------------------------- independence and coverage


def test_two_versions_of_one_work_are_one_unit_of_support() -> None:
    result = audit_claim_locally(audit_input())

    assert result.independence.effective_support == 3
    assert result.assessment.independent_support == 3
    assert any("versions" in warning for warning in result.warnings)


def test_a_claim_asked_to_be_stronger_than_its_evidence_is_lowered() -> None:
    result = audit_claim_locally(audit_input())

    assert result.assessment.requested is ClaimScope.FIELD_GENERALIZATION
    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert result.escalation_prevented is True
    assert result.assessment.status is ClaimStatus.QUALIFIED
    assert "several existing approaches" in result.maximum_defensible_wording
    assert "8 of 10 relevant works examined" in result.coverage_state


def exhaustive_absence_corpus() -> ClaimAuditInput:
    """Five independent works, a fully examined corpus, and an absence claim at L4.

    Everything the ladder asks of universal wording is satisfied, so the only thing left
    that can refuse it is the search record itself.
    """
    items = [evidence(number, work=number) for number in range(1, 6)]
    subject = claim(
        *((item.id, SUPPORTS) for item in items),
        requested=ClaimScope.UNIVERSAL_OR_ABSENCE,
        declared=ClaimScope.UNIVERSAL_OR_ABSENCE,
        claim_type=ClaimType.ABSENCE,
        coverage=Coverage(
            relevant_works=5,
            examined_works=5,
            unresolved_works=0,
            overturn_risk=OverturnRisk.LOW,
            search_runs=(sty.make_search_run().id,),
            cutoff=sty.make_search_run().executed_at.date(),
        ),
    )
    works = {WorkId.make(number): work(number, f"Author {number}") for number in range(1, 6)}
    return ClaimAuditInput(
        claim=subject,
        evidence={item.id: item for item in items},
        works=works,
        search_runs=[sty.make_search_run()],
    )


def test_an_exhaustive_search_record_permits_the_universal_wording() -> None:
    result = audit_claim_locally(exhaustive_absence_corpus())

    assert result.recommended_scope is ClaimScope.UNIVERSAL_OR_ABSENCE
    assert "permits an absence claim" in result.coverage_state
    assert result.maximum_defensible_wording.startswith("within the reviewed corpus")
    assert "we identified no work that" in result.maximum_defensible_wording


def test_an_absence_claim_the_search_record_cannot_support_is_capped_below_universal() -> None:
    stalled = sty.make_search_run(
        cursors=(
            {"source": "openalex", "query": "traffic", "pages_fetched": 2, "exhausted": False},
        )
    )
    data = exhaustive_absence_corpus()
    result = audit_claim_locally(
        ClaimAuditInput(
            claim=data.claim,
            evidence=data.evidence,
            works=data.works,
            search_runs=[stalled],
        )
    )

    assert result.recommended_scope is ClaimScope.FIELD_GENERALIZATION
    assert result.escalation_prevented is True
    assert result.status is ClaimStatus.QUALIFIED
    assert "does not permit an absence claim" in result.coverage_state
    assert any(warning.startswith("absence:") for warning in result.warnings)
    assert "we identified no work that" in result.maximum_defensible_wording


# ------------------------------------------------------------------ models may only narrow


def test_a_model_recommending_a_higher_scope_is_ignored_with_a_warning() -> None:
    data = audit_input(
        auditor=FakeAuditor("vendor-a", audit_output(ClaimScope.UNIVERSAL_OR_ABSENCE))
    )
    local = audit_claim_locally(data)
    result = apply_auditor(local, data)

    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert result.maximum_defensible_wording == local.maximum_defensible_wording
    assert any("falsify" in warning for warning in result.warnings)
    assert any("ignored" in warning for warning in result.warnings)


def test_a_model_lowering_the_scope_is_adopted_with_the_engine_s_own_wording() -> None:
    data = audit_input(auditor=FakeAuditor("vendor-a", audit_output(ClaimScope.OBSERVED_SUBSET)))
    result = apply_auditor(audit_claim_locally(data), data)

    assert result.recommended_scope is ClaimScope.OBSERVED_SUBSET
    assert result.maximum_defensible_wording == "among the papers examined"
    assert any("lowered the recommended scope" in warning for warning in result.warnings)


def test_the_auditors_proposed_wording_is_kept_beside_the_deterministic_ceiling() -> None:
    """Dogfood F15: `maximum_defensible_wording` was required of the model and discarded.

    The auditor's sentence is the ceiling said in this claim's own terms, which is what a
    writer wants; it is advice beside the deterministic ceiling and never in place of it.
    """
    data = audit_input(
        auditor=FakeAuditor("vendor-a", audit_output(ClaimScope.UNIVERSAL_OR_ABSENCE))
    )
    local = audit_claim_locally(data)
    result = apply_auditor(local, data)

    assert result.proposed_wording == "Most systems in the reviewed corpus tokenize traffic."
    assert result.maximum_defensible_wording == local.maximum_defensible_wording
    assert result.recommended_scope is local.recommended_scope
    assert local.proposed_wording == "", "an audit with no auditor proposes no wording"


def test_a_model_naming_evidence_it_was_never_given_is_refused() -> None:
    data = audit_input(
        auditor=FakeAuditor(
            "vendor-a",
            audit_output(ClaimScope.CORPUS_PATTERN, counter_evidence=["E7777"], support=["E8888"]),
        )
    )
    result = apply_auditor(audit_claim_locally(data), data)

    assert EvidenceId("E7777") not in result.counter_evidence
    assert any("was not supplied" in warning for warning in result.warnings)
    assert any("adds support" in warning for warning in result.warnings)


def test_the_model_judgement_is_kept_with_its_provider_and_fingerprint() -> None:
    provider = FakeAuditor("vendor-a", audit_output(ClaimScope.CORPUS_PATTERN), model="model-x")
    data = audit_input(auditor=provider)
    result = apply_auditor(audit_claim_locally(data), data)

    assert len(result.model_judgements) == 1
    judgement = result.model_judgements[0]
    assert judgement.role == "claim_auditor"
    assert judgement.label == "vendor-a/model-x"
    assert judgement.request_fingerprint == provider.calls[0].fingerprint()


def test_the_auditor_is_never_told_what_strength_the_researcher_asked_for() -> None:
    provider = FakeAuditor("vendor-a", audit_output(ClaimScope.CORPUS_PATTERN))
    data = audit_input(auditor=provider)
    audit_claim(data, cross_verify_policy=None)

    rendered = "\n".join(envelope.content for envelope in provider.calls[0].inputs)
    assert "requested_strength" not in rendered
    assert ClaimScope.FIELD_GENERALIZATION.value not in rendered
    assert data.claim.statement in rendered


# --------------------------------------------------------------- counter-evidence proposals


class FakeFinder:
    """Retrieval that returns one candidate; the audit may propose it, never accept it."""

    def find_counter_evidence(self, claim: Claim, *, limit: int) -> list[RetrievalCandidate]:
        return [
            RetrievalCandidate(
                ref="B0081",
                work=WorkId.make(5),
                text="On UNSW-NB15 the same tokenizer loses 8 points.",
                score=0.71,
                source="semantic_index",
                location="block B0081, page 4",
            )
        ][:limit]


class EvidenceReturningFinder:
    """A retrieval engine that mistakenly hands back accepted Evidence."""

    def find_counter_evidence(self, claim: Claim, *, limit: int) -> list[Any]:
        return [evidence(7, work=5)]


def test_counter_candidates_are_proposals_carrying_where_to_look() -> None:
    result = audit_claim_locally(audit_input(counter_finder=FakeFinder()))

    assert len(result.counter_candidates) == 1
    candidate = result.counter_candidates[0]
    assert candidate.ref == "B0081"
    assert candidate.source == "semantic_index"
    assert not isinstance(candidate, Evidence)


def test_retrieval_may_not_return_evidence() -> None:
    with pytest.raises(DomainValidationError, match="never"):
        audit_claim_locally(audit_input(counter_finder=EvidenceReturningFinder()))


# ------------------------------------------------------------------- no silent escalation


def test_to_assessment_keeps_the_request_and_caps_the_ceiling() -> None:
    data = audit_input()
    result = audit_claim_locally(data)
    assessment = to_assessment(result, data.claim)

    assert assessment.requested_strength is ClaimScope.FIELD_GENERALIZATION
    assert assessment.allowed_strength is ClaimScope.CORPUS_PATTERN
    assert assessment.status is ClaimStatus.QUALIFIED
    assert assessment.audited_at is not None
    assert assessment.maximum_defensible_wording == result.maximum_defensible_wording


def test_a_result_edited_to_be_stronger_than_the_engine_still_cannot_escalate() -> None:
    data = audit_input()
    engine_result = audit_claim_locally(data)
    tampered = engine_result.touch(recommended_scope=ClaimScope.UNIVERSAL_OR_ABSENCE)

    assessment = to_assessment(tampered, data.claim)
    assert assessment.allowed_strength <= data.claim.assessment.requested_strength
    assert assessment.allowed_strength is engine_result.assessment.allowed

    audited = apply_audit(data.claim, tampered, actor="human:alice")
    assert audited.allowed_strength is ClaimScope.CORPUS_PATTERN
    assert audited.requested_strength is ClaimScope.FIELD_GENERALIZATION


def test_applying_an_audit_twice_is_idempotent() -> None:
    data = audit_input()
    result = audit_claim_locally(data)
    once = apply_audit(data.claim, result, actor="human:alice")
    twice = apply_audit(once, result, actor="human:alice")

    assert twice.assessment.allowed_strength is once.assessment.allowed_strength
    assert twice.assessment.status is once.assessment.status
    assert twice.relations == data.claim.relations


def test_an_unsupported_claim_is_lowered_to_the_floor_rather_than_refused() -> None:
    subject = claim((EvidenceId("E0001"), SUPPORTS), requested=ClaimScope.CORPUS_PATTERN)
    unaccepted = evidence(1, work=1, accepted=False)
    result = audit_claim_locally(
        ClaimAuditInput(
            claim=subject,
            evidence={unaccepted.id: unaccepted},
            works={WorkId.make(1): work(1, "A. First")},
            search_runs=[sty.make_search_run()],
        )
    )

    assert result.recommended_scope is ClaimScope.INDIVIDUAL
    assert result.assessment.status is ClaimStatus.UNSUPPORTED
    assert result.escalation_prevented is True


def test_a_result_round_trips_through_json() -> None:
    """The workflow persists the audit between stages, so it must survive serialization."""
    data = audit_input(counter_finder=FakeFinder())
    result = audit_claim_locally(data)
    restored = ClaimAuditResult.model_validate(
        json.loads(json.dumps(result.model_dump(mode="json")))
    )
    assert restored == result
