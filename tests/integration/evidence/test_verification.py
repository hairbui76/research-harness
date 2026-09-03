"""ROADMAP Task 6.2: verification is independent, quoted, and still has no authority.

The two acceptance requirements are the first two sections. The verifier is not given the
extractor's hidden reasoning — its request carries the source spans and the candidate's
assertion and nothing else — and a paper or dataset name alone cannot establish a property
the source does not state, which is enforced deterministically: a supporting verdict whose
quote does not occur in the supplied context is downgraded to `insufficient_evidence`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import EvidenceStatus, VerificationVerdict
from research_harness.evidence.extraction import extract_candidates
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.evidence.staging import (
    CandidateStatus,
    EvidenceCandidate,
    StagingStore,
)
from research_harness.evidence.verification import (
    QUOTE_NOT_IN_SOURCE,
    build_source_context,
    verify_candidate,
)
from research_harness.providers.models.base import ModelRequest
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.roles.contracts import HIDDEN_REASONING_FIELDS, InputKind
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.models import StageStatus
from research_harness.workflows.verify import run_verification, verify_stage_name
from research_harness.workspace.repository import WorkspaceRepository
from tests.integration.evidence.conftest import (
    DATASET_SENTENCE,
    WORK,
    canonical_digest,
    dataset_candidate,
    extraction_dict,
    metric_candidate,
)

RUN_ID = "run_20260101T000000Z_deadbeef"
EXTRACTOR_RATIONALE = "The experiments section names the corpus."


def verdict_dict(
    verdict: VerificationVerdict,
    *,
    quoted_support: str | None = DATASET_SENTENCE,
    rationale: str = "The span states the candidate.",
    discrepancies: Sequence[str] = (),
) -> dict[str, Any]:
    """One `VerificationOutput` payload as a verifier would emit it."""
    return {
        "verdict": verdict.value,
        "rationale": rationale,
        "quoted_support": quoted_support,
        "discrepancies": list(discrepancies),
    }


def stage_dataset_candidate(
    doc: ParsedDocument, staging: StagingStore | None = None
) -> EvidenceCandidate:
    """One proposed candidate, produced by the real extraction path."""
    provider = ScriptedProvider(
        [extraction_dict([dataset_candidate(doc)])], name="scripted-a", model="model-a"
    )
    result = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["dataset"], staging=staging
    )
    (candidate,) = result.candidates
    assert candidate.extraction.rationale == EXTRACTOR_RATIONALE
    return candidate


def _verifier(*payloads: dict[str, Any]) -> ScriptedProvider:
    return ScriptedProvider(list(payloads), name="scripted-v", model="model-v")


def rendered(request: ModelRequest[Any]) -> str:
    """Everything the request would put in front of a model."""
    return "\n".join([request.instructions, *(item.content for item in request.inputs)])


def supplied_content(request: ModelRequest[Any]) -> str:
    """Only the research content, without the role's own standing instructions."""
    return "\n".join(item.content for item in request.inputs)


# ------------------------------------------- the verifier is not given the extractor


def test_the_verifier_sees_the_source_and_the_candidate_but_not_the_extractor(
    doc: ParsedDocument,
) -> None:
    candidate = stage_dataset_candidate(doc)
    provider = _verifier(verdict_dict(VerificationVerdict.SUPPORTED))

    verify_candidate(candidate, doc, provider)

    (request,) = provider.requests
    assert DATASET_SENTENCE in rendered(request), "the candidate's quoted text must reach it"
    supplied = supplied_content(request)
    assert "labelled capture of benign and attack traffic" in supplied, "source block missing"
    assert EXTRACTOR_RATIONALE not in supplied
    assert "scripted-a/model-a" not in supplied, "the proposing model must stay hidden"
    lowered = supplied.lower()
    assert "rationale" not in lowered, "no extractor justification travels with the candidate"
    for name in HIDDEN_REASONING_FIELDS:
        assert name not in lowered


def test_the_candidate_payload_omits_every_extractor_judgement(doc: ParsedDocument) -> None:
    candidate = stage_dataset_candidate(doc)

    inputs = build_source_context(doc, candidate)

    kinds = [item.kind for item in inputs]
    assert kinds == [InputKind.CANDIDATE_EVIDENCE, InputKind.DOCUMENT_BLOCKS]
    payload = inputs[0].content
    assert isinstance(payload, dict)
    assert set(payload) == {"field", "exact_text", "block", "page", "char_start", "char_end"}
    assert "origin" not in payload
    assert "evidence_type" not in payload
    assert "strength" not in payload
    assert "rationale" not in payload


def test_the_source_context_carries_the_neighbouring_blocks_in_reading_order(
    doc: ParsedDocument,
) -> None:
    candidate = stage_dataset_candidate(doc)

    inputs = build_source_context(doc, candidate, neighbors=1)

    blocks = inputs[1].content
    assert isinstance(blocks, dict)
    ids = [item["block"] for item in blocks["blocks"]]
    assert ids == ["B0016", "B0017", "B0018"]


def test_a_table_candidate_keeps_its_cells_in_the_source_context(doc: ParsedDocument) -> None:
    provider = ScriptedProvider(
        [extraction_dict([metric_candidate(doc)])], name="scripted-a", model="model-a"
    )
    (candidate,) = extract_candidates(
        doc, DEFAULT_SCHEMA, provider, run_id=RUN_ID, fields=["metric_result"]
    ).candidates

    inputs = build_source_context(doc, candidate, neighbors=0)

    blocks = inputs[1].content
    assert isinstance(blocks, dict)
    (table,) = blocks["blocks"]
    assert {"row": 1, "col": 2, "text": "94.32", "char_start": 58, "char_end": 63} in table["cells"]


# --------------------------------------------------------------------- verdict mapping


@pytest.mark.parametrize("verdict", list(VerificationVerdict))
def test_every_verdict_lands_on_the_candidate_and_its_evidence(
    doc: ParsedDocument, verdict: VerificationVerdict
) -> None:
    candidate = stage_dataset_candidate(doc)
    quote = None if verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE else DATASET_SENTENCE
    provider = _verifier(verdict_dict(verdict, quoted_support=quote))

    verified = verify_candidate(candidate, doc, provider)

    assert verified.status is CandidateStatus.VERIFIED
    assert verified.verification is not None
    assert verified.verification.verdict is verdict
    assert verified.verifier == "scripted-v/model-v"
    assert verified.evidence.status is EvidenceStatus.VERIFIED
    assert verified.evidence.verification.verdict is verdict
    assert verified.evidence.verification.verifier == "scripted-v/model-v"
    assert verified.evidence.verification.accepted_by is None, "verification is not acceptance"


def test_a_contradiction_keeps_its_discrepancies(doc: ParsedDocument) -> None:
    candidate = stage_dataset_candidate(doc)
    provider = _verifier(
        verdict_dict(
            VerificationVerdict.CONTRADICTED,
            rationale="The span names a different corpus.",
            discrepancies=["dataset mismatch"],
        )
    )

    verified = verify_candidate(candidate, doc, provider)

    assert verified.verification is not None
    assert verified.verification.discrepancies == ["dataset mismatch"]


# ------------------------------------------------ a familiar name establishes nothing


@pytest.mark.parametrize(
    "verdict", [VerificationVerdict.SUPPORTED, VerificationVerdict.PARTIALLY_SUPPORTED]
)
def test_a_quote_absent_from_the_source_downgrades_the_verdict(
    doc: ParsedDocument, verdict: VerificationVerdict
) -> None:
    """Answering from knowledge of CICIDS2017 produces a quote the paper does not contain."""
    candidate = stage_dataset_candidate(doc)
    provider = _verifier(
        verdict_dict(
            verdict,
            quoted_support="CICIDS2017 contains encrypted TLS 1.3 traffic captured in 2023",
            rationale="The dataset is well known to contain this traffic.",
        )
    )

    verified = verify_candidate(candidate, doc, provider)

    assert verified.verification is not None
    assert verified.verification.verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE
    assert QUOTE_NOT_IN_SOURCE in verified.verification.discrepancies
    assert verified.evidence.verification.verdict is VerificationVerdict.INSUFFICIENT_EVIDENCE


def test_a_real_quote_survives_line_wrapping_and_whitespace(doc: ParsedDocument) -> None:
    candidate = stage_dataset_candidate(doc)
    provider = _verifier(
        verdict_dict(
            VerificationVerdict.SUPPORTED, quoted_support="All  experiments\nuse\nCICIDS2017"
        )
    )

    verified = verify_candidate(candidate, doc, provider)

    assert verified.verification is not None
    assert verified.verification.verdict is VerificationVerdict.SUPPORTED
    assert verified.verification.discrepancies == []


# ------------------------------------------------------------------------- workflow


def test_run_verification_writes_verdicts_back_to_staging_only(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    candidate = stage_dataset_candidate(doc, staging)
    before = canonical_digest(workspace.root)
    provider = _verifier(verdict_dict(VerificationVerdict.SUPPORTED))

    report = run_verification(engine, staging, workspace, WORK, provider)

    assert report.verdicts == {candidate.candidate_id: VerificationVerdict.SUPPORTED}
    assert staging.get(candidate.candidate_id).status is CandidateStatus.VERIFIED
    assert canonical_digest(workspace.root) == before
    assert not workspace.layout.evidence_file(WORK).exists()
    assert list(workspace.iter_evidence(WORK)) == []


def test_rerunning_verification_skips_candidates_that_already_have_a_verdict(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    candidate = stage_dataset_candidate(doc, staging)
    provider = _verifier(verdict_dict(VerificationVerdict.SUPPORTED))
    first = run_verification(engine, staging, workspace, WORK, provider)
    assert len(provider.requests) == 1

    again = run_verification(engine, staging, workspace, WORK, provider)

    assert again.skipped == []
    assert again.candidates == []
    assert len(provider.requests) == 1, "a verified candidate is not re-verified"
    assert staging.get(candidate.candidate_id).verification is not None
    assert first.run.stage(verify_stage_name(candidate.candidate_id)).status is (
        StageStatus.succeeded
    )


def test_naming_a_verified_candidate_explicitly_still_does_not_re_verify_it(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    candidate = stage_dataset_candidate(doc, staging)
    provider = _verifier(verdict_dict(VerificationVerdict.SUPPORTED))
    run_verification(engine, staging, workspace, WORK, provider)

    again = run_verification(
        engine, staging, workspace, WORK, provider, candidate_ids=[candidate.candidate_id]
    )

    assert again.skipped == [candidate.candidate_id]
    assert len(provider.requests) == 1


def test_a_second_opinion_is_available_but_must_be_asked_for(
    doc: ParsedDocument,
    engine: WorkflowEngine,
    staging: StagingStore,
    workspace: WorkspaceRepository,
) -> None:
    candidate = stage_dataset_candidate(doc, staging)
    first = _verifier(verdict_dict(VerificationVerdict.SUPPORTED))
    run_verification(engine, staging, workspace, WORK, first)

    second = ScriptedProvider(
        [
            verdict_dict(
                VerificationVerdict.PARTIALLY_SUPPORTED,
                rationale="The span names the corpus but not the split.",
                discrepancies=["split not stated"],
            )
        ],
        name="scripted-w",
        model="model-w",
    )
    report = run_verification(
        engine,
        staging,
        workspace,
        WORK,
        second,
        candidate_ids=[candidate.candidate_id],
        force=True,
    )

    assert report.verdicts[candidate.candidate_id] is VerificationVerdict.PARTIALLY_SUPPORTED
    assert staging.get(candidate.candidate_id).verifier == "scripted-w/model-w"
