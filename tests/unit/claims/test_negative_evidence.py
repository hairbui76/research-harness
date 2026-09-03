"""Absence states stay distinct and `absent` is only ever reached by audit (Product 11, 42.F)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from research_harness.claims import (
    ABSENCE_PHRASE,
    PromotionCheck,
    SearchEffort,
    absence_wording,
    check_promotion,
    classify_absence,
    promote_absence,
)
from research_harness.domain import (
    AuthorityError,
    ClaimScope,
    ClaimScopeSpec,
    Coverage,
    Decision,
    DecisionId,
    DecisionStatus,
    DecisionType,
    DomainValidationError,
    Evidence,
    EvidenceContent,
    NegativeEvidenceState,
    SearchRunId,
    TransitionError,
)
from tests.unit.domain import strategies as sty

CUTOFF = date(2026, 8, 31)
RUNS = (SearchRunId("SR0019"),)


def effort(**overrides: Any) -> SearchEffort:
    """A broad effort: sections, tables, synonyms, and structured fields, zero hits."""
    fields: dict[str, Any] = {
        "sections_searched": ("Method", "Experiments"),
        "tables_searched": True,
        "supplementary_searched": True,
        "synonyms": ("throughput", "packets per second"),
        "structured_fields_checked": ("dataset", "metric"),
        "lexical_hits": 0,
        "semantic_hits": 0,
    }
    return SearchEffort(**{**fields, **overrides})


def negative_evidence(state: NegativeEvidenceState) -> Evidence:
    return sty.make_evidence(
        content=EvidenceContent(negative_state=state, field="reported_throughput")
    )


def decision(**overrides: Any) -> Decision:
    fields: dict[str, Any] = {
        "id": DecisionId("D0031"),
        "type": DecisionType.OTHER,
        "status": DecisionStatus.ACCEPTED,
        "rationale": "Searched sections, tables, synonyms, and structured fields; nothing found.",
        "provenance": sty.HUMAN,
    }
    return Decision(**{**fields, **overrides})


def coverage(**overrides: Any) -> Coverage:
    fields: dict[str, Any] = {
        "relevant_works": 17,
        "examined_works": 17,
        "unresolved_works": 0,
        "search_runs": RUNS,
        "cutoff": CUTOFF,
    }
    return Coverage(**{**fields, **overrides})


# --- classification ---------------------------------------------------------


def test_a_broad_search_with_no_hits_is_not_reported() -> None:
    assert classify_absence(effort()) is NegativeEvidenceState.NOT_REPORTED


def test_a_narrow_search_with_no_hits_is_only_not_found() -> None:
    narrow = effort(tables_searched=False, synonyms=(), structured_fields_checked=())

    assert classify_absence(narrow) is NegativeEvidenceState.NOT_FOUND
    assert narrow.gaps == ("tables", "synonyms and semantic variants", "structured paper fields")


def test_missing_lexical_hits_alone_are_never_more_than_not_found() -> None:
    lexical_only = SearchEffort(sections_searched=("Method",), lexical_hits=0)

    assert classify_absence(lexical_only) is NegativeEvidenceState.NOT_FOUND


def test_a_search_that_covered_nothing_is_unclear() -> None:
    assert classify_absence(SearchEffort()) is NegativeEvidenceState.UNCLEAR


def test_any_hit_means_the_passage_must_still_be_read() -> None:
    assert classify_absence(effort(lexical_hits=2)) is NegativeEvidenceState.UNCLEAR
    assert classify_absence(effort(semantic_hits=1)) is NegativeEvidenceState.UNCLEAR


@given(
    sections=st.lists(st.sampled_from(["Method", "Results"]), max_size=2),
    tables=st.booleans(),
    supplementary=st.booleans(),
    synonyms=st.lists(st.sampled_from(["a", "b"]), max_size=2),
    fields=st.lists(st.sampled_from(["dataset", "metric"]), max_size=2),
    lexical=st.integers(min_value=0, max_value=5),
    semantic=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=50)
def test_classification_never_produces_absent(
    sections: list[str],
    tables: bool,
    supplementary: bool,
    synonyms: list[str],
    fields: list[str],
    lexical: int,
    semantic: int,
) -> None:
    state = classify_absence(
        SearchEffort(
            sections_searched=tuple(sections),
            tables_searched=tables,
            supplementary_searched=supplementary,
            synonyms=tuple(synonyms),
            structured_fields_checked=tuple(fields),
            lexical_hits=lexical,
            semantic_hits=semantic,
        )
    )

    assert state is not NegativeEvidenceState.ABSENT


# --- promotion policy -------------------------------------------------------


def check(
    from_state: NegativeEvidenceState,
    to_state: NegativeEvidenceState = NegativeEvidenceState.ABSENT,
    **overrides: Any,
) -> PromotionCheck:
    fields: dict[str, Any] = {
        "decision": decision(),
        "actor": "human:alice",
        "coverage": coverage(),
        "search_runs_recorded": 1,
    }
    return check_promotion(from_state, to_state, **{**fields, **overrides})


def test_not_reported_may_be_promoted_with_a_human_decision_and_coverage() -> None:
    result = check(NegativeEvidenceState.NOT_REPORTED)

    assert result == PromotionCheck(allowed=True, reasons=())


def test_not_found_can_never_be_promoted_to_absent() -> None:
    result = check(NegativeEvidenceState.NOT_FOUND)

    assert not result.allowed
    assert any("not_reported" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "state",
    [
        NegativeEvidenceState.NOT_APPLICABLE,
        NegativeEvidenceState.UNCLEAR,
        NegativeEvidenceState.ABSENT,
    ],
)
def test_states_outside_the_audited_path_never_promote(state: NegativeEvidenceState) -> None:
    result = check(state)

    assert not result.allowed
    assert result.reasons


@pytest.mark.parametrize(
    "target",
    [
        NegativeEvidenceState.NOT_FOUND,
        NegativeEvidenceState.NOT_REPORTED,
        NegativeEvidenceState.UNCLEAR,
        NegativeEvidenceState.NOT_APPLICABLE,
    ],
)
def test_only_absent_is_an_audited_promotion(target: NegativeEvidenceState) -> None:
    result = check(NegativeEvidenceState.NOT_REPORTED, target)

    assert not result.allowed


def test_a_model_actor_cannot_conclude_absence() -> None:
    result = check(NegativeEvidenceState.NOT_REPORTED, actor="vendor-a/model-x")

    assert not result.allowed
    assert any("human actor" in reason for reason in result.reasons)


def test_promotion_requires_an_accepted_decision() -> None:
    assert not check(NegativeEvidenceState.NOT_REPORTED, decision=None).allowed
    proposed = check(
        NegativeEvidenceState.NOT_REPORTED, decision=decision(status=DecisionStatus.PROPOSED)
    )
    assert not proposed.allowed
    assert any("accepted" in reason for reason in proposed.reasons)


def test_promotion_requires_coverage_with_a_cutoff_and_a_recorded_run() -> None:
    assert not check(NegativeEvidenceState.NOT_REPORTED, coverage=None).allowed
    assert not check(NegativeEvidenceState.NOT_REPORTED, coverage=coverage(cutoff=None)).allowed
    assert not check(NegativeEvidenceState.NOT_REPORTED, search_runs_recorded=0).allowed


def test_every_missing_condition_is_reported_at_once() -> None:
    result = check(
        NegativeEvidenceState.NOT_REPORTED,
        decision=None,
        actor="workflow:absence_audit",
        coverage=coverage(cutoff=None),
        search_runs_recorded=0,
    )

    assert not result.allowed
    assert len(result.reasons) == 4


# --- the transition itself --------------------------------------------------


def test_promote_absence_records_the_state_and_the_authorising_decision() -> None:
    audited = decision()

    promoted = promote_absence(
        negative_evidence(NegativeEvidenceState.NOT_REPORTED),
        decision=audited,
        actor="human:alice",
        coverage=coverage(),
    )

    assert promoted.content.negative_state is NegativeEvidenceState.ABSENT
    assert audited.id in promoted.decisions
    assert promoted.verification.rationale == audited.rationale


def test_promote_absence_defaults_the_run_count_to_the_coverage_record() -> None:
    with pytest.raises(TransitionError, match="no search run is recorded"):
        promote_absence(
            negative_evidence(NegativeEvidenceState.NOT_REPORTED),
            decision=decision(),
            actor="human:alice",
            coverage=coverage(search_runs=()),
        )


def test_promote_absence_refuses_a_model_actor_with_an_authority_error() -> None:
    with pytest.raises(AuthorityError, match="human actor"):
        promote_absence(
            negative_evidence(NegativeEvidenceState.NOT_REPORTED),
            decision=decision(),
            actor="vendor-a/model-x",
            coverage=coverage(),
        )


def test_promote_absence_refuses_not_found_evidence() -> None:
    with pytest.raises(TransitionError, match="broaden the search"):
        promote_absence(
            negative_evidence(NegativeEvidenceState.NOT_FOUND),
            decision=decision(),
            actor="human:alice",
            coverage=coverage(),
        )


def test_promote_absence_needs_evidence_that_records_a_negative_state() -> None:
    with pytest.raises(TransitionError, match="does not record a negative state"):
        promote_absence(
            sty.make_evidence(),
            decision=decision(),
            actor="human:alice",
            coverage=coverage(),
        )


# --- wording ----------------------------------------------------------------


def scope(**overrides: Any) -> ClaimScopeSpec:
    fields: dict[str, Any] = {
        "level": ClaimScope.UNIVERSAL_OR_ABSENCE,
        "corpus": "structured-traffic-llm",
        "publication_until": "2026-08",
    }
    return ClaimScopeSpec(**{**fields, **overrides})


def test_absence_wording_names_the_corpus_cutoff_and_the_size_of_the_search() -> None:
    runs = (
        sty.make_search_run(),
        sty.make_search_run(
            id=SearchRunId("SR0020"),
            sources=("dblp",),
            queries=("adversarial traffic", "protocol compliance"),
        ),
    )

    wording = absence_wording(scope(), coverage(), runs)

    assert wording.startswith("Within the structured-traffic-llm corpus up to 2026-08")
    assert "3 sources" in wording
    assert "3 queries" in wording
    assert "2 recorded search runs" in wording
    assert ABSENCE_PHRASE in wording
    assert "no work exists" not in wording


def test_absence_wording_requires_recorded_search_coverage() -> None:
    with pytest.raises(DomainValidationError, match="recorded search coverage"):
        absence_wording(scope(), coverage(search_runs=()), (sty.make_search_run(),))
    with pytest.raises(DomainValidationError, match="recorded search coverage"):
        absence_wording(scope(), coverage(), ())


def test_absence_wording_falls_back_to_the_coverage_and_run_cutoffs() -> None:
    run = sty.make_search_run(cutoff=date(2026, 7, 1), executed_at=datetime(2026, 7, 2, tzinfo=UTC))

    from_coverage = absence_wording(scope(publication_until=None), coverage(), (run,))
    from_run = absence_wording(scope(publication_until=None), coverage(cutoff=None), (run,))
    from_execution = absence_wording(
        scope(publication_until=None),
        coverage(cutoff=None),
        (sty.make_search_run(executed_at=datetime(2026, 7, 2, tzinfo=UTC)),),
    )

    assert "up to 2026-08-31" in from_coverage
    assert "up to 2026-07-01" in from_run
    assert "up to 2026-07-02" in from_execution


def test_absence_wording_uses_a_neutral_corpus_name_when_none_is_declared() -> None:
    wording = absence_wording(scope(corpus=None), coverage(), (sty.make_search_run(),))

    assert wording.startswith("Within the reviewed corpus")
    assert "1 query across 1 recorded search run)" in wording
