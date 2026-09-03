"""Gate P7 end to end: a claim stronger than its evidence comes back weaker, and stays weak.

    create a claim deliberately stronger than its evidence; `research claim audit` must
    return a weaker maximum defensible wording, show support/qualifiers/counter-evidence,
    and prevent silent strength escalation.  -- ROADMAP Gate P7

The same run also has to leave the canonical record alone (ADR-001) and be resumable
without paying for the models a second time (Product 19.1).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_harness.claims.audit import (
    ClaimAuditInput,
    ClaimAuditResult,
    apply_audit,
    audit_claim,
    audit_claim_locally,
    to_assessment,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    EvidenceStatus,
)
from research_harness.domain.errors import TransitionError
from research_harness.domain.ids import ClaimId, EvidenceId
from research_harness.domain.transitions import override_claim_strength
from research_harness.providers.models.base import ProviderError
from research_harness.providers.models.cross_verify import (
    DEFAULT_POLICY,
    CrossVerificationGate,
    CrossVerifyPolicy,
)
from research_harness.workflows.claim_audit import (
    CLAIM_AUDIT_WORKFLOW,
    COLLECT_STAGE,
    CROSS_VERIFY_STAGE,
    LOCAL_STAGE,
    NO_GATE_REASON,
    REPORT_STAGE,
    SKEPTIC_STAGE,
    read_result,
    report_path,
    run_claim_audit,
)
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.models import RunStatus, StageStatus
from tests.integration.claims.conftest import (
    CLAIM_ID,
    FakeCounterFinder,
    FakeModel,
    auditor_answer,
    gate_p7_claim,
    gate_p7_evidence,
    gate_p7_search_runs,
    gate_p7_works,
    skeptic_answer,
)
from tests.unit.domain import strategies as sty

NO_CONFLICT_POLICY = CrossVerifyPolicy()
"""No gate enabled: the audit stays single-provider unless a test asks for more."""


def full_input(**overrides: object) -> ClaimAuditInput:
    """The Gate P7 claim with a counter finder and both model roles configured."""
    fields: dict[str, object] = {
        "claim": gate_p7_claim(),
        "evidence": gate_p7_evidence(),
        "works": gate_p7_works(),
        "search_runs": gate_p7_search_runs(),
        "counter_finder": FakeCounterFinder(),
        "skeptic": FakeModel("vendor-a", skeptic_answer(), model="model-x"),
        "auditor": FakeModel("vendor-a", auditor_answer(), model="model-x"),
    }
    return ClaimAuditInput(**{**fields, **overrides})  # type: ignore[arg-type]


def tree_digest(root: Path, *, skip: str) -> dict[str, str]:
    """Path -> content digest for every file under `root`, ignoring one subtree."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or skip in path.relative_to(root).parts:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digests[path.relative_to(root).as_posix()] = digest
    return digests


# ------------------------------------------------------------------------------- Gate P7


def test_a_claim_stronger_than_its_evidence_comes_back_weaker(audit_input: ClaimAuditInput) -> None:
    result = audit_claim_locally(audit_input)

    assert result.assessment.requested is ClaimScope.FIELD_GENERALIZATION
    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert result.maximum_defensible_wording == "several existing approaches"
    assert result.escalation_prevented is True
    assert any(
        "field-level generalization needs 5" in reason for reason in result.assessment.reasons
    )


def test_the_audit_shows_support_qualifiers_and_counter_evidence() -> None:
    result = audit_claim(full_input(), cross_verify_policy=NO_CONFLICT_POLICY)

    assert result.support == tuple(
        EvidenceId(name) for name in ("E0001", "E0002", "E0003", "E0004")
    )
    assert result.counter_evidence == (EvidenceId("E0009"),)
    assert result.qualifier_notes  # the Skeptic and the Auditor both narrowed the claim
    assert any("flow-level" in note for note in result.qualifier_notes)
    assert [candidate.ref for candidate in result.counter_candidates] == ["B0142", "B0142"]
    assert {candidate.source for candidate in result.counter_candidates} == {
        "semantic_index",
        "skeptic",
    }


def test_two_versions_of_one_work_do_not_count_twice(audit_input: ClaimAuditInput) -> None:
    result = audit_claim_locally(audit_input)

    assert result.independence.effective_support == 3
    assert result.independence.has_dependence is True
    assert any("versions of W0001" in warning for warning in result.warnings)


def test_a_result_on_another_dataset_is_proposed_as_incomparable(
    audit_input: ClaimAuditInput,
) -> None:
    result = audit_claim_locally(audit_input)

    assert len(result.incomparable) == 1
    change = result.incomparable[0]
    assert change.evidence == EvidenceId("E0009")
    assert change.proposed is ClaimEvidenceRelationType.INCOMPARABLE_UNDER_CURRENT_EVIDENCE
    assert "dataset" in change.note
    # The claim itself is untouched: reclassifying a relation is a researcher act.
    assert audit_input.claim.contradicting == (EvidenceId("E0009"),)


def test_silent_escalation_is_impossible(audit_input: ClaimAuditInput) -> None:
    result = audit_claim_locally(audit_input)
    audited = apply_audit(audit_input.claim, result, actor="human:alice")

    assert audited.requested_strength is ClaimScope.FIELD_GENERALIZATION
    assert audited.allowed_strength is ClaimScope.CORPUS_PATTERN
    assert audited.status is ClaimStatus.QUALIFIED
    assert audited.assessment.maximum_defensible_wording == "several existing approaches"
    assert audited.assessment.audited_at is not None


def test_escalating_past_the_auditor_needs_an_accepted_decision(
    audit_input: ClaimAuditInput,
) -> None:
    """Product 38: the researcher keeps authority, but the override is visible."""
    audited = apply_audit(audit_input.claim, audit_claim_locally(audit_input), actor="human:alice")
    decision = sty.make_override_decision(
        claim=audited.id,
        auditor_recommendation=ClaimScope.CORPUS_PATTERN,
        researcher_selected=ClaimScope.FIELD_GENERALIZATION,
    )

    overridden = override_claim_strength(audited, decision)
    assert overridden.allowed_strength is ClaimScope.FIELD_GENERALIZATION
    assert decision.id in overridden.decisions

    stale_decision = decision.touch(auditor_recommendation=ClaimScope.INDIVIDUAL)
    with pytest.raises(TransitionError, match="re-audit"):
        override_claim_strength(audited, stale_decision)


def test_unaccepted_evidence_is_not_counted_as_support() -> None:
    """ADR-003: only accepted evidence carries scientific weight."""
    evidence = gate_p7_evidence()
    for key in (EvidenceId("E0003"), EvidenceId("E0004")):
        item = evidence[key]
        evidence[key] = item.touch(
            verification=item.verification.touch(status=EvidenceStatus.PROPOSED, accepted_by=None)
        )
    result = audit_claim_locally(
        ClaimAuditInput(
            claim=gate_p7_claim(),
            evidence=evidence,
            works=gate_p7_works(),
            search_runs=gate_p7_search_runs(),
        )
    )

    assert result.recommended_scope is ClaimScope.OBSERVED_SUBSET
    assert result.maximum_defensible_wording == "among the papers examined"


# ------------------------------------------------------------------- provider disagreement


def test_two_providers_that_disagree_produce_one_conflict_and_no_overwrite() -> None:
    """Gate P13 inside a claim audit: one explicit conflict, neither answer preferred."""
    data = full_input(
        claim=gate_p7_claim(),
        skeptic=FakeModel("vendor-a", skeptic_answer(), model="model-x"),
        auditor=FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-x"),
        cross_verify_providers=(
            (
                FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN), model="model-x"),
                "model-x",
            ),
            (
                FakeModel("vendor-b", auditor_answer(ClaimScope.OBSERVED_SUBSET), model="model-y"),
                "model-y",
            ),
        ),
    )
    result = audit_claim(data, cross_verify_policy=DEFAULT_POLICY)

    conflict = result.conflict
    assert conflict is not None
    # A numeric corpus-level claim meets the numeric gate before the counter-evidence one.
    assert conflict.gate is CrossVerificationGate.NUMERIC_HIGH_IMPACT
    assert conflict.subject == CLAIM_ID
    assert conflict.differing_fields == ("recommended_scope",)
    assert [position.label for position in conflict.positions] == [
        "vendor-a/model-x",
        "vendor-b/model-y",
    ]
    # Neither provider silently wins: the recommendation is still the engine's own.
    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert any("No position is preferred" in warning for warning in result.warnings)


def test_provider_agreement_records_agreement_and_accepts_nothing() -> None:
    data = full_input(
        cross_verify_providers=(
            (FakeModel("vendor-a", auditor_answer(ClaimScope.CORPUS_PATTERN)), "model-x"),
            (FakeModel("vendor-b", auditor_answer(ClaimScope.CORPUS_PATTERN)), "model-y"),
        ),
    )
    result = audit_claim(data, cross_verify_policy=DEFAULT_POLICY)

    verification = result.cross_verification
    assert verification is not None
    assert verification.agreement is True
    assert result.conflict is None
    assert not hasattr(verification, "accepted")
    # Agreement changed nothing about the claim: acceptance is still a human act.
    audited = apply_audit(data.claim, result, actor="human:alice")
    assert audited.allowed_strength is ClaimScope.CORPUS_PATTERN


def test_a_provider_failure_leaves_the_cross_check_incomplete() -> None:
    data = full_input(
        cross_verify_providers=(
            (FakeModel("vendor-a", auditor_answer()), "model-x"),
            (FakeModel("vendor-b", error=ProviderError("timeout", provider="vendor-b")), "model-y"),
        ),
    )
    result = audit_claim(data, cross_verify_policy=DEFAULT_POLICY)

    verification = result.cross_verification
    assert verification is not None
    assert verification.incomplete is True
    assert verification.agreement is False
    assert result.conflict is None
    assert any("did not complete" in warning for warning in result.warnings)


def test_a_routine_audit_is_not_cross_verified() -> None:
    """Product 20.4: no gate enabled means no second provider and no extra call."""
    second = FakeModel("vendor-b", auditor_answer())
    data = full_input(
        cross_verify_providers=(
            (FakeModel("vendor-a", auditor_answer()), "model-x"),
            (second, "y"),
        ),
    )
    result = audit_claim(data, cross_verify_policy=NO_CONFLICT_POLICY)

    assert result.cross_verification is None
    assert result.conflict is None
    assert not second.calls


# ------------------------------------------------------------------------------- workflow


def test_the_workflow_writes_only_under_research_staging(
    engine: WorkflowEngine, project: Path, research_dir: Path
) -> None:
    before = tree_digest(project, skip=".research")
    data = full_input()

    run, result = run_claim_audit(
        engine, research_dir, lambda: data, ClaimId(CLAIM_ID), policy=NO_CONFLICT_POLICY
    )

    assert run.status is RunStatus.succeeded
    assert run.workflow == CLAIM_AUDIT_WORKFLOW
    assert tree_digest(project, skip=".research") == before, "the canonical record changed"

    report = report_path(research_dir, ClaimId(CLAIM_ID), run.run_id)
    assert report.is_file()
    assert report.parent == research_dir / "staging" / "claim_audit" / CLAIM_ID
    assert read_result(report) == result
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["claim"] == CLAIM_ID
    assert payload["run_id"] == run.run_id


def test_the_workflow_reports_the_weaker_wording_and_the_proposals(
    engine: WorkflowEngine, research_dir: Path
) -> None:
    data = full_input()
    run, result = run_claim_audit(
        engine, research_dir, lambda: data, ClaimId(CLAIM_ID), policy=NO_CONFLICT_POLICY
    )

    assert isinstance(result, ClaimAuditResult)
    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert result.escalation_prevented is True
    assert [str(change.evidence) for change in result.incomparable] == ["E0009"]
    assert [judgement.role for judgement in result.model_judgements] == ["skeptic", "claim_auditor"]

    local = run.stage(LOCAL_STAGE)
    assert local.status is StageStatus.succeeded
    assert run.stage(CROSS_VERIFY_STAGE).status is StageStatus.succeeded


def test_resuming_a_finished_run_recomputes_nothing(
    engine: WorkflowEngine, research_dir: Path
) -> None:
    data = full_input()
    skeptic = data.skeptic
    auditor = data.auditor
    assert isinstance(skeptic, FakeModel) and isinstance(auditor, FakeModel)

    first_run, first = run_claim_audit(
        engine, research_dir, lambda: data, ClaimId(CLAIM_ID), policy=NO_CONFLICT_POLICY
    )
    calls_after_first = (len(skeptic.calls), len(auditor.calls))

    second_run, second = run_claim_audit(
        engine,
        research_dir,
        lambda: data,
        ClaimId(CLAIM_ID),
        policy=NO_CONFLICT_POLICY,
        run_id=first_run.run_id,
    )

    assert second_run.run_id == first_run.run_id
    assert second == first
    assert (len(skeptic.calls), len(auditor.calls)) == calls_after_first
    for stage in (COLLECT_STAGE, LOCAL_STAGE, SKEPTIC_STAGE, CROSS_VERIFY_STAGE, REPORT_STAGE):
        assert second_run.stage(stage).status is StageStatus.skipped_cached


def test_an_unconfigured_model_skips_the_model_pass_without_losing_the_audit(
    engine: WorkflowEngine, research_dir: Path, audit_input: ClaimAuditInput
) -> None:
    run, result = run_claim_audit(
        engine, research_dir, lambda: audit_input, ClaimId(CLAIM_ID), policy=NO_CONFLICT_POLICY
    )

    assert run.status is RunStatus.succeeded
    assert result.model_judgements == ()
    assert result.recommended_scope is ClaimScope.CORPUS_PATTERN
    assert result.escalation_prevented is True


def test_the_cross_verify_stage_says_why_it_did_nothing(
    engine: WorkflowEngine, research_dir: Path
) -> None:
    data = full_input()
    run, _ = run_claim_audit(
        engine, research_dir, lambda: data, ClaimId(CLAIM_ID), policy=NO_CONFLICT_POLICY
    )
    checkpoint = engine.store.load_checkpoint(run.run_id, CROSS_VERIFY_STAGE)

    assert checkpoint is not None
    assert checkpoint["skipped"] == NO_GATE_REASON


def test_the_audited_assessment_can_be_written_back_to_the_claim(
    engine: WorkflowEngine, research_dir: Path, audit_input: ClaimAuditInput
) -> None:
    _, result = run_claim_audit(
        engine, research_dir, lambda: audit_input, ClaimId(CLAIM_ID), policy=NO_CONFLICT_POLICY
    )
    assessment = to_assessment(result, audit_input.claim)

    assert assessment.allowed_strength <= assessment.requested_strength
    assert assessment.allowed_strength is ClaimScope.CORPUS_PATTERN
    assert assessment.status is ClaimStatus.QUALIFIED
