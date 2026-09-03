"""Gate P5: one corpus, two questions, provenance shown for both.

The gate asks for exactly one demonstration: the *same* local corpus answering an exact
dataset query through structured/FTS retrieval and a terminology-mismatch query through
semantic retrieval, with provenance shown in both cases. Everything here is therefore built
once, from the real synthetic paper, through the real capability layer - ingest, parse,
accept two Evidence objects, rebuild the projection, build the vector index with the
offline hashing embedder - and then queried the way a researcher would.

Two further properties are asserted because they are what make the gate mean anything:
auditing an empirical result prefers the Results table to the abstract (Task 5.4), and
deleting the vector index costs recall and nothing else (ADR-006, Task 5.2).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import typer
from sqlalchemy.engine import Engine
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    CreateClaimRequest,
    InitProjectRequest,
)
from research_harness.capabilities.handlers import accept_evidence, create_claim, init_project
from research_harness.claims.audit import CounterEvidenceFinder
from research_harness.cli.commands.search import register
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.document import DocumentBlock
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    DocumentBlockKind,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.evidence import Evidence, EvidenceContent, NumericValue, SourceAnchor
from research_harness.domain.ids import ClaimId, EvidenceId, WorkId
from research_harness.ingest.service import IngestService
from research_harness.parsing.text import text_sha256
from research_harness.projection.rebuild import rebuild_workspace
from research_harness.projection.schema import create_engine_for
from research_harness.providers.models.embeddings import HashingEmbeddingProvider
from research_harness.retrieval.counter import RetrievalCounterEvidenceFinder
from research_harness.retrieval.planner import Intent, QueryHints, RetrievalMode
from research_harness.retrieval.rerank import rerank
from research_harness.retrieval.semantic import SemanticIndex
from research_harness.retrieval.service import RetrievalService, build_semantic_index
from research_harness.retrieval.structured import Authority, StructuredQuery
from research_harness.workspace.repository import WorkspaceRepository

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_research_paper.pdf"
DIMENSION = 512

DATASET = "CICIDS2017"
DATASET_QUERY = f"Which papers use {DATASET}?"
#: A terminology-mismatch query: the cue makes the planner reach for the vector index, and
#: the distinctive tokens are there because the offline embedder is lexical (its own
#: docstring says so). A trained model would not need the overlap.
MISMATCH_QUERY = (
    "systems that encode an ordered sequence of packet descriptors, "
    "similar idea but different terminology"
)

DATASET_SENTENCE = "All experiments use CICIDS2017"
METHOD_SENTENCE = "ordered sequence of packet descriptors"
TABLE_ROW = "TrafficLM | CICIDS2017 | 94.32 | 93.10"

runner = CliRunner()


@dataclass(frozen=True)
class Gate:
    """The workspace under test and the ids the assertions name."""

    root: Path
    work: WorkId
    dataset_evidence: EvidenceId
    table_evidence: EvidenceId
    dataset_block: str
    method_block: str
    table_block: str
    claim: ClaimId
    embedder: HashingEmbeddingProvider


# --- building the corpus ----------------------------------------------------


def anchor(block: DocumentBlock, text: str, *, file_hash: str) -> SourceAnchor:
    """A complete source anchor into one parsed block (Product 9: no anchor, no evidence)."""
    start = max(block.text.find(text), 0)
    return SourceAnchor(
        work=block.work,
        version=block.version,
        artifact=block.artifact,
        file_hash=file_hash,
        block=block.id,
        text_hash=text_sha256(text),
        page=block.page,
        section_path=block.section_path,
        char_start=start,
        char_end=start + len(text),
    )


def candidate(
    evidence_id: str,
    block: DocumentBlock,
    text: str,
    *,
    file_hash: str,
    evidence_type: EvidenceType,
    numeric: NumericValue | None = None,
) -> Evidence:
    return Evidence(
        id=EvidenceId(evidence_id),
        source=anchor(block, text, file_hash=file_hash),
        content=EvidenceContent(exact_text=text, numeric=numeric),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=evidence_type,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.model("vendor-a/model-x"),
    )


def accept(ctx: CapabilityContext, evidence: Evidence) -> EvidenceId:
    accept_evidence(
        ctx,
        AcceptEvidenceRequest(
            candidate=evidence,
            review_action=ReviewAction.ACCEPT,
            verdict=VerificationVerdict.SUPPORTED,
            rationale="read the span in the source",
        ),
    )
    return evidence.id


def find(blocks: tuple[DocumentBlock, ...], needle: str, kind: DocumentBlockKind) -> DocumentBlock:
    return next(block for block in blocks if block.kind is kind and needle in block.text)


@pytest.fixture(scope="module")
def gate(tmp_path_factory: pytest.TempPathFactory) -> Gate:
    """Ingest, parse, accept two Evidence objects, rebuild, and build the vector index."""
    root = tmp_path_factory.mktemp("gate-p5") / "project"
    init_project(InitProjectRequest(root=root, name="gate-p5"))
    ctx = open_context(root)

    ingest = IngestService(ctx)
    ingested = ingest.ingest_local_pdf(FIXTURE)
    parsed = ingest.parse_work(ingested.work)
    artifact = ctx.repo.get_artifact(ingested.artifact, work=ingested.work)

    dataset_block = find(parsed.blocks, DATASET_SENTENCE, DocumentBlockKind.PARAGRAPH)
    method_block = find(parsed.blocks, METHOD_SENTENCE, DocumentBlockKind.PARAGRAPH)
    table_block = find(parsed.blocks, "94.32", DocumentBlockKind.TABLE)

    dataset_evidence = accept(
        ctx,
        candidate(
            "E0001",
            dataset_block,
            f"{DATASET_SENTENCE}, a labelled capture of benign and attack traffic",
            file_hash=artifact.file_hash,
            evidence_type=EvidenceType.DATASET_DESCRIPTION,
        ),
    )
    table_evidence = accept(
        ctx,
        candidate(
            "E0002",
            table_block,
            TABLE_ROW,
            file_hash=artifact.file_hash,
            evidence_type=EvidenceType.EXPERIMENTAL_RESULT,
            numeric=NumericValue(
                raw="94.32",
                parsed=94.32,
                metric="F1",
                dataset=DATASET,
                condition={"split": "test"},
                source_table="Table 1",
                source_row="TrafficLM",
                source_column="F1",
            ),
        ),
    )
    claim = ClaimId("C0001")
    create_claim(
        ctx,
        CreateClaimRequest(
            claim=Claim(
                id=claim,
                statement="Pretrained traffic encoders improve detection on CICIDS2017.",
                type=ClaimType.DESCRIPTIVE,
                semantics=ClaimSemantics(
                    subject="pretrained_traffic_encoder",
                    predicate="improves",
                    object="detection",
                    qualifier={"dataset": DATASET},
                ),
                scope=ClaimScopeSpec(level=ClaimScope.INDIVIDUAL),
                relations=(
                    ClaimEvidenceRelation(
                        evidence=table_evidence, relation=ClaimEvidenceRelationType.SUPPORTS
                    ),
                ),
                assessment=ClaimAssessment(
                    requested_strength=ClaimScope.INDIVIDUAL,
                    allowed_strength=ClaimScope.INDIVIDUAL,
                ),
                provenance=Provenance.human(),
            )
        ),
    )

    report = rebuild_workspace(ctx.repo)
    assert report.ok, report.invalid_files
    embedder = HashingEmbeddingProvider(dimension=DIMENSION)
    stats = build_semantic_index(ctx.repo, embedder)
    assert stats.unit_count > 0 and not stats.needs_rebuild

    return Gate(
        root=root,
        work=ingested.work,
        dataset_evidence=dataset_evidence,
        table_evidence=table_evidence,
        dataset_block=f"{dataset_block.id}@{dataset_block.artifact}",
        method_block=f"{method_block.id}@{method_block.artifact}",
        table_block=f"{table_block.id}@{table_block.artifact}",
        claim=claim,
        embedder=embedder,
    )


@pytest.fixture
def service(gate: Gate) -> Iterator[RetrievalService]:
    repo = WorkspaceRepository.open(gate.root)
    engine: Engine = create_engine_for(repo.layout.database_file)
    try:
        yield RetrievalService(engine, repo, embedder=gate.embedder)
    finally:
        engine.dispose()


def cli() -> typer.Typer:
    """`research search|resolve|index` on a bare app, the way `cli/app.py` mounts them."""
    app = typer.Typer()

    @app.callback()
    def _root() -> None:
        """Test harness."""

    register(app)
    return app


def run(*args: str) -> Result:
    return runner.invoke(cli(), list(args))


# --- 1. the exact dataset query ---------------------------------------------


def test_an_exact_dataset_question_is_answered_from_accepted_state(
    gate: Gate, service: RetrievalService
) -> None:
    response = service.search(DATASET_QUERY)

    assert response.plan.modes == (RetrievalMode.STRUCTURED_ONLY, RetrievalMode.FTS_SECTION)
    assert set(response.rungs_consulted) == {
        RetrievalMode.STRUCTURED_ONLY,
        RetrievalMode.FTS_SECTION,
    }
    top = response.hits[0]
    assert top.authority is Authority.ACCEPTED_EVIDENCE
    assert top.ref in {str(gate.dataset_evidence), str(gate.table_evidence)}
    assert top.provenance
    assert top.components["authority"] == 1.0


def test_the_dataset_question_never_needed_the_vector_index(service: RetrievalService) -> None:
    """Exact terminology is answerable exactly; Task 3.3 and ADR-006 both require it."""
    response = service.search(DATASET_QUERY)

    assert RetrievalMode.STRUCTURED_SEMANTIC not in response.plan.modes
    assert all("semantic" not in hit.provenance for hit in response.hits)


def test_the_parsed_block_behind_the_answer_resolves_to_page_three(
    gate: Gate, service: RetrievalService
) -> None:
    """Ground truth: `make_synthetic_paper.GROUND_TRUTH` puts the dataset sentence on page 3."""
    response = service.search(DATASET_QUERY, k=20)
    blocks = [hit for hit in response.hits if "@" in hit.ref]

    assert gate.dataset_block in {hit.ref for hit in blocks}
    source = service.resolve_source(gate.dataset_block)
    assert source.page == 3
    assert source.section_path == ("3 Experiments", "3.1 Dataset")
    assert DATASET in source.text


def test_the_work_is_reachable_by_joining_accepted_evidence(
    gate: Gate, service: RetrievalService
) -> None:
    response = service.search(DATASET_QUERY, k=20)

    works = [hit for hit in response.hits if hit.ref == str(gate.work)]
    assert works and works[0].provenance.startswith("works_with_evidence")


# --- 2. the terminology-mismatch query --------------------------------------


def test_a_terminology_mismatch_query_is_answered_by_the_vector_index(
    gate: Gate, service: RetrievalService
) -> None:
    response = service.search(MISMATCH_QUERY, k=5)

    assert RetrievalMode.STRUCTURED_SEMANTIC in response.plan.modes
    assert RetrievalMode.STRUCTURED_SEMANTIC in response.rungs_consulted
    semantic = [hit for hit in response.hits if "semantic" in hit.provenance]
    assert semantic, response.notes
    assert gate.method_block in {hit.ref for hit in semantic}


def test_the_semantic_hit_carries_the_provenance_and_the_place_it_came_from(
    gate: Gate, service: RetrievalService
) -> None:
    response = service.search(MISMATCH_QUERY, k=5)
    hit = next(item for item in response.hits if item.ref == gate.method_block)

    assert hit.provenance == "semantic"
    assert hit.components["semantic"] > 0.0
    assert hit.location.page == 2
    assert hit.location.section_path == ("2 Method",)
    assert service.resolve_source(hit.ref).page == 2


# --- 3. research-utility reranking ------------------------------------------


def test_auditing_an_empirical_result_puts_the_results_table_above_the_abstract(
    gate: Gate, service: RetrievalService
) -> None:
    table = service.structured(
        StructuredQuery(entity="evidence", filters={"id": str(gate.table_evidence)})
    )
    abstract = service.lexical("pretrained sequence model transfer", section_prefix="Abstract")

    assert table and abstract
    ranked = rerank([*abstract, *table], intent=Intent.AUDIT_EMPIRICAL_RESULT)

    assert ranked[0].ref == str(gate.table_evidence)
    assert ranked[0].components["structure"] > ranked[-1].components["structure"]


def test_an_audit_query_end_to_end_prefers_the_measured_number(
    gate: Gate, service: RetrievalService
) -> None:
    response = service.search(
        f"What F1 does TrafficLM report on {DATASET}?",
        hints=QueryHints(intent=Intent.AUDIT_EMPIRICAL_RESULT),
    )

    assert response.hits[0].ref == str(gate.table_evidence)
    assert "94.32" in response.hits[0].snippet


# --- 4. the index is disposable ---------------------------------------------


def test_deleting_the_vector_index_costs_recall_and_nothing_else(
    gate: Gate, service: RetrievalService
) -> None:
    before = service.search(DATASET_QUERY, k=20)
    index = SemanticIndex.open(WorkspaceRepository.open(gate.root).layout.index_dir, gate.embedder)
    try:
        index.delete()
        assert not index.directory.exists()

        degraded = RetrievalService(
            create_engine_for(WorkspaceRepository.open(gate.root).layout.database_file),
            WorkspaceRepository.open(gate.root),
            embedder=gate.embedder,
        )
        mismatch = degraded.search(MISMATCH_QUERY, k=5)
        exact = degraded.search(DATASET_QUERY, k=20)

        assert all("semantic" not in hit.provenance for hit in mismatch.hits)
        assert any("vector index" in note for note in mismatch.notes)
        assert not any("state" in note and "incomplete" in note for note in mismatch.notes)
        assert [hit.ref for hit in exact.hits] == [hit.ref for hit in before.hits]
        assert exact.hits[0].authority is Authority.ACCEPTED_EVIDENCE
    finally:
        build_semantic_index(WorkspaceRepository.open(gate.root), gate.embedder)


def test_accepted_state_survives_a_deleted_index(gate: Gate) -> None:
    repo = WorkspaceRepository.open(gate.root)
    evidence = {str(item.id) for item in repo.iter_evidence(gate.work)}

    assert evidence == {str(gate.dataset_evidence), str(gate.table_evidence)}


# --- 5. the CLI -------------------------------------------------------------


def payload(result: Result) -> Any:
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_the_cli_reports_authority_location_components_and_provenance(gate: Gate) -> None:
    body = payload(run("search", DATASET_QUERY, "-w", str(gate.root), "--json"))

    assert body["plan"]["modes"] == ["structured_only", "fts_section"]
    top = body["hits"][0]
    assert top["authority"] == "accepted_evidence"
    assert top["provenance"]
    assert set(top["components"]) >= {"authority", "structure", "independence", "staleness"}
    assert body["weights"]["staleness"] < 0


def test_the_cli_prints_a_readable_result_list(gate: Gate) -> None:
    result = run("search", DATASET_QUERY, "-w", str(gate.root))

    assert result.exit_code == 0, result.stdout
    assert "accepted_evidence" in result.stdout
    assert str(gate.dataset_evidence) in result.stdout or str(gate.table_evidence) in result.stdout


def test_the_cli_resolves_a_reference_to_its_exact_source(gate: Gate) -> None:
    body = payload(run("resolve", gate.dataset_block, "-w", str(gate.root), "--json"))

    assert body["page"] == 3
    assert body["section_path"] == ["3 Experiments", "3.1 Dataset"]
    assert body["bbox"] is not None


def test_the_cli_can_rebuild_the_index_and_report_it(gate: Gate) -> None:
    body = payload(
        run("index", "build", "-w", str(gate.root), "--dimension", str(DIMENSION), "--json")
    )

    assert body["unit_count"] > 0
    assert body["needs_rebuild"] is False
    assert body["provider"] == "hashing"


def test_the_cli_refuses_an_unknown_mode_with_one_line(gate: Gate) -> None:
    result = run("search", DATASET_QUERY, "-w", str(gate.root), "--mode", "vibes")

    assert result.exit_code == 1
    assert (result.stdout + result.stderr).count("error:") == 1


# --- counter-evidence, the claim-audit consumer -----------------------------


def test_counter_evidence_search_proposes_candidates_and_never_accepted_support(
    gate: Gate, service: RetrievalService
) -> None:
    claim = WorkspaceRepository.open(gate.root).get_claim(gate.claim)
    finder = RetrievalCounterEvidenceFinder(service)

    candidates = finder.find_counter_evidence(claim, limit=5)

    assert isinstance(finder, CounterEvidenceFinder)
    assert candidates
    assert all(item.ref != str(gate.table_evidence) for item in candidates)
    assert all(item.source for item in candidates)
    assert any(item.location for item in candidates)


def test_a_counter_candidate_is_a_pointer_and_never_evidence(
    gate: Gate, service: RetrievalService
) -> None:
    """ADR-003: a retrieval hit has no anchor, no acceptance, and no authority of its own."""
    claim = WorkspaceRepository.open(gate.root).get_claim(gate.claim)

    candidates = RetrievalCounterEvidenceFinder(service).find_counter_evidence(claim, limit=3)

    assert not any(isinstance(item, Evidence) for item in candidates)
    assert set(type(candidates[0]).model_fields) == {
        "ref",
        "work",
        "text",
        "score",
        "source",
        "location",
    }
