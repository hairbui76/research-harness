"""Controlled vocabularies match the Product specification and stay distinct."""

from __future__ import annotations

import enum

import pytest

from research_harness.domain import enums


def _vocabularies() -> list[type[enum.Enum]]:
    return [
        value
        for value in vars(enums).values()
        if isinstance(value, type)
        and issubclass(value, enum.Enum)
        and value.__module__ == enums.__name__
    ]


def test_every_vocabulary_is_a_string_enum_except_the_numeric_review_tier() -> None:
    for vocabulary in _vocabularies():
        if vocabulary is enums.ReviewTier:
            assert issubclass(vocabulary, enum.IntEnum)
        else:
            assert issubclass(vocabulary, enum.StrEnum), vocabulary


def test_vocabulary_values_are_unique() -> None:
    for vocabulary in _vocabularies():
        values = [member.value for member in vocabulary]
        assert len(values) == len(set(values)), vocabulary


def test_evidence_origins_match_product_9_1() -> None:
    assert {origin.value for origin in enums.EvidenceOrigin} == {
        "source_observed",
        "author_claimed",
        "author_interpreted",
        "researcher_inferred",
        "model_proposed",
        "external_metadata",
    }


def test_evidence_types_match_product_9_2() -> None:
    assert {kind.value for kind in enums.EvidenceType} == {
        "method_description",
        "representation_description",
        "experimental_setup",
        "experimental_result",
        "ablation_result",
        "dataset_description",
        "baseline_description",
        "limitation",
        "author_conclusion",
        "definition",
        "theoretical_result",
        "implementation_detail",
        "deployment_assumption",
        "bibliographic_metadata",
    }


def test_evidence_strengths_match_product_9_3() -> None:
    assert [strength.value for strength in enums.EvidenceStrength] == [
        "direct",
        "indirect",
        "derived",
    ]


def test_negative_evidence_states_remain_five_distinct_values() -> None:
    """Product 11 / principle P5: absence of evidence is not evidence of absence."""
    states = list(enums.NegativeEvidenceState)
    assert len(states) == 5
    assert len({state.value for state in states}) == 5
    assert enums.NegativeEvidenceState.NOT_FOUND != enums.NegativeEvidenceState.ABSENT
    assert enums.NegativeEvidenceState.NOT_REPORTED != enums.NegativeEvidenceState.NOT_FOUND
    assert enums.NegativeEvidenceState.NOT_APPLICABLE != enums.NegativeEvidenceState.UNCLEAR


def test_only_not_found_and_not_reported_are_promotable_to_absent() -> None:
    assert {
        enums.NegativeEvidenceState.NOT_FOUND,
        enums.NegativeEvidenceState.NOT_REPORTED,
    } == enums.PROMOTABLE_NEGATIVE_STATES


def test_claim_types_match_product_10_1() -> None:
    assert {kind.value for kind in enums.ClaimType} == {
        "descriptive",
        "comparative",
        "prevalence",
        "absence",
        "causal",
        "taxonomic",
        "methodological",
        "synthesis",
        "recommendation",
    }


def test_claim_scope_ladder_is_ordered_l0_to_l4() -> None:
    ladder = [
        enums.ClaimScope.INDIVIDUAL,
        enums.ClaimScope.OBSERVED_SUBSET,
        enums.ClaimScope.CORPUS_PATTERN,
        enums.ClaimScope.FIELD_GENERALIZATION,
        enums.ClaimScope.UNIVERSAL_OR_ABSENCE,
    ]
    assert [scope.level for scope in ladder] == [0, 1, 2, 3, 4]
    assert sorted(reversed(ladder)) == ladder
    assert enums.ClaimScope.CORPUS_PATTERN < enums.ClaimScope.FIELD_GENERALIZATION
    assert enums.ClaimScope.UNIVERSAL_OR_ABSENCE > enums.ClaimScope.INDIVIDUAL
    assert enums.ClaimScope.CORPUS_PATTERN <= enums.ClaimScope.CORPUS_PATTERN
    assert enums.ClaimScope.CORPUS_PATTERN >= enums.ClaimScope.CORPUS_PATTERN


def test_claim_scope_order_is_not_alphabetical() -> None:
    """`corpus_pattern` sorts before `individual` alphabetically but is a stronger scope."""
    assert enums.ClaimScope.CORPUS_PATTERN > enums.ClaimScope.INDIVIDUAL


def test_claim_scope_from_level_and_label() -> None:
    assert enums.ClaimScope.from_level(2) is enums.ClaimScope.CORPUS_PATTERN
    assert enums.ClaimScope.CORPUS_PATTERN.label == "L2 corpus_pattern"
    with pytest.raises(ValueError, match="out of range"):
        enums.ClaimScope.from_level(5)


def test_claim_statuses_match_product_10_3() -> None:
    assert {status.value for status in enums.ClaimStatus} == {
        "unverified",
        "supported",
        "qualified",
        "contested",
        "unsupported",
        "superseded",
    }


def test_claim_evidence_relations_match_product_10_4() -> None:
    assert {relation.value for relation in enums.ClaimEvidenceRelationType} == {
        "supports",
        "contradicts",
        "qualifies",
        "contextualizes",
        "exemplifies",
        "incomparable_under_current_evidence",
    }


def test_screening_states_match_product_14() -> None:
    assert [state.value for state in enums.ScreeningState] == [
        "discovered",
        "screened",
        "included",
        "excluded",
    ]


def test_question_statuses_match_product_31() -> None:
    assert {status.value for status in enums.QuestionStatus} == {
        "open",
        "partially_answered",
        "answered",
        "blocked",
    }


def test_evidence_lifecycle_statuses() -> None:
    assert {status.value for status in enums.EvidenceStatus} == {
        "proposed",
        "verified",
        "accepted",
        "rejected",
        "deferred",
        "stale",
        "superseded",
    }


def test_review_actions_match_product_24_3() -> None:
    assert {action.value for action in enums.ReviewAction} == {
        "accept",
        "accept_with_qualification",
        "edit",
        "reject",
        "defer",
        "request_more_evidence",
    }
    assert {
        enums.ReviewAction.ACCEPT,
        enums.ReviewAction.ACCEPT_WITH_QUALIFICATION,
    } == enums.ACCEPTING_REVIEW_ACTIONS


def test_review_tiers_are_ordered_levels() -> None:
    assert [int(tier) for tier in enums.ReviewTier] == [0, 1, 2]
    assert enums.ReviewTier.TIER_0 < enums.ReviewTier.TIER_2


def test_strict_is_the_default_review_policy_vocabulary() -> None:
    assert enums.ReviewPolicy.STRICT.value == "strict"
    assert enums.ReviewPolicy.POLICY_BATCH.value == "policy_batch"


def test_interpretive_origins_require_human_judgement() -> None:
    assert {
        enums.EvidenceOrigin.AUTHOR_INTERPRETED,
        enums.EvidenceOrigin.RESEARCHER_INFERRED,
        enums.EvidenceOrigin.MODEL_PROPOSED,
    } == enums.INTERPRETIVE_ORIGINS
    assert enums.EvidenceOrigin.SOURCE_OBSERVED not in enums.INTERPRETIVE_ORIGINS
    assert enums.EvidenceOrigin.AUTHOR_CLAIMED not in enums.INTERPRETIVE_ORIGINS


def test_semantic_event_types_include_product_19_3() -> None:
    # Product 19.3 lists the core vocabulary; the capability layer adds further
    # state-changing semantics (never prompts or traces).
    assert {event.value for event in enums.ResearchEventType} >= {
        "work.ingested",
        "evidence.proposed",
        "evidence.accepted",
        "evidence.rejected",
        "claim.created",
        "claim.audited",
        "claim.qualified",
        "taxonomy.revised",
        "decision.accepted",
        "manuscript.claim_attached",
    }


def test_a_superseded_decision_has_its_own_event_type() -> None:
    """`taxonomy.revised` names a vocabulary change; retiring the decision behind it does not.

    `decision.supersede` used to borrow `taxonomy.revised` or `decision.accepted` for want
    of a member, which made the log say a taxonomy was written when one was retired.
    """
    assert enums.ResearchEventType.DECISION_SUPERSEDED.value == "decision.superseded"
    assert (
        enums.ResearchEventType.DECISION_SUPERSEDED is not enums.ResearchEventType.TAXONOMY_REVISED
    )


def test_provenance_sources_carry_no_provider_names() -> None:
    values = {source.value for source in enums.ProvenanceSource}
    assert values == {"human", "model", "system", "external_metadata"}
    assert not {value for value in values if value in {"openai", "anthropic", "claude"}}


def test_supporting_vocabularies_exist() -> None:
    assert {kind.value for kind in enums.DocumentBlockKind} >= {
        "section",
        "paragraph",
        "table",
        "table_cell",
        "figure_caption",
        "table_caption",
        "equation",
        "reference",
        "footnote",
        "other",
    }
    assert {kind.value for kind in enums.VersionKind} >= {"arxiv", "camera_ready", "publisher"}
    assert {kind.value for kind in enums.ArtifactKind} >= {"pdf", "html", "supplement"}
    assert {risk.value for risk in enums.OverturnRisk} == {
        "low",
        "low_moderate",
        "moderate",
        "high",
        "unknown",
    }
    assert {state.value for state in enums.StaleState} == {"fresh", "stale"}
    assert {status.value for status in enums.NoteStatus} == {
        "captured",
        "promoted",
        "discarded",
    }
    assert {kind.value for kind in enums.DecisionType} >= {
        "taxonomy_revision",
        "epistemic_override",
        "inclusion",
        "exclusion",
        "methodology",
        "other",
    }
    assert {status.value for status in enums.DecisionStatus} == {
        "proposed",
        "accepted",
        "superseded",
    }
    assert {verdict.value for verdict in enums.VerificationVerdict} == {
        "supported",
        "partially_supported",
        "contradicted",
        "insufficient_evidence",
    }
    assert {outcome.value for outcome in enums.IdentityResolutionOutcome} == {
        "same_artifact",
        "same_version",
        "same_work",
        "distinct_work",
        "unresolved",
    }
    assert {kind.value for kind in enums.ManuscriptFindingKind} == {
        "unregistered_claim",
        "over_strong_wording",
        "citation_mismatch",
        "unsupported_numeric",
        "stale_claim",
        "invalid_evidence_anchor",
    }
    assert {status.value for status in enums.ManuscriptAnchorStatus} == {
        "valid",
        "stale",
        "missing",
    }
