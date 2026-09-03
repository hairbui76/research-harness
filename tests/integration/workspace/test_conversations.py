"""`ConversationStore` against a real workspace: durability, counters, locking, search."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    AttachmentState,
    AttemptStatus,
    AuthorityLabel,
    ContextClass,
    ContextItem,
    ContextPack,
    ContextReceipt,
    ConversationSession,
    EgressClass,
    Message,
    MessageAttempt,
    MessageRole,
    ModelIdentity,
    OmissionReason,
    OmittedContextItem,
    SessionAttachment,
    SessionDefaults,
    TextBlock,
    Visibility,
    transition_attachment,
)
from research_harness.domain.errors import WorkspaceError
from research_harness.domain.ids import (
    ContextPackId,
    ConversationSessionId,
    MessageId,
    SessionAttachmentId,
)
from research_harness.workspace.conversations import (
    ConversationNotFoundError,
    ConversationStore,
    derive_summary,
)
from research_harness.workspace.events import iter_canonical_entries
from research_harness.workspace.journal import Transaction, recover
from research_harness.workspace.layout import GITIGNORE_CONTENT
from research_harness.workspace.locking import WorkspaceLock, WorkspaceLockedError
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.serialization import iter_jsonl, read_yaml

HUMAN = Provenance.human()
SYSTEM = Provenance.system()
PDF_BYTES = b"%PDF-1.7\nnot a real pdf\n"
PDF_HASH = f"sha256:{hashlib.sha256(PDF_BYTES).hexdigest()}"


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return WorkspaceRepository.init(tmp_path / "project", "demo")


@pytest.fixture
def store(repo: WorkspaceRepository) -> ConversationStore:
    return ConversationStore(repo.layout)


def user_message(session: ConversationSessionId, text: str) -> Callable[[MessageId], Message]:
    """Builder for a plain user message; the store supplies the allocated id."""

    def build(message_id: MessageId) -> Message:
        return Message(
            id=message_id,
            session=session,
            role=MessageRole.USER,
            blocks=(TextBlock(text=text),),
            provenance=HUMAN,
        )

    return build


def open_session(
    store: ConversationStore, title: str = "Tokenization terminology"
) -> ConversationSession:
    return store.create_session(title=title, provenance=HUMAN)


def attachment_builder(
    session: ConversationSessionId, filename: str = "paper.pdf"
) -> Callable[[SessionAttachmentId], SessionAttachment]:
    def build(attachment_id: SessionAttachmentId) -> SessionAttachment:
        return SessionAttachment(
            id=attachment_id,
            session=session,
            state=AttachmentState.SELECTED,
            filename=filename,
            media_type="application/pdf",
            size_bytes=len(PDF_BYTES),
            provenance=HUMAN,
        )

    return build


def pack_builder(
    session: ConversationSessionId, message: MessageId | None = None
) -> Callable[[ContextPackId], ContextPack]:
    def build(pack_id: ContextPackId) -> ContextPack:
        return ContextPack(
            id=pack_id,
            session=session,
            message=message,
            model=ModelIdentity(provider="vendor-a", model="model-x"),
            egress=EgressClass.EXTERNAL,
            receipt=ContextReceipt(
                included=(
                    ContextItem(
                        context_class=ContextClass.ACCEPTED_STATE,
                        source="rh://claim/C0041",
                        authority=AuthorityLabel.ACCEPTED,
                        tokens=120,
                    ),
                ),
                omitted=(
                    OmittedContextItem(
                        context_class=ContextClass.PRIOR_SESSIONS,
                        source="rh://session/CS0002?message=M0009",
                        reason=OmissionReason.PRIVACY_POLICY,
                        tokens=80,
                    ),
                ),
            ),
            provenance=SYSTEM,
        )

    return build


# --- sessions ---------------------------------------------------------------


def test_create_session_writes_the_documented_layout(store: ConversationStore) -> None:
    session = open_session(store)
    layout = store.layout
    assert session.id == ConversationSessionId("CS0001")
    assert layout.session_file(session.id).is_file()
    assert layout.session_attachments_dir(session.id).is_dir()
    assert layout.session_context_dir(session.id).is_dir()
    assert layout.session_dir(session.id).parent == layout.conversations_dir
    assert read_yaml(layout.session_file(session.id), type(session)) == session


def test_session_ids_are_monotonic_per_project(store: ConversationStore) -> None:
    first = store.create_session(title="first", provenance=HUMAN)
    second = store.create_session(title="second", provenance=HUMAN)
    assert (first.id, second.id) == ("CS0001", "CS0002")
    assert [session.id for session in store.list_sessions()] == [first.id, second.id]


def test_conversations_are_gitignored_by_the_generated_workspace(
    repo: WorkspaceRepository,
) -> None:
    """Transcripts are durable but private; publishing them is a separate, explicit act."""
    gitignore = repo.layout.gitignore_file.read_text(encoding="utf-8").splitlines()
    assert "conversations/" in gitignore
    assert "conversations/" in GITIGNORE_CONTENT


def test_rename_keeps_the_id_transcript_and_attachments(store: ConversationStore) -> None:
    session = open_session(store, "untitled")
    store.append_message(session.id, user_message(session.id, "what changed between v1 and v2?"))
    store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)

    renamed = store.rename_session(session.id, "Version differences")

    assert renamed.id == session.id
    assert renamed.title == "Version differences"
    assert [message.text() for message in store.messages(session.id)] == [
        "what changed between v1 and v2?"
    ]
    assert [attachment.id for attachment in store.list_attachments(session.id)] == ["SA0001"]


def test_updating_a_session_records_new_defaults(store: ConversationStore) -> None:
    session = open_session(store)
    defaults = SessionDefaults(
        model=ModelIdentity(provider="vendor-a", model="model-x"), token_budget=8000
    )
    updated = store.update_session(session.id, visibility=Visibility.PROJECT, defaults=defaults)
    assert updated.visibility is Visibility.PROJECT
    assert store.get_session(session.id).defaults == defaults


def test_reading_an_unknown_session_fails_by_name(store: ConversationStore) -> None:
    with pytest.raises(ConversationNotFoundError, match="CS0009"):
        store.get_session(ConversationSessionId("CS0009"))


# --- messages ---------------------------------------------------------------


def test_appending_advances_the_session_record_in_one_unit(store: ConversationStore) -> None:
    session = open_session(store)
    first = store.append_message(session.id, user_message(session.id, "first"))
    second = store.append_message(session.id, user_message(session.id, "second"))

    record = store.get_session(session.id)
    assert (first.id, second.id) == ("M0001", "M0002")
    assert record.message_count == 2
    assert record.last_message == second.id
    assert record.last_message_at == second.created_at
    lines = store.layout.messages_file(session.id).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "M0001"


def test_message_ids_are_project_scoped_across_sessions(store: ConversationStore) -> None:
    first = store.create_session(title="first", provenance=HUMAN)
    second = store.create_session(title="second", provenance=HUMAN)
    a = store.append_message(first.id, user_message(first.id, "in the first session"))
    b = store.append_message(second.id, user_message(second.id, "in the second session"))
    c = store.append_message(first.id, user_message(first.id, "back in the first"))
    assert [a.id, b.id, c.id] == ["M0001", "M0002", "M0003"]


def test_a_message_built_with_the_wrong_id_or_session_is_refused(
    store: ConversationStore,
) -> None:
    session = open_session(store)

    def wrong_id(message_id: MessageId) -> Message:
        return Message(
            id=MessageId("M0099"),
            session=session.id,
            role=MessageRole.USER,
            blocks=(TextBlock(text="x"),),
            provenance=HUMAN,
        )

    with pytest.raises(WorkspaceError, match="M0099"):
        store.append_message(session.id, wrong_id)
    assert store.get_session(session.id).message_count == 0
    assert not store.layout.messages_file(session.id).exists()


def test_an_interrupted_stream_and_its_retry_are_both_kept(store: ConversationStore) -> None:
    session = open_session(store)

    def interrupted(message_id: MessageId) -> Message:
        return Message(
            id=message_id,
            session=session.id,
            role=MessageRole.ASSISTANT,
            blocks=(TextBlock(text="the first half"),),
            attempt=MessageAttempt(status=AttemptStatus.INTERRUPTED),
            model=ModelIdentity(provider="vendor-a", model="model-x"),
            provenance=Provenance.model("vendor-a/model-x"),
        )

    first = store.append_message(session.id, interrupted)

    def retry(message_id: MessageId) -> Message:
        return Message(
            id=message_id,
            session=session.id,
            role=MessageRole.ASSISTANT,
            blocks=(TextBlock(text="the whole answer"),),
            attempt=MessageAttempt(number=2, retry_of=first.id),
            provenance=Provenance.model("vendor-a/model-x"),
        )

    second = store.append_message(session.id, retry)
    transcript = store.messages(session.id)
    assert [message.id for message in transcript] == [first.id, second.id]
    assert transcript[0].incomplete and transcript[0].text() == "the first half"
    assert transcript[1].attempt.retry_of == first.id


def test_find_message_locates_a_message_in_any_session(store: ConversationStore) -> None:
    first = store.create_session(title="first", provenance=HUMAN)
    second = store.create_session(title="second", provenance=HUMAN)
    message = store.append_message(second.id, user_message(second.id, "only here"))
    assert store.find_message(message.id) == message
    assert store.find_message(MessageId("M0404")) is None
    with pytest.raises(ConversationNotFoundError):
        store.get_message(first.id, message.id)


# --- durability -------------------------------------------------------------


def test_conversation_state_survives_deleting_the_research_directory(
    repo: WorkspaceRepository, store: ConversationStore
) -> None:
    """`.research/` is regenerable; a transcript, an attachment, and a receipt are not."""
    session = open_session(store)
    message = store.append_message(
        session.id, user_message(session.id, "does the transcript survive?")
    )
    attachment = store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)
    pack = store.write_context_pack(session.id, pack_builder(session.id, message.id))
    store.regenerate_summary(session.id)

    shutil.rmtree(repo.layout.research_dir)
    reopened = ConversationStore(repo.layout)

    assert reopened.get_session(session.id).title == session.title
    assert [record.id for record in reopened.messages(session.id)] == [message.id]
    assert reopened.get_attachment(session.id, attachment.id) == attachment
    assert reopened.read_attachment_bytes(attachment) == PDF_BYTES
    assert reopened.read_context_pack(session.id, pack.id) == pack
    assert reopened.read_summary(session.id) is not None

    # Counters come from the durable files, so nothing is handed out twice.
    assert reopened.create_session(title="after the wipe", provenance=HUMAN).id == "CS0002"
    assert reopened.append_message(session.id, user_message(session.id, "and again")).id == "M0002"
    assert reopened.add_attachment(session.id, attachment_builder(session.id)).id == "SA0002"
    assert reopened.write_context_pack(session.id, pack_builder(session.id)).id == "CP0002"


def test_message_numbering_recovers_from_the_transcript_alone(
    repo: WorkspaceRepository, store: ConversationStore
) -> None:
    """A lost `session.yaml` must not restart the numbering over a live transcript."""
    session = open_session(store)
    store.append_message(session.id, user_message(session.id, "one"))
    store.append_message(session.id, user_message(session.id, "two"))
    other = store.create_session(title="other", provenance=HUMAN)
    repo.layout.session_file(session.id).unlink()

    assert store.append_message(other.id, user_message(other.id, "three")).id == "M0003"


def test_records_round_trip_through_their_canonical_files(store: ConversationStore) -> None:
    session = open_session(store)
    message = store.append_message(session.id, user_message(session.id, "round trip"))
    attachment = store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)
    pack = store.write_context_pack(session.id, pack_builder(session.id, message.id))
    layout = store.layout

    assert read_yaml(layout.session_file(session.id), type(session)) == store.get_session(
        session.id
    )
    assert list(iter_jsonl(layout.messages_file(session.id), Message)) == [message]
    assert (
        read_yaml(layout.session_attachment_file(session.id, attachment.id), SessionAttachment)
        == attachment
    )
    text = layout.context_pack_file(session.id, pack.id).read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == pack.model_dump(mode="json")


# --- locking ----------------------------------------------------------------


def test_appending_takes_the_workspace_lock(repo: WorkspaceRepository) -> None:
    store = ConversationStore(repo.layout, lock_timeout=0.05)
    session = store.create_session(title="locked", provenance=HUMAN)
    with WorkspaceLock(repo.layout, timeout=1.0), pytest.raises(WorkspaceLockedError):
        store.append_message(session.id, user_message(session.id, "blocked"))
    assert store.append_message(session.id, user_message(session.id, "now allowed")).id == "M0001"


def test_a_store_built_from_a_repository_reuses_its_lock(repo: WorkspaceRepository) -> None:
    """A promotion holds the workspace open; writing the session side must not deadlock."""
    store = ConversationStore.for_repository(repo)
    with repo.lock():
        session = store.create_session(title="under one lock", provenance=HUMAN)
        message = store.append_message(session.id, user_message(session.id, "still one lock"))
    assert message.id == "M0001"


# --- attachments ------------------------------------------------------------


def test_attachment_metadata_and_bytes_land_together(store: ConversationStore) -> None:
    session = open_session(store)
    attachment = store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)
    assert attachment.id == "SA0001"
    assert store.attachment_bytes_path(attachment).name == "SA0001.pdf"
    previews = store.layout.attachment_preview_dir(attachment.id)
    assert previews.parent == store.layout.attachment_cache_dir
    assert store.layout.is_regenerable(previews)
    assert store.read_attachment_bytes(attachment) == PDF_BYTES
    assert store.list_attachments(session.id) == [attachment]


def test_attachment_transitions_persist_and_keep_the_session_copy(
    store: ConversationStore,
) -> None:
    session = open_session(store)
    attachment = store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)
    validating = store.put_attachment(transition_attachment(attachment, AttachmentState.VALIDATING))
    ready = store.put_attachment(
        transition_attachment(
            validating, AttachmentState.READY, content_hash=PDF_HASH, page_count=1
        )
    )
    failed = store.put_attachment(
        transition_attachment(
            transition_attachment(ready, AttachmentState.PROMOTING),
            AttachmentState.FAILED,
            failure_reason="identity was ambiguous",
        )
    )
    stored = store.get_attachment(session.id, attachment.id)
    assert stored == failed
    assert stored.state is AttachmentState.FAILED
    assert store.read_attachment_bytes(stored) == PDF_BYTES


def test_attachment_bytes_are_immutable_once_stored(store: ConversationStore) -> None:
    session = open_session(store)
    attachment = store.add_attachment(session.id, attachment_builder(session.id))
    store.store_attachment_bytes(attachment, PDF_BYTES)
    assert store.store_attachment_bytes(attachment, PDF_BYTES).is_file()
    with pytest.raises(WorkspaceError, match="immutable"):
        store.store_attachment_bytes(attachment, b"different bytes")


def test_attachment_ids_are_project_scoped(store: ConversationStore) -> None:
    first = store.create_session(title="first", provenance=HUMAN)
    second = store.create_session(title="second", provenance=HUMAN)
    a = store.add_attachment(first.id, attachment_builder(first.id))
    b = store.add_attachment(second.id, attachment_builder(second.id))
    assert [a.id, b.id] == ["SA0001", "SA0002"]


# --- context packs ----------------------------------------------------------


def test_context_packs_are_listed_and_read_back(store: ConversationStore) -> None:
    session = open_session(store)
    first = store.write_context_pack(session.id, pack_builder(session.id))
    second = store.write_context_pack(session.id, pack_builder(session.id))
    assert store.list_context_packs(session.id) == [first.id, second.id]
    restored = store.read_context_pack(session.id, first.id)
    assert restored == first
    assert restored.receipt.tokens_by_class() == {ContextClass.ACCEPTED_STATE: 120}
    assert list(restored.receipt.omissions_by_reason()) == [OmissionReason.PRIVACY_POLICY]
    with pytest.raises(ConversationNotFoundError):
        store.read_context_pack(session.id, ContextPackId("CP0404"))


# --- search and resume ------------------------------------------------------


def test_search_finds_sessions_by_title_and_by_message_text(store: ConversationStore) -> None:
    first = store.create_session(title="Tokenization terminology", provenance=HUMAN)
    second = store.create_session(title="Unrelated", provenance=HUMAN)
    store.append_message(second.id, user_message(second.id, "byte-pair TOKENIZATION appears here"))

    by_title = store.search("tokenization terminology")
    assert [match.session for match in by_title] == [first.id]
    assert by_title[0].title_matched and by_title[0].messages == ()

    by_text = store.search("byte-pair")
    assert [match.session for match in by_text] == [second.id]
    assert by_text[0].messages == ("M0001",)
    assert by_text[0].snippet is not None and "byte-pair" in by_text[0].snippet

    both = store.search("tokenization")
    assert {match.session for match in both} == {first.id, second.id}
    assert both[0].session == second.id  # most recently updated first
    assert store.search("   ") == []
    assert store.search("nothing here") == []


def test_search_honours_its_limit(store: ConversationStore) -> None:
    for index in range(3):
        store.create_session(title=f"topic {index}", provenance=HUMAN)
    assert len(store.search("topic", limit=2)) == 2


def test_resume_returns_the_record_transcript_and_attachments(
    store: ConversationStore,
) -> None:
    session = open_session(store)
    message = store.append_message(
        session.id, user_message(session.id, "continue where we stopped")
    )
    attachment = store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)
    transcript = store.resume(session.id)
    assert transcript.session.id == session.id
    assert transcript.messages == (message,)
    assert transcript.attachments == (attachment,)


# --- derived summaries ------------------------------------------------------


def test_summaries_are_derived_regenerable_and_deterministic(
    store: ConversationStore,
) -> None:
    session = open_session(store)
    message = store.append_message(session.id, user_message(session.id, "what did we conclude?"))
    store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)

    first = store.regenerate_summary(session.id)
    second = store.regenerate_summary(session.id)
    assert first == second == store.read_summary(session.id)
    assert f"`{session.id}`" in first
    assert "what did we conclude?" in first
    assert "never outranks the transcript" in first
    assert store.get_session(session.id).summarized_through == message.id

    later = store.append_message(session.id, user_message(session.id, "a second question"))
    assert store.regenerate_summary(session.id) != first
    assert store.get_session(session.id).summarized_through == later.id


def test_a_summary_may_be_written_by_a_model_without_touching_the_transcript(
    store: ConversationStore,
) -> None:
    session = open_session(store)
    message = store.append_message(session.id, user_message(session.id, "the only message"))
    store.write_summary(session.id, "# A model's summary\n", through=message.id)
    assert store.read_summary(session.id) == "# A model's summary\n"
    assert [record.id for record in store.messages(session.id)] == [message.id]


def test_derive_summary_is_pure(store: ConversationStore) -> None:
    session = open_session(store)
    store.append_message(session.id, user_message(session.id, "one"))
    transcript = store.resume(session.id)
    once = derive_summary(transcript.session, transcript.messages, transcript.attachments)
    twice = derive_summary(transcript.session, transcript.messages, transcript.attachments)
    assert once == twice
    assert store.read_summary(session.id) is None


# --- crash tolerance --------------------------------------------------------


def test_an_append_interrupted_before_the_commit_point_is_finished_by_recovery(
    store: ConversationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The transcript line and the session counters are one journalled unit."""

    def explode(self: Transaction, record: object) -> None:
        raise RuntimeError("power cut at the commit point")

    session = open_session(store)
    monkeypatch.setattr(Transaction, "_commit_record", explode)
    with pytest.raises(RuntimeError, match="power cut"):
        store.append_message(session.id, user_message(session.id, "did this land?"))
    monkeypatch.undo()
    recover(store.layout)  # what the next workspace open does

    record = store.get_session(session.id)
    transcript = store.messages(session.id)
    assert record.message_count == len(transcript) == 1
    assert record.last_message == transcript[0].id == "M0001"
    assert store.append_message(session.id, user_message(session.id, "next")).id == "M0002"


def test_a_message_naming_another_session_is_refused(store: ConversationStore) -> None:
    first = open_session(store, "first")
    second = open_session(store, "second")
    with pytest.raises(WorkspaceError, match="names session"):
        store.append_message(first.id, user_message(second.id, "wrong session"))
    assert store.get_session(first.id).message_count == 0


def test_conversation_writes_stay_out_of_the_canonical_digest(
    repo: WorkspaceRepository, store: ConversationStore
) -> None:
    """Durable is not authoritative: a chat message is not a canonical-state change."""
    repo.verify()
    before = [relative for relative, _ in iter_canonical_entries(repo.layout)]

    session = open_session(store)
    store.append_message(session.id, user_message(session.id, "a private thought"))
    store.add_attachment(session.id, attachment_builder(session.id), data=PDF_BYTES)
    store.regenerate_summary(session.id)

    assert [relative for relative, _ in iter_canonical_entries(repo.layout)] == before
    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.consistency.consistent
    assert reopened.consistency.skipped_reason is not None
