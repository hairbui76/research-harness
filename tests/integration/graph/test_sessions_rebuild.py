"""Sessions project, resolve, and survive a rebuild — graph spec §11.1, extended to §11.6.

The workspace here is `conftest.populated_workspace` plus a conversation history: one
`project`-visible session that references accepted state and carries an attachment, and one
`private` session that references the same Evidence. That pairing is what the privacy and
context tests need, so the builders live here and the other two modules import them.

What this module asserts is the projection itself: identities are the plain ids, one
durable file is one unit, an append re-projects one transcript, and deleting `.research/`
and rebuilding resolves every reference to the same object.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    AttachmentBlock,
    AttachmentState,
    ConversationSession,
    Message,
    MessageRole,
    ReferenceBlock,
    SessionAttachment,
    TextBlock,
    Visibility,
)
from research_harness.domain.graph import (
    EdgeKind,
    GraphAuthority,
    GraphVisibility,
    NodeKind,
)
from research_harness.domain.ids import (
    ClaimId,
    ConversationSessionId,
    EvidenceId,
    MessageId,
    SessionAttachmentId,
)
from research_harness.graph.queries import Direction, GraphFilter
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.conversations import ConversationStore
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.graph.conftest import CLAIM, SUPPORTING

HUMAN = Provenance.human("human:alice")

SHARED = ConversationSessionId("CS0001")
PRIVATE = ConversationSessionId("CS0002")

SHARED_QUESTION = MessageId("M0001")
SHARED_ANSWER = MessageId("M0002")
PRIVATE_NOTE = MessageId("M0003")

SHARED_ATTACHMENT = SessionAttachmentId("SA0001")

PRIVATE_TEXT = "Unpublished hunch: the CICIDS2017 split leaks flows across the boundary."
SHARED_TEXT = "What does the accepted evidence say about the CICIDS2017 evaluation?"
ATTACHMENT_BYTES = b"%PDF-1.7\n% a session attachment\n"


def add_sessions(repo: WorkspaceRepository) -> ConversationStore:
    """Two sessions over the canonical fixture: one project-visible, one private.

    Both reference accepted state, so every privacy assertion downstream is about the
    *session* node rather than about which objects happen to be reachable.
    """
    store = ConversationStore.for_repository(repo)
    shared = store.create_session(
        title="Shared plan for the traffic evaluation",
        provenance=HUMAN,
        visibility=Visibility.PROJECT,
    )
    store.append_message(shared.id, _question)
    store.append_message(shared.id, _answer)
    store.add_attachment(shared.id, _attachment, data=ATTACHMENT_BYTES)
    private = store.create_session(
        title="Private hunches about CICIDS2017",
        provenance=HUMAN,
        visibility=Visibility.PRIVATE,
    )
    store.append_message(private.id, _private_note)
    return store


def _question(new_id: MessageId) -> Message:
    return Message(
        id=new_id,
        session=SHARED,
        role=MessageRole.USER,
        visibility=Visibility.PROJECT,
        blocks=(
            TextBlock(text=SHARED_TEXT),
            ReferenceBlock(target=ClaimId(str(CLAIM)), label="the tokenization claim"),
        ),
        provenance=HUMAN,
    )


def _answer(new_id: MessageId) -> Message:
    return Message(
        id=new_id,
        session=SHARED,
        role=MessageRole.ASSISTANT,
        visibility=Visibility.PROJECT,
        blocks=(
            TextBlock(text="Two accepted records bear on it; one contradicts the reported F1."),
            AttachmentBlock(attachment=SHARED_ATTACHMENT, caption="the table"),
        ),
        attachments=(SHARED_ATTACHMENT,),
        provenance=HUMAN,
    )


def _private_note(new_id: MessageId) -> Message:
    return Message(
        id=new_id,
        session=PRIVATE,
        role=MessageRole.USER,
        visibility=Visibility.PRIVATE,
        blocks=(
            TextBlock(text=PRIVATE_TEXT),
            ReferenceBlock(target=EvidenceId(str(SUPPORTING))),
        ),
        provenance=HUMAN,
    )


def _attachment(new_id: SessionAttachmentId) -> SessionAttachment:
    return SessionAttachment(
        id=new_id,
        session=SHARED,
        state=AttachmentState.READY,
        filename="table-1.pdf",
        media_type="application/pdf",
        size_bytes=len(ATTACHMENT_BYTES),
        content_hash="sha256:" + "a" * 64,
        page_count=1,
        visibility=Visibility.PROJECT,
        provenance=HUMAN,
    )


@pytest.fixture
def conversation_repo(repo: WorkspaceRepository) -> WorkspaceRepository:
    """The canonical fixture with a conversation history written into it."""
    add_sessions(repo)
    return repo


@pytest.fixture
def conversation_graph(conversation_repo: WorkspaceRepository) -> Iterator[ResearchGraph]:
    """The graph over that workspace, freshly rebuilt."""
    built = ResearchGraph(conversation_repo)
    built.rebuild()
    yield built
    built.close()


# --- projection -------------------------------------------------------------


def test_a_session_projects_under_its_own_plain_id(conversation_graph: ResearchGraph) -> None:
    node = conversation_graph.resolve("@CS0001")

    assert node is not None
    assert (node.identity, node.kind) == ("CS0001", NodeKind.SESSION)
    assert node.source == "conversations/CS0001/session.yaml"


def test_working_context_is_never_labelled_accepted(conversation_graph: ResearchGraph) -> None:
    """A transcript is private working context; the projection may not promote it."""
    kinds = (NodeKind.SESSION, NodeKind.MESSAGE, NodeKind.ATTACHMENT)
    nodes = conversation_graph.query(GraphFilter(kinds=kinds, limit=100))

    assert nodes
    assert {node.authority for node in nodes} == {GraphAuthority.PRIVATE}


def test_a_message_inherits_the_egress_class_of_its_session(
    conversation_graph: ResearchGraph,
) -> None:
    shared = conversation_graph.resolve("M0001")
    private = conversation_graph.resolve("M0003")

    assert shared is not None and shared.visibility is GraphVisibility.PROJECT
    assert private is not None and private.visibility is GraphVisibility.PRIVATE


def test_the_session_owns_its_messages_and_the_project_owns_the_session(
    conversation_graph: ResearchGraph,
) -> None:
    out = conversation_graph.neighbors(
        "CS0001", hops=1, direction=Direction.OUT, edge_kinds=(EdgeKind.CONTAINS,)
    )
    inbound = conversation_graph.neighbors(
        "CS0001", hops=1, direction=Direction.IN, edge_kinds=(EdgeKind.CONTAINS,)
    )

    assert {item.node.identity for item in out} == {"M0001", "M0002"}
    assert [item.node.kind for item in inbound] == [NodeKind.PROJECT]


def test_a_reference_block_becomes_a_mentioned_in_edge_to_the_object_it_named(
    conversation_graph: ResearchGraph,
) -> None:
    """`@C0041` typed in the composer is a resolvable edge, not prose to re-parse."""
    found = conversation_graph.neighbors(
        "M0001", hops=1, direction=Direction.OUT, edge_kinds=(EdgeKind.MENTIONED_IN,)
    )

    assert [item.node.identity for item in found] == [str(CLAIM)]


def test_an_attachment_is_attached_to_both_its_session_and_the_message_carrying_it(
    conversation_graph: ResearchGraph,
) -> None:
    found = conversation_graph.neighbors(
        "SA0001", hops=1, direction=Direction.OUT, edge_kinds=(EdgeKind.ATTACHED_TO,)
    )

    assert {item.node.identity for item in found} == {"CS0001", "M0002"}


# --- rebuild and update -----------------------------------------------------


def _delete_the_projection(repo: WorkspaceRepository, backup: Path) -> None:
    """`rm -rf .research/`, keeping the staged proposals so the comparison covers them.

    Staging is regenerable too, so a bare delete would take the model's proposals with it
    and the two dumps would differ for a reason that has nothing to do with sessions.
    """
    research = repo.layout.research_dir
    shutil.copytree(research / "staging", backup)
    shutil.rmtree(research)
    research.mkdir(parents=True)
    shutil.copytree(backup, research / "staging")


def test_deleting_the_projection_and_rebuilding_resolves_the_same_references(
    conversation_repo: WorkspaceRepository, conversation_graph: ResearchGraph, tmp_path: Path
) -> None:
    """Graph spec §11.1, extended to sessions: identity survives the index (Product 42 O)."""
    references = ("CS0001", "M0001", "SA0001", "CS0002", "M0003", str(CLAIM), str(SUPPORTING))
    before = {name: conversation_graph.resolve(name) for name in references}
    before_dump = conversation_graph.dump()
    conversation_graph.close()

    _delete_the_projection(conversation_repo, tmp_path / "staging-backup")
    rebuilt = ResearchGraph(conversation_repo)
    try:
        rebuilt.rebuild()
        after = {name: rebuilt.resolve(name) for name in references}

        assert all(node is not None for node in after.values())
        assert after == before
        assert rebuilt.dump() == before_dump
    finally:
        rebuilt.close()


def test_a_transcript_survives_deleting_the_projection(
    conversation_repo: WorkspaceRepository,
) -> None:
    """Deleting `.research/` may cost navigation speed and never a durable transcript."""
    shutil.rmtree(conversation_repo.layout.research_dir)
    store = ConversationStore.for_repository(conversation_repo)

    assert [message.id for message in store.iter_messages(PRIVATE)] == [PRIVATE_NOTE]
    assert store.get_session(PRIVATE).visibility is Visibility.PRIVATE


def test_appending_a_message_re_projects_one_transcript_and_agrees_with_a_rebuild(
    conversation_repo: WorkspaceRepository, conversation_graph: ResearchGraph
) -> None:
    """Graph spec §11.6: an update leaves exactly what a full rebuild would have written."""
    store = ConversationStore.for_repository(conversation_repo)
    store.append_message(
        SHARED,
        lambda new_id: Message(
            id=new_id,
            session=SHARED,
            role=MessageRole.USER,
            visibility=Visibility.PROJECT,
            blocks=(TextBlock(text="And what contradicts it?"),),
            provenance=HUMAN,
        ),
    )
    report = conversation_graph.update()

    assert "conversations/CS0001/messages.jsonl" in report.changed_sources
    assert "conversations/CS0002/messages.jsonl" not in report.changed_sources
    updated_dump = conversation_graph.dump()
    conversation_graph.close()

    rebuilt = ResearchGraph(conversation_repo)
    try:
        rebuilt.rebuild()
        assert rebuilt.dump() == updated_dump
    finally:
        rebuilt.close()


def test_a_session_directory_that_cannot_be_read_does_not_fail_the_build(
    conversation_repo: WorkspaceRepository, tmp_path: Path
) -> None:
    """A projection must never be the reason a workspace cannot be indexed."""
    record = conversation_repo.layout.session_file(PRIVATE)
    record.write_text("this is not a session record\n", encoding="utf-8")
    graph = ResearchGraph(conversation_repo)
    try:
        graph.rebuild()

        assert graph.resolve("CS0001") is not None
        assert graph.resolve("CS0002") is None
    finally:
        graph.close()


def test_a_promoted_attachment_joins_the_corpus_spine(
    conversation_repo: WorkspaceRepository,
) -> None:
    """`Save to corpus` links the session copy to the Version its Artifact belongs to."""
    store = ConversationStore.for_repository(conversation_repo)
    attachment = store.get_attachment(SHARED, SHARED_ATTACHMENT)
    work = conversation_repo.list_works()[0]
    promoted = attachment.model_copy(
        update={
            "state": AttachmentState.IN_CORPUS,
            "work": work.id,
            "version": work.versions[0],
            "artifact": work.artifacts[0],
        }
    )
    store.put_attachment(promoted)
    graph = ResearchGraph(conversation_repo)
    try:
        graph.rebuild()
        found = graph.neighbors(
            str(SHARED_ATTACHMENT),
            hops=1,
            direction=Direction.OUT,
            edge_kinds=(EdgeKind.ARTIFACT_OF,),
        )

        assert [item.node.identity for item in found] == [str(work.versions[0])]
        node = graph.resolve(str(SHARED_ATTACHMENT))
        assert node is not None
        assert node.metadata["artifact"] == str(work.artifacts[0])
        assert node.authority is GraphAuthority.PRIVATE
    finally:
        graph.close()


def test_a_session_record_names_the_counts_a_client_lists_it_by(
    conversation_graph: ResearchGraph,
) -> None:
    node = conversation_graph.resolve("CS0001")

    assert node is not None
    assert node.metadata["messages"] == 2
    assert node.metadata["last_message"] == str(SHARED_ANSWER)
    assert node.label == "Shared plan for the traffic evaluation"


def test_a_session_is_findable_by_its_title(conversation_graph: ResearchGraph) -> None:
    hits = conversation_graph.search("hunches", kinds=(NodeKind.SESSION,))

    assert [hit.node.identity for hit in hits] == [str(PRIVATE)]


def test_the_projected_session_record_is_a_conversation_session(
    conversation_repo: WorkspaceRepository,
) -> None:
    """The graph reads the same durable record the store writes; nothing is re-derived."""
    store = ConversationStore.for_repository(conversation_repo)
    session = store.get_session(SHARED)

    assert isinstance(session, ConversationSession)
    assert session.message_count == 2
