"""Research-utility reranking: the preferences ROADMAP Task 5.4 requires, as assertions.

Two of these are acceptance requirements verbatim - a Results table outranks an abstract
claim when auditing a number, and accepted Evidence outranks similar-sounding prose when
looking for support - and the third is that every hit says why it ranked where it did.
"""

from __future__ import annotations

import pytest

from research_harness.domain.ids import BlockId, WorkId
from research_harness.retrieval.planner import Intent, RetrievalHit
from research_harness.retrieval.rerank import (
    AUTHORITY_SCORES,
    RERANK_WEIGHTS,
    authority_score,
    independence_scores,
    rerank,
    structure_score,
)
from research_harness.retrieval.structured import Authority, Location

RESULTS = ("4 Results",)
ABSTRACT = ("Abstract",)
LIMITATIONS = ("5 Limitations",)


def hit(
    ref: str,
    *,
    kind: str,
    authority: Authority,
    section: tuple[str, ...] = (),
    work: str = "W0001",
    lexical: float = 0.0,
    semantic: float = 0.0,
    stale: bool = False,
    page: int = 1,
) -> RetrievalHit:
    components: dict[str, float] = {}
    if lexical:
        components["lexical"] = lexical
    if semantic:
        components["semantic"] = semantic
    return RetrievalHit(
        ref=ref,
        kind=kind,
        work=WorkId(work),
        location=Location(page=page, section_path=section, block=BlockId("B0001")),
        authority=authority,
        components=components,
        snippet=ref,
        provenance="test",
        stale=stale,
    )


def order(hits: list[RetrievalHit], *, intent: Intent) -> list[str]:
    return [item.ref for item in rerank(hits, intent=intent)]


# --- the two acceptance requirements ----------------------------------------


def test_a_results_table_outranks_an_abstract_claim_when_auditing_a_number() -> None:
    """The number was measured in the table; the abstract only summarises it."""
    table = hit(
        "E0482",
        kind="table",
        authority=Authority.ACCEPTED_EVIDENCE,
        section=RESULTS,
        lexical=0.5,
        page=4,
    )
    abstract = hit(
        "C0041",
        kind="claim",
        authority=Authority.ACCEPTED_CLAIM,
        section=ABSTRACT,
        lexical=0.9,
    )

    assert order([abstract, table], intent=Intent.AUDIT_EMPIRICAL_RESULT) == ["E0482", "C0041"]


def test_accepted_evidence_outranks_semantically_similar_raw_prose_for_support() -> None:
    """A perfect vector match on unreviewed prose must not displace accepted Evidence."""
    accepted = hit("E0482", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, lexical=0.3)
    prose = hit(
        "B0081@A0001-1",
        kind="paragraph",
        authority=Authority.PARSED_CORPUS,
        semantic=1.0,
        work="W0002",
    )

    assert order([prose, accepted], intent=Intent.FIND_SUPPORT) == ["E0482", "B0081@A0001-1"]


def test_every_hit_exposes_the_components_it_was_ranked_by() -> None:
    ranked = rerank(
        [
            hit("E0482", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, lexical=0.4),
            hit("B0081@A0001-1", kind="paragraph", authority=Authority.PARSED_CORPUS, semantic=0.7),
        ],
        intent=Intent.EXPLORE,
    )

    for item in ranked:
        assert {"authority", "structure", "staleness", "independence"} <= set(item.components)
        assert 0.0 <= item.score <= 1.0
    assert ranked[0].components["lexical"] == pytest.approx(0.4)
    assert ranked[1].components["semantic"] == pytest.approx(0.7)


# --- components -------------------------------------------------------------


def test_authority_is_ordered_the_way_the_ladder_is() -> None:
    scores = [AUTHORITY_SCORES[authority] for authority in Authority]

    assert scores == sorted(scores, reverse=True)
    assert authority_score(Authority.ACCEPTED_EVIDENCE) > authority_score(Authority.PARSED_CORPUS)


def test_an_audit_caps_whatever_it_finds_in_the_abstract() -> None:
    assert structure_score("table", ABSTRACT, Intent.AUDIT_EMPIRICAL_RESULT) <= 0.2
    assert structure_score("table", RESULTS, Intent.AUDIT_EMPIRICAL_RESULT) == pytest.approx(1.0)


def test_counter_evidence_search_trusts_the_sections_where_papers_hedge() -> None:
    limitations = structure_score("paragraph", LIMITATIONS, Intent.FIND_COUNTER_EVIDENCE)
    results = structure_score("paragraph", RESULTS, Intent.FIND_COUNTER_EVIDENCE)

    assert limitations > results


def test_numbered_headings_are_recognised_by_name() -> None:
    assert structure_score("paragraph", ("4 Results",), Intent.AUDIT_EMPIRICAL_RESULT) == (
        structure_score("paragraph", ("Results",), Intent.AUDIT_EMPIRICAL_RESULT)
    )


def test_a_stale_hit_stops_outranking_a_fresh_one() -> None:
    fresh = hit("E0001", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE)
    stale = hit("E0002", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, stale=True)

    ranked = rerank([stale, fresh], intent=Intent.FIND_SUPPORT)

    assert [item.ref for item in ranked] == ["E0001", "E0002"]
    assert ranked[1].components["staleness"] == pytest.approx(1.0)


def test_the_first_hit_from_each_work_gets_the_independence_bonus() -> None:
    hits = [
        hit("E0001", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, work="W0001"),
        hit("E0002", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, work="W0001"),
        hit("E0003", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, work="W0002"),
    ]

    assert independence_scores(hits) == [1.0, 0.5, 1.0]
    ranked = {
        item.ref: item.components["independence"] for item in rerank(hits, intent=Intent.EXPLORE)
    }
    assert ranked["E0002"] < ranked["E0001"]


def test_a_hit_with_no_work_is_neither_rewarded_nor_punished() -> None:
    orphan = RetrievalHit(
        ref="C0041", kind="claim", authority=Authority.ACCEPTED_CLAIM, provenance="t"
    )

    assert independence_scores([orphan]) == [0.5]


# --- weights ----------------------------------------------------------------


@pytest.mark.parametrize("intent", list(Intent))
def test_every_intent_has_weights_and_authority_is_never_the_smallest(intent: Intent) -> None:
    weights = RERANK_WEIGHTS[intent]

    assert weights.authority >= max(weights.lexical, weights.semantic)
    assert set(weights.as_dict()) == {
        "authority",
        "structure",
        "lexical",
        "semantic",
        "staleness",
        "independence",
    }
    assert weights.as_dict()["staleness"] < 0


@pytest.mark.parametrize("intent", list(Intent))
def test_no_single_index_can_promote_raw_prose_over_accepted_state(intent: Intent) -> None:
    """ADR-006: the ladder, not the index, decides what a project treats as known."""
    weights = RERANK_WEIGHTS[intent]
    gap = AUTHORITY_SCORES[Authority.ACCEPTED_EVIDENCE] - AUTHORITY_SCORES[Authority.PARSED_CORPUS]

    assert weights.authority * gap > max(weights.lexical, weights.semantic)


def test_ranking_is_deterministic_when_scores_tie() -> None:
    first = hit("E0002", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, work="W0009")
    second = hit("E0001", kind="evidence", authority=Authority.ACCEPTED_EVIDENCE, work="W0009")

    assert order([first, second], intent=Intent.EXPLORE) == order(
        [second, first], intent=Intent.EXPLORE
    )


def test_reranking_nothing_is_not_an_error() -> None:
    assert rerank([], intent=Intent.EXPLORE) == []
