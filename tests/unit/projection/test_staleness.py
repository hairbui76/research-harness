"""Dependency propagation: the PRODUCT 37 chain, termination, and order independence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from research_harness.domain import (
    ClaimId,
    Decision,
    DecisionId,
    DecisionStatus,
    DecisionType,
    EvidenceId,
    ManuscriptAnchor,
    MatrixCell,
    QuestionId,
    StaleState,
    SynthesisId,
    SynthesisMatrix,
    Taxonomy,
    TaxonomyTerm,
    WorkId,
)
from research_harness.projection import (
    DependencyGraph,
    DependencyKind,
    StalePriority,
    StaleSet,
    affected_by,
    create_all,
    create_engine_for,
    load_stale_marks,
    manuscript_anchor_key,
    mark_changed,
    mark_changed_many,
    matrix_cell_node_id,
    persist_stale_marks,
    priority_for,
)
from tests.unit.domain import strategies as sty

TAXONOMY_DECISION = DecisionId("D0012")
MATRIX = SynthesisId("S0007")
SYNTHESIS_CLAIM = ClaimId("C0021")
ANCHOR_FILE = "manuscript/main.tex"


def _taxonomy_chain() -> tuple[DependencyGraph, dict[str, object]]:
    """PRODUCT 37: taxonomy decision -> classifications -> matrix -> claim -> manuscript."""
    decision = Decision(
        id=TAXONOMY_DECISION,
        type=DecisionType.TAXONOMY_REVISION,
        status=DecisionStatus.ACCEPTED,
        rationale="Split byte-level from field-level tokenization.",
        taxonomy_terms=("byte_level",),
        provenance=sty.HUMAN,
    )
    taxonomy = Taxonomy(
        name="representation",
        terms=(TaxonomyTerm(term="byte_level", decision=TAXONOMY_DECISION),),
        provenance=sty.HUMAN,
    )
    matrix = SynthesisMatrix(
        id=MATRIX,
        name="representation matrix",
        taxonomy="representation",
        works=(WorkId("W0017"),),
        fields=("tokenization",),
        cells=(
            MatrixCell(
                work=WorkId("W0017"),
                field="tokenization",
                labels=("byte_level",),
                evidence=(EvidenceId("E0482"),),
            ),
        ),
        provenance=sty.HUMAN,
    )
    claim = sty.make_claim(id=SYNTHESIS_CLAIM, relations=(), decisions=(), derived_from=(MATRIX,))
    anchor = ManuscriptAnchor(
        file=ANCHOR_FILE,
        line_start=41,
        line_end=41,
        sentence="Representations differ in tokenization granularity.",
        sentence_fingerprint=sty.HASH_C,
        claim=SYNTHESIS_CLAIM,
        provenance=sty.HUMAN,
    )
    # Every link in the chain, matrix -> claim included, comes from a canonical field.
    graph = DependencyGraph.from_objects([decision, taxonomy, matrix, claim, anchor])
    objects = {"matrix": matrix, "claim": claim, "anchor": anchor}
    return graph, objects


# --- the ROADMAP 3.4 / PRODUCT 42.I scenario --------------------------------


def test_taxonomy_decision_marks_classification_matrix_claim_and_anchor_stale() -> None:
    graph, _ = _taxonomy_chain()

    stale = mark_changed(graph, str(TAXONOMY_DECISION))

    cell = matrix_cell_node_id(str(MATRIX), "W0017", "tokenization")
    anchor_id = manuscript_anchor_key(ANCHOR_FILE, sty.HASH_C)
    assert set(stale.object_ids()) == {
        "TX:representation",
        cell,
        str(MATRIX),
        str(SYNTHESIS_CLAIM),
        anchor_id,
    }


def test_stale_priority_orders_the_chain_by_scientific_impact() -> None:
    graph, _ = _taxonomy_chain()

    stale = mark_changed(graph, str(TAXONOMY_DECISION))

    by_priority = stale.by_priority()
    assert list(by_priority) == [
        StalePriority.MANUSCRIPT_ANCHOR,
        StalePriority.CLAIM,
        StalePriority.SYNTHESIS,
        StalePriority.CLASSIFICATION,
    ]
    assert stale.object_ids()[0] == manuscript_anchor_key(ANCHOR_FILE, sty.HASH_C)
    assert stale.object_ids()[1] == str(SYNTHESIS_CLAIM)
    assert stale.object_ids()[2] == str(MATRIX)


def test_propagation_never_rewrites_the_derived_objects() -> None:
    graph, objects = _taxonomy_chain()

    mark_changed(graph, str(TAXONOMY_DECISION))

    for obj in objects.values():
        assert obj.stale is StaleState.FRESH  # type: ignore[attr-defined]


def test_every_mark_records_the_change_that_caused_it() -> None:
    graph, _ = _taxonomy_chain()

    stale = mark_changed(graph, str(TAXONOMY_DECISION), reason="taxonomy revised")

    assert {mark.source_change for mark in stale} == {str(TAXONOMY_DECISION)}
    assert {mark.reason for mark in stale} == {"taxonomy revised"}


def test_derived_edges_come_only_from_canonical_fields() -> None:
    graph, _ = _taxonomy_chain()

    kinds = {(edge.upstream_id, edge.downstream_id): edge.kind for edge in graph.edges()}
    cell = matrix_cell_node_id(str(MATRIX), "W0017", "tokenization")
    assert kinds[(str(TAXONOMY_DECISION), "TX:representation")] is DependencyKind.CLASSIFIES
    assert kinds[("TX:representation", str(MATRIX))] is DependencyKind.CLASSIFIES
    assert kinds[(cell, str(MATRIX))] is DependencyKind.CLASSIFIES
    assert kinds[("E0482", cell)] is DependencyKind.CITES_EVIDENCE
    assert kinds[(str(MATRIX), str(SYNTHESIS_CLAIM))] is DependencyKind.DERIVES_CLAIM
    assert (
        kinds[(str(SYNTHESIS_CLAIM), manuscript_anchor_key(ANCHOR_FILE, sty.HASH_C))]
        is DependencyKind.ATTACHES_CLAIM
    )


def test_a_synthesis_claim_names_the_matrix_it_was_derived_from() -> None:
    """PRODUCT 37: the matrix -> claim edge is canonical state, not an out-of-band hint."""
    claim = sty.make_claim(id=SYNTHESIS_CLAIM, relations=(), decisions=(), derived_from=(MATRIX,))

    graph = DependencyGraph.from_objects([claim])

    assert graph.upstream(str(SYNTHESIS_CLAIM)) == {str(MATRIX)}
    assert affected_by(graph, str(MATRIX)) == {str(SYNTHESIS_CLAIM)}


def test_add_edge_still_registers_a_dependency_no_canonical_field_records() -> None:
    """A link the schema does not express is registered explicitly and propagates alike."""
    graph, _ = _taxonomy_chain()

    graph.add_edge("S9999", str(SYNTHESIS_CLAIM), DependencyKind.DERIVES_CLAIM)

    assert str(SYNTHESIS_CLAIM) in graph.downstream("S9999")
    assert affected_by(graph, "S9999") == {
        str(SYNTHESIS_CLAIM),
        manuscript_anchor_key(ANCHOR_FILE, sty.HASH_C),
    }


def test_evidence_and_question_edges_are_derived_from_their_own_fields() -> None:
    evidence = sty.make_evidence()
    question = sty.make_question(claims=("C0041",))

    graph = DependencyGraph.from_objects([evidence, question, sty.make_claim()])

    assert "E0482" in graph.downstream("A0017-3")
    assert "RQ0003" in graph.downstream("C0041")
    assert graph.upstream("C0041") >= {"E0132", "E0180"}
    assert affected_by(graph, "A0017-3") == {"E0482"}


# --- priority mapping -------------------------------------------------------


def test_priority_for_dispatches_on_node_id_shape() -> None:
    assert priority_for(manuscript_anchor_key("m.tex", sty.HASH_A)) is (
        StalePriority.MANUSCRIPT_ANCHOR
    )
    assert priority_for(str(ClaimId("C0041"))) is StalePriority.CLAIM
    assert priority_for(str(QuestionId("RQ0003"))) is StalePriority.CLAIM
    assert priority_for(str(MATRIX)) is StalePriority.SYNTHESIS
    assert priority_for("I0009") is StalePriority.SYNTHESIS
    assert priority_for(matrix_cell_node_id("S0007", "W0017", "f")) is (
        StalePriority.CLASSIFICATION
    )
    assert priority_for("TX:representation") is StalePriority.CLASSIFICATION
    assert priority_for("E0482") is StalePriority.CLASSIFICATION
    assert priority_for("W0017") is StalePriority.INDEX
    assert priority_for("not-an-id") is StalePriority.INDEX


# --- property-based invariants ----------------------------------------------

NODES = (
    "W0001",
    "A0001-1",
    "B0001",
    "D0001",
    "SR0001",
    "E0001",
    "E0002",
    "TX:representation",
    "S0001#W0001#tokenization",
    "I0001",
    "S0001",
    "C0001",
    "C0002",
    "RQ0001",
    "MA:main.tex#" + sty.HASH_A,
)

_INDEX_PAIRS = st.lists(
    st.tuples(st.integers(0, len(NODES) - 1), st.integers(0, len(NODES) - 1)), max_size=24
)


def _graph(pairs: list[tuple[int, int]], *, acyclic: bool) -> DependencyGraph:
    graph = DependencyGraph()
    for left, right in pairs:
        if acyclic:
            if left == right:
                continue
            low, high = (left, right) if left < right else (right, left)
        else:
            low, high = left, right
        graph.add_edge(NODES[low], NODES[high], DependencyKind.CLASSIFIES)
    return graph


@given(_INDEX_PAIRS, st.integers(0, len(NODES) - 1))
def test_propagation_terminates_on_a_dag(pairs: list[tuple[int, int]], start: int) -> None:
    graph = _graph(pairs, acyclic=True)

    stale = mark_changed(graph, NODES[start])

    assert stale.object_ids() == tuple(dict.fromkeys(stale.object_ids()))
    assert set(stale.object_ids()) <= set(NODES) - {NODES[start]}


@given(_INDEX_PAIRS, st.integers(0, len(NODES) - 1))
def test_propagation_terminates_on_a_cyclic_graph(pairs: list[tuple[int, int]], start: int) -> None:
    graph = _graph(pairs, acyclic=False)

    stale = mark_changed(graph, NODES[start])

    assert len(stale) < len(NODES)
    assert NODES[start] not in stale.object_ids()


@given(_INDEX_PAIRS, st.lists(st.integers(0, len(NODES) - 1), max_size=5))
def test_mark_changed_many_is_the_union_of_the_individual_calls(
    pairs: list[tuple[int, int]], starts: list[int]
) -> None:
    graph = _graph(pairs, acyclic=False)
    ids = [NODES[index] for index in starts]

    union: StaleSet = StaleSet()
    for object_id in ids:
        union |= mark_changed(graph, object_id)

    assert mark_changed_many(graph, ids) == union


@given(_INDEX_PAIRS, st.lists(st.integers(0, len(NODES) - 1), max_size=5), st.randoms())
def test_mark_changed_many_is_order_independent(
    pairs: list[tuple[int, int]], starts: list[int], random: object
) -> None:
    graph = _graph(pairs, acyclic=False)
    ids = [NODES[index] for index in starts]
    shuffled = list(ids)
    random.shuffle(shuffled)  # type: ignore[attr-defined]

    assert mark_changed_many(graph, ids) == mark_changed_many(graph, shuffled)


@given(_INDEX_PAIRS)
def test_marking_a_leaf_yields_an_empty_stale_set(pairs: list[tuple[int, int]]) -> None:
    graph = _graph(pairs, acyclic=True)
    leaf = NODES[-1]

    assert not graph.downstream(leaf)
    assert mark_changed(graph, leaf) == StaleSet()
    assert affected_by(graph, leaf) == frozenset()


def test_marking_an_unknown_object_yields_an_empty_stale_set() -> None:
    assert mark_changed(DependencyGraph(), "C9999") == StaleSet()


# --- persistence ------------------------------------------------------------


def test_stale_marks_round_trip_through_the_projection_table(tmp_path: Path) -> None:
    graph, _ = _taxonomy_chain()
    stale = mark_changed(graph, str(TAXONOMY_DECISION))
    engine = create_engine_for(tmp_path / ".research" / "research.db")
    create_all(engine)

    with engine.begin() as connection:
        persist_stale_marks(connection, stale, datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
        persist_stale_marks(connection, stale, datetime(2026, 9, 3, 12, 5, tzinfo=UTC))
        loaded = load_stale_marks(connection)

    assert loaded == stale
    assert list(loaded) == list(stale)
    engine.dispose()
