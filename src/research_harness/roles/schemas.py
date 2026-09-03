"""Validated output schemas for every bounded role (Product 20.3).

A role returns structured data, never prose: the prose a model would have written is
presentation, and only a schema-validated object can be checked, staged, and reviewed.
Invalid output is rejected by the provider layer before it reaches staging (ADR-005).

The schemas also carry the epistemic rules that a prompt alone cannot enforce. An
extractor may not label quoted text `researcher_inferred`, because inference is a
researcher act; it may not report `absent`, because absence is an audited conclusion and
not an extraction result (Product 11, principle P5). A verifier that says the source
supports a candidate must quote the span it relied on. Every rationale is length-capped,
so a reasoning trace cannot be smuggled in as a justification.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_harness.domain.enums import (
    ClaimScope,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    NegativeEvidenceState,
    VerificationVerdict,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.evidence import NumericValue
from research_harness.domain.ids import BlockId, ClaimId, EvidenceId, ResearchId, WorkId
from research_harness.roles.contracts import Rationale, json_schema_fingerprint

__all__ = [
    "EXTRACTOR_ALLOWED_NEGATIVE_STATES",
    "EXTRACTOR_ALLOWED_ORIGINS",
    "CellProposal",
    "ClaimAuditOutput",
    "EvidenceCandidateOutput",
    "ExtractionOutput",
    "QualifierNote",
    "RoleOutput",
    "SkepticOutput",
    "SynthesisOutput",
    "VerificationOutput",
    "WriterOutput",
]

EXTRACTOR_ALLOWED_ORIGINS: frozenset[EvidenceOrigin] = frozenset(
    {
        EvidenceOrigin.SOURCE_OBSERVED,
        EvidenceOrigin.AUTHOR_CLAIMED,
        EvidenceOrigin.AUTHOR_INTERPRETED,
    }
)
"""Origins a role may assign to text it quotes.

`researcher_inferred` is excluded because inference is a researcher act; `model_proposed`
and `external_metadata` describe how a record was produced, which is provenance, not what
the source says (Product 9.1, ADR-003).
"""

EXTRACTOR_ALLOWED_NEGATIVE_STATES: frozenset[NegativeEvidenceState] = frozenset(
    {
        NegativeEvidenceState.NOT_FOUND,
        NegativeEvidenceState.NOT_REPORTED,
        NegativeEvidenceState.NOT_APPLICABLE,
        NegativeEvidenceState.UNCLEAR,
    }
)
"""Absence states a model may report. `absent` is an audited conclusion, never output."""

_VERDICTS_REQUIRING_A_QUOTE: frozenset[VerificationVerdict] = frozenset(
    {
        VerificationVerdict.SUPPORTED,
        VerificationVerdict.PARTIALLY_SUPPORTED,
        VerificationVerdict.CONTRADICTED,
    }
)


class RoleOutput(BaseModel):
    """Base for every role output: closed, frozen, and fingerprintable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def json_schema_fingerprint(cls) -> str:
        """sha256 (hex) of this schema, persisted as reproducibility metadata (20.5)."""
        return json_schema_fingerprint(cls)


def _validate_ids(values: list[str], id_type: type[ResearchId], label: str) -> list[str]:
    """Reject references that are not well-formed harness ids.

    A role echoes ids it was given; anything else is invented, and an invented reference
    is caught here rather than after it has been written somewhere.
    """
    for value in values:
        try:
            id_type(value)
        except DomainValidationError as exc:
            raise ValueError(f"{label} must be {id_type.__name__} values: {exc}") from exc
    return values


class EvidenceCandidateOutput(RoleOutput):
    """One proposed evidence object, anchored in an exact span of one source block.

    A candidate has no scientific authority: it is verified independently and accepted
    only by a researcher (Product 8.3, ADR-003).
    """

    exact_text: str = ""
    page: int | None = Field(default=None, ge=1)
    block: str
    """Id of the parsed block the text came from, echoed from the supplied document."""
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    origin: EvidenceOrigin
    evidence_type: EvidenceType
    strength: EvidenceStrength
    field: str = Field(min_length=1)
    """Interrogation field this candidate answers."""
    labels: list[str] = Field(default_factory=list)
    """Categories from the field's declared vocabulary that this span places the work in.

    Optional, and checked against the schema at extraction: a label the field does not
    declare is a rejection, not a new category (Product 33). Extraction refuses labels on
    a field that declares none.
    """
    numeric: NumericValue | None = None
    negative_state: NegativeEvidenceState | None = None
    rationale: Rationale | None = None

    @field_validator("block")
    @classmethod
    def _block_is_a_block_id(cls, value: str) -> str:
        BlockId(value)
        return value

    @field_validator("origin")
    @classmethod
    def _origin_is_observable(cls, value: EvidenceOrigin) -> EvidenceOrigin:
        if value not in EXTRACTOR_ALLOWED_ORIGINS:
            allowed = ", ".join(sorted(origin.value for origin in EXTRACTOR_ALLOWED_ORIGINS))
            raise ValueError(
                f"a role may not assign origin {value.value!r} to quoted text; use one of: "
                f"{allowed}"
            )
        return value

    @field_validator("negative_state")
    @classmethod
    def _absence_is_not_extracted(
        cls, value: NegativeEvidenceState | None
    ) -> NegativeEvidenceState | None:
        if value is not None and value not in EXTRACTOR_ALLOWED_NEGATIVE_STATES:
            allowed = ", ".join(sorted(state.value for state in EXTRACTOR_ALLOWED_NEGATIVE_STATES))
            raise ValueError(
                f"{value.value!r} is an audited conclusion, not an extraction result; "
                f"use one of: {allowed}"
            )
        return value

    @model_validator(mode="after")
    def _anchor_is_exact(self) -> EvidenceCandidateOutput:
        """Quoted text needs a character span; an absence record has nothing to quote."""
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start and char_end must be given together")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must not precede char_start")
        if self.negative_state is None:
            if not self.exact_text.strip():
                raise ValueError("a candidate requires exact_text unless it records absence")
            if self.char_start is None:
                raise ValueError("quoted evidence requires an exact char_start/char_end span")
        return self


class ExtractionOutput(RoleOutput):
    """Everything one extraction pass produced, including what it could not answer."""

    candidates: list[EvidenceCandidateOutput] = Field(default_factory=list)
    fields_not_found: list[str] = Field(default_factory=list)
    """Interrogation fields this document does not answer; never a claim of absence."""

    @model_validator(mode="after")
    def _a_field_is_answered_or_not_found(self) -> ExtractionOutput:
        answered = {candidate.field for candidate in self.candidates}
        both = sorted(answered.intersection(self.fields_not_found))
        if both:
            raise ValueError(f"fields are both answered and reported not found: {', '.join(both)}")
        return self


class VerificationOutput(RoleOutput):
    """An independent verdict on one candidate, judged only from the supplied spans.

    Confidence is deliberately absent: the categorical verdict is the primary signal and
    confidence is never an acceptance input (Product 24.4, 43).
    """

    verdict: VerificationVerdict
    rationale: Rationale
    quoted_support: str | None = None
    """The span relied on, verbatim; required for any verdict about what the source says."""
    discrepancies: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _assertions_about_the_source_are_quoted(self) -> VerificationOutput:
        if self.verdict in _VERDICTS_REQUIRING_A_QUOTE and not (self.quoted_support or "").strip():
            raise ValueError(
                f"verdict {self.verdict.value!r} requires quoted_support from the source span; "
                "answer 'insufficient_evidence' when no span establishes the candidate"
            )
        return self


class QualifierNote(RoleOutput):
    """A condition that narrows a claim, tied to the evidence it rests on."""

    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)

    @field_validator("evidence_refs")
    @classmethod
    def _refs_are_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, EvidenceId, "evidence_refs")


class SkepticOutput(RoleOutput):
    """Counter-evidence, qualifiers, and incomparability found against a claim.

    Finding nothing is a real result: empty lists with a rationale beat an invented
    objection (Product 43, ROADMAP Task 7.4).
    """

    counter_candidates: list[EvidenceCandidateOutput] = Field(default_factory=list)
    qualifiers: list[QualifierNote] = Field(default_factory=list)
    incomparability_notes: list[str] = Field(default_factory=list)
    """Results that differ under different metrics/datasets/conditions are incomparable,
    not contradictory (ROADMAP Task 7.4)."""
    rationale: Rationale


class ClaimAuditOutput(RoleOutput):
    """What the accepted evidence actually defends, by evidence id.

    `recommended_scope` and `maximum_defensible_wording` are advice: only a researcher
    changes an accepted claim, and an override is recorded as a Decision (Product 38).
    """

    support: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    qualifiers: list[str] = Field(default_factory=list)
    independence_warnings: list[str] = Field(default_factory=list)
    """Shared authors, datasets, or systems that make the support less independent."""
    coverage_state: str = Field(min_length=1)
    recommended_scope: ClaimScope
    maximum_defensible_wording: str = Field(min_length=1)
    rationale: Rationale

    @field_validator("support", "counter_evidence")
    @classmethod
    def _refs_are_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, EvidenceId, "evidence references")


class CellProposal(RoleOutput):
    """One synthesis-matrix cell: a work, a field, its labels, and its evidence."""

    work: str
    field: str = Field(min_length=1)
    labels: list[str] = Field(min_length=1)
    """Multi-label by design; a cell is never forced into false exclusivity (8.2)."""
    evidence: list[str] = Field(default_factory=list)
    """Accepted evidence ids behind the cell; empty means unsupported, not implied."""

    @field_validator("work")
    @classmethod
    def _work_is_a_work_id(cls, value: str) -> str:
        WorkId(value)
        return value

    @field_validator("evidence")
    @classmethod
    def _refs_are_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, EvidenceId, "evidence")


class SynthesisOutput(RoleOutput):
    """Proposed matrix cells plus what did not fit the taxonomy."""

    cells: list[CellProposal] = Field(default_factory=list)
    notes: Rationale | None = None


class WriterOutput(RoleOutput):
    """Draft manuscript text plus everything it could not support.

    The writer flags gaps instead of filling them: an unsupported sentence is listed, not
    given an invented citation or number (Product 30, 30.2).
    """

    draft: str
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    unsupported_statements: list[str] = Field(default_factory=list)
    needs_source: list[str] = Field(default_factory=list)

    @field_validator("claim_refs")
    @classmethod
    def _refs_are_claim_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, ClaimId, "claim_refs")

    @field_validator("evidence_refs")
    @classmethod
    def _refs_are_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, EvidenceId, "evidence_refs")
