"""Transition legality and authority rules (Product 24, 38, 42.E-42.H)."""

from __future__ import annotations

import inspect

import pytest

from research_harness.domain import (
    AuthorityError,
    Claim,
    ClaimScope,
    ClaimStatus,
    DecisionStatus,
    DecisionType,
    DomainValidationError,
    Evidence,
    EvidenceOrigin,
    EvidenceStatus,
    Interpretation,
    NegativeEvidenceState,
    NoteStatus,
    Provenance,
    QuestionStatus,
    ReviewAction,
    ReviewPolicy,
    ReviewTier,
    StaleState,
    TransitionError,
    TransitionKind,
    VerificationVerdict,
)
from research_harness.domain.enums import EvidenceStrength, EvidenceType
from research_harness.domain.evidence import EvidenceContent, VerificationRecord
from research_harness.domain.ids import ClaimId, DecisionId, EvidenceId, InterpretationId
from research_harness.domain.transitions import (
    AUDITED_CLAIM_STATUSES,
    CLAIM_TRANSITIONS,
    DECISION_TRANSITIONS,
    EVIDENCE_TRANSITIONS,
    NOTE_TRANSITIONS,
    QUESTION_TRANSITIONS,
    BatchPolicyConditions,
    allowed_transitions,
    audit_claim,
    discard_note,
    is_human_actor,
    negative_state_from_search,
    override_claim_strength,
    promote_negative_state,
    promote_note,
    reclassify_origin,
    supersede_claim,
    transition_decision,
    transition_evidence,
    transition_question,
)
from tests.unit.domain import strategies as sty

MODEL_ACTOR = "vendor-a/model-x"
ALL_CONDITIONS_MET = BatchPolicyConditions(
    verifier_supported=True,
    anchor_valid=True,
    no_competing_candidate=True,
    low_risk_field=True,
    no_accepted_state_conflict=True,
)


def verified(**overrides: object) -> Evidence:
    """Evidence already moved to `verified` by a model verifier."""
    evidence = sty.make_evidence(**overrides)
    return transition_evidence(
        evidence,
        EvidenceStatus.VERIFIED,
        actor=MODEL_ACTOR,
        verdict=VerificationVerdict.SUPPORTED,
    )


# --- actor authority --------------------------------------------------------


@pytest.mark.parametrize("actor", ["human", "human:alice"])
def test_human_actors_are_recognised(actor: str) -> None:
    assert is_human_actor(actor)


@pytest.mark.parametrize(
    "actor", ["vendor-a/model-x", "vendor-b/model-y", "system", "humanoid", ""]
)
def test_non_human_actors_are_rejected(actor: str) -> None:
    assert not is_human_actor(actor)


# --- evidence lifecycle -----------------------------------------------------


def test_proposed_cannot_skip_verification_and_be_accepted() -> None:
    evidence = sty.make_evidence()
    with pytest.raises(TransitionError, match="not allowed"):
        transition_evidence(
            evidence,
            EvidenceStatus.ACCEPTED,
            actor="human",
            review_action=ReviewAction.ACCEPT,
        )


def test_verification_requires_a_verdict() -> None:
    with pytest.raises(TransitionError, match="verdict"):
        transition_evidence(sty.make_evidence(), EvidenceStatus.VERIFIED, actor=MODEL_ACTOR)


def test_verification_records_the_verifier_and_verdict() -> None:
    evidence = verified()
    assert evidence.verification.status is EvidenceStatus.VERIFIED
    assert evidence.verification.verifier == MODEL_ACTOR
    assert evidence.verification.verdict is VerificationVerdict.SUPPORTED
    assert evidence.updated_at >= evidence.created_at


def test_model_cannot_accept_a_tier_one_candidate_under_strict_policy() -> None:
    with pytest.raises(AuthorityError, match="human actor"):
        transition_evidence(verified(), EvidenceStatus.ACCEPTED, actor=MODEL_ACTOR)


def test_human_acceptance_requires_an_explicit_review_action() -> None:
    with pytest.raises(TransitionError, match="review_action"):
        transition_evidence(verified(), EvidenceStatus.ACCEPTED, actor="human")


def test_human_acceptance_records_the_acceptor_and_action() -> None:
    accepted = transition_evidence(
        verified(),
        EvidenceStatus.ACCEPTED,
        actor="human:alice",
        review_action=ReviewAction.ACCEPT,
    )
    assert accepted.verification.status is EvidenceStatus.ACCEPTED
    assert accepted.verification.accepted_by == "human:alice"
    assert accepted.verification.review_action is ReviewAction.ACCEPT
    assert accepted.verification.reviewed_at is not None


def test_accept_with_qualification_requires_a_qualification() -> None:
    with pytest.raises(TransitionError, match="qualification"):
        transition_evidence(
            verified(),
            EvidenceStatus.ACCEPTED,
            actor="human",
            review_action=ReviewAction.ACCEPT_WITH_QUALIFICATION,
        )
    accepted = transition_evidence(
        verified(),
        EvidenceStatus.ACCEPTED,
        actor="human",
        review_action=ReviewAction.ACCEPT_WITH_QUALIFICATION,
        qualification="Holds only for the encrypted subset.",
    )
    assert accepted.qualification == "Holds only for the encrypted subset."


def test_tier_zero_mechanical_facts_auto_accept_under_strict_policy() -> None:
    accepted = transition_evidence(
        verified(review_tier=ReviewTier.TIER_0),
        EvidenceStatus.ACCEPTED,
        actor="system",
    )
    assert accepted.verification.status is EvidenceStatus.ACCEPTED
    assert accepted.verification.accepted_by == "system"


@pytest.mark.parametrize("origin", sorted(EvidenceOrigin.__members__))
def test_interpretive_candidates_never_auto_accept(origin: str) -> None:
    """Product 42.H: a model cannot bypass the strict review gate for interpretation."""
    evidence = verified(origin=EvidenceOrigin[origin], review_tier=ReviewTier.TIER_0)
    if evidence.is_interpretive:
        with pytest.raises(AuthorityError):
            transition_evidence(
                evidence,
                EvidenceStatus.ACCEPTED,
                actor=MODEL_ACTOR,
                policy=ReviewPolicy.POLICY_BATCH,
                batch_conditions=ALL_CONDITIONS_MET,
            )
    else:
        assert transition_evidence(evidence, EvidenceStatus.ACCEPTED, actor="system")


def test_tier_two_needs_human_review_even_for_source_observed_evidence() -> None:
    with pytest.raises(AuthorityError):
        transition_evidence(
            verified(review_tier=ReviewTier.TIER_2),
            EvidenceStatus.ACCEPTED,
            actor=MODEL_ACTOR,
            policy=ReviewPolicy.POLICY_BATCH,
            batch_conditions=ALL_CONDITIONS_MET,
        )


def test_tier_one_batch_acceptance_needs_every_condition() -> None:
    evidence = verified()
    with pytest.raises(AuthorityError, match="human actor"):
        transition_evidence(
            evidence,
            EvidenceStatus.ACCEPTED,
            actor="batch",
            policy=ReviewPolicy.POLICY_BATCH,
        )
    partial = ALL_CONDITIONS_MET.model_copy(update={"anchor_valid": False})
    with pytest.raises(AuthorityError, match="anchor_valid"):
        transition_evidence(
            evidence,
            EvidenceStatus.ACCEPTED,
            actor="batch",
            policy=ReviewPolicy.POLICY_BATCH,
            batch_conditions=partial,
        )
    accepted = transition_evidence(
        evidence,
        EvidenceStatus.ACCEPTED,
        actor="batch",
        policy=ReviewPolicy.POLICY_BATCH,
        batch_conditions=ALL_CONDITIONS_MET,
    )
    assert accepted.verification.status is EvidenceStatus.ACCEPTED


def test_tier_one_batch_conditions_do_not_apply_under_strict_policy() -> None:
    with pytest.raises(AuthorityError):
        transition_evidence(
            verified(),
            EvidenceStatus.ACCEPTED,
            actor="batch",
            policy=ReviewPolicy.STRICT,
            batch_conditions=ALL_CONDITIONS_MET,
        )


def test_acceptance_takes_no_model_confidence_argument() -> None:
    """Product 24.4: model confidence alone is never sufficient, so it is not an input."""
    parameters = set(inspect.signature(transition_evidence).parameters)
    assert not parameters & {"confidence", "score", "probability", "certainty"}


def test_accepted_evidence_goes_stale_and_can_be_revalidated() -> None:
    accepted = transition_evidence(
        verified(), EvidenceStatus.ACCEPTED, actor="human", review_action=ReviewAction.ACCEPT
    )
    stale = transition_evidence(accepted, EvidenceStatus.STALE, actor="system")
    assert stale.stale is StaleState.STALE
    assert stale.verification.status is EvidenceStatus.STALE
    revalidated = transition_evidence(
        stale, EvidenceStatus.ACCEPTED, actor="human", review_action=ReviewAction.ACCEPT
    )
    assert revalidated.stale is StaleState.FRESH


def test_superseded_is_terminal() -> None:
    superseded = transition_evidence(sty.make_evidence(), EvidenceStatus.SUPERSEDED, actor="system")
    with pytest.raises(TransitionError):
        transition_evidence(
            superseded,
            EvidenceStatus.VERIFIED,
            actor="human",
            verdict=VerificationVerdict.SUPPORTED,
        )


def test_rejected_evidence_cannot_be_accepted_later() -> None:
    rejected = transition_evidence(verified(), EvidenceStatus.REJECTED, actor="human")
    with pytest.raises(TransitionError):
        transition_evidence(
            rejected, EvidenceStatus.ACCEPTED, actor="human", review_action=ReviewAction.ACCEPT
        )


def test_deferred_candidates_can_return_to_review() -> None:
    deferred = transition_evidence(verified(), EvidenceStatus.DEFERRED, actor="human")
    accepted = transition_evidence(
        deferred, EvidenceStatus.ACCEPTED, actor="human", review_action=ReviewAction.ACCEPT
    )
    assert accepted.verification.status is EvidenceStatus.ACCEPTED


def test_transitions_return_new_objects_and_never_mutate() -> None:
    evidence = sty.make_evidence()
    result = transition_evidence(
        evidence, EvidenceStatus.VERIFIED, actor=MODEL_ACTOR, verdict=VerificationVerdict.SUPPORTED
    )
    assert evidence.verification.status is EvidenceStatus.PROPOSED
    assert result is not evidence


def test_interpretations_follow_the_same_lifecycle() -> None:
    interpretation = Interpretation(
        id=InterpretationId("I0004"),
        evidence=(EvidenceId("E0482"),),
        text="The authors treat flow direction as a proxy for intent.",
        origin=EvidenceOrigin.MODEL_PROPOSED,
        provenance=sty.MODEL,
    )
    checked = transition_evidence(
        interpretation,
        EvidenceStatus.VERIFIED,
        actor=MODEL_ACTOR,
        verdict=VerificationVerdict.PARTIALLY_SUPPORTED,
    )
    with pytest.raises(AuthorityError):
        transition_evidence(checked, EvidenceStatus.ACCEPTED, actor=MODEL_ACTOR)
    accepted = transition_evidence(
        checked, EvidenceStatus.ACCEPTED, actor="human", review_action=ReviewAction.ACCEPT
    )
    assert isinstance(accepted, Interpretation)
    assert accepted.origin is EvidenceOrigin.MODEL_PROPOSED


# --- origin discipline ------------------------------------------------------


def test_model_proposed_cannot_become_source_observed() -> None:
    """Product 42.E: a model proposal is never promoted to an observation."""
    evidence = sty.make_evidence(origin=EvidenceOrigin.MODEL_PROPOSED)
    with pytest.raises(TransitionError, match="re-anchor"):
        reclassify_origin(
            evidence,
            EvidenceOrigin.SOURCE_OBSERVED,
            actor="human",
            rationale="I checked the PDF myself.",
        )


def test_model_proposed_cannot_become_source_observed_under_any_policy() -> None:
    evidence = sty.make_evidence(origin=EvidenceOrigin.MODEL_PROPOSED)
    for policy in ReviewPolicy:
        with pytest.raises(TransitionError):
            reclassify_origin(
                evidence,
                EvidenceOrigin.SOURCE_OBSERVED,
                actor="human:alice",
                rationale="verified by hand",
                policy=policy,
            )


def test_accepting_a_model_proposal_keeps_its_origin() -> None:
    accepted = transition_evidence(
        verified(origin=EvidenceOrigin.MODEL_PROPOSED),
        EvidenceStatus.ACCEPTED,
        actor="human",
        review_action=ReviewAction.ACCEPT,
    )
    assert accepted.origin is EvidenceOrigin.MODEL_PROPOSED


def test_only_a_human_may_reclassify_an_origin() -> None:
    evidence = sty.make_evidence(origin=EvidenceOrigin.MODEL_PROPOSED)
    with pytest.raises(AuthorityError):
        reclassify_origin(
            evidence,
            EvidenceOrigin.RESEARCHER_INFERRED,
            actor=MODEL_ACTOR,
            rationale="looks inferred",
        )


def test_reclassification_requires_a_rationale() -> None:
    evidence = sty.make_evidence(origin=EvidenceOrigin.MODEL_PROPOSED)
    with pytest.raises(DomainValidationError):
        reclassify_origin(
            evidence, EvidenceOrigin.RESEARCHER_INFERRED, actor="human", rationale="  "
        )


def test_human_reclassification_is_recorded() -> None:
    evidence = sty.make_evidence(origin=EvidenceOrigin.MODEL_PROPOSED)
    changed = reclassify_origin(
        evidence,
        EvidenceOrigin.RESEARCHER_INFERRED,
        actor="human:alice",
        rationale="This is my inference, not the model's.",
    )
    assert changed.origin is EvidenceOrigin.RESEARCHER_INFERRED
    assert changed.verification.rationale == "This is my inference, not the model's."
    assert changed.verification.reviewed_at is not None


def test_author_claims_do_not_silently_become_experimental_results() -> None:
    """Product 42.E: epistemic separation survives acceptance."""
    accepted = transition_evidence(
        verified(
            origin=EvidenceOrigin.AUTHOR_CLAIMED,
            evidence_type=EvidenceType.AUTHOR_CONCLUSION,
        ),
        EvidenceStatus.ACCEPTED,
        actor="human",
        review_action=ReviewAction.ACCEPT,
    )
    assert accepted.origin is EvidenceOrigin.AUTHOR_CLAIMED
    assert accepted.evidence_type is EvidenceType.AUTHOR_CONCLUSION


# --- negative evidence ------------------------------------------------------


@pytest.mark.parametrize("exhaustive", [True, False])
def test_zero_hits_never_produce_absent(exhaustive: bool) -> None:
    assert negative_state_from_search(0, exhaustive) is not NegativeEvidenceState.ABSENT


def test_exhaustive_zero_hit_search_is_not_found_and_partial_is_unclear() -> None:
    assert negative_state_from_search(0, exhaustive=True) is NegativeEvidenceState.NOT_FOUND
    assert negative_state_from_search(0, exhaustive=False) is NegativeEvidenceState.UNCLEAR


def test_a_search_with_hits_is_not_negative_evidence() -> None:
    with pytest.raises(DomainValidationError):
        negative_state_from_search(3, exhaustive=True)
    with pytest.raises(DomainValidationError):
        negative_state_from_search(-1, exhaustive=True)


def negative_evidence(state: NegativeEvidenceState) -> Evidence:
    return sty.make_evidence(
        content=EvidenceContent(exact_text="", negative_state=state, field="robustness_evaluation"),
        evidence_type=EvidenceType.LIMITATION,
        strength=EvidenceStrength.INDIRECT,
    )


def test_not_reported_becomes_absent_only_with_a_decision_and_a_human() -> None:
    """Product 42.F: `not_reported` cannot be converted without an explicit review path."""
    evidence = negative_evidence(NegativeEvidenceState.NOT_REPORTED)
    with pytest.raises(AuthorityError):
        promote_negative_state(
            evidence,
            to_state=NegativeEvidenceState.ABSENT,
            actor=MODEL_ACTOR,
            decision=DecisionId("D0031"),
        )
    promoted = promote_negative_state(
        evidence,
        to_state=NegativeEvidenceState.ABSENT,
        actor="human",
        decision=DecisionId("D0031"),
        rationale="Exhaustive search of the supplement.",
    )
    assert promoted.content.negative_state is NegativeEvidenceState.ABSENT
    assert DecisionId("D0031") in promoted.decisions


def test_only_not_found_and_not_reported_may_be_promoted() -> None:
    for state in (NegativeEvidenceState.NOT_APPLICABLE, NegativeEvidenceState.UNCLEAR):
        with pytest.raises(TransitionError):
            promote_negative_state(
                negative_evidence(state),
                to_state=NegativeEvidenceState.ABSENT,
                actor="human",
                decision=DecisionId("D0031"),
            )


def test_promotion_targets_only_absent() -> None:
    with pytest.raises(TransitionError):
        promote_negative_state(
            negative_evidence(NegativeEvidenceState.NOT_FOUND),
            to_state=NegativeEvidenceState.NOT_REPORTED,
            actor="human",
            decision=DecisionId("D0031"),
        )


def test_evidence_without_a_negative_state_cannot_be_promoted() -> None:
    with pytest.raises(TransitionError):
        promote_negative_state(
            sty.make_evidence(),
            to_state=NegativeEvidenceState.ABSENT,
            actor="human",
            decision=DecisionId("D0031"),
        )


# --- claims -----------------------------------------------------------------


def test_audit_records_status_and_allowed_strength_without_touching_the_request() -> None:
    claim = sty.make_claim()
    audited = audit_claim(
        claim,
        status=ClaimStatus.QUALIFIED,
        allowed_strength=ClaimScope.CORPUS_PATTERN,
        actor="auditor",
        maximum_defensible_wording="most systems in the reviewed corpus",
    )
    assert audited.status is ClaimStatus.QUALIFIED
    assert audited.allowed_strength is ClaimScope.CORPUS_PATTERN
    assert audited.requested_strength is claim.requested_strength
    assert audited.assessment.audited_at is not None


def test_audit_cannot_escalate_beyond_the_requested_strength() -> None:
    """Product 42.G: no silent escalation from corpus level to universal wording."""
    claim = sty.make_claim()
    with pytest.raises(TransitionError, match="epistemic_override"):
        audit_claim(
            claim,
            status=ClaimStatus.SUPPORTED,
            allowed_strength=ClaimScope.UNIVERSAL_OR_ABSENCE,
            actor="auditor",
        )


def test_audit_respects_the_claim_status_table() -> None:
    superseded = supersede_claim(sty.make_claim(), actor="human")
    with pytest.raises(TransitionError):
        audit_claim(
            superseded,
            status=ClaimStatus.SUPPORTED,
            allowed_strength=ClaimScope.INDIVIDUAL,
            actor="auditor",
        )


@pytest.mark.parametrize("status", sorted(AUDITED_CLAIM_STATUSES))
def test_re_auditing_a_claim_into_its_current_status_records_a_fresh_assessment(
    status: ClaimStatus,
) -> None:
    """A confirming re-audit is a real audit: the verdict stands and the assessment is new."""
    first = audit_claim(
        sty.make_claim(),
        status=status,
        allowed_strength=ClaimScope.INDIVIDUAL,
        actor="auditor",
        maximum_defensible_wording="in the work examined",
    )
    again = audit_claim(
        first,
        status=status,
        allowed_strength=ClaimScope.INDIVIDUAL,
        actor="auditor",
        maximum_defensible_wording="among the papers examined",
    )

    assert again.status is status
    assert again.assessment.maximum_defensible_wording == "among the papers examined"
    assert again.assessment.audited_at is not None
    assert first.assessment.audited_at is not None
    assert again.assessment.audited_at >= first.assessment.audited_at


def test_an_audited_claim_never_returns_to_unverified() -> None:
    """`unverified` is the state before any audit, so nothing transitions back into it."""
    for status in AUDITED_CLAIM_STATUSES:
        assert ClaimStatus.UNVERIFIED not in CLAIM_TRANSITIONS[status]
    assert ClaimStatus.UNVERIFIED not in CLAIM_TRANSITIONS[ClaimStatus.UNVERIFIED]


def test_superseded_is_the_only_terminal_claim_status() -> None:
    assert CLAIM_TRANSITIONS[ClaimStatus.SUPERSEDED] == frozenset()
    for status, targets in CLAIM_TRANSITIONS.items():
        if status is not ClaimStatus.SUPERSEDED:
            assert ClaimStatus.SUPERSEDED in targets


def audited_claim() -> Claim:
    return audit_claim(
        sty.make_claim(),
        status=ClaimStatus.QUALIFIED,
        allowed_strength=ClaimScope.CORPUS_PATTERN,
        actor="auditor",
    )


def test_override_requires_an_accepted_epistemic_override_decision() -> None:
    claim = audited_claim()
    proposed = sty.make_override_decision(status=DecisionStatus.PROPOSED)
    with pytest.raises(TransitionError, match="accepted"):
        override_claim_strength(claim, proposed)
    wrong_type = sty.make_override_decision(
        type=DecisionType.METHODOLOGY,
        claim=None,
        auditor_recommendation=None,
        researcher_selected=None,
    )
    with pytest.raises(TransitionError, match="epistemic_override"):
        override_claim_strength(claim, wrong_type)


def test_override_must_reference_this_claim() -> None:
    with pytest.raises(TransitionError, match="does not reference"):
        override_claim_strength(audited_claim(), sty.make_override_decision(claim=ClaimId("C0099")))


def test_override_must_be_authored_by_the_researcher() -> None:
    decision = sty.make_override_decision(provenance=Provenance.model(MODEL_ACTOR))
    with pytest.raises(AuthorityError):
        override_claim_strength(audited_claim(), decision)


def test_override_must_agree_with_the_current_auditor_recommendation() -> None:
    stale_decision = sty.make_override_decision(
        auditor_recommendation=ClaimScope.INDIVIDUAL,
        researcher_selected=ClaimScope.FIELD_GENERALIZATION,
    )
    with pytest.raises(TransitionError, match="re-audit"):
        override_claim_strength(audited_claim(), stale_decision)


def test_override_records_the_decision_on_the_claim() -> None:
    """Product 38: the researcher may overrule the auditor, visibly."""
    claim = audited_claim()
    decision = sty.make_override_decision()
    overridden = override_claim_strength(claim, decision)
    assert overridden.allowed_strength is ClaimScope.FIELD_GENERALIZATION
    assert DecisionId("D0027") in overridden.decisions
    assert overridden.requested_strength is claim.requested_strength
    again = override_claim_strength(claim, decision)
    assert again.decisions == overridden.decisions


def test_override_cannot_exceed_the_requested_strength() -> None:
    claim = audit_claim(
        sty.make_claim(),
        status=ClaimStatus.QUALIFIED,
        allowed_strength=ClaimScope.CORPUS_PATTERN,
        actor="auditor",
    )
    decision = sty.make_override_decision(researcher_selected=ClaimScope.UNIVERSAL_OR_ABSENCE)
    with pytest.raises(TransitionError, match="exceeds the requested"):
        override_claim_strength(claim, decision)


# --- notes, questions, decisions -------------------------------------------


def test_notes_are_promoted_only_by_a_human_and_only_once() -> None:
    note = sty.make_note()
    with pytest.raises(AuthorityError):
        promote_note(note, promoted_to=ClaimId("C0041"), actor=MODEL_ACTOR)
    promoted = promote_note(note, promoted_to=ClaimId("C0041"), actor="human")
    assert promoted.status is NoteStatus.PROMOTED
    assert promoted.promoted_to == ClaimId("C0041")
    with pytest.raises(TransitionError):
        promote_note(promoted, promoted_to=ClaimId("C0042"), actor="human")


def test_discarded_notes_are_terminal() -> None:
    discarded = discard_note(sty.make_note(), actor="human")
    assert discarded.status is NoteStatus.DISCARDED
    with pytest.raises(TransitionError):
        promote_note(discarded, promoted_to=ClaimId("C0041"), actor="human")


def test_questions_move_between_open_partial_answered_and_blocked() -> None:
    question = sty.make_question()
    partial = transition_question(question, QuestionStatus.PARTIALLY_ANSWERED, actor="human")
    answered = transition_question(partial, QuestionStatus.ANSWERED, actor="human")
    blocked = transition_question(answered, QuestionStatus.BLOCKED, actor="human")
    assert transition_question(blocked, QuestionStatus.OPEN, actor="human").status is (
        QuestionStatus.OPEN
    )
    with pytest.raises(TransitionError):
        transition_question(question, QuestionStatus.OPEN, actor="human")


def test_decisions_are_accepted_only_by_a_human() -> None:
    decision = sty.make_override_decision(status=DecisionStatus.PROPOSED)
    with pytest.raises(AuthorityError):
        transition_decision(decision, DecisionStatus.ACCEPTED, actor=MODEL_ACTOR)
    accepted = transition_decision(decision, DecisionStatus.ACCEPTED, actor="human")
    assert accepted.status is DecisionStatus.ACCEPTED
    superseded = transition_decision(accepted, DecisionStatus.SUPERSEDED, actor="system")
    assert superseded.status is DecisionStatus.SUPERSEDED
    with pytest.raises(TransitionError):
        transition_decision(superseded, DecisionStatus.ACCEPTED, actor="human")


# --- introspection ----------------------------------------------------------


@pytest.mark.parametrize("kind", list(TransitionKind))
def test_allowed_transitions_exposes_every_table(kind: TransitionKind) -> None:
    table = allowed_transitions(kind)
    assert table
    assert allowed_transitions(kind.value) == table


def test_allowed_transitions_accepts_enum_members_as_keys() -> None:
    table = allowed_transitions(TransitionKind.EVIDENCE)
    assert EvidenceStatus.ACCEPTED in table[EvidenceStatus.VERIFIED]
    assert EvidenceStatus.ACCEPTED not in table[EvidenceStatus.PROPOSED]


def test_allowed_transitions_rejects_an_unknown_kind() -> None:
    with pytest.raises(DomainValidationError):
        allowed_transitions("manuscript")


@pytest.mark.parametrize(
    ("table", "states"),
    [
        (EVIDENCE_TRANSITIONS, EvidenceStatus),
        (CLAIM_TRANSITIONS, ClaimStatus),
        (DECISION_TRANSITIONS, DecisionStatus),
        (NOTE_TRANSITIONS, NoteStatus),
        (QUESTION_TRANSITIONS, QuestionStatus),
    ],
)
def test_tables_are_total_and_closed(table: object, states: type) -> None:
    assert set(table) == set(states)  # type: ignore[call-overload]
    for targets in table.values():  # type: ignore[attr-defined]
        assert set(targets) <= set(states)


def test_verification_record_cannot_claim_acceptance_without_an_acceptor() -> None:
    with pytest.raises(ValueError, match="accepted_by"):
        VerificationRecord(status=EvidenceStatus.ACCEPTED)
