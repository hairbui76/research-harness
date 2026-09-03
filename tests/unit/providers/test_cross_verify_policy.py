"""Selective cross-provider verification: which gates apply, and what disagreement produces.

Every assertion defends one rule from Product 20.4/25 and ROADMAP Task 13.1/13.2 and
Gate P13: routine work is not doubled, two providers that disagree become exactly one
explicit conflict rather than one silently overwriting the other, and agreement is recorded
without accepting anything.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from research_harness.domain.claim import ClaimAssessment, ClaimEvidenceRelation, ClaimScopeSpec
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    EvidenceType,
)
from research_harness.domain.evidence import Evidence, EvidenceContent
from research_harness.domain.ids import EvidenceId
from research_harness.providers.models.base import ModelRequest, ProviderError
from research_harness.providers.models.cross_verify import (
    CONFLICT_KIND,
    DEFAULT_POLICY,
    CrossVerification,
    CrossVerificationGate,
    CrossVerifyPolicy,
    Eligibility,
    ProviderConflict,
    ProviderPosition,
    cross_verify,
    decision_of,
    effective_scope,
    is_eligible,
    provider_label,
)
from research_harness.providers.models.router import ProviderEntry
from tests.unit.domain import strategies as sty
from tests.unit.providers.conftest import REQUIREMENTS, FakeProvider, Judgement

GATE = CrossVerificationGate.COUNTER_EVIDENCE_INTERPRETATION
DECISION_FIELDS = ("verdict",)


# ----------------------------------------------------------------------------- fixtures


def claim_at(
    level: ClaimScope,
    *,
    claim_type: ClaimType = ClaimType.PREVALENCE,
    contradicting: bool = False,
) -> Any:
    """A claim whose declared scope and requested strength are both `level`."""
    relations = (
        (
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0132"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0900"), relation=ClaimEvidenceRelationType.CONTRADICTS
            ),
        )
        if contradicting
        else (
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0132"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        )
    )
    return sty.make_claim(
        type=claim_type,
        scope=ClaimScopeSpec(level=level, corpus="structured-traffic-llm"),
        relations=relations,
        assessment=ClaimAssessment(
            requested_strength=level, allowed_strength=ClaimScope.INDIVIDUAL
        ),
    )


def numeric_evidence() -> Evidence:
    """Accepted evidence carrying a measured value with full provenance (Product 12)."""
    return sty.make_evidence(
        content=EvidenceContent(
            exact_text="F1 is 94.32 on CICIDS2017.", numeric=sty.make_numeric()
        ),
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
    )


def prose_evidence() -> Evidence:
    """Accepted evidence with no number in it."""
    return sty.make_evidence()


def request_for(schema: type[BaseModel] = Judgement) -> ModelRequest[Any]:
    """One neutral request every fake provider can answer."""
    return ModelRequest(
        role="claim_auditor",
        requirements=REQUIREMENTS,
        instructions="Report the strongest wording the evidence defends.",
        response_schema=schema,
        metadata={"subject": "C0041"},
    )


# --------------------------------------------------------------------------- eligibility


def test_default_policy_enables_exactly_the_five_roadmap_gates() -> None:
    assert DEFAULT_POLICY.enabled_gates == frozenset(CrossVerificationGate)
    assert DEFAULT_POLICY.min_providers == 2
    assert DEFAULT_POLICY.require_distinct_vendors is True
    assert DEFAULT_POLICY.max_extra_calls_per_object == 1


def test_effective_scope_is_the_more_ambitious_of_declared_and_requested() -> None:
    claim = sty.make_claim()  # declared L2, requested L3
    assert claim.scope.level is ClaimScope.CORPUS_PATTERN
    assert effective_scope(claim) is ClaimScope.FIELD_GENERALIZATION


ELIGIBILITY_TABLE: list[tuple[str, CrossVerificationGate, dict[str, Any], bool]] = [
    (
        "absence claim type",
        CrossVerificationGate.ABSENCE_CLAIM,
        {"claim": claim_at(ClaimScope.OBSERVED_SUBSET, claim_type=ClaimType.ABSENCE)},
        True,
    ),
    (
        "universal wording",
        CrossVerificationGate.ABSENCE_CLAIM,
        {"claim": claim_at(ClaimScope.UNIVERSAL_OR_ABSENCE)},
        True,
    ),
    (
        "ordinary corpus claim",
        CrossVerificationGate.ABSENCE_CLAIM,
        {"claim": claim_at(ClaimScope.CORPUS_PATTERN)},
        False,
    ),
    (
        "numeric carrying a corpus claim",
        CrossVerificationGate.NUMERIC_HIGH_IMPACT,
        {"claim": claim_at(ClaimScope.CORPUS_PATTERN), "evidence": numeric_evidence()},
        True,
    ),
    (
        "numeric in the manuscript",
        CrossVerificationGate.NUMERIC_HIGH_IMPACT,
        {"evidence": numeric_evidence(), "manuscript_attached": True},
        True,
    ),
    (
        "numeric on a single-paper claim",
        CrossVerificationGate.NUMERIC_HIGH_IMPACT,
        {"claim": claim_at(ClaimScope.INDIVIDUAL), "evidence": numeric_evidence()},
        False,
    ),
    (
        "prose evidence in the manuscript",
        CrossVerificationGate.NUMERIC_HIGH_IMPACT,
        {"evidence": prose_evidence(), "manuscript_attached": True},
        False,
    ),
    (
        "claim with a contradiction",
        CrossVerificationGate.COUNTER_EVIDENCE_INTERPRETATION,
        {"claim": claim_at(ClaimScope.OBSERVED_SUBSET, contradicting=True)},
        True,
    ),
    (
        "claim without a contradiction",
        CrossVerificationGate.COUNTER_EVIDENCE_INTERPRETATION,
        {"claim": claim_at(ClaimScope.OBSERVED_SUBSET)},
        False,
    ),
    (
        "submission-ready field claim",
        CrossVerificationGate.SUBMISSION_FIELD_CLAIM,
        {"claim": claim_at(ClaimScope.FIELD_GENERALIZATION), "submission_ready": True},
        True,
    ),
    (
        "submission-ready corpus claim",
        CrossVerificationGate.SUBMISSION_FIELD_CLAIM,
        {"claim": claim_at(ClaimScope.CORPUS_PATTERN), "submission_ready": True},
        False,
    ),
    (
        "field claim not yet submitted",
        CrossVerificationGate.SUBMISSION_FIELD_CLAIM,
        {"claim": claim_at(ClaimScope.FIELD_GENERALIZATION)},
        False,
    ),
    (
        "manuscript sentence with a number",
        CrossVerificationGate.MANUSCRIPT_HIGH_CONSEQUENCE,
        {"evidence": numeric_evidence(), "manuscript_attached": True},
        True,
    ),
    (
        "manuscript sentence generalizing over the field",
        CrossVerificationGate.MANUSCRIPT_HIGH_CONSEQUENCE,
        {"claim": claim_at(ClaimScope.FIELD_GENERALIZATION), "manuscript_attached": True},
        True,
    ),
    (
        "manuscript sentence about one paper",
        CrossVerificationGate.MANUSCRIPT_HIGH_CONSEQUENCE,
        {"claim": claim_at(ClaimScope.INDIVIDUAL), "manuscript_attached": True},
        False,
    ),
    (
        "field claim with no manuscript",
        CrossVerificationGate.MANUSCRIPT_HIGH_CONSEQUENCE,
        {"claim": claim_at(ClaimScope.FIELD_GENERALIZATION)},
        False,
    ),
]


@pytest.mark.parametrize(
    ("gate", "context", "expected"),
    [(gate, context, expected) for _, gate, context, expected in ELIGIBILITY_TABLE],
    ids=[name for name, _, _, _ in ELIGIBILITY_TABLE],
)
def test_gate_eligibility_table(
    gate: CrossVerificationGate, context: dict[str, Any], expected: bool
) -> None:
    verdict = is_eligible(DEFAULT_POLICY, gate, **context)
    assert verdict.eligible is expected
    assert verdict.gate is gate
    assert verdict.reasons, "an eligibility decision always says why"


def test_routine_work_is_not_eligible_by_default() -> None:
    """A gate a policy does not enable is never cross-verified, whatever the object is."""
    policy = CrossVerifyPolicy(enabled_gates=frozenset({CrossVerificationGate.ABSENCE_CLAIM}))
    verdict = is_eligible(
        policy,
        CrossVerificationGate.NUMERIC_HIGH_IMPACT,
        claim=claim_at(ClaimScope.FIELD_GENERALIZATION),
        evidence=numeric_evidence(),
    )
    assert verdict.eligible is False
    assert "not enabled" in verdict.reasons[0]


def test_a_missing_object_refuses_rather_than_guesses() -> None:
    for gate in CrossVerificationGate:
        assert is_eligible(DEFAULT_POLICY, gate).eligible is False


# -------------------------------------------------------------------------- verification


def test_an_ineligible_gate_skips_without_calling_a_provider() -> None:
    left, right = FakeProvider("vendor-a"), FakeProvider("vendor-b")
    result = cross_verify(
        request_for(),
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=False, gate=GATE, reasons=("the claim has no counter",)),
        decision_fields=DECISION_FIELDS,
    )
    assert result.eligible is False
    assert result.skipped_reason == "the claim has no counter"
    assert result.positions == ()
    assert result.agreement is False
    assert not left.calls and not right.calls


def test_force_runs_an_ineligible_gate_and_still_reports_it_as_ineligible() -> None:
    left, right = FakeProvider("vendor-a"), FakeProvider("vendor-b")
    result = cross_verify(
        request_for(),
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=False, gate=GATE, reasons=("not eligible",)),
        decision_fields=DECISION_FIELDS,
        force=True,
    )
    assert result.eligible is False
    assert result.agreement is True
    assert len(result.positions) == 2
    assert len(left.calls) == 1 and len(right.calls) == 1


def test_the_same_vendor_twice_is_not_two_opinions() -> None:
    first = FakeProvider("vendor-a", model="model-x")
    second = FakeProvider("vendor-a", model="model-y")
    result = cross_verify(
        request_for(),
        [(first, "model-x"), (second, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )
    assert result.positions == ()
    assert result.skipped_reason is not None
    assert "distinct providers" in result.skipped_reason
    assert not first.calls and not second.calls


def test_two_models_of_one_vendor_are_allowed_when_distinctness_is_waived() -> None:
    first = FakeProvider("vendor-a", model="model-x")
    second = FakeProvider("vendor-a", {"verdict": "contradicted"}, model="model-y")
    policy = CrossVerifyPolicy(
        enabled_gates=frozenset(CrossVerificationGate), require_distinct_vendors=False
    )
    result = cross_verify(
        request_for(),
        [(first, "model-x"), (second, "model-y")],
        gate=GATE,
        policy=policy,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )
    assert result.conflict is not None
    assert [position.label for position in result.positions] == [
        "vendor-a/model-x",
        "vendor-a/model-y",
    ]


def test_disagreement_is_one_conflict_listing_both_positions_and_the_field() -> None:
    """Gate P13: two provider results disagree, and the researcher gets one explicit conflict."""
    left = FakeProvider("vendor-a", {"verdict": "supported"}, model="model-x")
    right = FakeProvider("vendor-b", {"verdict": "contradicted"}, model="model-y")
    result = cross_verify(
        request_for(),
        [(left, "model-x"), ProviderEntry(provider=right, model="model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )

    assert result.agreement is False
    conflict = result.conflict
    assert isinstance(conflict, ProviderConflict)
    assert conflict.kind == CONFLICT_KIND
    assert conflict.subject == "C0041"
    assert conflict.gate is GATE
    assert conflict.differing_fields == ("verdict",)
    assert [position.label for position in conflict.positions] == [
        "vendor-a/model-x",
        "vendor-b/model-y",
    ]
    assert [position.decision["verdict"] for position in conflict.positions] == [
        "supported",
        "contradicted",
    ]
    assert "supported" in conflict.summary and "contradicted" in conflict.summary


def test_neither_position_is_preferred_or_merged() -> None:
    left = FakeProvider("vendor-a", {"verdict": "supported"})
    right = FakeProvider("vendor-b", {"verdict": "contradicted"})
    result = cross_verify(
        request_for(),
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )
    conflict = result.conflict
    assert conflict is not None
    assert len(conflict.positions) == 2
    for name in ("winner", "preferred", "resolution", "merged", "accepted"):
        assert not hasattr(conflict, name)
        assert name not in ProviderConflict.model_fields


def test_same_decision_with_different_prose_is_agreement_and_accepts_nothing() -> None:
    left = FakeProvider(
        "vendor-a", {"verdict": "supported", "rationale": "Table 3 states it directly."}
    )
    right = FakeProvider(
        "vendor-b", {"verdict": "supported", "rationale": "The abstract already says so."}
    )
    result = cross_verify(
        request_for(),
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )

    assert result.agreement is True
    assert result.conflict is None
    assert {position.rationale for position in result.positions} == {
        "Table 3 states it directly.",
        "The abstract already says so.",
    }
    # Agreement between models is not acceptance: nothing here can carry that meaning.
    for model in (CrossVerification, ProviderConflict, ProviderPosition):
        assert "accepted" not in model.model_fields
        assert "verdict" not in model.model_fields
    assert not hasattr(result, "accepted")


def test_a_failing_provider_leaves_the_verification_incomplete_and_not_agreed() -> None:
    left = FakeProvider("vendor-a", {"verdict": "supported"})
    right = FakeProvider("vendor-b", error=ProviderError("429 slow down", provider="vendor-b"))
    result = cross_verify(
        request_for(),
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )

    assert result.incomplete is True
    assert result.agreement is False
    assert result.conflict is None
    assert len(result.positions) == 1
    assert result.skipped_reason == "provider_error:vendor-b"


def test_a_call_budget_of_zero_extra_calls_refuses_to_cross_verify() -> None:
    left, right = FakeProvider("vendor-a"), FakeProvider("vendor-b")
    policy = CrossVerifyPolicy(
        enabled_gates=frozenset(CrossVerificationGate), max_extra_calls_per_object=0
    )
    result = cross_verify(
        request_for(),
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        policy=policy,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )
    assert result.positions == ()
    assert not left.calls and not right.calls


def test_every_position_carries_the_one_request_fingerprint() -> None:
    """Comparability rests on both providers having answered the same job (Product 20.4)."""
    request = request_for()
    left = FakeProvider("vendor-a", {"verdict": "supported"})
    right = FakeProvider("vendor-b", {"verdict": "contradicted"})
    result = cross_verify(
        request,
        [(left, "model-x"), (right, "model-y")],
        gate=GATE,
        eligibility=Eligibility(eligible=True, gate=GATE),
        decision_fields=DECISION_FIELDS,
    )
    assert {position.fingerprint for position in result.positions} == {request.fingerprint()}


def test_a_decision_field_the_schema_does_not_have_is_refused_before_any_call() -> None:
    left, right = FakeProvider("vendor-a"), FakeProvider("vendor-b")
    with pytest.raises(ValueError, match="has no field"):
        cross_verify(
            request_for(),
            [(left, "model-x"), (right, "model-y")],
            gate=GATE,
            eligibility=Eligibility(eligible=True, gate=GATE),
            decision_fields=("recommended_scope",),
        )
    assert not left.calls and not right.calls


def test_eligibility_for_another_gate_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="was computed for"):
        cross_verify(
            request_for(),
            [(FakeProvider("vendor-a"), "model-x"), (FakeProvider("vendor-b"), "model-y")],
            gate=GATE,
            eligibility=Eligibility(
                eligible=True, gate=CrossVerificationGate.ABSENCE_CLAIM, reasons=()
            ),
            decision_fields=DECISION_FIELDS,
        )


def test_decisions_compare_the_named_fields_only() -> None:
    judgement = Judgement(verdict="supported", coverage_state="14 of 17", rationale="prose")
    assert decision_of(judgement, ("verdict",)) == {"verdict": "supported"}
    assert decision_of(judgement, ("verdict", "coverage_state")) == {
        "verdict": "supported",
        "coverage_state": "14 of 17",
    }


def test_provider_label_reads_both_candidate_forms() -> None:
    provider = FakeProvider("vendor-a")
    assert provider_label((provider, "model-x")) == "vendor-a/model-x"
    assert provider_label(ProviderEntry(provider=provider, model="model-y")) == "vendor-a/model-y"
