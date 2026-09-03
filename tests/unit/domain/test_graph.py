"""Graph vocabularies, the reference grammar, deep links, and the candidate/accepted rule."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_harness.domain.conversation import AuthorityLabel, Visibility
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.graph import (
    DETERMINISTIC_EDGE_KINDS,
    SCIENTIFIC_EDGE_KINDS,
    DeepLink,
    DeepLinkKind,
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphEdge,
    GraphNode,
    GraphVisibility,
    NodeKind,
    StableReference,
    known_reference_prefixes,
)

# --- vocabularies -----------------------------------------------------------


def test_graph_authority_mirrors_the_conversation_authority_label() -> None:
    """The two enums are declared separately so the modules stay independent (plan 0.3)."""
    assert [member.value for member in GraphAuthority] == [
        member.value for member in AuthorityLabel
    ]


def test_graph_visibility_mirrors_the_conversation_visibility() -> None:
    assert [member.value for member in GraphVisibility] == [member.value for member in Visibility]


def test_every_edge_kind_is_either_deterministic_or_scientific() -> None:
    assert set(EdgeKind) == DETERMINISTIC_EDGE_KINDS | SCIENTIFIC_EDGE_KINDS
    assert not DETERMINISTIC_EDGE_KINDS & SCIENTIFIC_EDGE_KINDS


def test_node_kinds_cover_every_namespace_the_plan_locked() -> None:
    assert {member.value for member in NodeKind} == {
        "project",
        "session",
        "message",
        "attachment",
        "work",
        "version",
        "artifact",
        "section",
        "paragraph",
        "table",
        "figure",
        "equation",
        "reference",
        "evidence",
        "claim",
        "question",
        "decision",
        "synthesis",
        "manuscript_file",
        "manuscript_anchor",
        "citation",
    }


# --- the reference grammar --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "prefix", "identifier"),
    [
        ("@W0017", "W", "W0017"),
        ("W0017", "W", "W0017"),
        ("@E0482", "E", "E0482"),
        ("@C0041", "C", "C0041"),
        ("@RQ0002", "RQ", "RQ0002"),
        ("@D0001", "D", "D0001"),
        ("@V0017-2", "V", "V0017-2"),
        ("@A0017-3", "A", "A0017-3"),
        ("@CS0001", "CS", "CS0001"),
        ("@M0042", "M", "M0042"),
        ("@SA0003", "SA", "SA0003"),
        ("@CP0007", "CP", "CP0007"),
        ("  @S0007  ", "S", "S0007"),
    ],
)
def test_stable_reference_parses_every_known_prefix(
    text: str, prefix: str, identifier: str
) -> None:
    reference = StableReference.parse(text)

    assert (reference.prefix, reference.identifier) == (prefix, identifier)
    assert reference.format() == f"@{identifier}"


def test_the_prefix_is_the_whole_run_of_capitals_so_cs_is_never_a_claim() -> None:
    """`CS0001` is a session, not claim `S0001`; the grammar leaves no ambiguity to resolve."""
    assert StableReference.parse("@CS0001").prefix == "CS"
    assert StableReference.parse("@C0041").prefix == "C"
    assert StableReference.parse("@SA0003").prefix == "SA"
    assert StableReference.parse("@S0007").prefix == "S"


@pytest.mark.parametrize(
    "text", ["@ZZ0001", "@W17", "W0017x", "@", "", "@0017", "@w0017", "@W0017-", "@W 0017"]
)
def test_stable_reference_refuses_anything_that_is_not_a_known_id(text: str) -> None:
    assert StableReference.try_parse(text) is None
    with pytest.raises(DomainValidationError):
        StableReference.parse(text)


def test_a_typed_prefix_returns_its_research_id() -> None:
    assert StableReference.parse("@W0017").as_research_id() == "W0017"
    assert StableReference.parse("@W0017").is_typed


def test_the_conversation_prefixes_are_accepted_whether_or_not_they_have_a_type_yet() -> None:
    """`CS`/`M`/`SA`/`CP` parse as references even before their id classes land."""
    assert {"CS", "M", "SA", "CP"} <= known_reference_prefixes()
    assert StableReference.parse("@M0042").identifier == "M0042"


@given(
    prefix=st.sampled_from(sorted(known_reference_prefixes())),
    number=st.integers(min_value=0, max_value=999_999),
    suffix=st.none() | st.integers(min_value=0, max_value=99),
)
def test_stable_reference_round_trips(prefix: str, number: int, suffix: int | None) -> None:
    text = f"@{prefix}{number:04d}" + ("" if suffix is None else f"-{suffix}")

    reference = StableReference.parse(text)

    assert StableReference.parse(reference.format()) == reference
    assert reference.format() == text


# --- deep links -------------------------------------------------------------


def test_deep_link_parses_the_documented_example() -> None:
    link = DeepLink.parse("rh://artifact/A0017-3?page=6&block=B0081")

    assert link.kind is DeepLinkKind.ARTIFACT
    assert (link.target, link.page, link.block) == ("A0017-3", 6, "B0081")
    assert link.format() == "rh://artifact/A0017-3?page=6&block=B0081"


@pytest.mark.parametrize(
    "text",
    [
        "rh://evidence/E0482",
        "rh://claim/C0041",
        "rh://work/W0017",
        "rh://version/V0017-2",
        "rh://question/RQ0002",
        "rh://decision/D0001",
        "rh://session/CS0001?message=M0042",
        "rh://attachment/SA0003",
        "rh://manuscript/main.tex?line=120",
        "rh://manuscript/sections/intro.tex?line=1",
    ],
)
def test_deep_link_round_trips_every_kind(text: str) -> None:
    assert DeepLink.parse(text).format() == text


def test_a_deep_link_query_order_is_normalized_but_the_meaning_survives() -> None:
    link = DeepLink.parse("rh://artifact/A0017-3?block=B0081&page=6")

    assert link.format() == "rh://artifact/A0017-3?page=6&block=B0081"
    assert DeepLink.parse(link.format()) == link


@pytest.mark.parametrize(
    "text",
    [
        "https://example.org/A0017-3",
        "rh://symbol/A0017-3",
        "rh://artifact/",
        "rh://artifact/A0017-3?colour=red",
        "rh://artifact/A0017-3?page=six",
        "rh://artifact/A0017-3?page=0",
    ],
)
def test_deep_link_refuses_a_link_it_cannot_mean(text: str) -> None:
    assert DeepLink.try_parse(text) is None
    with pytest.raises(DomainValidationError):
        DeepLink.parse(text)


def test_a_deep_link_exposes_the_reference_it_addresses() -> None:
    assert DeepLink.parse("rh://evidence/E0482").reference == StableReference.parse("@E0482")
    assert DeepLink.parse("rh://manuscript/main.tex").reference is None


@given(
    kind=st.sampled_from(list(DeepLinkKind)),
    target=st.sampled_from(["A0017-3", "E0482", "main.tex", "sections/intro.tex", "a b"]),
    page=st.none() | st.integers(min_value=1, max_value=2000),
    block=st.none() | st.sampled_from(["B0081", "B0002"]),
    line=st.none() | st.integers(min_value=1, max_value=5000),
    message=st.none() | st.sampled_from(["M0042"]),
)
def test_deep_link_round_trips(
    kind: DeepLinkKind,
    target: str,
    page: int | None,
    block: str | None,
    line: int | None,
    message: str | None,
) -> None:
    link = DeepLink(kind=kind, target=target, page=page, block=block, line=line, message=message)

    assert DeepLink.parse(link.format()) == link


# --- the invariant ----------------------------------------------------------


def test_a_model_proposed_edge_cannot_be_accepted() -> None:
    with pytest.raises(ValueError, match="model-proposed edge cannot be accepted"):
        GraphEdge(
            from_id="E0482",
            to_id="C0041",
            kind=EdgeKind.SUPPORTS,
            origin=EdgeOrigin.MODEL_PROPOSED,
            authority=GraphAuthority.ACCEPTED,
        )


def test_an_accepted_relation_is_not_a_candidate() -> None:
    with pytest.raises(ValueError, match="not a candidate"):
        GraphEdge(
            from_id="E0482",
            to_id="C0041",
            kind=EdgeKind.SUPPORTS,
            origin=EdgeOrigin.ACCEPTED,
            authority=GraphAuthority.CANDIDATE,
        )


@given(
    origin=st.sampled_from(list(EdgeOrigin)),
    authority=st.sampled_from(list(GraphAuthority)),
)
def test_no_edge_is_ever_both_model_proposed_and_accepted(
    origin: EdgeOrigin, authority: GraphAuthority
) -> None:
    try:
        edge = GraphEdge(
            from_id="E0482",
            to_id="C0041",
            kind=EdgeKind.SUPPORTS,
            origin=origin,
            authority=authority,
        )
    except ValueError:
        return
    assert not (
        edge.origin is EdgeOrigin.MODEL_PROPOSED and edge.authority is GraphAuthority.ACCEPTED
    )


def test_a_candidate_edge_is_buildable_and_says_so() -> None:
    edge = GraphEdge(
        from_id="E0482",
        to_id="C0041",
        kind=EdgeKind.SUPPORTS,
        origin=EdgeOrigin.MODEL_PROPOSED,
        authority=GraphAuthority.CANDIDATE,
    )

    assert edge.is_scientific
    assert edge.key == ("E0482", "C0041", "supports", "model_proposed")


@pytest.mark.parametrize("identity", ["with\nnewline", "with\ttab"])
def test_an_identity_stays_one_line_so_a_dump_stays_comparable(identity: str) -> None:
    with pytest.raises(ValueError, match="newline or tab"):
        GraphNode(identity=identity, kind=NodeKind.WORK)


def test_a_node_defaults_to_accepted_project_visible() -> None:
    node = GraphNode(identity="W0017", kind=NodeKind.WORK, label="A paper")

    assert node.authority is GraphAuthority.ACCEPTED
    assert node.visibility is GraphVisibility.PROJECT
    assert node.metadata == {}
