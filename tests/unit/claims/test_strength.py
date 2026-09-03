"""The scope ladder L0-L4 and the maximum defensible wording it licenses (Product 10)."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from research_harness.claims import (
    ABSENCE_PHRASE,
    FIELD_WORDING,
    INDIVIDUAL_WORDING,
    LEVEL_REQUIREMENTS,
    MAJORITY_WORDING,
    OBSERVED_SUBSET_WORDING,
    SEVERAL_WORDING,
    UNIVERSAL_WORDING,
    EvidenceSummary,
    StrengthInput,
    assess_strength,
    build_facts,
    summarize,
    wording_for,
)
from research_harness.domain import (
    ClaimEvidenceRelation,
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    Coverage,
    EvidenceContent,
    EvidenceId,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    OverturnRisk,
    StaleState,
    WorkId,
)
from tests.unit.domain import strategies as sty

LADDER = list(ClaimScope)


def summary(number: int, work: int | None = None, **overrides: Any) -> EvidenceSummary:
    """A supporting, accepted, fresh, direct, source-observed summary from its own work."""
    fields: dict[str, Any] = {
        "evidence": EvidenceId.make(number),
        "work": WorkId.make(number if work is None else work),
        "origin": EvidenceOrigin.SOURCE_OBSERVED,
        "strength": EvidenceStrength.DIRECT,
        "evidence_type": EvidenceType.METHOD_DESCRIPTION,
        "status": EvidenceStatus.ACCEPTED,
        "stale": StaleState.FRESH,
        "relation": ClaimEvidenceRelationType.SUPPORTS,
    }
    return EvidenceSummary(**{**fields, **overrides})


def supports(count: int, start: int = 1) -> tuple[EvidenceSummary, ...]:
    """``count`` independent supporting works."""
    return tuple(summary(number) for number in range(start, start + count))


def coverage(
    relevant: int = 10,
    examined: int = 10,
    unresolved: int = 0,
    risk: OverturnRisk = OverturnRisk.LOW,
    cutoff: str | None = "2026-08-31",
) -> Coverage:
    """A coverage record described by its counts, not by a ledger."""
    from datetime import date

    return Coverage(
        relevant_works=relevant,
        examined_works=examined,
        unresolved_works=unresolved,
        overturn_risk=risk,
        cutoff=date.fromisoformat(cutoff) if cutoff else None,
    )


def request(
    requested: ClaimScope,
    summaries: tuple[EvidenceSummary, ...] = (),
    **overrides: Any,
) -> StrengthInput:
    fields: dict[str, Any] = {
        "claim_type": ClaimType.PREVALENCE,
        "requested": requested,
        "summaries": summaries,
        "coverage": coverage(),
        "search_runs_recorded": 1,
    }
    return StrengthInput(**{**fields, **overrides})


# --- the ladder, level by level ---------------------------------------------


def test_level_requirements_name_every_scope_with_unique_keys() -> None:
    assert set(LEVEL_REQUIREMENTS) == set(ClaimScope)
    keys = [item.key for level in LEVEL_REQUIREMENTS.values() for item in level]
    assert len(keys) == len(set(keys))
    assert all(item.requirement for level in LEVEL_REQUIREMENTS.values() for item in level)


def test_no_accepted_support_is_unsupported_at_the_ladder_floor() -> None:
    result = assess_strength(request(ClaimScope.OBSERVED_SUBSET))

    assert result.allowed is ClaimScope.INDIVIDUAL
    assert result.status is ClaimStatus.UNSUPPORTED
    assert "l0.support" in result.blocked_by


def test_one_support_reaches_the_observed_subset_wording() -> None:
    result = assess_strength(request(ClaimScope.OBSERVED_SUBSET, supports(1)))

    assert result.allowed is ClaimScope.OBSERVED_SUBSET
    assert result.wording == OBSERVED_SUBSET_WORDING
    assert result.status is ClaimStatus.SUPPORTED


def test_corpus_pattern_needs_three_independent_works() -> None:
    two_works = (summary(1, work=1), summary(2, work=1), summary(3, work=2))

    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, two_works))

    assert result.independent_support == 2
    assert result.allowed is ClaimScope.OBSERVED_SUBSET
    assert "l2.independent_support" in result.blocked_by


def test_corpus_pattern_needs_a_recorded_relevant_corpus() -> None:
    result = assess_strength(
        request(ClaimScope.CORPUS_PATTERN, supports(3), coverage=coverage(relevant=0, examined=0))
    )

    assert result.allowed is ClaimScope.OBSERVED_SUBSET
    assert "l2.relevant_works" in result.blocked_by


def test_corpus_pattern_needs_half_the_relevant_corpus_examined() -> None:
    result = assess_strength(
        request(ClaimScope.CORPUS_PATTERN, supports(3), coverage=coverage(relevant=10, examined=4))
    )

    assert result.allowed is ClaimScope.OBSERVED_SUBSET
    assert "l2.examined_ratio" in result.blocked_by


def test_corpus_pattern_refuses_contradictions_above_a_third_of_support() -> None:
    against = (
        summary(90, relation=ClaimEvidenceRelationType.CONTRADICTS),
        summary(91, relation=ClaimEvidenceRelationType.CONTRADICTS),
    )

    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, (*supports(3), *against)))

    assert result.contradiction_count == 2
    assert result.allowed is ClaimScope.OBSERVED_SUBSET
    assert "l2.contradictions" in result.blocked_by


def test_corpus_wording_is_several_when_supporting_works_are_a_minority() -> None:
    result = assess_strength(
        request(ClaimScope.CORPUS_PATTERN, supports(3), coverage=coverage(relevant=10, examined=8))
    )

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert result.wording == SEVERAL_WORDING


def test_corpus_wording_is_most_when_supporting_works_are_a_majority() -> None:
    result = assess_strength(
        request(ClaimScope.CORPUS_PATTERN, supports(4), coverage=coverage(relevant=8, examined=6))
    )

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert result.wording == MAJORITY_WORDING


def test_field_generalization_needs_five_independent_works() -> None:
    result = assess_strength(request(ClaimScope.FIELD_GENERALIZATION, supports(4)))

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert "l3.independent_support" in result.blocked_by


def test_field_generalization_needs_a_recorded_search_run() -> None:
    result = assess_strength(
        request(ClaimScope.FIELD_GENERALIZATION, supports(5), search_runs_recorded=0)
    )

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert "l3.search_runs" in result.blocked_by


def test_field_generalization_needs_low_or_low_moderate_overturn_risk() -> None:
    result = assess_strength(
        request(
            ClaimScope.FIELD_GENERALIZATION,
            supports(5),
            coverage=coverage(risk=OverturnRisk.MODERATE),
        )
    )

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert "l3.overturn_risk" in result.blocked_by


def test_field_generalization_refuses_a_contradiction_against_the_whole_claim() -> None:
    flat = summary(90, relation=ClaimEvidenceRelationType.CONTRADICTS)

    result = assess_strength(request(ClaimScope.FIELD_GENERALIZATION, (*supports(9), flat)))

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert "l3.unqualified_contradiction" in result.blocked_by


def test_a_contradiction_scoped_to_an_aspect_does_not_block_field_generalization() -> None:
    scoped = summary(
        90, relation=ClaimEvidenceRelationType.CONTRADICTS, aspect="tokenizer granularity"
    )

    result = assess_strength(request(ClaimScope.FIELD_GENERALIZATION, (*supports(9), scoped)))

    assert result.allowed is ClaimScope.FIELD_GENERALIZATION
    assert result.wording == FIELD_WORDING
    assert result.status is ClaimStatus.QUALIFIED


def test_universal_wording_requires_stricter_evidence_than_corpus_level() -> None:
    """Everything that suffices for L3 still leaves L4 refused (ROADMAP Task 7.2)."""
    at_l3 = request(
        ClaimScope.UNIVERSAL_OR_ABSENCE,
        supports(6),
        coverage=coverage(relevant=10, examined=9, unresolved=1, risk=OverturnRisk.LOW_MODERATE),
    )

    result = assess_strength(at_l3)

    assert result.allowed is ClaimScope.FIELD_GENERALIZATION
    assert set(result.blocked_by) == {"l4.overturn_risk", "l4.unresolved"}


def test_universal_scope_needs_a_publication_cutoff() -> None:
    result = assess_strength(
        request(
            ClaimScope.UNIVERSAL_OR_ABSENCE,
            supports(6),
            coverage=coverage(relevant=10, examined=10, cutoff=None),
        )
    )

    assert result.allowed is ClaimScope.FIELD_GENERALIZATION
    assert "l4.cutoff" in result.blocked_by


def test_universal_scope_is_reachable_with_complete_coverage() -> None:
    result = assess_strength(
        request(ClaimScope.UNIVERSAL_OR_ABSENCE, supports(6), coverage=coverage())
    )

    assert result.allowed is ClaimScope.UNIVERSAL_OR_ABSENCE
    assert result.wording == UNIVERSAL_WORDING
    assert result.status is ClaimStatus.SUPPORTED


def test_absence_claim_needs_a_recorded_search_run_even_with_perfect_coverage() -> None:
    result = assess_strength(
        request(
            ClaimScope.UNIVERSAL_OR_ABSENCE,
            supports(6),
            claim_type=ClaimType.ABSENCE,
            search_runs_recorded=0,
        )
    )

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert "l4.absence_search_run" in result.blocked_by
    assert "l3.search_runs" in result.blocked_by


def test_absence_wording_is_hedged_at_every_level() -> None:
    for level in LADDER:
        wording = wording_for(level, ClaimType.ABSENCE, coverage(), ratio=1.0)
        assert ABSENCE_PHRASE in wording
        assert "no work exists" not in wording
        assert "2026-08-31" in wording


def test_wording_for_each_level_of_a_positive_claim() -> None:
    said = [wording_for(level, ClaimType.PREVALENCE, coverage(), 0.2) for level in LADDER]

    assert said == [
        INDIVIDUAL_WORDING,
        OBSERVED_SUBSET_WORDING,
        SEVERAL_WORDING,
        FIELD_WORDING,
        UNIVERSAL_WORDING,
    ]


# --- Gate P7 ----------------------------------------------------------------


def test_gate_p7_thin_coverage_lowers_a_field_claim_to_a_corpus_pattern() -> None:
    """Three local supports and thin coverage cannot buy a field-level generalization."""
    result = assess_strength(
        request(
            ClaimScope.FIELD_GENERALIZATION,
            supports(3),
            coverage=coverage(relevant=17, examined=9, unresolved=3, risk=OverturnRisk.MODERATE),
        )
    )

    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert result.wording in {SEVERAL_WORDING, MAJORITY_WORDING}
    assert result.status is ClaimStatus.QUALIFIED
    assert result.escalated
    assert set(result.blocked_by) == {
        "l3.independent_support",
        "l3.examined_ratio",
        "l3.unresolved_ratio",
        "l3.overturn_risk",
    }
    assert all(reason.startswith("L3 field_generalization:") for reason in result.reasons)
    assert any("3 were counted" in reason for reason in result.reasons)


# --- epistemic separation and evidence hygiene ------------------------------


def test_author_claimed_evidence_cannot_directly_support_a_numeric_claim() -> None:
    authors = tuple(summary(number, origin=EvidenceOrigin.AUTHOR_CLAIMED) for number in range(1, 4))

    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, authors, numeric=True))

    assert result.support_count == 0.0
    assert result.qualifier_count == 3
    assert result.status is ClaimStatus.UNSUPPORTED
    assert any("Product 12, 42.E" in reason for reason in result.reasons)


def test_author_claimed_evidence_may_support_a_non_numeric_descriptive_claim() -> None:
    authors = tuple(summary(number, origin=EvidenceOrigin.AUTHOR_CLAIMED) for number in range(1, 4))

    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, authors, numeric=False))

    assert result.support_count == 3.0
    assert result.allowed is ClaimScope.CORPUS_PATTERN


def test_author_claimed_experimental_result_is_never_direct_support() -> None:
    claimed = summary(
        1,
        origin=EvidenceOrigin.AUTHOR_INTERPRETED,
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
    )

    result = assess_strength(request(ClaimScope.INDIVIDUAL, (claimed,), numeric=False))

    assert result.support_count == 0.0
    assert result.qualifier_count == 1
    assert result.status is ClaimStatus.UNSUPPORTED


def test_derived_and_indirect_evidence_count_as_half_a_direct_support() -> None:
    halves = (
        summary(1, strength=EvidenceStrength.DERIVED),
        summary(2, strength=EvidenceStrength.INDIRECT),
    )

    facts = build_facts(request(ClaimScope.INDIVIDUAL, halves))

    assert facts.support_count == 1.0
    assert facts.direct_support_count == 0


def test_proposed_and_stale_evidence_are_ignored() -> None:
    ignored = (
        summary(1, status=EvidenceStatus.PROPOSED),
        summary(2, status=EvidenceStatus.VERIFIED),
        summary(3, status=EvidenceStatus.ACCEPTED, stale=StaleState.STALE),
    )

    result = assess_strength(request(ClaimScope.OBSERVED_SUBSET, ignored))

    assert result.support_count == 0.0
    assert result.status is ClaimStatus.UNSUPPORTED
    assert any("not accepted or are stale" in reason for reason in result.reasons)


def test_a_claim_is_contested_when_contradictions_match_its_support() -> None:
    against = tuple(
        summary(number, relation=ClaimEvidenceRelationType.CONTRADICTS) for number in range(90, 93)
    )

    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, (*supports(3), *against)))

    assert result.status is ClaimStatus.CONTESTED


def test_incomparable_results_are_qualifiers_not_contradictions() -> None:
    incomparable = summary(
        90, relation=ClaimEvidenceRelationType.INCOMPARABLE_UNDER_CURRENT_EVIDENCE
    )

    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, (*supports(3), incomparable)))

    assert result.contradiction_count == 0
    assert result.qualifier_count == 1
    assert result.allowed is ClaimScope.CORPUS_PATTERN
    assert result.status is ClaimStatus.QUALIFIED


def test_independent_works_override_replaces_the_distinct_work_count() -> None:
    result = assess_strength(request(ClaimScope.CORPUS_PATTERN, supports(5), independent_works=2))

    assert result.independent_support == 2
    assert result.allowed is ClaimScope.OBSERVED_SUBSET


# --- building the input from canonical objects ------------------------------


def test_summarize_reads_relations_and_skips_unknown_evidence() -> None:
    claim = sty.make_claim()
    known = sty.make_evidence(id=EvidenceId("E0132"))

    summaries = summarize(claim, {known.id: known})

    assert [item.evidence for item in summaries] == [EvidenceId("E0132")]
    assert summaries[0].relation is ClaimEvidenceRelationType.SUPPORTS
    assert summaries[0].work == known.source.work


def test_from_claim_detects_a_numeric_claim_from_its_supporting_evidence() -> None:
    claim = sty.make_claim()
    numeric = sty.make_evidence(
        id=EvidenceId("E0132"),
        content=EvidenceContent(exact_text="94.32 F1", numeric=sty.make_numeric()),
    )

    built = StrengthInput.from_claim(claim, {numeric.id: numeric})

    assert built.numeric is True
    assert built.requested is claim.assessment.requested_strength
    assert built.coverage == claim.coverage
    assert built.search_runs_recorded == 0


def test_from_claim_ignores_numbers_attached_to_a_qualifying_relation() -> None:
    claim = sty.make_claim(
        relations=(
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0180"),
                relation=ClaimEvidenceRelationType.QUALIFIES,
            ),
        )
    )
    numeric = sty.make_evidence(
        id=EvidenceId("E0180"),
        content=EvidenceContent(exact_text="94.32 F1", numeric=sty.make_numeric()),
    )

    assert StrengthInput.from_claim(claim, {numeric.id: numeric}).numeric is False


# --- invariants -------------------------------------------------------------


def _base(supports_count: int, examined: int, requested: ClaimScope) -> StrengthInput:
    return request(
        requested,
        supports(supports_count),
        coverage=coverage(relevant=10, examined=examined, risk=OverturnRisk.LOW),
    )


@given(
    supports_count=st.integers(min_value=0, max_value=7),
    extra=st.integers(min_value=0, max_value=5),
    examined=st.integers(min_value=0, max_value=10),
    requested=st.sampled_from(LADDER),
)
@settings(max_examples=50)
def test_adding_support_never_lowers_the_allowed_scope(
    supports_count: int, extra: int, examined: int, requested: ClaimScope
) -> None:
    weaker = assess_strength(_base(supports_count, examined, requested))
    stronger = assess_strength(_base(supports_count + extra, examined, requested))

    assert stronger.allowed >= weaker.allowed
    assert weaker.allowed <= stronger.allowed


@given(
    supports_count=st.integers(min_value=0, max_value=7),
    examined=st.integers(min_value=0, max_value=10),
    extra=st.integers(min_value=0, max_value=10),
    requested=st.sampled_from(LADDER),
)
@settings(max_examples=50)
def test_examining_more_of_the_corpus_never_lowers_the_allowed_scope(
    supports_count: int, examined: int, extra: int, requested: ClaimScope
) -> None:
    thin = assess_strength(_base(supports_count, examined, requested))
    thick = assess_strength(_base(supports_count, min(examined + extra, 10), requested))

    assert thick.allowed >= thin.allowed


@given(
    supports_count=st.integers(min_value=0, max_value=8),
    requested=st.sampled_from(LADDER),
    risk=st.sampled_from(list(OverturnRisk)),
    unresolved=st.integers(min_value=0, max_value=4),
)
@settings(max_examples=50)
def test_the_allowed_scope_never_exceeds_the_requested_one(
    supports_count: int, requested: ClaimScope, risk: OverturnRisk, unresolved: int
) -> None:
    result = assess_strength(
        request(
            requested,
            supports(supports_count),
            coverage=coverage(relevant=10, examined=10, unresolved=unresolved, risk=risk),
        )
    )

    assert result.allowed <= requested
    assert result.wording
