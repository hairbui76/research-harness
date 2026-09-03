"""Task 2.1: a local PDF becomes an immutable Artifact, and stays one.

Re-ingesting the same bytes changes nothing, a revision is a new Version rather than an
overwrite, and a parse that fails leaves canonical state byte-for-byte identical.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    InitProjectRequest,
)
from research_harness.capabilities.handlers import accept_evidence, init_project
from research_harness.domain.base import Provenance
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    ArtifactKind,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    IdentityResolutionOutcome,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.evidence import Evidence, EvidenceContent
from research_harness.domain.ids import EvidenceId, WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.ingest.service import IngestService
from research_harness.parsing.anchors import build_anchor, resolve_anchor
from research_harness.parsing.base import ParseError
from research_harness.workspace.layout import RESEARCH_DIRNAME

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"
#: Appended after `%%EOF`, so the file still opens but its bytes - and its hash - differ.
REVISION_SUFFIX = b"\n%revision\n"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="corpus"))
    yield open_context(result.root, HUMAN_ACTOR)


@pytest.fixture
def service(project: CapabilityContext) -> IngestService:
    return IngestService(project)


@pytest.fixture
def revision(tmp_path: Path) -> Path:
    path = tmp_path / "revision.pdf"
    path.write_bytes(FIXTURE.read_bytes() + REVISION_SUFFIX)
    return path


def tree_digest(root: Path) -> str:
    """Digest of every canonical file; `.research/` is regenerable and excluded."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] == RESEARCH_DIRNAME:
            continue
        digest.update(str(relative).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


# -- ingest ------------------------------------------------------------------


def test_ingesting_a_local_pdf_registers_a_work_version_and_immutable_artifact(
    project: CapabilityContext, service: IngestService
) -> None:
    result = service.ingest_local_pdf(FIXTURE)

    assert result.created == "work"
    assert result.resolution.outcome is IdentityResolutionOutcome.DISTINCT_WORK
    assert result.mutation is not None and result.mutation.event.event.value == "work.ingested"

    work = project.repo.get_work(result.work)
    assert work.title == "Deep Representations for Encrypted Network Traffic"
    assert work.year == 2024
    assert work.versions == (result.version,) and work.artifacts == (result.artifact,)

    artifact = project.repo.get_artifact(result.artifact)
    assert artifact.kind is ArtifactKind.PDF
    assert artifact.mime_type == "application/pdf"
    assert artifact.original_filename == FIXTURE.name
    assert artifact.file_hash == f"sha256:{hashlib.sha256(FIXTURE.read_bytes()).hexdigest()}"
    assert project.repo.read_artifact_bytes(artifact) == FIXTURE.read_bytes()


def test_re_ingesting_the_same_bytes_is_idempotent(
    project: CapabilityContext, service: IngestService
) -> None:
    first = service.ingest_local_pdf(FIXTURE)
    digest = tree_digest(project.root)
    events = len(list(project.repo.iter_events()))

    again = service.ingest_local_pdf(FIXTURE)

    assert again.created == "nothing"
    assert again.idempotent
    assert again.mutation is None
    assert (again.work, again.version, again.artifact) == (
        first.work,
        first.version,
        first.artifact,
    )
    assert again.resolution.outcome is IdentityResolutionOutcome.SAME_ARTIFACT
    assert len(project.repo.list_artifacts(first.work)) == 1
    assert tree_digest(project.root) == digest
    assert len(list(project.repo.iter_events())) == events


def test_a_revision_becomes_a_new_version_and_never_overwrites_the_old_artifact(
    project: CapabilityContext, service: IngestService, revision: Path
) -> None:
    first = service.ingest_local_pdf(FIXTURE)
    second = service.ingest_local_pdf(revision)

    assert second.created == "version"
    assert second.resolution.outcome is IdentityResolutionOutcome.SAME_WORK
    assert second.work == first.work
    assert second.version != first.version and second.artifact != first.artifact

    artifacts = project.repo.list_artifacts(first.work)
    assert [artifact.id for artifact in artifacts] == [first.artifact, second.artifact]
    assert project.repo.read_artifact_bytes(artifacts[0]) == FIXTURE.read_bytes()
    assert project.repo.read_artifact_bytes(artifacts[1]) == revision.read_bytes()
    assert artifacts[0].file_hash != artifacts[1].file_hash

    work = project.repo.get_work(first.work)
    assert work.versions == (first.version, second.version)
    assert work.artifacts == (first.artifact, second.artifact)


def test_an_ambiguous_identity_is_handed_back_to_the_researcher(
    project: CapabilityContext, service: IngestService, revision: Path
) -> None:
    service.ingest_local_pdf(FIXTURE)
    service.ingest_local_pdf(FIXTURE, as_new=True)

    with pytest.raises(CapabilityError, match="unresolved"):
        service.ingest_local_pdf(revision)

    attached = service.ingest_local_pdf(revision, attach_to=WorkId("W0001"))
    assert attached.created == "version"
    assert attached.work == WorkId("W0001")
    assert len(project.repo.list_works()) == 2


# -- parse -------------------------------------------------------------------


def test_parse_work_stores_blocks_that_an_anchor_resolves_against(
    project: CapabilityContext, service: IngestService
) -> None:
    ingested = service.ingest_local_pdf(FIXTURE)
    parsed = service.parse_work(ingested.work)

    assert parsed.page_count > 0
    assert parsed.blocks
    assert parsed.mutation.event.event.value == "work.parsed"

    stored = tuple(project.repo.iter_blocks(ingested.artifact, work=ingested.work))
    assert [block.id for block in stored] == [block.id for block in parsed.blocks]

    block = next(candidate for candidate in parsed.blocks if len(candidate.text) > 20)
    anchor = build_anchor(parsed.document, block, 0, 20)
    replayed = ParsedDocument(
        work=ingested.work,
        version=ingested.version,
        artifact=ingested.artifact,
        file_hash=parsed.document.file_hash,
        parser_name=parsed.document.parser_name,
        parser_version=parsed.document.parser_version,
        page_count=parsed.page_count,
        blocks=stored,
        provenance=parsed.document.provenance,
    )
    span = resolve_anchor(anchor, replayed)
    assert span.text == block.text[:20]
    assert span.page == block.page


def test_accepted_evidence_can_be_anchored_in_a_parsed_block(
    project: CapabilityContext, service: IngestService
) -> None:
    ingested = service.ingest_local_pdf(FIXTURE)
    parsed = service.parse_work(ingested.work)
    block = next(candidate for candidate in parsed.blocks if len(candidate.text) > 20)
    candidate = Evidence(
        id=EvidenceId("E0001"),
        source=build_anchor(parsed.document, block, 0, 20),
        content=EvidenceContent(exact_text=block.text[:20]),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.METHOD_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.model("vendor-a/model-x"),
    )
    accepted = accept_evidence(
        project,
        AcceptEvidenceRequest(
            candidate=candidate,
            review_action=ReviewAction.ACCEPT,
            verdict=VerificationVerdict.SUPPORTED,
        ),
    )
    stored = next(iter(project.repo.iter_evidence(ingested.work)))
    assert stored.status is EvidenceStatus.ACCEPTED
    assert stored.source.file_hash == project.repo.get_artifact(ingested.artifact).file_hash
    assert accepted.validation.ok


def test_a_corrupt_pdf_fails_to_parse_and_leaves_canonical_state_untouched(
    project: CapabilityContext, service: IngestService, tmp_path: Path
) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nthis file claims to be a PDF and is not\n")
    ingested = service.ingest_local_pdf(corrupt)
    before = tree_digest(project.root)

    with pytest.raises(ParseError):
        service.parse_work(ingested.work)

    assert tree_digest(project.root) == before
    assert list(project.repo.iter_blocks(ingested.artifact, work=ingested.work)) == []
    assert all(event.event.value != "work.parsed" for event in project.repo.iter_events())


def test_parsing_a_work_that_does_not_exist_is_refused(service: IngestService) -> None:
    with pytest.raises(CapabilityError, match="no Work W0009"):
        service.parse_work(WorkId("W0009"))
