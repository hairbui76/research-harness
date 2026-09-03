"""`Save to corpus`: identity resolution, the copy, idempotence, and failure recovery.

The five things Product 42 N and attachments design SS6-SS7 ask of a promotion, checked
against a real corpus:

1. the identity is *resolved and shown* before anything is written;
2. saving a revision of a known paper adds a Version and an Artifact to that Work rather
   than a second Work, and never overwrites the registered Artifact (ADR-002);
3. saving the same bytes twice resolves to the existing Artifact and copies nothing;
4. a failure leaves the session copy intact and the promotion retryable;
5. nothing scientific is accepted: no Evidence, no Claim, no candidate.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.conversation.attachments import AttachmentError, AttachmentService
from research_harness.conversation.promotion_corpus import (
    AttachmentPromotionService,
    IdentityChoice,
)
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    AttachmentState,
    ConversationSession,
    SessionAttachment,
)
from research_harness.domain.enums import ArtifactKind, IdentityResolutionOutcome
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.ingest.service import IngestResult, IngestService
from research_harness.workspace.conversations import ConversationStore
from tests.fixtures.attachments import png_bytes

HUMAN = Provenance.human()
PAPER = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"
#: Appended after `%%EOF`, so the file still opens but its bytes — and its hash — differ.
REVISION_SUFFIX = b"\n%revision\n"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="promotion"))
    yield open_context(result.root, HUMAN_ACTOR)


@pytest.fixture
def store(project: CapabilityContext) -> ConversationStore:
    return ConversationStore.for_repository(project.repo)


@pytest.fixture
def service(store: ConversationStore) -> AttachmentService:
    return AttachmentService(store)


@pytest.fixture
def promotion(project: CapabilityContext, store: ConversationStore) -> AttachmentPromotionService:
    return AttachmentPromotionService(project, store=store)


@pytest.fixture
def session(store: ConversationStore) -> ConversationSession:
    return store.create_session(title="reading", provenance=HUMAN)


def attach(
    service: AttachmentService,
    session: ConversationSession,
    data: bytes,
    *,
    filename: str = "paper.pdf",
    media_type: str = "application/pdf",
) -> SessionAttachment:
    return service.add(
        session.id,
        filename=filename,
        media_type=media_type,
        data=data,
        provenance=HUMAN,
    )


def evidence_lines(root: Path) -> list[str]:
    return [
        line
        for path in (root / "corpus").rglob("evidence.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# -- resolution --------------------------------------------------------------


def test_resolution_reads_the_file_and_writes_nothing(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    attachment = attach(service, session, PAPER.read_bytes())

    identity = promotion.resolve(attachment)

    assert identity.choice is IdentityChoice.NEW_WORK
    assert identity.outcome is IdentityResolutionOutcome.DISTINCT_WORK
    assert identity.content_hash == attachment.content_hash
    assert identity.title
    assert identity.parsable is True
    assert identity.requires_confirmation is False
    assert list((project.root / "corpus" / "works").iterdir()) == []
    assert service.get(session.id, attachment.id).state is AttachmentState.READY


def test_a_revision_of_a_saved_paper_resolves_to_the_same_work(
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    """ADR-002: the same work, a different file — a Version, not a second paper."""
    first = attach(service, session, PAPER.read_bytes())
    saved = promotion.save(first)

    revision = attach(
        service, session, PAPER.read_bytes() + REVISION_SUFFIX, filename="paper-v2.pdf"
    )
    identity = promotion.resolve(revision)

    assert identity.choice is IdentityChoice.EXISTING_WORK
    assert identity.work == saved.work
    assert identity.artifact is None


# -- the promotion -----------------------------------------------------------


def test_saving_a_pdf_creates_the_work_parses_it_and_links_the_attachment(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    attachment = attach(service, session, PAPER.read_bytes())

    result = promotion.save(attachment)

    registered = project.repo.get_artifact(result.artifact)
    assert result.created == "work"
    assert result.parsed is True
    assert registered.kind is ArtifactKind.PDF
    assert registered.file_hash == attachment.content_hash
    # The Artifact records the researcher's filename, not the `SA####` it was stored under.
    assert registered.original_filename == "paper.pdf"
    assert project.repo.layout.blocks_file(result.work, result.artifact).is_file()

    linked = service.get(session.id, attachment.id)
    assert linked.state is AttachmentState.IN_CORPUS
    assert (linked.work, linked.version, linked.artifact) == (
        result.work,
        result.version,
        result.artifact,
    )
    # The session copy is still there: the corpus got a copy, not the original.
    assert service.store.read_attachment_bytes(linked) == PAPER.read_bytes()


def test_saving_a_revision_adds_a_version_and_artifact_to_the_existing_work(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    """Gate P19: promote a PDF through identity resolution to an existing Work."""
    first = promotion.save(attach(service, session, PAPER.read_bytes()))
    revision = attach(
        service, session, PAPER.read_bytes() + REVISION_SUFFIX, filename="paper-v2.pdf"
    )

    second = promotion.save(revision)

    assert second.work == first.work
    assert second.version != first.version
    assert second.artifact != first.artifact
    assert second.created == "version"
    assert [work.id for work in project.repo.list_works()] == [first.work]
    # Nothing overwrote the first artifact: both files are still on disk, byte for byte.
    assert (
        project.repo.layout.artifact_bytes_file(
            project.repo.get_artifact(first.artifact)
        ).read_bytes()
        == PAPER.read_bytes()
    )


def test_saving_the_same_bytes_twice_resolves_to_the_existing_artifact(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    """Gate P19: the same bytes are one Artifact, whichever attachment carried them."""
    first = promotion.save(attach(service, session, PAPER.read_bytes()))
    duplicate = attach(service, session, PAPER.read_bytes(), filename="paper-again.pdf")

    identity = promotion.resolve(duplicate)
    second = promotion.save(duplicate)

    assert identity.choice is IdentityChoice.EXISTING_ARTIFACT
    assert identity.duplicate is True
    assert (second.work, second.version, second.artifact) == (
        first.work,
        first.version,
        first.artifact,
    )
    assert second.created == "nothing"
    assert second.linked_existing is True
    assert len(project.repo.list_artifacts(first.work)) == 1
    assert service.get(session.id, duplicate.id).state is AttachmentState.IN_CORPUS


def test_saving_an_attachment_already_in_the_corpus_changes_nothing(
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    attachment = attach(service, session, PAPER.read_bytes())
    first = promotion.save(attachment)

    again = promotion.save(service.get(session.id, attachment.id))

    assert again.artifact == first.artifact
    assert again.created == "nothing"
    assert again.attachment.state is AttachmentState.IN_CORPUS


def test_a_non_pdf_attachment_is_registered_without_being_parsed(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    image = attach(service, session, png_bytes(), filename="figure.png", media_type="image/png")

    result = promotion.save(image)

    assert result.parsed is False
    assert project.repo.get_artifact(result.artifact).kind is ArtifactKind.OTHER
    assert not project.repo.layout.blocks_file(result.work, result.artifact).exists()


# -- the boundary ------------------------------------------------------------


def test_saving_to_the_corpus_accepts_no_evidence_and_no_claim(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    """Attachments design SS7: corpus identity is not evidence."""
    promotion.save(attach(service, session, PAPER.read_bytes()))

    assert evidence_lines(project.root) == []
    assert list((project.root / "claims").iterdir()) == []
    assert list((project.root / "questions").iterdir()) == []
    staging = project.repo.layout.staging_dir
    assert not staging.exists() or not list(staging.rglob("*.json"))


# -- failure and recovery ----------------------------------------------------


class BrokenIngest(IngestService):
    """An ingest service that fails the way a real one can: after reading, before writing."""

    def ingest_local_pdf(self, path: Path | str, **kwargs: object) -> IngestResult:
        raise RuntimeError("the corpus write failed half-way")


def test_a_failed_promotion_keeps_the_session_copy_and_stays_retryable(
    project: CapabilityContext,
    service: AttachmentService,
    session: ConversationSession,
    store: ConversationStore,
) -> None:
    """Gate P19: recover cleanly from a failed promotion."""
    attachment = attach(service, session, PAPER.read_bytes())
    broken = AttachmentPromotionService(project, store=store, ingest=BrokenIngest(project))

    with pytest.raises(RuntimeError, match="failed half-way"):
        broken.save(attachment)

    failed = service.get(session.id, attachment.id)
    assert failed.state is AttachmentState.FAILED
    assert "save to corpus failed" in str(failed.failure_reason)
    assert store.read_attachment_bytes(failed) == PAPER.read_bytes()
    assert list((project.root / "corpus" / "works").iterdir()) == []

    recovered = AttachmentPromotionService(project, store=store).save(failed)

    assert recovered.attachment.state is AttachmentState.IN_CORPUS
    assert recovered.created == "work"
    assert (
        project.repo.get_artifact(recovered.artifact).file_hash
        == f"sha256:{hashlib.sha256(PAPER.read_bytes()).hexdigest()}"
    )


def test_an_attachment_that_never_became_ready_cannot_be_saved(
    service: AttachmentService,
    session: ConversationSession,
    promotion: AttachmentPromotionService,
) -> None:
    broken = attach(service, session, b"not a pdf at all", filename="broken.pdf")

    assert broken.state is AttachmentState.FAILED
    with pytest.raises(AttachmentError, match="no validated bytes"):
        promotion.resolve(broken)
    with pytest.raises(AttachmentError, match="no validated bytes"):
        promotion.save(broken)
