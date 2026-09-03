"""The query planner: the four worked examples of Product 15.2, and the ladder order.

Planning is rule-based, so these tests are the specification of the rules. Each of the
four example queries in Product 15.2 has to reach the plan the product says it should, the
modes always have to come back in authority order, and a caller's hints always have to win
over a regular expression.
"""

from __future__ import annotations

import pytest

from research_harness.domain.ids import ClaimId, WorkId
from research_harness.projection.fts import fts_query
from research_harness.retrieval.planner import (
    LADDER,
    Intent,
    QueryHints,
    RetrievalHit,
    RetrievalMode,
    identifiers,
    infer_intent,
    plan_query,
    search_terms,
)
from research_harness.retrieval.structured import Authority, Location

DATASET_QUERY = "Which papers use CICIDS2017?"
MISMATCH_QUERY = "Which systems serialize traffic similarly but use different terminology?"
ACKNOWLEDGE_QUERY = "Does this paper acknowledge encrypted-traffic limitations?"
CHALLENGE_QUERY = "Which independent papers challenge C0041?"


# --- Product 15.2, example by example ---------------------------------------


def test_a_named_dataset_is_looked_up_in_accepted_state_and_searched_exactly() -> None:
    plan = plan_query(DATASET_QUERY)

    assert plan.modes == (RetrievalMode.STRUCTURED_ONLY, RetrievalMode.FTS_SECTION)
    assert plan.identifiers == ("CICIDS2017",)
    assert plan.works_question is True
    assert plan.structured is not None
    assert plan.structured.entity == "evidence"
    assert plan.structured.filters == {"dataset": "CICIDS2017", "status": "accepted"}
    assert plan.rationale


def test_a_dataset_query_does_not_reach_for_the_vector_index() -> None:
    """An exact term is answerable exactly; embeddings would only add noise (ADR-006)."""
    plan = plan_query(DATASET_QUERY)

    assert RetrievalMode.STRUCTURED_SEMANTIC not in plan.modes
    assert RetrievalMode.CITATION_NEIGHBORHOOD not in plan.modes


def test_a_terminology_mismatch_cue_adds_semantic_search_to_structured_filters() -> None:
    plan = plan_query(MISMATCH_QUERY)

    assert RetrievalMode.STRUCTURED_SEMANTIC in plan.modes
    assert RetrievalMode.STRUCTURED_ONLY in plan.modes
    assert plan.semantic_query == MISMATCH_QUERY


def test_an_acknowledgement_question_is_constrained_to_the_hedging_sections() -> None:
    plan = plan_query(ACKNOWLEDGE_QUERY)

    assert RetrievalMode.FTS_SECTION in plan.modes
    assert RetrievalMode.STRUCTURED_SEMANTIC in plan.modes
    assert plan.sections == ("Discussion", "Limitations", "Conclusion")


def test_a_challenge_to_a_claim_walks_the_claim_graph_then_citations_then_semantics() -> None:
    plan = plan_query(CHALLENGE_QUERY)

    assert plan.claim == ClaimId("C0041")
    assert RetrievalMode.CLAIM_GRAPH_SEMANTIC in plan.modes
    assert RetrievalMode.CITATION_NEIGHBORHOOD in plan.modes
    assert RetrievalMode.STRUCTURED_SEMANTIC in plan.modes
    assert plan.intent is Intent.FIND_COUNTER_EVIDENCE
    assert plan.structured is not None and plan.structured.entity == "claim"


# --- the ladder -------------------------------------------------------------


@pytest.mark.parametrize(
    "query", [DATASET_QUERY, MISMATCH_QUERY, ACKNOWLEDGE_QUERY, CHALLENGE_QUERY, "traffic"]
)
def test_modes_always_come_back_in_authority_order(query: str) -> None:
    modes = plan_query(query).modes

    assert list(modes) == [mode for mode in LADDER if mode in modes]


def test_the_ladder_never_puts_a_weaker_rung_before_a_stronger_one() -> None:
    rungs = [mode.rung for mode in LADDER]

    assert rungs == sorted(rungs)
    assert LADDER[0] is RetrievalMode.STRUCTURED_ONLY
    assert LADDER[-1] is RetrievalMode.EXTERNAL_DISCOVERY


def test_an_unclassified_query_walks_the_local_ladder_and_stops_before_the_neighbourhood() -> None:
    plan = plan_query("packet descriptor buckets")

    assert plan.modes == (
        RetrievalMode.STRUCTURED_ONLY,
        RetrievalMode.FTS_SECTION,
        RetrievalMode.STRUCTURED_SEMANTIC,
    )
    assert RetrievalMode.EXTERNAL_DISCOVERY not in plan.modes


def test_a_query_with_no_structural_filter_plans_no_structured_lookup() -> None:
    """Returning the first page of a table would look like an answer without being one."""
    assert plan_query("packet descriptor buckets").structured is None


# --- hints override rules ---------------------------------------------------


def test_caller_hints_beat_the_rules() -> None:
    hints = QueryHints(
        modes=(RetrievalMode.STRUCTURED_SEMANTIC,),
        intent=Intent.FIND_SUPPORT,
        work=WorkId("W0017"),
        claim=ClaimId("C0007"),
    )

    plan = plan_query(DATASET_QUERY, hints=hints)

    assert plan.modes == (RetrievalMode.STRUCTURED_SEMANTIC,)
    assert plan.intent is Intent.FIND_SUPPORT
    assert plan.work == WorkId("W0017")
    assert plan.claim == ClaimId("C0007")


def test_an_entity_hint_becomes_the_structured_query() -> None:
    hints = QueryHints(entity="block", filters={"kind": "table"})

    plan = plan_query("anything", hints=hints)

    assert plan.structured is not None
    assert plan.structured.entity == "block"
    assert plan.structured.filters == {"kind": "table"}


# --- terms ------------------------------------------------------------------


def test_search_terms_drops_grammar_and_the_words_that_name_the_corpus() -> None:
    terms = search_terms(DATASET_QUERY)

    assert terms == "use OR CICIDS2017"
    assert fts_query(terms)


def test_search_terms_keeps_a_quoted_phrase_whole() -> None:
    terms = search_terms('papers about "encrypted network traffic" and F1')

    assert terms.startswith('"encrypted network traffic"')
    assert "F1" in terms


def test_search_terms_is_empty_when_nothing_searchable_is_left() -> None:
    assert search_terms("which of these are the same?") == ""


def test_identifiers_finds_dataset_tokens_and_ignores_harness_ids() -> None:
    assert identifiers("Does W0017 evaluate on CICIDS2017 and ImageNet21k?") == (
        "CICIDS2017",
        "ImageNet21k",
    )
    assert identifiers("compare C0041 with E0482") == ()


# --- intent -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("which papers contradict C0041?", Intent.FIND_COUNTER_EVIDENCE),
        ("what supports the claim that pretraining helps?", Intent.FIND_SUPPORT),
        ("what F1 did TrafficLM report?", Intent.AUDIT_EMPIRICAL_RESULT),
        ("results on the held out split", Intent.AUDIT_EMPIRICAL_RESULT),
        ("packet descriptor tokenization", Intent.EXPLORE),
    ],
)
def test_intent_is_read_from_the_verbs(query: str, expected: Intent) -> None:
    assert infer_intent(query) is expected


# --- hits -------------------------------------------------------------------


def test_finding_the_same_object_twice_keeps_the_stronger_authority_and_both_indexes() -> None:
    lexical = RetrievalHit(
        ref="E0482",
        kind="evidence",
        authority=Authority.ACCEPTED_EVIDENCE,
        components={"lexical": 0.8},
        provenance="fts:evidence",
        location=Location(page=3),
    )
    semantic = RetrievalHit(
        ref="E0482",
        kind="evidence",
        authority=Authority.PARSED_CORPUS,
        components={"semantic": 0.6},
        provenance="semantic",
    )

    merged = lexical.merged_with(semantic)

    assert merged.authority is Authority.ACCEPTED_EVIDENCE
    assert merged.provenance == "fts:evidence+semantic"
    assert merged.components == {"lexical": 0.8, "semantic": 0.6}
    assert merged.location.page == 3
