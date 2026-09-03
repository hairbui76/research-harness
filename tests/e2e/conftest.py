"""The manuscript-audit fixture: a small LaTeX project and the research graph behind it.

The graph is hand-authored so every finding the auditor is meant to raise has a single,
nameable cause, and it is consistent with the ground truth recorded in
`tests.fixtures.make_synthetic_paper`: the Work is the synthetic single-column paper, and
the numeric Evidence is anchored to the real `94.32` cell of its Table 1, parsed from the
real PDF bytes, so `resolve_anchor` reaches page 4 for real rather than by construction.

Fixture sentence -> intended finding (`tests/fixtures/manuscript/audit/main.tex`):

===== ==================================================== ===========================
line  sentence                                             finding
===== ==================================================== ===========================
16    "Every ... and no prior work ..."                     `OVER_STRONG_WORDING`
19    "Ostrom and Lindqvist describe ..."                   `CITATION_MISMATCH`
24    "TrafficLM reaches an F1 of 94.32 ... 71.40"          `UNSUPPORTED_NUMERIC` (71.40)
27    "Our sweep shows ..." (no anchor)                     `UNREGISTERED_CLAIM`
29    "The tokenizer improves recall ..."                   `STALE_CLAIM`
31    "We employ the frozen bucket boundaries ..."          `INVALID_EVIDENCE_ANCHOR`
34    "The pretrained encoder improves F1 ..."              none; the Gate P9 trace
===== ==================================================== ===========================
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
    Coverage,
)
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DocumentBlockKind,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ProvenanceSource,
    ScreeningState,
    StaleState,
)
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    NumericValue,
    SourceAnchor,
    VerificationRecord,
)
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    EvidenceId,
    VersionId,
    WorkId,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.work import IdentifierField, Work, WorkIdentifiers
from research_harness.manuscript import (
    BibDatabase,
    LatexProject,
    Sentence,
    parse_bibtex_file,
)
from research_harness.manuscript import build_anchor as build_sentence_anchor
from research_harness.manuscript.audit import AuditContext
from research_harness.parsing import ParseTarget, PyMuPdfParser, cell_span
from research_harness.parsing import build_anchor as build_source_anchor
from tests.fixtures.make_synthetic_paper import GROUND_TRUTH

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
AUDIT_MANUSCRIPT = FIXTURES / "manuscript" / "audit" / "main.tex"
AUDIT_BIBLIOGRAPHY = FIXTURES / "manuscript" / "audit" / "references.bib"
PAPER = GROUND_TRUTH["synthetic_research_paper"]

WORK = WorkId("W0001")
VERSION = VersionId("V0001-1")
ARTIFACT = ArtifactId("A0001-1")
OTHER_WORK = WorkId("W0002")

#: The measured value the manuscript reuses, and where the source records it.
MEASURED_VALUE = "94.32"
MEASURED_METRIC = "F1"
MEASURED_DATASET = "CICIDS2017"
MEASURED_PAGE = PAPER["table"]["page"]

#: A hash no parse of the artifact can produce: it stands for "the file was revised".
REVISED_FILE_HASH = f"sha256:{'0' * 64}"

HUMAN = Provenance.human("human:alice")
SYSTEM = Provenance.system("manuscript-audit-fixture")
REVIEWED_AT = datetime(2026, 1, 2, tzinfo=UTC)

#: Which fixture sentence each claim is attached to, by 1-based line in `main.tex`.
ANCHOR_LINES: Mapping[ClaimId, int] = {
    ClaimId("C0001"): 16,
    ClaimId("C0002"): 19,
    ClaimId("C0003"): 24,
    ClaimId("C0004"): 29,
    ClaimId("C0005"): 31,
    ClaimId("C0006"): 34,
}
UNANCHORED_LINE = 27


# ------------------------------------------------------------------------- source parse


def parse_target(path: Path) -> ParseTarget:
    """A parse target for the immutable fixture bytes, hashed the way ingestion would."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ParseTarget(
        work=WORK,
        version=VERSION,
        artifact=ARTIFACT,
        file_hash=f"sha256:{digest}",
        path=path,
        mime_type="application/pdf",
    )


def table_block(doc: ParsedDocument) -> DocumentBlock:
    """The Table 1 block of the synthetic paper."""
    return next(block for block in doc.blocks if block.kind is DocumentBlockKind.TABLE)


def paragraph_containing(doc: ParsedDocument, needle: str) -> DocumentBlock:
    return next(block for block in doc.blocks if needle in block.text)


# ------------------------------------------------------------------------------- graph


@dataclass(frozen=True)
class ResearchGraph:
    """The accepted state the fixture manuscript is audited against."""

    works: dict[WorkId, Work]
    evidence: dict[EvidenceId, Evidence]
    claims: dict[ClaimId, Claim]
    anchors: tuple[ManuscriptAnchor, ...]
    parsed: dict[ArtifactId, ParsedDocument]


def _work(work_id: WorkId, title: str, year: int, *, doi: str | None = None) -> Work:
    identifiers = WorkIdentifiers()
    if doi is not None:
        identifiers = WorkIdentifiers(
            doi=IdentifierField(value=doi, source=ProvenanceSource.EXTERNAL_METADATA),
            arxiv=IdentifierField(
                value="arXiv:2401.12345", source=ProvenanceSource.EXTERNAL_METADATA
            ),
        )
    return Work(
        id=work_id,
        title=title,
        year=year,
        identifiers=identifiers,
        screening=ScreeningState.INCLUDED,
        versions=(VERSION,) if doi is not None else (),
        artifacts=(ARTIFACT,) if doi is not None else (),
        provenance=SYSTEM,
    )


def _accepted(
    evidence_id: EvidenceId,
    anchor: SourceAnchor,
    text: str,
    *,
    evidence_type: EvidenceType = EvidenceType.EXPERIMENTAL_RESULT,
    numeric: NumericValue | None = None,
) -> Evidence:
    """Accepted, source-observed, direct evidence: the only kind a number may lean on."""
    return Evidence(
        id=evidence_id,
        source=anchor,
        content=EvidenceContent(exact_text=text, numeric=numeric),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=evidence_type,
        strength=EvidenceStrength.DIRECT,
        verification=VerificationRecord(
            status=EvidenceStatus.ACCEPTED,
            accepted_by="human:alice",
            reviewed_at=REVIEWED_AT,
        ),
        provenance=HUMAN,
    )


def _claim(
    claim_id: ClaimId,
    statement: str,
    *,
    requested: ClaimScope,
    allowed: ClaimScope,
    supports: tuple[EvidenceId, ...] = (),
    status: ClaimStatus = ClaimStatus.SUPPORTED,
    stale: StaleState = StaleState.FRESH,
) -> Claim:
    return Claim(
        id=claim_id,
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="TrafficLM", predicate="reports", object=statement[:60]),
        scope=ClaimScopeSpec(level=allowed, corpus="encrypted traffic classifiers"),
        relations=tuple(
            ClaimEvidenceRelation(evidence=evidence_id, relation=ClaimEvidenceRelationType.SUPPORTS)
            for evidence_id in supports
        ),
        coverage=Coverage(relevant_works=4, examined_works=4),
        assessment=ClaimAssessment(
            requested_strength=requested,
            allowed_strength=allowed,
            status=status,
            maximum_defensible_wording="most systems in the reviewed corpus",
            audited_at=REVIEWED_AT,
        ),
        stale=stale,
        provenance=HUMAN,
    )


def sentence_on_line(project: LatexProject, line: int) -> Sentence:
    """The single sentence of `main.tex` that starts on ``line``."""
    found = [item for item in project.sentences if item.line_start == line]
    if len(found) != 1:  # pragma: no cover - the fixture is checked by its own test
        raise AssertionError(f"expected one sentence on line {line}, got {len(found)}")
    return found[0]


def build_graph(project: LatexProject) -> ResearchGraph:
    """Build the accepted graph, anchoring evidence to the real synthetic-paper parse."""
    doc = PyMuPdfParser().parse(parse_target(PAPER["path"]))
    table = table_block(doc)
    start, end = cell_span(table, PAPER["table"]["numeric_cell"]["row"], 2)
    prose = paragraph_containing(doc, "The pretrained encoder improves F1")
    offset = prose.text.index("The pretrained encoder")

    measured = _accepted(
        EvidenceId("E0001"),
        build_source_anchor(doc, table, start, end),
        MEASURED_VALUE,
        numeric=NumericValue(
            raw=MEASURED_VALUE,
            parsed=94.32,
            unit=None,
            metric=MEASURED_METRIC,
            dataset=MEASURED_DATASET,
            condition={"split": "held-out"},
            source_table="Table 1",
            source_row="TrafficLM",
            source_column="F1",
        ),
    )
    narrative = _accepted(
        EvidenceId("E0002"),
        build_source_anchor(doc, prose, offset, offset + 60),
        prose.text[offset : offset + 60],
        evidence_type=EvidenceType.AUTHOR_CONCLUSION,
    )
    # Accepted and fresh, but taken from bytes this parse cannot reproduce: the artifact
    # was revised under it, so its provenance is broken (ADR-008, Product 42.D).
    orphaned = _accepted(
        EvidenceId("E0003"),
        build_source_anchor(doc, prose, offset, offset + 20, file_hash=REVISED_FILE_HASH),
        prose.text[offset : offset + 20],
        evidence_type=EvidenceType.IMPLEMENTATION_DETAIL,
    )

    claims = {
        ClaimId("C0001"): _claim(
            ClaimId("C0001"),
            "Encrypted traffic defeats signature detectors in the reviewed corpus",
            requested=ClaimScope.UNIVERSAL_OR_ABSENCE,
            allowed=ClaimScope.CORPUS_PATTERN,
            supports=(narrative.id,),
            status=ClaimStatus.QUALIFIED,
        ),
        ClaimId("C0002"): _claim(
            ClaimId("C0002"),
            "The corrected split changes the reported operating point",
            requested=ClaimScope.INDIVIDUAL,
            allowed=ClaimScope.INDIVIDUAL,
            supports=(narrative.id,),
        ),
        ClaimId("C0003"): _claim(
            ClaimId("C0003"),
            "TrafficLM reaches an F1 of 94.32 on CICIDS2017",
            requested=ClaimScope.INDIVIDUAL,
            allowed=ClaimScope.INDIVIDUAL,
            supports=(measured.id,),
        ),
        ClaimId("C0004"): _claim(
            ClaimId("C0004"),
            "Tokenization improves recall on short flows",
            requested=ClaimScope.INDIVIDUAL,
            allowed=ClaimScope.INDIVIDUAL,
            supports=(narrative.id,),
            stale=StaleState.STALE,
        ),
        ClaimId("C0005"): _claim(
            ClaimId("C0005"),
            "Bucket boundaries are frozen after pretraining",
            requested=ClaimScope.INDIVIDUAL,
            allowed=ClaimScope.INDIVIDUAL,
            supports=(orphaned.id,),
        ),
        ClaimId("C0006"): _claim(
            ClaimId("C0006"),
            "The pretrained encoder improves F1 over the strongest baseline",
            requested=ClaimScope.INDIVIDUAL,
            allowed=ClaimScope.INDIVIDUAL,
            supports=(measured.id,),
        ),
    }
    anchors = tuple(
        build_sentence_anchor(sentence_on_line(project, line), claim_id, HUMAN)
        for claim_id, line in ANCHOR_LINES.items()
    )
    return ResearchGraph(
        works={
            WORK: _work(
                WORK,
                "Deep Representations for Encrypted Network Traffic",
                2023,
                doi="10.1000/xyz123",
            ),
            OTHER_WORK: _work(OTHER_WORK, "A Corrected Split for Structured Traffic Corpora", 2020),
        },
        evidence={item.id: item for item in (measured, narrative, orphaned)},
        claims=claims,
        anchors=anchors,
        parsed={ARTIFACT: doc},
    )


# ------------------------------------------------------------------------------ fixtures


@pytest.fixture(scope="session")
def audit_project() -> LatexProject:
    """The fixture manuscript, parsed once for the session."""
    return LatexProject.load(AUDIT_MANUSCRIPT)


@pytest.fixture(scope="session")
def audit_bib() -> BibDatabase:
    """The fixture bibliography."""
    return parse_bibtex_file(AUDIT_BIBLIOGRAPHY)


@pytest.fixture(scope="session")
def audit_graph(audit_project: LatexProject) -> ResearchGraph:
    """Works, Evidence, Claims, and anchors for the fixture manuscript."""
    return build_graph(audit_project)


@pytest.fixture(scope="session")
def audit_context(
    audit_project: LatexProject, audit_bib: BibDatabase, audit_graph: ResearchGraph
) -> AuditContext:
    """The complete audit context, with the source PDF parse available for tracing."""
    return AuditContext(
        project=audit_project,
        bib=audit_bib,
        anchors=audit_graph.anchors,
        claims=audit_graph.claims,
        evidence=audit_graph.evidence,
        works=audit_graph.works,
        parsed=audit_graph.parsed,
    )
