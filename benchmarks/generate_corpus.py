"""Deterministic synthetic workspace generator for the Task 17.3 benchmarks.

The corpus is built through the public :class:`WorkspaceRepository` transaction API only,
so every cost a real project pays -- schema validation, canonical YAML/JSONL, atomic
replace, fsync, the journal, and the semantic event log -- is paid here too. Nothing is
random at run time: a seed fixes the text, the structure, and every timestamp, so two runs
with the same seed produce byte-identical canonical files and comparable measurements.

Artifact bytes are tiny placeholders, never real PDFs: parsing is benchmarked elsewhere and
a synthetic corpus should not spend its time in a PDF library.

    uv run python -m benchmarks.generate_corpus --root /tmp/bench --scale 0.05
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from research_harness.domain import (
    Artifact,
    ArtifactId,
    ArtifactKind,
    BlockId,
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimEvidenceRelationType,
    ClaimId,
    ClaimScope,
    ClaimScopeSpec,
    ClaimSemantics,
    ClaimStatus,
    ClaimType,
    Coverage,
    Decision,
    DecisionId,
    DecisionStatus,
    DecisionType,
    DocumentBlock,
    DocumentBlockKind,
    Evidence,
    EvidenceContent,
    EvidenceId,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ManuscriptAnchor,
    MatrixCell,
    NumericValue,
    OverturnRisk,
    ParsedDocument,
    Provenance,
    QuestionId,
    ResearchEvent,
    ResearchEventType,
    ResearchQuestion,
    ReviewAction,
    ReviewTier,
    ScreeningState,
    SearchRun,
    SearchRunId,
    SourceAnchor,
    StaleState,
    SynthesisId,
    SynthesisMatrix,
    TableCell,
    Taxonomy,
    TaxonomyTerm,
    VerificationRecord,
    VerificationVerdict,
    Version,
    VersionId,
    VersionKind,
    Work,
    WorkId,
)
from research_harness.parsing.anchors import build_anchor
from research_harness.parsing.text import text_sha256
from research_harness.workspace.repository import WorkspaceRepository, WorkspaceTransaction

__all__ = [
    "BLOCKS_PER_WORK",
    "CLAIMS",
    "CLAIMS_PER_TRANSACTION",
    "DATASETS",
    "EVIDENCE_PER_WORK",
    "METRICS",
    "WORKS",
    "WORKS_PER_TRANSACTION",
    "GenerationReport",
    "WorkFacts",
    "generate_workspace",
    "main",
]

logger = logging.getLogger(__name__)

# --- target corpus (ROADMAP Task 17.3) --------------------------------------

WORKS = 1_000
BLOCKS_PER_WORK = 100
EVIDENCE_PER_WORK = 50
CLAIMS = 5_000
RELATIONS_PER_CLAIM = 3

WORKS_PER_TRANSACTION = 25
"""Works committed as one journalled unit.

Chosen against two ceilings rather than by taste. A transaction records one digest per
written object in its semantic event, and `workspace.events.MAX_EVENT_OBJECTS` caps that at
10,000: at 54 digests per work (work, version, artifact, block file, 50 evidence) the hard
ceiling is 185. The journal stages and fsyncs every file twice, so the per-transaction fixed
cost is amortized over 25 x 6 = 150 files while the staged payload stays around 10 MB.
"""

CLAIMS_PER_TRANSACTION = 250
"""Claims per journalled unit; a claim is one small file and one digest."""

ACTOR = "system:benchmark"
BENCH_TAXONOMY = "benchmark-taxonomy"
MANUSCRIPT_FILE = "manuscript/main.tex"

STALE_CLAIM_EVERY = 97
"""Every Nth claim is marked stale so the rebuild's stale set is not trivially empty."""

# --- vocabulary -------------------------------------------------------------

DATASETS: tuple[str, ...] = (
    "CICIDS2017",
    "UNSW-NB15",
    "CIC-DDoS2019",
    "ImageNet",
    "CIFAR-10",
    "SQuAD",
    "GLUE",
    "MS-MARCO",
    "WikiText-103",
    "LibriSpeech",
    "KITTI",
    "MIMIC-III",
)

METRICS: tuple[str, ...] = (
    "F1",
    "precision",
    "recall",
    "accuracy",
    "AUROC",
    "BLEU",
    "ROUGE-L",
    "perplexity",
    "mAP",
    "EER",
    "MRR",
    "nDCG",
)

_METHODS: tuple[str, ...] = (
    "the protocol-aware tokenizer",
    "our structured encoder",
    "the retrieval-augmented classifier",
    "a hierarchical attention model",
    "the byte-level transformer",
    "the graph neural detector",
    "the contrastive pretraining stage",
    "a sparse mixture-of-experts head",
)

_BASELINES: tuple[str, ...] = (
    "the flat-sequence baseline",
    "a bag-of-features classifier",
    "the published reference implementation",
    "an n-gram language model",
    "the unsupervised clustering baseline",
)

_CONCEPTS: tuple[str, ...] = (
    "traffic tokenization",
    "protocol field semantics",
    "representation granularity",
    "label noise",
    "distribution shift",
    "annotation agreement",
    "sampling bias",
    "calibration error",
    "inference latency",
    "memory footprint",
)

_SENTENCES: tuple[str, ...] = (
    "We evaluate {method} on {dataset} and report a {metric} of {value}.",
    "On {dataset}, {method} improves {metric} by {delta} points over {baseline}.",
    "The ablation isolates {concept} and shows that {metric} degrades to {value} on {dataset}.",
    "Unlike {baseline}, {method} preserves {concept} across the {dataset} splits.",
    "We attribute the remaining gap on {dataset} to {concept} rather than to model capacity.",
    "Following prior work, {metric} is computed on the held-out split of {dataset}.",
    "The reported {metric} of {value} is averaged over five seeds on {dataset}.",
    "{method} trades {metric} for a lower inference cost when {concept} is severe.",
    "We find no significant difference in {metric} between {method} and {baseline} on {dataset}.",
    "Because {concept} is not annotated in {dataset}, the {metric} figure is an upper bound.",
    "Practitioners should treat the {metric} numbers as comparable only within {dataset}.",
    "The results section reports {metric}, while the appendix records {concept} for completeness.",
)

_TITLE_HEADS: tuple[str, ...] = (
    "Structured representations for",
    "Rethinking",
    "On the limits of",
    "A systematic study of",
    "Efficient",
    "Robust",
    "Towards reproducible",
    "Measuring",
)

_TITLE_TAILS: tuple[str, ...] = (
    "protocol-aware detection",
    "long-context retrieval",
    "tabular result extraction",
    "cross-dataset generalization",
    "low-resource fine-tuning",
    "evidence-grounded summarization",
    "calibration under shift",
    "graph-structured inputs",
)

_SURNAMES: tuple[str, ...] = (
    "Adeyemi",
    "Bhattacharya",
    "Costa",
    "Dubois",
    "Eriksson",
    "Fujimoto",
    "Gutierrez",
    "Haddad",
    "Ivanova",
    "Jansen",
    "Kowalski",
    "Lindqvist",
    "Moreau",
    "Nakamura",
    "Okonkwo",
    "Petrov",
    "Quintero",
    "Rasmussen",
    "Silva",
    "Tanaka",
    "Ueda",
    "Vasquez",
    "Weber",
    "Yildirim",
)

_VENUES: tuple[str, ...] = (
    "Proceedings of the Synthetic Systems Conference",
    "Journal of Reproducible Measurement",
    "Workshop on Structured Representations",
    "Transactions on Applied Detection",
    "Symposium on Evidence and Provenance",
)

#: Heading path of every section a synthetic paper carries, in document order.
_SECTION_PLAN: tuple[tuple[str, ...], ...] = (
    ("Abstract",),
    ("Introduction",),
    ("Related Work",),
    ("Method",),
    ("Method", "Architecture"),
    ("Experiments",),
    ("Experiments", "Dataset"),
    ("Experiments", "Setup"),
    ("Results",),
    ("Results", "Ablations"),
    ("Discussion",),
    ("Conclusion",),
    ("References",),
)

_BLOCKS_PER_PAGE = 6

# --- deterministic clock ----------------------------------------------------

_EPOCH = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
_PHASE_SECONDS = 10_000_000


class _Phase:
    """Generation phases, ordered so no object is ever older than what it depends on.

    `projection.rebuild` derives staleness by comparing an object's ``updated_at`` with its
    upstream's, so a corpus written in dependency order starts out fresh and any stale mark
    in a benchmark comes from a deliberately stale field, not from generation order.
    """

    WORK = 0
    VERSION = 1
    ARTIFACT = 2
    BLOCKS = 3
    EVIDENCE = 4
    SEARCH_RUN = 5
    DECISION = 6
    TAXONOMY = 7
    MATRIX = 8
    CLAIM = 9
    QUESTION = 10
    ANCHOR = 11
    EVENT = 12


def _moment(phase: int, index: int = 0) -> datetime:
    """A deterministic timestamp inside ``phase``; later phases are always later."""
    return _EPOCH + timedelta(seconds=phase * _PHASE_SECONDS + index)


# --- reports ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkFacts:
    """What later phases need to know about one generated Work."""

    work: WorkId
    version: VersionId
    artifact: ArtifactId
    authors: tuple[str, ...]
    year: int
    evidence: tuple[EvidenceId, ...]
    numeric_evidence: tuple[EvidenceId, ...]
    blocks: int


@dataclass(frozen=True, slots=True)
class GenerationReport:
    """Everything one generation produced, plus how long it took and how big it is."""

    root: str
    seed: int
    scale: float
    works: int
    versions: int
    artifacts: int
    blocks: int
    evidence: int
    claims: int
    claim_relations: int
    decisions: int
    taxonomies: int
    matrices: int
    matrix_cells: int
    questions: int
    search_runs: int
    manuscript_anchors: int
    events: int
    transactions: int
    works_per_transaction: int
    claims_per_transaction: int
    duration_s: float
    canonical_bytes: int
    event_log_bytes: int

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return asdict(self)

    def summary(self) -> str:
        """One line for a terminal or a log."""
        return (
            f"{self.works} works, {self.blocks} blocks, {self.evidence} evidence, "
            f"{self.claims} claims in {self.transactions} transactions "
            f"({self.duration_s:.1f}s, {self.canonical_bytes / 1e6:.1f} MB canonical)"
        )


# --- text -------------------------------------------------------------------


def _sentence(rng: random.Random) -> str:
    """One pseudo-scientific sentence carrying at least one dataset or metric name."""
    return rng.choice(_SENTENCES).format(
        method=rng.choice(_METHODS),
        baseline=rng.choice(_BASELINES),
        dataset=rng.choice(DATASETS),
        metric=rng.choice(METRICS),
        concept=rng.choice(_CONCEPTS),
        value=f"{rng.uniform(40.0, 99.4):.2f}",
        delta=f"{rng.uniform(0.3, 8.9):.1f}",
    )


def _paragraph(rng: random.Random, *, min_words: int = 40, max_words: int = 120) -> str:
    """A paragraph of ``min_words``..``max_words`` words built from whole sentences."""
    target = rng.randint(min_words, max_words)
    parts: list[str] = []
    words = 0
    while words < target:
        sentence = _sentence(rng)
        parts.append(sentence)
        words += len(sentence.split())
    return " ".join(parts)


def _title(rng: random.Random) -> str:
    return f"{rng.choice(_TITLE_HEADS)} {rng.choice(_TITLE_TAILS)}"


def _authors(rng: random.Random) -> tuple[str, ...]:
    """Two to five surnames; overlapping author sets are what independence accounting reads."""
    count = rng.randint(2, 5)
    picked = rng.sample(_SURNAMES, count)
    return tuple(f"{chr(ord('A') + index)}. {surname}" for index, surname in enumerate(picked))


def _reference_line(rng: random.Random) -> str:
    surname = rng.choice(_SURNAMES)
    year = rng.randint(2015, 2026)
    return f"{surname} et al. {_title(rng)}. {rng.choice(_VENUES)}, {year}."


# --- blocks -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _BlockBudget:
    """How many blocks of each kind one synthetic paper carries."""

    sections: int
    paragraphs: int
    tables: int
    figures: int
    references: int

    @property
    def total(self) -> int:
        return self.sections + self.paragraphs + 2 * self.tables + self.figures + self.references


def _budget(blocks_per_work: int) -> _BlockBudget:
    """Split a block budget into a realistic paragraph/table/caption/reference mix."""
    sections = min(len(_SECTION_PLAN), max(1, blocks_per_work // 4))
    remaining = max(0, blocks_per_work - sections)
    references = remaining * 4 // 25
    tables = max(1, remaining // 25) if remaining >= 6 else 0
    figures = max(1, remaining // 25) if remaining >= 6 else 0
    paragraphs = remaining - references - 2 * tables - figures
    while paragraphs < 0 and tables > 0:
        tables -= 1
        paragraphs += 2
    return _BlockBudget(
        sections=sections,
        paragraphs=max(0, paragraphs),
        tables=tables,
        figures=figures,
        references=references,
    )


def _table_text(rng: random.Random, cells: Sequence[TableCell]) -> str:
    """Flattened table text; the metric names inside it are what FTS matches."""
    del rng
    rows: dict[int, list[str]] = {}
    for cell in cells:
        rows.setdefault(cell.row, []).append(cell.text)
    return " ; ".join(" | ".join(values) for _, values in sorted(rows.items()))


def _table_cells(rng: random.Random) -> tuple[TableCell, ...]:
    """A small results table: one header row plus three system rows."""
    metrics = rng.sample(METRICS, 3)
    dataset = rng.choice(DATASETS)
    systems = [rng.choice(_BASELINES), rng.choice(_BASELINES), rng.choice(_METHODS)]
    cells: list[TableCell] = [TableCell(row=0, col=0, text=f"System ({dataset})")]
    cells.extend(TableCell(row=0, col=1 + i, text=metric) for i, metric in enumerate(metrics))
    for row, system in enumerate(systems, start=1):
        cells.append(TableCell(row=row, col=0, text=system))
        cells.extend(
            TableCell(row=row, col=1 + i, text=f"{rng.uniform(40.0, 99.4):.2f}")
            for i in range(len(metrics))
        )
    return tuple(cells)


class _BlockBuilder:
    """Allocates ids and accumulates the blocks of one artifact in document order."""

    def __init__(
        self,
        tx: WorkspaceTransaction,
        *,
        work: WorkId,
        version: VersionId,
        artifact: ArtifactId,
        stamp: datetime,
        provenance: Provenance,
    ) -> None:
        self._tx = tx
        self._work = work
        self._version = version
        self._artifact = artifact
        self._stamp = stamp
        self._provenance = provenance
        self.blocks: list[DocumentBlock] = []

    def add(
        self,
        kind: DocumentBlockKind,
        text: str,
        section_path: tuple[str, ...],
        *,
        cells: tuple[TableCell, ...] = (),
        caption: str | None = None,
        caption_for: BlockId | None = None,
        reference_key: str | None = None,
        reference_raw: str | None = None,
    ) -> DocumentBlock:
        order = len(self.blocks)
        block = DocumentBlock(
            id=self._tx.allocate_id(BlockId),
            work=self._work,
            version=self._version,
            artifact=self._artifact,
            kind=kind,
            page=1 + order // _BLOCKS_PER_PAGE,
            order=order,
            text=text,
            text_hash=text_sha256(text),
            section_path=section_path,
            cells=cells,
            caption=caption,
            caption_for=caption_for,
            reference_key=reference_key,
            reference_raw=reference_raw,
            created_at=self._stamp,
            updated_at=self._stamp,
            provenance=self._provenance,
        )
        self.blocks.append(block)
        return block


def _build_blocks(
    builder: _BlockBuilder, rng: random.Random, budget: _BlockBudget
) -> list[DocumentBlock]:
    """Sections, then paragraphs/tables/figures spread across them, then references."""
    plan = _SECTION_PLAN[: budget.sections]
    body = [path for path in plan if path[0] != "References"] or [plan[0]]
    per_section = [budget.paragraphs // len(body)] * len(body)
    for index in range(budget.paragraphs % len(body)):
        per_section[index] += 1
    table_slots = {body[(index * 3 + 5) % len(body)] for index in range(budget.tables)}
    figure_slots = {body[(index * 3 + 2) % len(body)] for index in range(budget.figures)}

    tables_left, figures_left = budget.tables, budget.figures
    for position, path in enumerate(plan):
        builder.add(DocumentBlockKind.SECTION, path[-1], path)
        if path[0] == "References":
            continue
        index = body.index(path) if path in body else 0
        for _ in range(per_section[index] if path in body else 0):
            builder.add(DocumentBlockKind.PARAGRAPH, _paragraph(rng), path)
        if tables_left and path in table_slots:
            tables_left -= 1
            cells = _table_cells(rng)
            table = builder.add(DocumentBlockKind.TABLE, _table_text(rng, cells), path, cells=cells)
            builder.add(
                DocumentBlockKind.TABLE_CAPTION,
                f"Table {position}: {_sentence(rng)}",
                path,
                caption_for=table.id,
            )
        if figures_left and path in figure_slots:
            figures_left -= 1
            builder.add(
                DocumentBlockKind.FIGURE_CAPTION, f"Figure {position}: {_sentence(rng)}", path
            )

    references = ("References",)
    for number in range(budget.references):
        builder.add(
            DocumentBlockKind.REFERENCE,
            _reference_line(rng),
            references,
            reference_key=f"ref{number:03d}",
            reference_raw=_reference_line(rng),
        )
    return builder.blocks


# --- evidence ---------------------------------------------------------------


def _accepted(rng: random.Random) -> VerificationRecord:
    return VerificationRecord(
        status=EvidenceStatus.ACCEPTED,
        verdict=VerificationVerdict.SUPPORTED,
        extractor="vendor-a/model-x",
        verifier="vendor-b/model-y",
        accepted_by="human:benchmark",
        review_action=rng.choice([ReviewAction.ACCEPT, ReviewAction.ACCEPT_WITH_QUALIFICATION]),
        rationale="synthetic corpus: accepted by construction",
        reviewed_at=_moment(_Phase.EVIDENCE),
    )


def _numeric_value(rng: random.Random, block: DocumentBlock) -> NumericValue:
    """A measured value whose table provenance points at the block it was read from."""
    metric = rng.choice(METRICS)
    parsed = round(rng.uniform(40.0, 99.4), 2)
    return NumericValue(
        raw=f"{parsed:.2f}",
        parsed=parsed,
        unit="percent",
        metric=metric,
        dataset=rng.choice(DATASETS),
        condition={"split": rng.choice(["test", "dev", "held-out"])},
        source_table=str(block.id),
        source_row=rng.choice(["ours", "baseline", "prior work"]),
        source_column=metric,
    )


def _span(rng: random.Random, block: DocumentBlock) -> tuple[int, int]:
    """A character span inside ``block`` that starts and ends on a word boundary."""
    text = block.text
    if len(text) <= 60:
        return 0, len(text)
    start = rng.randrange(0, max(1, len(text) - 60))
    start = text.rfind(" ", 0, start) + 1
    end = text.find(" ", min(len(text) - 1, start + rng.randint(40, 200)))
    return start, len(text) if end <= start else end


def _evidence_for_work(
    tx: WorkspaceTransaction,
    rng: random.Random,
    doc: ParsedDocument,
    *,
    count: int,
    provenance: Provenance,
) -> tuple[list[Evidence], list[EvidenceId]]:
    """Accepted evidence anchored into ``doc``; one in five is numeric table evidence."""
    paragraphs = [b for b in doc.blocks if b.kind is DocumentBlockKind.PARAGRAPH]
    tables = [b for b in doc.blocks if b.kind is DocumentBlockKind.TABLE]
    stamp = _moment(_Phase.EVIDENCE)
    records: list[Evidence] = []
    numeric_ids: list[EvidenceId] = []
    for index in range(count):
        numeric = bool(tables) and index % 5 == 0
        pool = tables if numeric else (paragraphs or doc.blocks)
        block = pool[index % len(pool)]
        start, end = _span(rng, block)
        anchor: SourceAnchor = build_anchor(doc, block, start, end)
        evidence_id = tx.allocate_id(EvidenceId)
        content = EvidenceContent(
            exact_text=block.text[start:end],
            numeric=_numeric_value(rng, block) if numeric else None,
            field="reported_metric" if numeric else "method_summary",
        )
        records.append(
            Evidence(
                id=evidence_id,
                source=anchor,
                content=content,
                origin=EvidenceOrigin.SOURCE_OBSERVED,
                evidence_type=(
                    EvidenceType.EXPERIMENTAL_RESULT if numeric else EvidenceType.METHOD_DESCRIPTION
                ),
                strength=EvidenceStrength.DIRECT,
                verification=_accepted(rng),
                review_tier=ReviewTier.TIER_1,
                created_at=stamp,
                updated_at=stamp,
                provenance=provenance,
            )
        )
        if numeric:
            numeric_ids.append(evidence_id)
    return records, numeric_ids


# --- phases -----------------------------------------------------------------


def _event(
    kind: ResearchEventType, summary: str, subjects: Sequence[Any], index: int
) -> ResearchEvent:
    return ResearchEvent(
        event=kind,
        subjects=tuple(subjects[:8]),
        actor=ACTOR,
        occurred_at=_moment(_Phase.EVENT, index),
        summary=summary,
    )


def _generate_one_work(
    tx: WorkspaceTransaction,
    rng: random.Random,
    *,
    blocks_per_work: int,
    evidence_per_work: int,
) -> WorkFacts:
    """Work, Version, Artifact, placeholder bytes, parsed blocks, and accepted evidence."""
    provenance = Provenance.system(actor="benchmark-generator")
    work_id = tx.allocate_id(WorkId)
    version_id = tx.allocate_id(VersionId, work=work_id)
    artifact_id = tx.allocate_id(ArtifactId, work=work_id)
    authors = _authors(rng)
    year = rng.randint(2018, 2026)

    payload = f"%PDF-1.7 synthetic benchmark placeholder for {artifact_id}\n".encode()
    file_hash = f"sha256:{hashlib.sha256(payload).hexdigest()}"

    tx.put(
        Work(
            id=work_id,
            title=_title(rng),
            authors=authors,
            year=year,
            venue=rng.choice(_VENUES),
            screening=ScreeningState.INCLUDED,
            versions=(version_id,),
            artifacts=(artifact_id,),
            created_at=_moment(_Phase.WORK),
            updated_at=_moment(_Phase.WORK),
            provenance=provenance,
        )
    )
    tx.put(
        Version(
            id=version_id,
            work=work_id,
            kind=VersionKind.ARXIV,
            label="v1",
            created_at=_moment(_Phase.VERSION),
            updated_at=_moment(_Phase.VERSION),
            provenance=provenance,
        )
    )
    artifact = Artifact(
        id=artifact_id,
        work=work_id,
        version=version_id,
        kind=ArtifactKind.PDF,
        file_hash=file_hash,
        original_filename=f"{artifact_id}.pdf",
        mime_type="application/pdf",
        size_bytes=len(payload),
        ingested_at=_moment(_Phase.ARTIFACT),
        created_at=_moment(_Phase.ARTIFACT),
        updated_at=_moment(_Phase.ARTIFACT),
        provenance=provenance,
    )
    tx.put(artifact)
    tx.store_artifact_bytes(artifact, payload)

    builder = _BlockBuilder(
        tx,
        work=work_id,
        version=version_id,
        artifact=artifact_id,
        stamp=_moment(_Phase.BLOCKS),
        provenance=provenance,
    )
    blocks = _build_blocks(builder, rng, _budget(blocks_per_work))
    document = ParsedDocument(
        work=work_id,
        version=version_id,
        artifact=artifact_id,
        file_hash=file_hash,
        parser_name="benchmark-generator",
        parser_version="1",
        page_count=max(block.page for block in blocks),
        blocks=tuple(blocks),
        parsed_at=_moment(_Phase.BLOCKS),
        created_at=_moment(_Phase.BLOCKS),
        updated_at=_moment(_Phase.BLOCKS),
        provenance=provenance,
    )
    tx.put_blocks(document, work=work_id)

    records, numeric_ids = _evidence_for_work(
        tx, rng, document, count=evidence_per_work, provenance=Provenance.model("vendor-a/model-x")
    )
    for record in records:
        tx.append_evidence(record)

    return WorkFacts(
        work=work_id,
        version=version_id,
        artifact=artifact_id,
        authors=authors,
        year=year,
        evidence=tuple(record.id for record in records),
        numeric_evidence=tuple(numeric_ids),
        blocks=len(blocks),
    )


def _generate_corpus(
    repo: WorkspaceRepository,
    *,
    works: int,
    blocks_per_work: int,
    evidence_per_work: int,
    seed: int,
    batch: int,
) -> tuple[list[WorkFacts], int]:
    """Every Work, in transactions of ``batch`` works; returns the facts and the tx count."""
    facts: list[WorkFacts] = []
    transactions = 0
    for start in range(0, works, batch):
        size = min(batch, works - start)
        event = _event(
            ResearchEventType.WORK_INGESTED,
            f"ingested synthetic works {start + 1}..{start + size}",
            [],
            start,
        )
        with repo.transaction(event, actor=ACTOR) as tx:
            for offset in range(size):
                rng = random.Random(seed * 1_000_003 + start + offset)
                facts.append(
                    _generate_one_work(
                        tx,
                        rng,
                        blocks_per_work=blocks_per_work,
                        evidence_per_work=evidence_per_work,
                    )
                )
        transactions += 1
        logger.info("generated %d/%d works", start + size, works)
    return facts, transactions


def _generate_searches(repo: WorkspaceRepository, count: int) -> list[SearchRunId]:
    """Search runs a claim's coverage can point at; no candidates, so no funnel to satisfy."""
    provenance = Provenance.system(actor="benchmark-generator")
    runs: list[SearchRunId] = []
    event = _event(ResearchEventType.SEARCH_RUN_RECORDED, f"recorded {count} search runs", [], 0)
    with repo.transaction(event, actor=ACTOR) as tx:
        for index in range(count):
            run_id = tx.allocate_id(SearchRunId)
            tx.put(
                SearchRun(
                    id=run_id,
                    question=f"benchmark discovery sweep {index}",
                    sources=("semantic_scholar", "openalex"),
                    queries=(f"{DATASETS[index % len(DATASETS)]} {METRICS[index % len(METRICS)]}",),
                    executed_at=_moment(_Phase.SEARCH_RUN, index),
                    created_at=_moment(_Phase.SEARCH_RUN, index),
                    updated_at=_moment(_Phase.SEARCH_RUN, index),
                    provenance=provenance,
                )
            )
            runs.append(run_id)
    return runs


def _generate_taxonomy(
    repo: WorkspaceRepository, *, terms: int
) -> tuple[list[DecisionId], list[str]]:
    """One taxonomy whose terms are each approved by a Decision: the graph's deep root."""
    provenance = Provenance.human(actor="human:benchmark")
    names = [f"{concept.replace(' ', '-')}" for concept in _CONCEPTS][:terms]
    decisions: list[DecisionId] = []
    event = _event(
        ResearchEventType.TAXONOMY_REVISED, f"approved {len(names)} taxonomy terms", [], 0
    )
    with repo.transaction(event, actor=ACTOR) as tx:
        approved: list[TaxonomyTerm] = []
        for index, name in enumerate(names):
            decision_id = tx.allocate_id(DecisionId)
            tx.put(
                Decision(
                    id=decision_id,
                    type=DecisionType.TAXONOMY_REVISION,
                    status=DecisionStatus.ACCEPTED,
                    title=f"approve taxonomy term {name}",
                    rationale=f"The corpus separates {name} from adjacent concepts.",
                    taxonomy_terms=(name,),
                    created_at=_moment(_Phase.DECISION, index),
                    updated_at=_moment(_Phase.DECISION, index),
                    provenance=provenance,
                )
            )
            decisions.append(decision_id)
            approved.append(
                TaxonomyTerm(
                    term=name,
                    definition=f"Project-approved reading of {name.replace('-', ' ')}.",
                    decision=decision_id,
                )
            )
        tx.put(
            Taxonomy(
                name=BENCH_TAXONOMY,
                terms=tuple(approved),
                created_at=_moment(_Phase.TAXONOMY),
                updated_at=_moment(_Phase.TAXONOMY),
                provenance=provenance,
            )
        )
    return decisions, names


def _generate_matrices(
    repo: WorkspaceRepository,
    facts: Sequence[WorkFacts],
    terms: Sequence[str],
    *,
    count: int,
    works_per_matrix: int,
) -> tuple[list[SynthesisId], int]:
    """Synthesis matrices over the taxonomy, with cells citing accepted evidence."""
    provenance = Provenance.human(actor="human:benchmark")
    fields = tuple(terms[:4]) or ("field",)
    matrices: list[SynthesisId] = []
    cells_written = 0
    event = _event(ResearchEventType.MATRIX_BUILT, f"built {count} synthesis matrices", [], 0)
    with repo.transaction(event, actor=ACTOR) as tx:
        for index in range(count):
            start = (index * works_per_matrix) % max(1, len(facts))
            rows = list(facts[start : start + works_per_matrix]) or list(facts[:1])
            cells = tuple(
                MatrixCell(
                    work=row.work,
                    field=field,
                    labels=(terms[(position + offset) % len(terms)],) if terms else (),
                    evidence=row.evidence[:2],
                )
                for position, row in enumerate(rows)
                for offset, field in enumerate(fields)
            )
            matrix_id = tx.allocate_id(SynthesisId)
            tx.put(
                SynthesisMatrix(
                    id=matrix_id,
                    name=f"benchmark matrix {index}",
                    taxonomy=BENCH_TAXONOMY,
                    works=tuple(row.work for row in rows),
                    fields=fields,
                    cells=cells,
                    created_at=_moment(_Phase.MATRIX, index),
                    updated_at=_moment(_Phase.MATRIX, index),
                    provenance=provenance,
                )
            )
            matrices.append(matrix_id)
            cells_written += len(cells)
    return matrices, cells_written


def _claim_for(
    claim_id: ClaimId,
    rng: random.Random,
    index: int,
    *,
    facts: Sequence[WorkFacts],
    runs: Sequence[SearchRunId],
    matrices: Sequence[SynthesisId],
    decisions: Sequence[DecisionId],
    relations_per_claim: int,
) -> Claim:
    """One claim whose relations reach across several Works, so the graph is not a forest."""
    relations: list[ClaimEvidenceRelation] = []
    kinds = (
        ClaimEvidenceRelationType.SUPPORTS,
        ClaimEvidenceRelationType.QUALIFIES,
        ClaimEvidenceRelationType.CONTRADICTS,
    )
    for position in range(relations_per_claim):
        source = facts[(index * 7 + position * 13) % len(facts)]
        if not source.evidence:
            continue
        relations.append(
            ClaimEvidenceRelation(
                evidence=source.evidence[(index + position) % len(source.evidence)],
                relation=kinds[position % len(kinds)] if position else kinds[0],
                aspect=None if position % 2 else rng.choice(_CONCEPTS),
            )
        )
    supporting_works = max(1, sum(1 for link in relations if link.relation is kinds[0]))
    requested = rng.choice(
        [ClaimScope.OBSERVED_SUBSET, ClaimScope.CORPUS_PATTERN, ClaimScope.FIELD_GENERALIZATION]
    )
    stamp = _moment(_Phase.CLAIM, index)
    return Claim(
        id=claim_id,
        statement=f"{_sentence(rng)} ({claim_id})",
        type=rng.choice([ClaimType.DESCRIPTIVE, ClaimType.COMPARATIVE, ClaimType.PREVALENCE]),
        semantics=ClaimSemantics(
            subject=rng.choice(_METHODS),
            predicate=rng.choice(["improves", "preserves", "degrades", "matches"]),
            object=rng.choice(_CONCEPTS),
            qualifier={"dataset": rng.choice(DATASETS), "metric": rng.choice(METRICS)},
        ),
        scope=ClaimScopeSpec(
            level=requested, corpus="benchmark-corpus", publication_until="2026-08"
        ),
        relations=tuple(relations),
        coverage=Coverage(
            relevant_works=len(facts),
            examined_works=max(supporting_works, int(len(facts) * 0.6)),
            unresolved_works=max(0, int(len(facts) * 0.1)),
            overturn_risk=OverturnRisk.LOW_MODERATE,
            search_runs=(runs[index % len(runs)],) if runs else (),
        ),
        assessment=ClaimAssessment(
            requested_strength=requested,
            allowed_strength=ClaimScope.INDIVIDUAL,
            status=ClaimStatus.UNVERIFIED,
        ),
        decisions=(decisions[index % len(decisions)],) if decisions else (),
        derived_from=(matrices[index % len(matrices)],) if matrices and index % 4 == 0 else (),
        stale=StaleState.STALE if index % STALE_CLAIM_EVERY == 0 else StaleState.FRESH,
        created_at=stamp,
        updated_at=stamp,
        provenance=Provenance.human(actor="human:benchmark"),
    )


def _generate_claims(
    repo: WorkspaceRepository,
    facts: Sequence[WorkFacts],
    *,
    claims: int,
    relations_per_claim: int,
    runs: Sequence[SearchRunId],
    matrices: Sequence[SynthesisId],
    decisions: Sequence[DecisionId],
    seed: int,
    batch: int,
) -> tuple[list[ClaimId], int, int]:
    """Claims in transactions of ``batch``; returns the ids, relation count, and tx count."""
    written: list[ClaimId] = []
    relations = 0
    transactions = 0
    for start in range(0, claims, batch):
        size = min(batch, claims - start)
        event = _event(
            ResearchEventType.CLAIM_CREATED,
            f"created synthetic claims {start + 1}..{start + size}",
            [],
            start,
        )
        with repo.transaction(event, actor=ACTOR) as tx:
            for offset in range(size):
                index = start + offset
                claim = _claim_for(
                    tx.allocate_id(ClaimId),
                    random.Random(seed * 7_919 + index),
                    index,
                    facts=facts,
                    runs=runs,
                    matrices=matrices,
                    decisions=decisions,
                    relations_per_claim=relations_per_claim,
                )
                tx.put(claim)
                written.append(claim.id)
                relations += len(claim.relations)
        transactions += 1
    return written, relations, transactions


def _generate_questions(
    repo: WorkspaceRepository,
    claims: Sequence[ClaimId],
    facts: Sequence[WorkFacts],
    runs: Sequence[SearchRunId],
    *,
    count: int,
    claims_per_question: int,
) -> int:
    """Research questions linking claims and evidence, so the graph has another sink."""
    provenance = Provenance.human(actor="human:benchmark")
    event = _event(ResearchEventType.QUESTION_CREATED, f"opened {count} research questions", [], 0)
    with repo.transaction(event, actor=ACTOR) as tx:
        for index in range(count):
            start = (index * claims_per_question) % max(1, len(claims))
            linked = tuple(claims[start : start + claims_per_question])
            source = facts[index % len(facts)] if facts else None
            question_id: QuestionId = tx.allocate_id(QuestionId)
            tx.put(
                ResearchQuestion(
                    id=question_id,
                    question=(
                        f"What does the corpus support about {_CONCEPTS[index % len(_CONCEPTS)]}?"
                    ),
                    claims=linked,
                    search_runs=(runs[index % len(runs)],) if runs else (),
                    supporting_evidence=source.evidence[:3] if source else (),
                    remaining_uncertainty="Synthetic question generated for benchmarking.",
                    created_at=_moment(_Phase.QUESTION, index),
                    updated_at=_moment(_Phase.QUESTION, index),
                    provenance=provenance,
                )
            )
    return count


def _generate_anchors(repo: WorkspaceRepository, claims: Sequence[ClaimId], *, count: int) -> int:
    """Manuscript anchors: the downstream end of the dependency chain (Product 30)."""
    provenance = Provenance.human(actor="human:benchmark")
    event = _event(
        ResearchEventType.MANUSCRIPT_CLAIM_ATTACHED, f"attached {count} manuscript anchors", [], 0
    )
    with repo.transaction(event, actor=ACTOR) as tx:
        for index in range(count):
            sentence = (
                f"Sentence {index} asserts the claim recorded as {claims[index % len(claims)]}."
            )
            line = 1 + index * 2
            tx.put(
                ManuscriptAnchor(
                    file=MANUSCRIPT_FILE,
                    line_start=line,
                    line_end=line,
                    char_start=0,
                    char_end=len(sentence),
                    sentence=sentence,
                    sentence_fingerprint=text_sha256(sentence),
                    claim=claims[index % len(claims)],
                    citation_keys=(f"ref{index % 50:03d}",),
                    created_at=_moment(_Phase.ANCHOR, index),
                    updated_at=_moment(_Phase.ANCHOR, index),
                    provenance=provenance,
                )
            )
    return count


# --- sizing -----------------------------------------------------------------


def _tree_bytes(root: Path, *, skip: str = ".research") -> int:
    """Bytes of canonical state under ``root``, ignoring regenerable projections."""
    total = 0
    for path in root.rglob("*"):
        if skip in path.parts or not path.is_file():
            continue
        total += path.stat().st_size
    return total


# --- entry point ------------------------------------------------------------


def generate_workspace(
    root: Path,
    *,
    works: int = WORKS,
    blocks_per_work: int = BLOCKS_PER_WORK,
    evidence_per_work: int = EVIDENCE_PER_WORK,
    claims: int = CLAIMS,
    relations_per_claim: int = RELATIONS_PER_CLAIM,
    seed: int = 7,
    scale: float = 1.0,
    works_per_transaction: int = WORKS_PER_TRANSACTION,
    claims_per_transaction: int = CLAIMS_PER_TRANSACTION,
) -> GenerationReport:
    """Create a synthetic workspace at ``root`` and report what it contains.

    ``scale`` multiplies the Work and Claim counts (``0.05`` gives the 50-work quick run);
    per-work density stays fixed so block and evidence totals scale with it. The result is
    deterministic for a seed: same text, same structure, same timestamps, same ids.
    """
    started = time.perf_counter()
    target = Path(root)
    work_count = max(1, round(works * scale))
    claim_count = max(1, round(claims * scale))

    repo = WorkspaceRepository.init(target, f"benchmark-{work_count}w")
    facts, work_transactions = _generate_corpus(
        repo,
        works=work_count,
        blocks_per_work=blocks_per_work,
        evidence_per_work=evidence_per_work,
        seed=seed,
        batch=max(1, works_per_transaction),
    )

    search_count = max(2, min(20, work_count // 40 + 2))
    runs = _generate_searches(repo, search_count)
    decisions, terms = _generate_taxonomy(repo, terms=len(_CONCEPTS))
    matrix_count = max(1, min(12, work_count // 80 + 1))
    matrices, matrix_cells = _generate_matrices(
        repo,
        facts,
        terms,
        count=matrix_count,
        works_per_matrix=max(2, min(25, work_count // 8 or 2)),
    )
    claim_ids, relations, claim_transactions = _generate_claims(
        repo,
        facts,
        claims=claim_count,
        relations_per_claim=relations_per_claim,
        runs=runs,
        matrices=matrices,
        decisions=decisions,
        seed=seed,
        batch=max(1, claims_per_transaction),
    )
    question_count = max(2, min(40, claim_count // 100 + 2))
    _generate_questions(
        repo,
        claim_ids,
        facts,
        runs,
        count=question_count,
        claims_per_question=max(1, claim_count // max(1, question_count)),
    )
    anchor_count = max(4, min(500, claim_count // 10))
    _generate_anchors(repo, claim_ids, count=anchor_count)

    transactions = work_transactions + claim_transactions + 5
    events_file = repo.layout.events_file
    return GenerationReport(
        root=str(target),
        seed=seed,
        scale=scale,
        works=len(facts),
        versions=len(facts),
        artifacts=len(facts),
        blocks=sum(item.blocks for item in facts),
        evidence=sum(len(item.evidence) for item in facts),
        claims=len(claim_ids),
        claim_relations=relations,
        decisions=len(decisions),
        taxonomies=1,
        matrices=len(matrices),
        matrix_cells=matrix_cells,
        questions=question_count,
        search_runs=len(runs),
        manuscript_anchors=anchor_count,
        events=transactions + 1,
        transactions=transactions,
        works_per_transaction=works_per_transaction,
        claims_per_transaction=claims_per_transaction,
        duration_s=time.perf_counter() - started,
        canonical_bytes=_tree_bytes(target),
        event_log_bytes=events_file.stat().st_size if events_file.is_file() else 0,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: build a synthetic workspace and print its generation report as JSON."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, required=True, help="directory to create")
    parser.add_argument("--scale", type=float, default=1.0, help="fraction of the target corpus")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--works", type=int, default=WORKS)
    parser.add_argument("--blocks-per-work", type=int, default=BLOCKS_PER_WORK)
    parser.add_argument("--evidence-per-work", type=int, default=EVIDENCE_PER_WORK)
    parser.add_argument("--claims", type=int, default=CLAIMS)
    parser.add_argument("--works-per-transaction", type=int, default=WORKS_PER_TRANSACTION)
    parser.add_argument("--claims-per-transaction", type=int, default=CLAIMS_PER_TRANSACTION)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s"
    )
    report = generate_workspace(
        args.root,
        works=args.works,
        blocks_per_work=args.blocks_per_work,
        evidence_per_work=args.evidence_per_work,
        claims=args.claims,
        seed=args.seed,
        scale=args.scale,
        works_per_transaction=args.works_per_transaction,
        claims_per_transaction=args.claims_per_transaction,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
