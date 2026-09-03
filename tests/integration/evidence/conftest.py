"""Fixtures for the evidence pipeline: one real parse, one real workspace, scripted models.

Everything is derived from `tests/fixtures/synthetic_research_paper.pdf` through the real
`PyMuPdfParser`, so block ids, character offsets, and table cell spans are the ones the
pipeline will actually see. Model answers are scripted, so a test asserts on what the
pipeline does with an answer rather than on what a model happens to say.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    ArtifactKind,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ResearchEventType,
    VersionKind,
)
from research_harness.domain.ids import ArtifactId, BlockId, VersionId, WorkId
from research_harness.domain.research import ResearchEvent
from research_harness.domain.work import Artifact, Version, Work
from research_harness.evidence.staging import StagingStore
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.parsing.tables import cell_span
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore

FIXTURE_PDF = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"
PDF_BYTES = FIXTURE_PDF.read_bytes()
FILE_HASH = f"sha256:{hashlib.sha256(PDF_BYTES).hexdigest()}"

WORK = WorkId("W0001")
VERSION = VersionId("V0001-1")
ARTIFACT = ArtifactId("A0001-1")
ACTOR = "human:tester"

#: Blocks the tests quote from, chosen because their content is fixed by the fixture.
DATASET_BLOCK = BlockId("B0017")
TABLE_BLOCK = BlockId("B0022")
LIMITATION_BLOCK = BlockId("B0026")
METHOD_BLOCK = BlockId("B0009")

DATASET_SENTENCE = "All experiments use CICIDS2017"


def parse_fixture() -> ParsedDocument:
    """The synthetic paper parsed by the real parser: the only source of block ids here."""
    target = ParseTarget(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=FILE_HASH,
        path=FIXTURE_PDF,
        mime_type="application/pdf",
    )
    return PyMuPdfParser().parse(target)


@pytest.fixture(scope="session")
def doc() -> ParsedDocument:
    return parse_fixture()


def block_of(document: ParsedDocument, block: BlockId) -> DocumentBlock:
    """One block by id; fails loudly rather than silently testing nothing."""
    for candidate in document.blocks:
        if candidate.id == block:
            return candidate
    raise AssertionError(f"fixture has no block {block}")


def span_of(document: ParsedDocument, block: BlockId, text: str) -> tuple[int, int]:
    """Offsets of `text` inside a block, so a test never hard-codes a character index."""
    body = block_of(document, block).text
    start = body.find(text)
    assert start >= 0, f"{text!r} does not occur in block {block}"
    return start, start + len(text)


# ------------------------------------------------------------------ model output builders


def candidate_dict(
    *,
    block: BlockId,
    char_start: int | None,
    char_end: int | None,
    exact_text: str,
    field: str,
    evidence_type: EvidenceType,
    origin: EvidenceOrigin = EvidenceOrigin.SOURCE_OBSERVED,
    strength: EvidenceStrength = EvidenceStrength.DIRECT,
    numeric: dict[str, Any] | None = None,
    negative_state: str | None = None,
    rationale: str | None = None,
    page: int | None = None,
) -> dict[str, Any]:
    """One `EvidenceCandidateOutput` as a model would emit it, as raw JSON-shaped data."""
    return {
        "block": str(block),
        "char_start": char_start,
        "char_end": char_end,
        "exact_text": exact_text,
        "field": field,
        "evidence_type": evidence_type.value,
        "origin": origin.value,
        "strength": strength.value,
        "numeric": numeric,
        "negative_state": negative_state,
        "rationale": rationale,
        "page": page,
    }


def extraction_dict(
    candidates: Sequence[dict[str, Any]] = (), fields_not_found: Sequence[str] = ()
) -> dict[str, Any]:
    """One `ExtractionOutput` payload."""
    return {"candidates": list(candidates), "fields_not_found": list(fields_not_found)}


def dataset_candidate(document: ParsedDocument, **overrides: Any) -> dict[str, Any]:
    """A correct proposal for the `dataset` field, quoting the CICIDS2017 sentence."""
    start, end = span_of(document, DATASET_BLOCK, DATASET_SENTENCE)
    payload = candidate_dict(
        block=DATASET_BLOCK,
        char_start=start,
        char_end=end,
        exact_text=DATASET_SENTENCE,
        field="dataset",
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
        page=block_of(document, DATASET_BLOCK).page,
        rationale="The experiments section names the corpus.",
    )
    return {**payload, **overrides}


def numeric_value(**overrides: Any) -> dict[str, Any]:
    """A `NumericValue` carrying the metric, dataset, and table a number needs (§12)."""
    payload: dict[str, Any] = {
        "raw": "94.32",
        "parsed": 94.32,
        "unit": "percent",
        "metric": "F1",
        "dataset": "CICIDS2017",
        "condition": {"split": "held-out"},
        "source_table": "Table 1",
        "source_row": "TrafficLM",
        "source_column": "F1",
    }
    return {**payload, **overrides}


def metric_candidate(document: ParsedDocument, **overrides: Any) -> dict[str, Any]:
    """A correct proposal for `metric_result`, anchored at the 94.32 table cell."""
    table = block_of(document, TABLE_BLOCK)
    start, end = cell_span(table, 1, 2)
    payload = candidate_dict(
        block=TABLE_BLOCK,
        char_start=start,
        char_end=end,
        exact_text=table.text[start:end],
        field="metric_result",
        evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
        numeric=numeric_value(),
        page=table.page,
        rationale="Row TrafficLM, column F1 of Table 1.",
    )
    return {**payload, **overrides}


def limitation_candidate(document: ParsedDocument, **overrides: Any) -> dict[str, Any]:
    """A correct proposal for `author_limitation`, quoting the authors' own caveat."""
    quoted = "We do not claim transfer to other networks"
    start, end = span_of(document, LIMITATION_BLOCK, quoted)
    payload = candidate_dict(
        block=LIMITATION_BLOCK,
        char_start=start,
        char_end=end,
        exact_text=quoted,
        field="author_limitation",
        evidence_type=EvidenceType.LIMITATION,
        origin=EvidenceOrigin.AUTHOR_CLAIMED,
        page=block_of(document, LIMITATION_BLOCK).page,
    )
    return {**payload, **overrides}


def method_candidate(document: ParsedDocument, **overrides: Any) -> dict[str, Any]:
    """A correct proposal for `method_summary`."""
    quoted = "The encoder is a twelve layer transformer"
    start, end = span_of(document, METHOD_BLOCK, quoted)
    payload = candidate_dict(
        block=METHOD_BLOCK,
        char_start=start,
        char_end=end,
        exact_text=quoted,
        field="method_summary",
        evidence_type=EvidenceType.METHOD_DESCRIPTION,
        page=block_of(document, METHOD_BLOCK).page,
    )
    return {**payload, **overrides}


# --------------------------------------------------------------------------- workspace


@pytest.fixture
def workspace(tmp_path: Path, doc: ParsedDocument) -> WorkspaceRepository:
    """An initialised workspace with the fixture ingested through real transactions.

    Written here rather than through the capability layer, which is being built in parallel;
    the point of the fixture is a workspace whose canonical tree is real.
    """
    repo = WorkspaceRepository.init(tmp_path / "project", "evidence-pipeline")
    work = Work(
        id=WORK,
        title="Deep Representations for Encrypted Network Traffic",
        authors=("A. Researcher", "B. Collaborator"),
        year=2024,
        versions=(VERSION,),
        artifacts=(ARTIFACT,),
        provenance=_system(),
    )
    version = Version(id=VERSION, work=WORK, kind=VersionKind.PREPRINT, provenance=_system())
    artifact = Artifact(
        id=ARTIFACT,
        work=WORK,
        version=VERSION,
        kind=ArtifactKind.PDF,
        file_hash=FILE_HASH,
        original_filename="synthetic_research_paper.pdf",
        mime_type="application/pdf",
        size_bytes=len(PDF_BYTES),
        provenance=_system(),
    )
    event = ResearchEvent(
        event=ResearchEventType.WORK_INGESTED,
        subjects=(WORK,),
        actor=ACTOR,
        summary="ingest the synthetic fixture",
    )
    with repo.transaction(event, actor=ACTOR) as tx:
        tx.put(work)
        tx.put(version)
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)
        tx.put_blocks(doc, work=WORK)
    return repo


@pytest.fixture
def staging(workspace: WorkspaceRepository) -> StagingStore:
    return StagingStore(workspace.layout.research_dir)


@pytest.fixture
def engine(workspace: WorkspaceRepository) -> WorkflowEngine:
    return WorkflowEngine(RunStore(workspace.layout.research_dir))


def _system() -> Any:
    from research_harness.domain.base import Provenance

    return Provenance.system(actor="test-fixture", workflow="ingest")


# ------------------------------------------------------------------- canonical tree state


def canonical_digest(root: Path) -> str:
    """A digest of every canonical file, ignoring regenerable `.research/` state.

    Used to assert the property the whole phase rests on: extraction and verification can
    fail, hallucinate, or be re-run, and the scientific record does not move.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".research":
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
