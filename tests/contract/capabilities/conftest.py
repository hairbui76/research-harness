"""Hand-authored Gate P1 fixtures: a workspace, a tiny artifact, and one registered Work.

Nothing here parses, indexes, or calls a provider: Gate P1 must hold with none of them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest, RegisterWorkRequest
from research_harness.capabilities.handlers import init_project, register_work
from research_harness.domain.base import Provenance
from research_harness.domain.enums import (
    ArtifactKind,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    ReviewTier,
    VersionKind,
)
from research_harness.domain.evidence import Evidence, EvidenceContent, SourceAnchor
from research_harness.domain.ids import ArtifactId, BlockId, EvidenceId, VersionId, WorkId
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.domain.work import (
    CandidateMetadata,
    IdentifierField,
    WorkCandidate,
    WorkIdentifiers,
)
from tests.fixtures.cli.fakes import FakeCli

MODEL_ACTOR = "vendor-a/model-x"
ARTIFACT_BYTES = b"%PDF-1.7\n% hand-authored Gate P1 artifact bytes\n"
EXACT_TEXT = "We evaluate on CICIDS2017 and report macro F1."
TEXT_HASH = f"sha256:{hashlib.sha256(EXACT_TEXT.encode()).hexdigest()}"


def artifact_hash(data: bytes = ARTIFACT_BYTES) -> str:
    """`sha256:<hex>` of the artifact bytes, the way the workspace digests them."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@dataclass(frozen=True)
class Registered:
    """The ids one `work.register` produced."""

    work: WorkId
    version: VersionId
    artifact: ArtifactId


def make_candidate(
    path: Path, *, title: str = "Structured traffic representations"
) -> WorkCandidate:
    """A resolved-looking ingest candidate for ``path``; no parser is involved."""
    external = ProvenanceSource.EXTERNAL_METADATA
    return WorkCandidate(
        provenance=Provenance.system(actor="ingest", note=f"local file ingest: {path.name}"),
        metadata=CandidateMetadata(
            title=IdentifierField(value=title, source=external, confidence=0.8),
            authors=(IdentifierField(value="A. Researcher", source=external),),
            year=IdentifierField(value="2026", source=external),
            identifiers=WorkIdentifiers(
                doi=IdentifierField(value="10.1234/gate-p1", source=external)
            ),
        ),
        candidate_file_hash=artifact_hash(path.read_bytes()),
        original_filename=path.name,
    )


def make_evidence(
    registered: Registered,
    *,
    evidence_id: str = "E0001",
    origin: EvidenceOrigin = EvidenceOrigin.SOURCE_OBSERVED,
    tier: ReviewTier = ReviewTier.TIER_1,
    text: str = EXACT_TEXT,
) -> Evidence:
    """A proposed candidate anchored in the registered artifact."""
    return Evidence(
        id=EvidenceId(evidence_id),
        source=SourceAnchor(
            work=registered.work,
            version=registered.version,
            artifact=registered.artifact,
            file_hash=artifact_hash(),
            block=BlockId("B0007"),
            text_hash=f"sha256:{hashlib.sha256(text.encode()).hexdigest()}",
            page=3,
            section_path=("Experiments",),
            char_start=0,
            char_end=len(text),
        ),
        content=EvidenceContent(exact_text=text),
        origin=origin,
        evidence_type=EvidenceType.EXPERIMENTAL_SETUP,
        strength=EvidenceStrength.DIRECT,
        review_tier=tier,
        provenance=Provenance.model(MODEL_ACTOR),
    )


@pytest.fixture
def artifact_file(tmp_path: Path) -> Path:
    """A tiny file standing in for a source PDF; nothing ever parses it."""
    path = tmp_path / "source" / "paper.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ARTIFACT_BYTES)
    return path


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """An initialized workspace opened as the researcher."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="gate-p1"))
    yield open_context(result.root, HUMAN_ACTOR)


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    """A fake `codex` that probes clean; nothing here ever spawns the real one.

    A copy rather than an import: each suite's conftest stands on its own, and Gate P1
    must keep holding with no runtime installed at all.
    """
    from research_harness.providers.cli.detection import DEFAULT_CACHE

    DEFAULT_CACHE.clear()
    fake = FakeCli.install(
        tmp_path / "tools",
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[
            {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
            {
                "args": ["exec", "--help"],
                "stdout": (
                    "--sandbox --output-schema --json --ephemeral --skip-git-repo-check "
                    "--ignore-user-config --ignore-rules"
                ),
            },
            # An empty catalog, so the scan falls back to the runtime's declared models.
            {"args": ["debug", "models"], "stdout": "{}"},
        ],
        run={"lines": []},
    )
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return fake


@pytest.fixture
def registered(project: CapabilityContext, artifact_file: Path) -> Registered:
    """One Work, Version, and Artifact registered through the capability layer."""
    result = register_work(
        project,
        RegisterWorkRequest(
            candidate=make_candidate(artifact_file),
            artifact_path=artifact_file,
            version_kind=VersionKind.PREPRINT,
            version_label="v1",
            mime_type="application/pdf",
            artifact_kind=ArtifactKind.PDF,
        ),
    )
    work = project.repo.list_works()[0]
    assert result.validation.ok
    return Registered(work=work.id, version=work.versions[0], artifact=work.artifacts[0])
