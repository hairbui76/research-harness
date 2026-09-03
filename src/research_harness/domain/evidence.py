"""Evidence, numeric evidence, verification records, and interpretations (Product 9-12).

Evidence cannot exist without a complete source anchor: work, version, artifact, file
hash, block, and text hash are all required. Numbers are never naked: they carry metric,
dataset or condition, and table provenance.
"""

from __future__ import annotations

import re

from pydantic import Field, model_validator

from research_harness.domain.base import (
    CanonicalObject,
    DomainModel,
    NonEmptyStr,
    Sha256,
    UtcDatetime,
)
from research_harness.domain.document import BoundingBox
from research_harness.domain.enums import (
    INTERPRETIVE_ORIGINS,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    EvidenceType,
    NegativeEvidenceState,
    ReviewAction,
    ReviewTier,
    StaleState,
    VerificationVerdict,
)
from research_harness.domain.ids import (
    ArtifactId,
    BlockId,
    DecisionId,
    EvidenceId,
    InterpretationId,
    VersionId,
    WorkId,
)

__all__ = [
    "Evidence",
    "EvidenceContent",
    "Interpretation",
    "NumericValue",
    "SourceAnchor",
    "VerificationRecord",
    "normalize_label",
]

_LABEL_SEPARATORS = re.compile(r"[\s_-]+")


def normalize_label(value: str) -> str:
    """One spelling per category: casefolded, with `_`, `-` and whitespace collapsed.

    A schema declares `raw sequential` and a taxonomy may spell the same term
    `raw_sequential`; the vocabulary is one vocabulary, so `EvidenceContent.labels`
    compares under this normalization everywhere (dogfood F13).
    """
    return _LABEL_SEPARATORS.sub(" ", value).strip().casefold()


class SourceAnchor(DomainModel):
    """Exact source location of an evidence object (Product 9).

    Work, version, artifact, file hash, block, and text hash are mandatory: an evidence
    object that cannot be reopened at its source is not evidence.
    """

    work: WorkId
    version: VersionId
    artifact: ArtifactId
    file_hash: Sha256
    block: BlockId
    text_hash: Sha256
    page: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    bbox: BoundingBox | None = None

    @model_validator(mode="after")
    def _char_span_is_complete(self) -> SourceAnchor:
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start and char_end must be given together")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must not precede char_start")
        return self


class NumericValue(DomainModel):
    """A measured value with the provenance a number needs (Product 12).

    The writer must never silently change metric, unit, dataset, condition, rounding, or
    denominator, so all of those travel with the value.
    """

    raw: NonEmptyStr
    parsed: float
    unit: str | None = None
    metric: NonEmptyStr
    dataset: str | None = None
    condition: dict[str, str] = Field(default_factory=dict)
    source_table: NonEmptyStr
    source_row: str | None = None
    source_column: str | None = None

    @model_validator(mode="after")
    def _not_a_naked_number(self) -> NumericValue:
        """A number needs a metric, a dataset or condition, and table provenance."""
        if not self.dataset and not self.condition:
            raise ValueError("numeric evidence requires a dataset or an experimental condition")
        return self


class EvidenceContent(DomainModel):
    """What the evidence says: exact text, optional number, optional absence state."""

    exact_text: str = ""
    numeric: NumericValue | None = None
    negative_state: NegativeEvidenceState | None = None
    field: str | None = None
    """Interrogation field this evidence answers, when it came from a schema question."""
    labels: tuple[str, ...] = ()
    """Categories this answer places the work in, from the field's declared vocabulary.

    A categorical answer used to be a quoted span and nothing else, so the category was
    re-derived much later by keyword rules at matrix-build time and a classification was
    only as good as a substring match (dogfood F13). A label here is the extractor's
    proposal, checked against the field's declared categories and reviewed like everything
    else; it never replaces the reproducible `ClassificationRule` cross-check.
    """

    @model_validator(mode="after")
    def _text_required_unless_negative(self) -> EvidenceContent:
        if not self.exact_text.strip() and self.negative_state is None:
            raise ValueError("evidence content requires exact_text unless it records absence")
        return self


class VerificationRecord(DomainModel):
    """Lifecycle status plus who proposed, verified, and accepted the object.

    Model confidence is deliberately absent: it is never an input to acceptance.
    """

    status: EvidenceStatus = EvidenceStatus.PROPOSED
    verdict: VerificationVerdict | None = None
    extractor: str | None = None
    verifier: str | None = None
    accepted_by: str | None = None
    review_action: ReviewAction | None = None
    rationale: str | None = None
    reviewed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _accepted_needs_an_acceptor(self) -> VerificationRecord:
        if self.status is EvidenceStatus.ACCEPTED and not self.accepted_by:
            raise ValueError("accepted state requires accepted_by")
        return self


class Evidence(CanonicalObject):
    """Source-grounded evidence with epistemic classification (Product 9)."""

    id: EvidenceId
    source: SourceAnchor
    content: EvidenceContent
    origin: EvidenceOrigin
    evidence_type: EvidenceType
    strength: EvidenceStrength
    verification: VerificationRecord = VerificationRecord()
    stale: StaleState = StaleState.FRESH
    review_tier: ReviewTier = ReviewTier.TIER_1
    qualification: str | None = None
    decisions: tuple[DecisionId, ...] = ()
    """Decisions that authorised an epistemic change, e.g. promotion to `absent`."""

    @model_validator(mode="after")
    def _stale_flag_matches_status(self) -> Evidence:
        if self.verification.status is EvidenceStatus.STALE and self.stale is StaleState.FRESH:
            raise ValueError("evidence with status 'stale' must be marked stale")
        return self

    @property
    def is_interpretive(self) -> bool:
        """True when accepting this evidence is an interpretive judgement (human only)."""
        return self.origin in INTERPRETIVE_ORIGINS or self.review_tier is ReviewTier.TIER_2

    @property
    def status(self) -> EvidenceStatus:
        """Shorthand for ``verification.status``."""
        return self.verification.status


class Interpretation(CanonicalObject):
    """A derived reading of one or more Evidence objects (Product 7.1).

    An interpretation is never `source_observed`: reading meaning into evidence is an
    interpretive act and is reviewed as one.
    """

    id: InterpretationId
    evidence: tuple[EvidenceId, ...] = Field(min_length=1)
    text: NonEmptyStr
    origin: EvidenceOrigin
    verification: VerificationRecord = VerificationRecord()
    stale: StaleState = StaleState.FRESH
    review_tier: ReviewTier = ReviewTier.TIER_2
    qualification: str | None = None

    @model_validator(mode="after")
    def _origin_is_interpretive(self) -> Interpretation:
        if self.origin not in INTERPRETIVE_ORIGINS:
            allowed = ", ".join(sorted(origin.value for origin in INTERPRETIVE_ORIGINS))
            raise ValueError(f"interpretation origin must be one of: {allowed}")
        return self

    @property
    def is_interpretive(self) -> bool:
        """Always True; interpretations are Tier 2 by construction."""
        return True

    @property
    def status(self) -> EvidenceStatus:
        """Shorthand for ``verification.status``."""
        return self.verification.status
