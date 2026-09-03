"""The staging store: regenerable candidate state that can never be mistaken for authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_harness.domain.base import Provenance
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    ReviewAction,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.evidence import Evidence, EvidenceContent
from research_harness.domain.ids import ArtifactId, BlockId, EvidenceId, VersionId, WorkId
from research_harness.evidence.staging import (
    CANDIDATE_ID_PATTERN,
    PROVISIONAL_EVIDENCE_ID,
    CandidateNotFoundError,
    CandidateStatus,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingError,
    StagingStore,
    candidate_id_for,
    new_candidate_id,
)
from research_harness.parsing.anchors import build_anchor
from research_harness.parsing.base import ParseTarget
from research_harness.parsing.pymupdf_parser import PyMuPdfParser
from research_harness.roles.schemas import VerificationOutput

FIXTURE_PDF = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_research_paper.pdf"
FILE_HASH = f"sha256:{hashlib.sha256(FIXTURE_PDF.read_bytes()).hexdigest()}"
WORK = WorkId("W0001")
VERSION = VersionId("V0001-1")
ARTIFACT = ArtifactId("A0001-1")
DATASET_BLOCK = BlockId("B0017")


@pytest.fixture(scope="module")
def doc() -> ParsedDocument:
    """The synthetic paper, parsed for real; hand-built document IR is never trustworthy."""
    return PyMuPdfParser().parse(
        ParseTarget(
            work=WORK,
            version=VERSION,
            artifact=ARTIFACT,
            file_hash=FILE_HASH,
            path=FIXTURE_PDF,
            mime_type="application/pdf",
        )
    )


def block_of(document: ParsedDocument, block: BlockId) -> DocumentBlock:
    return next(item for item in document.blocks if item.id == block)


def make_evidence(document: ParsedDocument, *, field: str = "dataset") -> Evidence:
    block = block_of(document, DATASET_BLOCK)
    anchor = build_anchor(document, block, 0, 30)
    return Evidence(
        id=PROVISIONAL_EVIDENCE_ID,
        source=anchor,
        content=EvidenceContent(exact_text=block.text[0:30], field=field),
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
        strength=EvidenceStrength.DIRECT,
        review_tier=ReviewTier.TIER_1,
        provenance=Provenance.model(actor="scripted/model-a", run_id="run-1"),
    )


def make_candidate(document: ParsedDocument, **overrides: object) -> EvidenceCandidate:
    payload: dict[str, object] = {
        "candidate_id": "cand_0123456789abcdef",
        "work": WORK,
        "artifact": ARTIFACT,
        "field": "dataset",
        "evidence": make_evidence(document),
        "extraction": ExtractionProvenance(
            run_id="run-1",
            provider="scripted",
            model="model-a",
            template_version="1.0.0",
            request_fingerprint="a" * 64,
            response_schema_fingerprint="b" * 64,
            rationale="The experiments section names the corpus.",
        ),
    }
    return EvidenceCandidate(**{**payload, **overrides})  # type: ignore[arg-type]


def verification(
    verdict: VerificationVerdict = VerificationVerdict.SUPPORTED,
) -> VerificationOutput:
    return VerificationOutput(
        verdict=verdict,
        rationale="The span states the candidate.",
        quoted_support="All experiments use CICIDS2017",
    )


@pytest.fixture
def store(tmp_path: Path) -> StagingStore:
    return StagingStore(tmp_path / ".research")


# ------------------------------------------------------------------ candidate ids


def test_a_generated_candidate_id_matches_the_documented_shape() -> None:
    import re

    assert re.match(CANDIDATE_ID_PATTERN, new_candidate_id())
    assert new_candidate_id() != new_candidate_id()


def test_a_content_addressed_id_follows_the_evidence_not_the_model() -> None:
    """Two providers reading the same span propose the same candidate (Product §19.1)."""
    first = candidate_id_for(WORK, ARTIFACT, "dataset", DATASET_BLOCK, 0, 30)
    second = candidate_id_for(WORK, ARTIFACT, "dataset", DATASET_BLOCK, 0, 30)
    other_span = candidate_id_for(WORK, ARTIFACT, "dataset", DATASET_BLOCK, 0, 31)
    assert first == second
    assert first != other_span


def test_the_provisional_id_is_never_handed_out_to_accepted_evidence() -> None:
    assert PROVISIONAL_EVIDENCE_ID == "E0000"
    assert EvidenceId.next([str(PROVISIONAL_EVIDENCE_ID)]) == "E0001"


# ------------------------------------------------------------------- the candidate


def test_staging_refuses_to_hold_accepted_evidence(doc: ParsedDocument) -> None:
    accepted = make_evidence(doc).touch(
        verification=make_evidence(doc).verification.touch(
            status=EvidenceStatus.ACCEPTED, accepted_by="human:alice"
        )
    )
    with pytest.raises(ValueError, match="proposed or verified candidates only"):
        make_candidate(doc, evidence=accepted)


def test_a_verified_candidate_must_name_its_verifier(doc: ParsedDocument) -> None:
    with pytest.raises(ValueError, match="needs a verification result and a verifier"):
        make_candidate(doc, status=CandidateStatus.VERIFIED)


def test_a_reviewed_candidate_must_record_the_action_taken(doc: ParsedDocument) -> None:
    with pytest.raises(ValueError, match="needs the review action"):
        make_candidate(doc, status=CandidateStatus.REVIEWED)


def test_a_candidate_reports_its_review_tier_and_verdict(doc: ParsedDocument) -> None:
    candidate = make_candidate(doc)
    assert candidate.review_tier == 1
    assert candidate.verdict is None


# ------------------------------------------------------------------------- storage


def test_a_candidate_round_trips_through_its_own_file(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)

    path = store.put(candidate)

    assert path == store.root / "W0001" / "cand_0123456789abcdef.json"
    assert store.get(candidate.candidate_id) == candidate
    assert store.get(candidate.candidate_id, work=WORK) == candidate


def test_the_file_is_readable_json_a_researcher_can_diff(
    store: StagingStore, doc: ParsedDocument
) -> None:
    path = store.put(make_candidate(doc))

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "proposed"
    assert payload["evidence"]["source"]["block"] == "B0017"
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_writes_leave_no_partial_files_behind(store: StagingStore, doc: ParsedDocument) -> None:
    store.put(make_candidate(doc))
    assert list(store.root.rglob(".tmp-*")) == []


def test_everything_written_stays_under_the_research_directory(
    store: StagingStore, doc: ParsedDocument
) -> None:
    store.put(make_candidate(doc))
    assert store.root.is_relative_to(store.research_dir)
    assert store.research_dir.name == ".research"


def test_a_missing_candidate_is_an_error_not_an_empty_object(store: StagingStore) -> None:
    with pytest.raises(CandidateNotFoundError):
        store.get("cand_ffffffffffffffff")


def test_an_id_that_is_not_a_candidate_id_is_refused(store: StagingStore) -> None:
    with pytest.raises(StagingError, match="is not a candidate id"):
        store.get("../../etc/passwd")


def test_listing_filters_by_work_status_and_field(store: StagingStore, doc: ParsedDocument) -> None:
    dataset = make_candidate(doc)
    other = make_candidate(
        doc,
        candidate_id="cand_fedcba9876543210",
        field="method_summary",
        evidence=make_evidence(doc, field="method_summary"),
    )
    store.put(dataset)
    store.put(other)

    assert len(store.list()) == 2
    assert store.list(work=WORK) == [dataset, other]
    assert store.list(field="method_summary") == [other]
    assert store.list(status=CandidateStatus.VERIFIED) == []
    assert store.works() == [WORK]


def test_an_empty_store_lists_nothing(store: StagingStore) -> None:
    assert store.list() == []
    assert store.works() == []


# ---------------------------------------------------------------------- lifecycle


def test_marking_verified_transitions_the_evidence_and_records_the_verifier(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)
    store.put(candidate)

    updated = store.mark_verified(candidate.candidate_id, verification(), "scripted/model-v")

    assert updated.status is CandidateStatus.VERIFIED
    assert updated.verifier == "scripted/model-v"
    assert updated.evidence.status is EvidenceStatus.VERIFIED
    assert updated.evidence.verification.verdict is VerificationVerdict.SUPPORTED
    assert updated.evidence.verification.accepted_by is None
    assert store.get(candidate.candidate_id) == updated
    assert updated.updated_at >= candidate.updated_at


def test_marking_reviewed_records_the_action_without_accepting_anything(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)
    store.put(candidate)
    store.mark_verified(candidate.candidate_id, verification(), "scripted/model-v")

    reviewed = store.mark_reviewed(candidate.candidate_id, ReviewAction.ACCEPT)

    assert reviewed.status is CandidateStatus.REVIEWED
    assert reviewed.review_action is ReviewAction.ACCEPT
    assert reviewed.evidence.status is EvidenceStatus.VERIFIED, "acceptance is not staging's job"


def test_marking_invalid_keeps_the_candidate_for_the_reviewer(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)
    store.put(candidate)

    invalid = store.mark_invalid(candidate.candidate_id, "anchor went stale")

    assert invalid.status is CandidateStatus.INVALID
    assert store.list(status=CandidateStatus.INVALID) == [invalid]


def test_deleting_a_candidate_removes_only_that_file(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)
    store.put(candidate)

    assert store.delete(candidate.candidate_id) is True
    assert store.delete(candidate.candidate_id) is False
    assert store.list() == []


def test_putting_the_same_candidate_twice_replaces_it(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)
    store.put(candidate)
    store.put(candidate.touch(status=CandidateStatus.INVALID))

    assert len(store.list()) == 1
    assert store.get(candidate.candidate_id).status is CandidateStatus.INVALID


def test_an_unreadable_candidate_file_is_skipped_not_fatal(
    store: StagingStore, doc: ParsedDocument
) -> None:
    candidate = make_candidate(doc)
    path = store.put(candidate)
    (path.parent / "cand_aaaaaaaaaaaaaaaa.json").write_text("{ not json", encoding="utf-8")

    assert store.list() == [candidate]
