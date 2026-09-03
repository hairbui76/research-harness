"""Role output schemas carry epistemic rules a prompt cannot enforce.

A model that answers with `absent`, calls quoted text `researcher_inferred`, claims
support without quoting the source, or pads a rationale into a reasoning trace is
rejected before its answer can reach staging (ADR-003, ADR-005).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from research_harness.domain.enums import (
    ClaimScope,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    NegativeEvidenceState,
    VerificationVerdict,
)
from research_harness.roles import (
    RATIONALE_MAX_CHARS,
    CellProposal,
    ClaimAuditOutput,
    EvidenceCandidateOutput,
    ExtractionOutput,
    QualifierNote,
    RoleOutput,
    SkepticOutput,
    SynthesisOutput,
    VerificationOutput,
    WriterOutput,
)

CANDIDATE: dict[str, Any] = {
    "exact_text": "we measure 1.4 Gbps on CIC-IDS2017",
    "page": 7,
    "block": "B0042",
    "char_start": 0,
    "char_end": 34,
    "origin": EvidenceOrigin.SOURCE_OBSERVED,
    "evidence_type": EvidenceType.EXPERIMENTAL_RESULT,
    "strength": EvidenceStrength.DIRECT,
    "field": "throughput",
}

AUDIT: dict[str, Any] = {
    "support": ["E0001"],
    "coverage_state": "12 of 40 relevant works examined, 6 unresolved",
    "recommended_scope": ClaimScope.OBSERVED_SUBSET,
    "maximum_defensible_wording": "In the 12 examined systems, throughput exceeded 1 Gbps.",
    "rationale": "Support is limited to the examined subset.",
}

#: Fingerprints of the schemas persisted with every role result (Product 20.5).
#: Update deliberately: a change here invalidates the reproducibility metadata of
#: results already recorded against the old schema.
#:
#: `ExtractionOutput` and `SkepticOutput` both changed when `EvidenceCandidateOutput` gained
#: `labels` (dogfood F13): a categorical answer now carries its category, so both schemas
#: that embed a candidate are a new shape.
SCHEMA_FINGERPRINTS: dict[str, str] = {
    "ExtractionOutput": "b9b83baf6a1b4d7af9420a6596579907aa8c0c31f5530a24aaae8ae7f4709a14",
    "VerificationOutput": "466d12b4911a824e9f42669d39791c3f25cbdb0e3d0e5d032e909a54e84b610b",
    "SkepticOutput": "e9bf23e2515aaf01bed241d7a5c768a551e76220c957675bc1f67d8b047190e9",
    "ClaimAuditOutput": "fc89e6948bca4a1878dd988a0f0aeb5814705cf5ad2236ca3cc8bf2663afb7d6",
    "SynthesisOutput": "cc8c481c7383df2c9473a014ab420bacf3ea1b1c261788d9a8878b589117a93f",
    "WriterOutput": "2e48b14de495977534ecdf4aa045f3120a25a08a5ed3d63aee267acc0ac43d36",
}

ROLE_SCHEMAS: tuple[type[RoleOutput], ...] = (
    ExtractionOutput,
    VerificationOutput,
    SkepticOutput,
    ClaimAuditOutput,
    SynthesisOutput,
    WriterOutput,
)


# ------------------------------------------------------------------- epistemic rules


def test_a_model_cannot_report_evidence_as_researcher_inferred() -> None:
    """Inference is a researcher's act; a model may only classify what the text does."""
    with pytest.raises(ValidationError, match="researcher_inferred"):
        EvidenceCandidateOutput(**{**CANDIDATE, "origin": EvidenceOrigin.RESEARCHER_INFERRED})


@pytest.mark.parametrize(
    "origin",
    [EvidenceOrigin.MODEL_PROPOSED, EvidenceOrigin.EXTERNAL_METADATA],
)
def test_a_model_cannot_relabel_quoted_text_with_a_provenance_origin(
    origin: EvidenceOrigin,
) -> None:
    with pytest.raises(ValidationError):
        EvidenceCandidateOutput(**{**CANDIDATE, "origin": origin})


@pytest.mark.parametrize(
    "origin",
    [
        EvidenceOrigin.SOURCE_OBSERVED,
        EvidenceOrigin.AUTHOR_CLAIMED,
        EvidenceOrigin.AUTHOR_INTERPRETED,
    ],
)
def test_observable_origins_are_accepted(origin: EvidenceOrigin) -> None:
    assert EvidenceCandidateOutput(**{**CANDIDATE, "origin": origin}).origin is origin


def test_a_model_cannot_conclude_absent() -> None:
    """`absent` is an audited conclusion, never an extraction result (Product 11, P5)."""
    with pytest.raises(ValidationError, match="audited conclusion"):
        EvidenceCandidateOutput(
            block="B0042",
            origin=EvidenceOrigin.SOURCE_OBSERVED,
            evidence_type=EvidenceType.DATASET_DESCRIPTION,
            strength=EvidenceStrength.INDIRECT,
            field="dataset",
            negative_state=NegativeEvidenceState.ABSENT,
        )


@pytest.mark.parametrize(
    "state",
    [
        NegativeEvidenceState.NOT_FOUND,
        NegativeEvidenceState.NOT_REPORTED,
        NegativeEvidenceState.NOT_APPLICABLE,
        NegativeEvidenceState.UNCLEAR,
    ],
)
def test_reportable_absence_states_need_no_quoted_span(state: NegativeEvidenceState) -> None:
    candidate = EvidenceCandidateOutput(
        block="B0042",
        origin=EvidenceOrigin.SOURCE_OBSERVED,
        evidence_type=EvidenceType.DATASET_DESCRIPTION,
        strength=EvidenceStrength.INDIRECT,
        field="dataset",
        negative_state=state,
    )
    assert candidate.negative_state is state


def test_quoted_evidence_requires_an_exact_span() -> None:
    with pytest.raises(ValidationError, match="char_start"):
        EvidenceCandidateOutput(**{**CANDIDATE, "char_start": None, "char_end": None})
    with pytest.raises(ValidationError, match="together"):
        EvidenceCandidateOutput(**{**CANDIDATE, "char_end": None})
    with pytest.raises(ValidationError, match="precede"):
        EvidenceCandidateOutput(**{**CANDIDATE, "char_start": 40, "char_end": 4})


def test_a_candidate_block_must_be_a_real_block_id() -> None:
    with pytest.raises(ValidationError, match="BlockId"):
        EvidenceCandidateOutput(**{**CANDIDATE, "block": "the results section"})


def test_a_field_cannot_be_answered_and_reported_missing() -> None:
    with pytest.raises(ValidationError, match="not found"):
        ExtractionOutput(
            candidates=[EvidenceCandidateOutput(**CANDIDATE)],
            fields_not_found=["throughput"],
        )


def test_an_extraction_may_answer_nothing() -> None:
    output = ExtractionOutput(fields_not_found=["throughput", "dataset"])
    assert output.candidates == []


def test_a_verdict_about_the_source_must_quote_the_source() -> None:
    for verdict in (
        VerificationVerdict.SUPPORTED,
        VerificationVerdict.PARTIALLY_SUPPORTED,
        VerificationVerdict.CONTRADICTED,
    ):
        with pytest.raises(ValidationError, match="quoted_support"):
            VerificationOutput(verdict=verdict, rationale="the table says so")


def test_insufficient_evidence_needs_no_quote() -> None:
    output = VerificationOutput(
        verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
        rationale="The span names the dataset but reports no throughput.",
    )
    assert output.quoted_support is None
    assert output.discrepancies == []


def test_audit_and_writer_references_must_be_real_ids() -> None:
    """A fabricated reference is caught here, not after it reaches a manuscript."""
    with pytest.raises(ValidationError, match="EvidenceId"):
        ClaimAuditOutput(**{**AUDIT, "support": ["Smith et al. 2020"]})
    with pytest.raises(ValidationError, match="ClaimId"):
        WriterOutput(draft="text", claim_refs=["the throughput claim"])
    with pytest.raises(ValidationError, match="EvidenceId"):
        QualifierNote(text="only on encrypted traffic", evidence_refs=["table 3"])


def test_a_synthesis_cell_is_multi_label_and_evidence_linked() -> None:
    cell = CellProposal(
        work="W0003", field="representation", labels=["packet", "flow"], evidence=["E0009"]
    )
    assert cell.labels == ["packet", "flow"]
    with pytest.raises(ValidationError):
        CellProposal(work="W0003", field="representation", labels=[])


def test_a_writer_flags_gaps_instead_of_inventing_support() -> None:
    output = WriterOutput(
        draft="Reported throughput exceeds 1 Gbps [NEEDS SOURCE].",
        claim_refs=["C0004"],
        evidence_refs=["E0009"],
        unsupported_statements=["Reported throughput exceeds 1 Gbps."],
        needs_source=["throughput on unencrypted traffic"],
    )
    assert output.needs_source == ["throughput on unencrypted traffic"]


# ------------------------------------------------------------- shape and stability


def test_rationale_is_capped_so_it_cannot_become_a_reasoning_trace() -> None:
    assert VerificationOutput(
        verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE, rationale="x" * RATIONALE_MAX_CHARS
    ).rationale == ("x" * RATIONALE_MAX_CHARS)
    with pytest.raises(ValidationError, match="at most 600 characters"):
        VerificationOutput(
            verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
            rationale="x" * (RATIONALE_MAX_CHARS + 1),
        )
    with pytest.raises(ValidationError):
        SkepticOutput(rationale="   ")


@pytest.mark.parametrize("schema", ROLE_SCHEMAS, ids=lambda schema: schema.__name__)
def test_unknown_keys_are_rejected(schema: type[RoleOutput]) -> None:
    """A model that answers with an extra field, such as a reasoning trace, is invalid."""
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        schema.model_validate({"chain_of_thought": "step 1..."})


def test_a_candidate_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        EvidenceCandidateOutput(**{**CANDIDATE, "confidence": 0.97})


@pytest.mark.parametrize("schema", ROLE_SCHEMAS, ids=lambda schema: schema.__name__)
def test_schema_fingerprints_are_stable(schema: type[RoleOutput]) -> None:
    fingerprint = schema.json_schema_fingerprint()
    assert fingerprint == SCHEMA_FINGERPRINTS[schema.__name__], (
        f"{schema.__name__} changed shape; update SCHEMA_FINGERPRINTS deliberately, "
        "because results recorded against the old schema keep the old fingerprint"
    )
    assert fingerprint == schema.json_schema_fingerprint()


def test_schema_fingerprints_distinguish_the_roles() -> None:
    assert len(set(SCHEMA_FINGERPRINTS.values())) == len(ROLE_SCHEMAS)
