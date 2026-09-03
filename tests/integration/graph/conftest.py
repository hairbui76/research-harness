"""A synthetic workspace with everything the ResearchGraph projects.

Self-contained and offline: one Work with a parsed artifact, two accepted Evidence objects,
a Claim that supports/contradicts them, a Decision, a Question, a synthesis matrix, a
manuscript file with a bibliography and an anchor, plus two staged proposals under
`.research/staging/` so the candidate/accepted distinction has something to be about.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_harness.domain import (
    ArtifactId,
    BlockId,
    ClaimEvidenceRelation,
    ClaimEvidenceRelationType,
    ClaimId,
    Coverage,
    DecisionId,
    DocumentBlockKind,
    EvidenceContent,
    EvidenceId,
    EvidenceStatus,
    ManuscriptAnchor,
    MatrixCell,
    OverturnRisk,
    ParsedDocument,
    ResearchEvent,
    ResearchEventType,
    SearchRunId,
    SynthesisId,
    SynthesisMatrix,
    VerificationRecord,
    VersionId,
    WorkId,
)
from research_harness.graph.service import ResearchGraph
from research_harness.workspace.repository import WorkspaceRepository
from tests.unit.domain import strategies as sty

WORK = WorkId("W0017")
VERSION = VersionId("V0017-2")
ARTIFACT = ArtifactId("A0017-3")
PARAGRAPH = BlockId("B0081")
TABLE = BlockId("B0082")
REFERENCE = BlockId("B0083")
CLAIM = ClaimId("C0041")
DECISION = DecisionId("D0027")
SUPPORTING = EvidenceId("E0482")
CONTRADICTING = EvidenceId("E0483")
MATRIX = SynthesisId("S0007")
SEARCH_RUN = SearchRunId("SR0019")

MANUSCRIPT_FILE = "manuscript/main.tex"
BIB_FILE = "manuscript/references.bib"
CITATION_KEY = "smith2024"
DATASET = "CICIDS2017"
CANDIDATE_ID = "cand_00112233445566ff"

PDF_BYTES = b"%PDF-1.7\nsynthetic artifact bytes\n"
PDF_HASH = f"sha256:{hashlib.sha256(PDF_BYTES).hexdigest()}"
SENTENCE = "Representations differ in tokenization granularity."
SENTENCE_FINGERPRINT = f"sha256:{hashlib.sha256(SENTENCE.encode()).hexdigest()}"

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 1, 2, tzinfo=UTC)
T2 = datetime(2026, 1, 3, tzinfo=UTC)
T4 = datetime(2026, 1, 5, tzinfo=UTC)
T5 = datetime(2026, 1, 6, tzinfo=UTC)


def _tracked(moment: datetime) -> dict[str, datetime]:
    return {"created_at": moment, "updated_at": moment}


def _accepted() -> VerificationRecord:
    return VerificationRecord(status=EvidenceStatus.ACCEPTED, accepted_by="human:alice")


def _event(kind: ResearchEventType, summary: str) -> ResearchEvent:
    return ResearchEvent(event=kind, actor="human:alice", summary=summary, occurred_at=T4)


def populated_workspace(root: Path) -> WorkspaceRepository:
    """One of every canonical object the graph projects, in containment order."""
    repo = WorkspaceRepository.init(root, "structured-traffic")
    work = sty.make_work(versions=(VERSION,), artifacts=(ARTIFACT,), **_tracked(T0))
    version = sty.make_version(**_tracked(T0))
    artifact = sty.make_artifact(file_hash=PDF_HASH, size_bytes=len(PDF_BYTES), **_tracked(T0))
    paragraph = sty.make_block(
        id=PARAGRAPH,
        text=f"We evaluate on {DATASET}. The {DATASET} split is standard.",
        **_tracked(T1),
    )
    table = sty.make_block(
        id=TABLE,
        kind=DocumentBlockKind.TABLE,
        page=9,
        order=13,
        text="model F1",
        section_path=("Discussion", "Limitations"),
        **_tracked(T1),
    )
    reference = sty.make_block(
        id=REFERENCE,
        kind=DocumentBlockKind.REFERENCE,
        page=12,
        order=44,
        text="J. Smith. A prior system. 2024.",
        section_path=("References",),
        reference_key=CITATION_KEY,
        reference_raw="J. Smith. A prior system. 2024.",
        **_tracked(T1),
    )
    document = ParsedDocument(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=PDF_HASH,
        parser_name="pymupdf",
        parser_version="1.24.0",
        page_count=12,
        blocks=(paragraph, table, reference),
        provenance=sty.SYSTEM,
        **_tracked(T1),
    )
    supporting = sty.make_evidence(
        id=SUPPORTING,
        source=sty.make_anchor(file_hash=PDF_HASH),
        content=EvidenceContent(exact_text=f"We evaluate on {DATASET}."),
        verification=_accepted(),
        **_tracked(T2),
    )
    contradicting = sty.make_evidence(
        id=CONTRADICTING,
        source=sty.make_anchor(
            block=TABLE,
            page=9,
            file_hash=PDF_HASH,
            section_path=("Discussion", "Limitations"),
        ),
        content=EvidenceContent(exact_text="The reported F1 is not reproducible."),
        verification=_accepted(),
        **_tracked(T2),
    )
    decision = sty.make_override_decision(**_tracked(T2))
    search_run = sty.make_search_run(**_tracked(T2))
    claim = sty.make_claim(
        relations=(
            ClaimEvidenceRelation(evidence=SUPPORTING, relation=ClaimEvidenceRelationType.SUPPORTS),
            ClaimEvidenceRelation(
                evidence=CONTRADICTING, relation=ClaimEvidenceRelationType.CONTRADICTS
            ),
        ),
        decisions=(DECISION,),
        derived_from=(MATRIX,),
        coverage=Coverage(
            relevant_works=17,
            examined_works=14,
            unresolved_works=3,
            overturn_risk=OverturnRisk.LOW_MODERATE,
            search_runs=(SEARCH_RUN,),
        ),
        **_tracked(T4),
    )
    matrix = SynthesisMatrix(
        id=MATRIX,
        name="representation matrix",
        works=(WORK,),
        fields=("tokenization",),
        cells=(
            MatrixCell(
                work=WORK, field="tokenization", labels=("byte_level",), evidence=(SUPPORTING,)
            ),
        ),
        provenance=sty.HUMAN,
        **_tracked(T4),
    )
    question = sty.make_question(claims=(CLAIM,), supporting_evidence=(SUPPORTING,), **_tracked(T5))
    anchor = ManuscriptAnchor(
        file=MANUSCRIPT_FILE,
        line_start=41,
        line_end=41,
        sentence=SENTENCE,
        sentence_fingerprint=SENTENCE_FINGERPRINT,
        claim=CLAIM,
        citation_keys=(CITATION_KEY,),
        provenance=sty.HUMAN,
        **_tracked(T5),
    )
    with repo.transaction(_event(ResearchEventType.WORK_INGESTED, "ingest W0017")) as tx:
        tx.put(work)
        tx.put(version)
        tx.put(artifact)
        tx.store_artifact_bytes(artifact, PDF_BYTES)
        tx.put(document)
        tx.append_evidence(supporting)
        tx.append_evidence(contradicting)
        tx.put(decision)
        tx.put(search_run)
        tx.put(claim)
        tx.put(matrix)
        tx.put(question)
        tx.put(anchor)
    write_manuscript(repo)
    stage_evidence_candidate(repo)
    stage_relation_proposal(repo)
    return repo


def write_manuscript(repo: WorkspaceRepository) -> None:
    """The user-owned LaTeX source and bibliography the anchors point at."""
    root = repo.layout.root
    (root / MANUSCRIPT_FILE).write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "\n" * 38
        + f"{SENTENCE} \\cite{{{CITATION_KEY}}}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    (root / BIB_FILE).write_text(
        f"@article{{{CITATION_KEY},\n"
        "  title = {A prior system},\n"
        "  author = {Smith, J.},\n"
        "  year = {2024}\n}\n",
        encoding="utf-8",
    )


def stage_evidence_candidate(repo: WorkspaceRepository) -> Path:
    """A real `EvidenceCandidate` in `.research/staging/evidence/`; never accepted state."""
    from research_harness.evidence.staging import (
        EvidenceCandidate,
        ExtractionProvenance,
        StagingStore,
    )

    candidate = EvidenceCandidate(
        candidate_id=CANDIDATE_ID,
        work=WORK,
        artifact=ARTIFACT,
        field="dataset",
        evidence=sty.make_evidence(
            id=EvidenceId("E0000"),
            content=EvidenceContent(exact_text=f"The {DATASET} split is standard."),
            **_tracked(T4),
        ),
        extraction=ExtractionProvenance(
            run_id="run-1",
            provider="vendor-a",
            model="model-x",
            template_version="1",
            request_fingerprint="sha256:" + "0" * 64,
            response_schema_fingerprint="sha256:" + "1" * 64,
        ),
        created_at=T4,
        updated_at=T4,
    )
    return StagingStore(repo.layout.research_dir).put(candidate)


def stage_relation_proposal(repo: WorkspaceRepository) -> Path:
    """A staged claim-audit report proposing a `supports` relation nobody has reviewed.

    Written in the shape `workflows.claim_audit.WriteReport` produces, whose `incomparable`
    entries are `claims.audit.ProposedRelationChange` records.
    """
    path = repo.layout.research_dir / "staging" / "claim_audit" / str(CLAIM) / "run-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "workflow": "claim_audit",
                "run_id": "run-1",
                "claim": str(CLAIM),
                "result": {
                    "claim": str(CLAIM),
                    "incomparable": [
                        {
                            "evidence": str(CONTRADICTING),
                            "current": "contradicts",
                            "proposed": "supports",
                            "note": "the table reports the same metric after all",
                        }
                    ],
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def repo(tmp_path: Path) -> WorkspaceRepository:
    return populated_workspace(tmp_path / "project")


@pytest.fixture
def graph(repo: WorkspaceRepository) -> Iterator[ResearchGraph]:
    built = ResearchGraph(repo)
    built.rebuild()
    yield built
    built.close()
