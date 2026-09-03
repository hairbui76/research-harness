"""Attachment intake against a real workspace: durability, failure isolation, previews.

The four properties the design turns on (attachments design SS2, SS4, SS8):

* the bytes are durably in the session the moment the `SA####` exists, and no corpus
  object exists because of it;
* one item's failure costs no other item and loses nothing — the failed file stays
  visible, with a reason, and can be retried;
* what a file *is* comes from its bytes, and its name is display metadata that cannot
  reach the filesystem;
* previews are projections under `.research/`, regenerated on demand.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.conversation.attachments import (
    AttachmentError,
    AttachmentLimits,
    AttachmentService,
    PreviewUnavailableError,
    display_filename,
)
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    AttachmentState,
    ConversationSession,
    Visibility,
)
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.workspace.conversations import ConversationStore
from tests.fixtures.attachments import pdf_bytes, png_bytes

HUMAN = Provenance.human()
TEXT = b"# notes\n\nsome markdown\n"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="attachments"))
    yield open_context(result.root, HUMAN_ACTOR)


@pytest.fixture
def store(project: CapabilityContext) -> ConversationStore:
    return ConversationStore.for_repository(project.repo)


@pytest.fixture
def service(store: ConversationStore) -> AttachmentService:
    return AttachmentService(store)


@pytest.fixture
def session(store: ConversationStore) -> ConversationSession:
    return store.create_session(title="reading", provenance=HUMAN)


def corpus_digest(root: Path) -> str:
    """A fingerprint of the whole corpus tree, so "nothing was created" is checkable."""
    digest = hashlib.sha256()
    for path in sorted((root / "corpus").rglob("*")):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


# -- intake ------------------------------------------------------------------


def test_an_image_and_a_pdf_become_ready_without_touching_the_corpus(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
) -> None:
    """Gate P19: attaching creates session state and no corpus object at all."""
    events = project.root / "events" / "research.jsonl"
    before = corpus_digest(project.root)
    before_events = events.read_text(encoding="utf-8")

    image = service.add(
        session.id,
        filename="figure.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
    )
    document = service.add(
        session.id,
        filename="paper.pdf",
        media_type="application/pdf",
        data=pdf_bytes(),
        provenance=HUMAN,
    )

    assert (image.id, image.state) == ("SA0001", AttachmentState.READY)
    assert (document.id, document.state) == ("SA0002", AttachmentState.READY)
    assert document.page_count == 2
    assert image.content_hash == f"sha256:{hashlib.sha256(png_bytes()).hexdigest()}"
    assert service.store.read_attachment_bytes(image) == png_bytes()
    assert corpus_digest(project.root) == before
    assert list((project.root / "corpus" / "works").iterdir()) == []
    # Not one research event either: an attachment is not a change to accepted state.
    assert events.read_text(encoding="utf-8") == before_events


def test_the_media_type_comes_from_the_bytes_not_from_what_was_declared(
    service: AttachmentService, session: ConversationSession
) -> None:
    """A browser's `application/octet-stream` must not make a PDF an unknown blob."""
    unlabelled = service.add(
        session.id,
        filename="paper.pdf",
        media_type="application/octet-stream",
        data=pdf_bytes(),
        provenance=HUMAN,
    )
    mislabelled = service.add(
        session.id,
        filename="figure.pdf",
        media_type="application/pdf",
        data=png_bytes(),
        provenance=HUMAN,
    )

    assert unlabelled.media_type == "application/pdf"
    assert mislabelled.media_type == "image/png"
    assert mislabelled.state is AttachmentState.READY


def test_a_filename_is_display_metadata_and_never_a_path(
    project: CapabilityContext, service: AttachmentService, session: ConversationSession
) -> None:
    """Attachments design SS8: the name is what a remote client typed, not a location."""
    attachment = service.add(
        session.id,
        filename="../../../etc/passwd.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
    )
    stored = service.store.attachment_bytes_path(attachment)

    assert attachment.filename == "passwd.png"
    assert stored.parent == project.repo.layout.session_attachments_dir(session.id)
    assert stored.name == "SA0001.png"
    assert display_filename("C:\\Users\\r\\notes.md") == "notes.md"
    assert display_filename("..") == "attachment"


def test_a_text_file_is_accepted_and_json_must_actually_parse(
    service: AttachmentService, session: ConversationSession
) -> None:
    markdown = service.add(
        session.id,
        filename="notes.md",
        media_type="text/markdown",
        data=TEXT,
        provenance=HUMAN,
    )
    broken = service.add(
        session.id,
        filename="data.json",
        media_type="application/json",
        data=b"{not json",
        provenance=HUMAN,
    )

    assert markdown.state is AttachmentState.READY
    assert broken.state is AttachmentState.FAILED
    assert "does not parse" in str(broken.failure_reason)


def test_an_attachment_inherits_the_session_visibility_unless_told_otherwise(
    store: ConversationStore, service: AttachmentService
) -> None:
    """Whether bytes may leave the machine is a session property first (design SS7)."""
    shared = store.create_session(
        title="shareable", provenance=HUMAN, visibility=Visibility.PROJECT
    )
    inherited = service.add(
        shared.id, filename="a.png", media_type="image/png", data=png_bytes(), provenance=HUMAN
    )
    overridden = service.add(
        shared.id,
        filename="b.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
        visibility=Visibility.PRIVATE,
    )

    assert inherited.visibility is Visibility.PROJECT
    assert overridden.visibility is Visibility.PRIVATE


# -- failure isolation -------------------------------------------------------


def test_one_bad_file_in_a_batch_costs_no_other_file(
    service: AttachmentService, session: ConversationSession
) -> None:
    """Attachments design SS2: a failure never removes the ready items or the draft."""
    batch = [
        ("good.png", "image/png", png_bytes()),
        ("truncated.png", "image/png", b"\x89PNG\r\n\x1a\n"[:4] + b"broken"),
        ("paper.pdf", "application/pdf", pdf_bytes()),
        ("empty.txt", "text/plain", b""),
        ("archive.zip", "application/zip", b"PK\x03\x04rest"),
    ]
    results = [
        service.add(session.id, filename=name, media_type=media_type, data=data, provenance=HUMAN)
        for name, media_type, data in batch
    ]

    states = [item.state for item in results]
    assert states == [
        AttachmentState.READY,
        AttachmentState.FAILED,
        AttachmentState.READY,
        AttachmentState.FAILED,
        AttachmentState.FAILED,
    ]
    assert [item.id for item in service.list_attachments(session.id)] == [
        "SA0001",
        "SA0002",
        "SA0003",
        "SA0004",
        "SA0005",
    ]
    assert [item.id for item in service.sendable(session.id)] == ["SA0001", "SA0003"]
    assert all(item.failure_reason for item in results if item.state is AttachmentState.FAILED)
    assert "is not a supported attachment type" in str(results[4].failure_reason)


def test_a_failed_attachment_keeps_its_bytes_and_can_be_retried(
    service: AttachmentService, session: ConversationSession
) -> None:
    limits_service = AttachmentService(service.store, limits=AttachmentLimits(max_image_bytes=10))
    failed = limits_service.add(
        session.id,
        filename="figure.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
    )
    assert failed.state is AttachmentState.FAILED
    assert service.store.read_attachment_bytes(failed) == png_bytes()

    recovered = service.retry(failed)

    assert recovered.state is AttachmentState.READY
    assert recovered.content_hash is not None


def test_an_oversize_pdf_is_refused_with_the_page_count(
    session: ConversationSession, store: ConversationStore
) -> None:
    strict = AttachmentService(store, limits=AttachmentLimits(max_pdf_pages=1))

    refused = strict.add(
        session.id,
        filename="paper.pdf",
        media_type="application/pdf",
        data=pdf_bytes(),
        provenance=HUMAN,
    )

    assert refused.state is AttachmentState.FAILED
    assert "2 pages exceeds the 1-page attachment limit" in str(refused.failure_reason)


# -- previews ----------------------------------------------------------------


def test_previews_are_projections_that_regenerate_after_the_cache_is_deleted(
    project: CapabilityContext, service: AttachmentService, session: ConversationSession
) -> None:
    """Product 8.2: deleting `.research/` costs a re-render, never an attachment."""
    image = service.add(
        session.id,
        filename="figure.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
    )
    document = service.add(
        session.id,
        filename="paper.pdf",
        media_type="application/pdf",
        data=pdf_bytes(),
        provenance=HUMAN,
    )

    thumbnail = service.preview(image)
    page_two = service.preview(document, page=2)
    first = thumbnail.read_bytes()

    assert thumbnail.read_bytes().startswith(b"\x89PNG")
    assert page_two.read_bytes().startswith(b"\x89PNG")
    assert project.repo.layout.is_regenerable(thumbnail)
    assert service.preview_pages(document) == 2

    shutil.rmtree(project.repo.layout.research_dir / "cache")
    assert not thumbnail.exists()

    assert service.preview(image).read_bytes() == first
    assert service.store.read_attachment_bytes(image) == png_bytes()


def test_a_preview_of_a_page_that_does_not_exist_is_refused(
    service: AttachmentService, session: ConversationSession
) -> None:
    document = service.add(
        session.id,
        filename="paper.pdf",
        media_type="application/pdf",
        data=pdf_bytes(),
        provenance=HUMAN,
    )
    text = service.add(
        session.id, filename="notes.md", media_type="text/markdown", data=TEXT, provenance=HUMAN
    )

    with pytest.raises(PreviewUnavailableError, match="page 9 does not exist"):
        service.preview(document, page=9)
    with pytest.raises(PreviewUnavailableError, match="read its bytes"):
        service.preview(text)


# -- removal -----------------------------------------------------------------


def test_removing_an_attachment_deletes_its_bytes_and_its_previews(
    service: AttachmentService, session: ConversationSession, store: ConversationStore
) -> None:
    attachment = service.add(
        session.id,
        filename="figure.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
    )
    preview = service.preview(attachment)
    bytes_path = store.attachment_bytes_path(attachment)

    service.remove(attachment)

    assert not bytes_path.exists()
    assert not preview.exists()
    assert service.list_attachments(session.id) == []


def test_an_attachment_a_message_carries_is_not_removable(
    service: AttachmentService, session: ConversationSession, store: ConversationStore
) -> None:
    """Removing it would let the id be handed out again, under different bytes."""
    from research_harness.domain.conversation import Message, MessageRole, TextBlock

    attachment = service.add(
        session.id,
        filename="figure.png",
        media_type="image/png",
        data=png_bytes(),
        provenance=HUMAN,
    )
    store.append_message(
        session.id,
        lambda message_id: Message(
            id=message_id,
            session=session.id,
            role=MessageRole.USER,
            blocks=(TextBlock(text="what is in this figure?"),),
            attachments=(attachment.id,),
            provenance=HUMAN,
        ),
    )

    with pytest.raises(AttachmentError, match="is named by M0001"):
        service.remove(attachment)
    assert store.read_attachment_bytes(attachment) == png_bytes()
