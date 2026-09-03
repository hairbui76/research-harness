"""The offline demo loop: init → ingest → parse → interrogate → verify → rebuild."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    IngestLocalPdfRequest,
    InitProjectRequest,
    ParseWorkRequest,
)
from research_harness.capabilities.handlers import ingest_local_pdf, init_project, parse_work
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ReviewPolicy,
    VerificationVerdict,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import WorkId
from research_harness.evidence.staging import CandidateStatus, EvidenceCandidate, StagingStore
from research_harness.parsing.tables import cell_span
from research_harness.projection.rebuild import RebuildReport, rebuild_workspace
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.interrogate import run_interrogation
from research_harness.workflows.verify import run_verification
from research_harness.workspace.runs import RunStore

__all__ = ["DEMO_FIELDS", "DEMO_PDF", "DemoReport", "run_demo"]

DEMO_PDF = Path(__file__).with_name("synthetic_research_paper.pdf")
"""The bundled synthetic paper: sections, a results table, a caption, references."""

DEMO_FIELDS = ("dataset", "metric_result", "method_summary")
"""The default-schema fields the demo answers, in the order the workflow asks them."""

DATASET_SENTENCE = "All experiments use CICIDS2017"
METHOD_SENTENCE = "The encoder is a twelve layer transformer"
METRIC_VALUE = "94.32"


@dataclass(frozen=True)
class DemoReport:
    """What the demo produced, for the CLI to print and tests to assert on."""

    root: Path
    work: WorkId
    blocks: int
    pages: int
    staged: int
    verified: dict[str, str] = field(default_factory=dict)
    rebuild: RebuildReport | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "work": str(self.work),
            "blocks": self.blocks,
            "pages": self.pages,
            "staged": self.staged,
            "verified": dict(self.verified),
            "canonical_digest": self.rebuild.canonical_digest if self.rebuild else None,
        }


def run_demo(root: Path, *, name: str = "demo") -> DemoReport:
    """Build a workspace at ``root`` with three verified proposals waiting for review.

    Nothing is accepted: the researcher does that in the cockpit, the CLI, or an MCP host.
    """
    init_project(InitProjectRequest(root=root, name=name, policy=ReviewPolicy.STRICT))
    ctx = open_context(root)
    ingest = ingest_local_pdf(ctx, IngestLocalPdfRequest(path=DEMO_PDF))
    parsed = parse_work(ctx, ParseWorkRequest(work=ingest.work))
    document = parsed.document

    staging, engine = _runtime(ctx)
    extractor = ScriptedProvider([_extraction(document, field_name) for field_name in DEMO_FIELDS])
    interrogation = run_interrogation(
        engine, staging, ctx.repo, ingest.work, extractor, fields=DEMO_FIELDS
    )
    staged = sum(len(items) for items in interrogation.candidates_by_field.values())
    if staged != len(DEMO_FIELDS):
        raise ResearchHarnessError(
            f"demo staged {staged} candidates, expected {len(DEMO_FIELDS)}; "
            f"rejected: {[r.reason for r in interrogation.rejected]}"
        )

    pending = staging.list(work=ingest.work, status=CandidateStatus.PROPOSED)
    verifier = ScriptedProvider([_verification(candidate) for candidate in pending])
    verification = run_verification(engine, staging, ctx.repo, ingest.work, verifier)
    verified = {
        _field_of(staging, candidate_id): verdict.value
        for candidate_id, verdict in verification.verdicts.items()
    }
    rebuild = rebuild_workspace(ctx.repo)
    return DemoReport(
        root=root,
        work=ingest.work,
        blocks=len(document.blocks),
        pages=parsed.page_count,
        staged=staged,
        verified=verified,
        rebuild=rebuild,
    )


# -- scripted replies derived from the parsed document ------------------------


def _extraction(document: ParsedDocument, field_name: str) -> dict[str, Any]:
    """One `ExtractionOutput` for ``field_name``, anchored in the real parse."""
    if field_name == "dataset":
        block = _block_containing(document, DATASET_SENTENCE)
        candidate = _candidate(
            block,
            DATASET_SENTENCE,
            field_name,
            EvidenceType.DATASET_DESCRIPTION,
            rationale="The experiments section names the corpus.",
        )
    elif field_name == "metric_result":
        table = _table_containing(document, METRIC_VALUE)
        start, end = _cell_with(table, METRIC_VALUE)
        candidate = _candidate(
            table,
            table.text[start:end],
            field_name,
            EvidenceType.EXPERIMENTAL_RESULT,
            span=(start, end),
            numeric={
                "raw": METRIC_VALUE,
                "parsed": float(METRIC_VALUE),
                "unit": "percent",
                "metric": "F1",
                "dataset": "CICIDS2017",
                "condition": {"split": "held-out"},
                "source_table": "Table 1",
                "source_row": "TrafficLM",
                "source_column": "F1",
            },
            rationale="Row TrafficLM, column F1 of Table 1.",
        )
    elif field_name == "method_summary":
        block = _block_containing(document, METHOD_SENTENCE)
        candidate = _candidate(block, METHOD_SENTENCE, field_name, EvidenceType.METHOD_DESCRIPTION)
    else:  # pragma: no cover - DEMO_FIELDS is fixed
        raise ResearchHarnessError(f"the demo has no answer for field {field_name!r}")
    return {"candidates": [candidate], "fields_not_found": []}


def _verification(candidate: EvidenceCandidate) -> dict[str, Any]:
    """One `VerificationOutput`: supported where the span says it all, partial otherwise."""
    verdict = (
        VerificationVerdict.PARTIALLY_SUPPORTED
        if candidate.field == "method_summary"
        else VerificationVerdict.SUPPORTED
    )
    return {
        "verdict": verdict.value,
        "rationale": "Read the span and the blocks around it.",
        "quoted_support": candidate.evidence.content.exact_text,
        "discrepancies": (
            ["The sentence describes the encoder only, not the whole method."]
            if verdict is VerificationVerdict.PARTIALLY_SUPPORTED
            else []
        ),
    }


def _candidate(
    block: DocumentBlock,
    exact_text: str,
    field_name: str,
    evidence_type: EvidenceType,
    *,
    span: tuple[int, int] | None = None,
    numeric: dict[str, Any] | None = None,
    rationale: str | None = None,
) -> dict[str, Any]:
    start, end = span if span is not None else _span_of(block, exact_text)
    return {
        "block": str(block.id),
        "char_start": start,
        "char_end": end,
        "exact_text": exact_text,
        "field": field_name,
        "evidence_type": evidence_type.value,
        "origin": EvidenceOrigin.SOURCE_OBSERVED.value,
        "strength": EvidenceStrength.DIRECT.value,
        "numeric": numeric,
        "negative_state": None,
        "rationale": rationale,
        "page": block.page,
    }


def _block_containing(document: ParsedDocument, text: str) -> DocumentBlock:
    for block in document.blocks:
        if not block.cells and text in block.text:
            return block
    raise ResearchHarnessError(f"the bundled demo paper no longer contains {text!r}")


def _table_containing(document: ParsedDocument, text: str) -> DocumentBlock:
    for block in document.blocks:
        if block.cells and any(text == cell.text.strip() for cell in block.cells):
            return block
    raise ResearchHarnessError(f"the bundled demo paper has no table cell {text!r}")


def _cell_with(table: DocumentBlock, text: str) -> tuple[int, int]:
    for cell in table.cells:
        if cell.text.strip() == text:
            return cell_span(table, cell.row, cell.col)
    raise ResearchHarnessError(f"no cell {text!r} in {table.id}")  # pragma: no cover


def _span_of(block: DocumentBlock, text: str) -> tuple[int, int]:
    start = block.text.find(text)
    if start < 0:  # pragma: no cover - guarded by _block_containing
        raise ResearchHarnessError(f"{text!r} not in block {block.id}")
    return start, start + len(text)


def _runtime(ctx: CapabilityContext) -> tuple[StagingStore, WorkflowEngine]:
    research_dir = ctx.repo.layout.research_dir
    return StagingStore(research_dir), WorkflowEngine(RunStore(research_dir))


def _field_of(staging: StagingStore, candidate_id: str) -> str:
    return staging.get(candidate_id).field
