"""Pure context-assembly rules: token estimate, context class, ranking, and the fragment.

The walk itself needs a database and is tested in `tests/integration/graph`; what is
testable without one is the arithmetic and the classification, and those are exactly the
parts a receipt is built out of.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.domain.conversation import ContextClass
from research_harness.domain.graph import (
    ContextFragment,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.graph.context import (
    ACCEPTED_STATE,
    ATTACHMENTS,
    CORPUS_BLOCKS,
    CURRENT_SESSION,
    DISCOVERY,
    PRIOR_SESSIONS,
    ContextAssembly,
    OmittedFragment,
    assemble,
    context_class_for,
    estimate_tokens,
)
from research_harness.graph.queries import NodeRecord

SESSION = "CS0001"


def record(
    identity: str,
    kind: NodeKind,
    *,
    authority: GraphAuthority = GraphAuthority.ACCEPTED,
    visibility: GraphVisibility = GraphVisibility.PROJECT,
    session: str | None = None,
) -> NodeRecord:
    """One projected node row, with only the fields the classifier reads."""
    return NodeRecord(
        identity=identity,
        kind=kind,
        authority=authority,
        visibility=visibility,
        label=identity,
        text=identity,
        source=f"{identity}.yaml",
        fingerprint=None,
        metadata={} if session is None else {"session": session},
    )


# --- tokens -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "tokens"), [("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("x" * 400, 100)]
)
def test_the_token_estimate_is_characters_over_four_rounded_up(text: str, tokens: int) -> None:
    """Deterministic by construction: no tokenizer, no provider, no surprises in a budget."""
    assert estimate_tokens(text) == tokens


# --- the vocabulary the assembler names -------------------------------------


def test_every_context_class_the_graph_names_is_one_the_conversation_layer_knows() -> None:
    """`graph/` must not import `domain/conversation`, so the strings are pinned here.

    `ContextFragment.context_class` is a plain `str` on purpose (the two domain modules
    are independent), which means nothing but this test stops the two vocabularies from
    drifting apart and a receipt from carrying a class C1 cannot file.
    """
    named = {ACCEPTED_STATE, CURRENT_SESSION, PRIOR_SESSIONS, ATTACHMENTS, CORPUS_BLOCKS, DISCOVERY}

    assert named <= {member.value for member in ContextClass}


# --- context classes --------------------------------------------------------


def test_a_session_member_is_current_context_only_for_the_session_that_was_asked_about() -> None:
    mine = record("M0001", NodeKind.MESSAGE, authority=GraphAuthority.PRIVATE, session=SESSION)
    theirs = record("M0099", NodeKind.MESSAGE, authority=GraphAuthority.PRIVATE, session="CS0009")

    assert context_class_for(mine, session=SESSION) == CURRENT_SESSION
    assert context_class_for(theirs, session=SESSION) == PRIOR_SESSIONS
    assert context_class_for(mine, session=None) == PRIOR_SESSIONS


def test_the_session_node_itself_is_current_context() -> None:
    node = record(SESSION, NodeKind.SESSION, authority=GraphAuthority.PRIVATE)

    assert context_class_for(node, session=SESSION) == CURRENT_SESSION


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (NodeKind.EVIDENCE, ACCEPTED_STATE),
        (NodeKind.CLAIM, ACCEPTED_STATE),
        (NodeKind.DECISION, ACCEPTED_STATE),
        (NodeKind.PARAGRAPH, CORPUS_BLOCKS),
        (NodeKind.ARTIFACT, CORPUS_BLOCKS),
        (NodeKind.MANUSCRIPT_ANCHOR, CORPUS_BLOCKS),
        (NodeKind.ATTACHMENT, ATTACHMENTS),
    ],
)
def test_each_kind_lands_in_the_context_class_a_receipt_expects(
    kind: NodeKind, expected: str
) -> None:
    assert context_class_for(record("X0001", kind), session=SESSION) == expected


@pytest.mark.parametrize("authority", [GraphAuthority.CANDIDATE, GraphAuthority.STALE])
def test_candidate_and_stale_material_is_discovery_whatever_its_kind(
    authority: GraphAuthority,
) -> None:
    """Authority decides before kind, so no receipt files a proposal under accepted state."""
    node = record("E0482", NodeKind.EVIDENCE, authority=authority)

    assert context_class_for(node, session=SESSION) == DISCOVERY


# --- the fragment itself ----------------------------------------------------


def test_a_relation_path_must_end_at_the_fragment_it_describes() -> None:
    """The invariant that makes a path checkable: the last id is the fragment's own."""
    with pytest.raises(ValidationError, match="relation_path must end"):
        ContextFragment(
            id="E0482",
            kind=NodeKind.EVIDENCE,
            authority=GraphAuthority.ACCEPTED,
            visibility=GraphVisibility.PROJECT,
            source_pointer="corpus/works/W0017/evidence.jsonl",
            relation_path=("C0041", "E0483"),
            context_class=ACCEPTED_STATE,
        )


def test_a_fragment_with_no_path_is_allowed_because_a_seed_was_not_walked_to() -> None:
    fragment = ContextFragment(
        id="E0482",
        kind=NodeKind.EVIDENCE,
        authority=GraphAuthority.ACCEPTED,
        visibility=GraphVisibility.PROJECT,
        source_pointer="corpus/works/W0017/evidence.jsonl",
        context_class=ACCEPTED_STATE,
    )

    assert fragment.relation_path == ()


# --- degradation ------------------------------------------------------------


def test_assembling_without_a_graph_returns_nothing_rather_than_raising() -> None:
    """`.research/` is disposable: a missing index degrades context, never a workspace."""
    assert assemble(None, session=SESSION, query="anything") == ContextAssembly()


def test_a_non_positive_limit_assembles_nothing() -> None:
    assert assemble(None, limit=0).fragments == ()


def test_an_assembly_reports_the_tokens_it_would_cost() -> None:
    fragments = tuple(
        ContextFragment(
            id=identity,
            kind=NodeKind.EVIDENCE,
            authority=GraphAuthority.ACCEPTED,
            visibility=GraphVisibility.PROJECT,
            source_pointer=f"{identity}.yaml",
            text="x" * 40,
            tokens=estimate_tokens("x" * 40),
            context_class=ACCEPTED_STATE,
        )
        for identity in ("E0001", "E0002")
    )

    assert ContextAssembly(fragments=fragments).total_tokens() == 20


def test_an_omission_names_what_was_left_out_and_why() -> None:
    omitted = OmittedFragment(id="CS0002", reason="privacy_policy", detail="private session")

    assert (omitted.id, omitted.reason) == ("CS0002", "privacy_policy")
