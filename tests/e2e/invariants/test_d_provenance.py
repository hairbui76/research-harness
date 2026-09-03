"""Product §42.D - Provenance.

"Every accepted Evidence object opens the exact source artifact and location it was
accepted from."

The check is literal: each accepted Evidence anchor is replayed with `resolve_anchor`
against a parse of the *stored artifact bytes*, and the page, the geometry, and the text it
comes back with are compared against the original PDF. Then the bytes are revised and the
same anchor is required to go `stale` - never to be quietly re-pointed at the new file
(ADR-002, ADR-008).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import EvidenceStatus
from research_harness.domain.evidence import Evidence
from research_harness.parsing.anchors import (
    AnchorError,
    AnchorValidationStatus,
    resolve_anchor,
    validate_anchor,
)
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.workspace.repository import WorkspaceRepository
from tests.e2e.invariants.workstation import (
    FIXTURE,
    MEASURED_PAGE,
    MEASURED_VALUE,
    Workstation,
)


def stored_parse(repo: WorkspaceRepository, evidence: Evidence) -> ParsedDocument:
    """Parse the artifact from the bytes the workspace stored, not from the fixture file."""
    artifact = repo.get_artifact(evidence.source.artifact, work=evidence.source.work)
    return PyMuPdfParser().parse(
        ParseTarget(
            work=artifact.work,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=artifact.file_hash,
            path=repo.layout.artifact_bytes_file(artifact),
            mime_type=artifact.mime_type,
        )
    )


def accepted_evidence(repo: WorkspaceRepository) -> list[Evidence]:
    return [
        record
        for work in repo.list_works()
        for record in repo.iter_evidence(work.id)
        if record.status is EvidenceStatus.ACCEPTED
    ]


@pytest.fixture
def repo(workstation: Workstation) -> WorkspaceRepository:
    return WorkspaceRepository.open(workstation.root)


# ------------------------------------------------------------------ the anchor resolves


def test_every_accepted_evidence_object_resolves_to_its_exact_span(
    repo: WorkspaceRepository,
) -> None:
    """Product §42.D, for every accepted object rather than for a chosen one."""
    records = accepted_evidence(repo)
    assert records, "the loop accepted no evidence, so there is nothing to check"

    for record in records:
        document = stored_parse(repo, record)
        span = resolve_anchor(record.source, document)
        assert span.page == record.source.page
        assert span.bbox is not None
        assert span.text == record.content.exact_text


def test_the_measured_value_opens_on_the_page_of_the_real_table(
    repo: WorkspaceRepository,
    workstation: Workstation,
) -> None:
    """The number Product §12 cares about opens where the source paper actually prints it."""
    numeric = next(
        record for record in accepted_evidence(repo) if record.content.numeric is not None
    )
    span = resolve_anchor(numeric.source, stored_parse(repo, numeric))

    assert numeric.content.numeric is not None
    assert numeric.content.numeric.raw == MEASURED_VALUE
    assert span.text == MEASURED_VALUE
    assert span.page == MEASURED_PAGE


def test_the_stored_artifact_bytes_are_the_ingested_bytes(
    repo: WorkspaceRepository, workstation: Workstation
) -> None:
    """The exact source artifact is the immutable file, hashed and kept (ADR-002)."""
    artifact = repo.get_artifact(workstation.artifact, work=workstation.work)
    stored = repo.read_artifact_bytes(artifact)

    assert stored == FIXTURE.read_bytes()
    assert artifact.file_hash == f"sha256:{hashlib.sha256(stored).hexdigest()}"


def test_the_anchor_names_the_artifact_hash_it_was_read_from(
    repo: WorkspaceRepository,
) -> None:
    """An anchor that cannot say which bytes it came from cannot be replayed at all."""
    artifacts = {
        artifact.id: artifact
        for work in repo.list_works()
        for artifact in repo.list_artifacts(work.id)
    }
    for record in accepted_evidence(repo):
        assert record.source.file_hash == artifacts[record.source.artifact].file_hash
        assert record.source.text_hash.startswith("sha256:")


# ---------------------------------------------------------------- a revised file is stale


@pytest.fixture
def revised_parse(repo: WorkspaceRepository, tmp_path: Path) -> ParsedDocument:
    """A parse of a *copy* of the artifact whose bytes were changed after acceptance.

    The workspace's own artifact is never touched: a revision is a new Artifact, so the
    thing being simulated is "a researcher points at a file that is no longer the one the
    evidence was read from".
    """
    record = accepted_evidence(repo)[0]
    artifact = repo.get_artifact(record.source.artifact, work=record.source.work)
    revised = tmp_path / "revised.pdf"
    revised.write_bytes(repo.read_artifact_bytes(artifact) + b"\n% camera-ready revision\n")
    digest = f"sha256:{hashlib.sha256(revised.read_bytes()).hexdigest()}"
    return PyMuPdfParser().parse(
        ParseTarget(
            work=artifact.work,
            version=artifact.version,
            artifact=artifact.id,
            file_hash=digest,
            path=revised,
            mime_type=artifact.mime_type,
        )
    )


def test_a_revised_artifact_makes_the_anchor_stale(
    repo: WorkspaceRepository, revised_parse: ParsedDocument
) -> None:
    record = accepted_evidence(repo)[0]

    outcome = validate_anchor(record.source, revised_parse)

    assert outcome.status is AnchorValidationStatus.STALE
    assert record.source.file_hash in outcome.reason
    assert outcome.matched_block is None


def test_a_stale_anchor_is_never_resolved_to_a_span_anyway(
    repo: WorkspaceRepository, revised_parse: ParsedDocument
) -> None:
    """Re-anchoring is refused rather than attempted: a wrong span is worse than none."""
    record = accepted_evidence(repo)[0]

    with pytest.raises(AnchorError, match="stale"):
        resolve_anchor(record.source, revised_parse)


def test_the_revision_changes_nothing_in_the_workspace(
    repo: WorkspaceRepository, revised_parse: ParsedDocument, workstation: Workstation
) -> None:
    """A file changing under the researcher's feet does not rewrite accepted state."""
    reopened = WorkspaceRepository.open(workstation.root)
    record = accepted_evidence(reopened)[0]

    assert record.stale.value == "fresh"
    assert resolve_anchor(record.source, stored_parse(reopened, record)).text == (
        record.content.exact_text
    )
