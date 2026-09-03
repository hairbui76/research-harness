"""Structured claims, evidence relations, coverage, and assessment (Product 10, 18).

A claim is not a sentence with citations: scope, coverage, and the separation between the
strength the researcher requested and the strength the evidence allows are all explicit.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from research_harness.domain.base import (
    CanonicalObject,
    DomainModel,
    NonEmptyStr,
    UtcDatetime,
    YearMonth,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
    OverturnRisk,
    StaleState,
)
from research_harness.domain.ids import ClaimId, DecisionId, EvidenceId, SearchRunId, SynthesisId

__all__ = [
    "Claim",
    "ClaimAssessment",
    "ClaimEvidenceRelation",
    "ClaimScopeSpec",
    "ClaimSemantics",
    "Coverage",
]


class ClaimSemantics(DomainModel):
    """The proposition behind the prose: subject, predicate, object, qualifiers."""

    subject: NonEmptyStr
    predicate: NonEmptyStr
    object: NonEmptyStr
    qualifier: dict[str, str] = Field(default_factory=dict)


class ClaimScopeSpec(DomainModel):
    """Where the claim is asserted to hold: ladder level, corpus, publication cutoff."""

    level: ClaimScope
    corpus: str | None = None
    publication_until: YearMonth | None = None


class ClaimEvidenceRelation(DomainModel):
    """One directed claim-evidence link (Product 10.4).

    The link is many-to-many and aspect-scoped: the same evidence may support a claim on
    one aspect and qualify it on another, so relations are edges rather than buckets.
    """

    evidence: EvidenceId
    relation: ClaimEvidenceRelationType
    aspect: str | None = None
    note: str | None = None


class Coverage(DomainModel):
    """Search coverage behind a prevalence or absence claim (Product 18).

    Coverage is what separates "we identified no work that ..." from "no work exists".
    """

    relevant_works: int = Field(default=0, ge=0)
    examined_works: int = Field(default=0, ge=0)
    unresolved_works: int = Field(default=0, ge=0)
    overturn_risk: OverturnRisk = OverturnRisk.UNKNOWN
    search_runs: tuple[SearchRunId, ...] = ()
    cutoff: date | None = None


class ClaimAssessment(DomainModel):
    """Auditor result: what was requested, what the evidence allows, and the wording.

    ``requested_strength`` is the researcher's ask and is never mutated by an audit;
    ``allowed_strength`` is the audited ceiling and can never silently exceed it.
    """

    requested_strength: ClaimScope
    allowed_strength: ClaimScope
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    maximum_defensible_wording: str | None = None
    audited_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _allowed_never_exceeds_requested(self) -> ClaimAssessment:
        if self.allowed_strength > self.requested_strength:
            raise ValueError(
                "allowed_strength "
                f"({self.allowed_strength.label}) may not exceed requested_strength "
                f"({self.requested_strength.label})"
            )
        return self


class Claim(CanonicalObject):
    """A structured research statement with scope, evidence relations, and status."""

    id: ClaimId
    statement: NonEmptyStr
    type: ClaimType
    semantics: ClaimSemantics
    scope: ClaimScopeSpec
    relations: tuple[ClaimEvidenceRelation, ...] = ()
    coverage: Coverage = Coverage()
    assessment: ClaimAssessment
    decisions: tuple[DecisionId, ...] = ()
    derived_from: tuple[SynthesisId, ...] = ()
    """Synthesis matrices this claim was read off (Product 37).

    A synthesis claim summarises a cross-paper comparison, so a change to the matrix
    makes the claim stale; recording the matrices here is what lets the dependency graph
    derive that edge from canonical state instead of being told about it.
    """

    stale: StaleState = StaleState.FRESH

    def evidence_with_relation(self, relation: ClaimEvidenceRelationType) -> tuple[EvidenceId, ...]:
        """Evidence ids linked to this claim by ``relation``, in declaration order."""
        return tuple(link.evidence for link in self.relations if link.relation is relation)

    @property
    def supporting(self) -> tuple[EvidenceId, ...]:
        """Evidence ids that support this claim."""
        return self.evidence_with_relation(ClaimEvidenceRelationType.SUPPORTS)

    @property
    def contradicting(self) -> tuple[EvidenceId, ...]:
        """Evidence ids that contradict this claim."""
        return self.evidence_with_relation(ClaimEvidenceRelationType.CONTRADICTS)

    @property
    def qualifying(self) -> tuple[EvidenceId, ...]:
        """Evidence ids that qualify this claim."""
        return self.evidence_with_relation(ClaimEvidenceRelationType.QUALIFIES)

    @property
    def requested_strength(self) -> ClaimScope:
        """Scope the researcher asked for."""
        return self.assessment.requested_strength

    @property
    def allowed_strength(self) -> ClaimScope:
        """Scope the audited evidence allows."""
        return self.assessment.allowed_strength

    @property
    def status(self) -> ClaimStatus:
        """Shorthand for ``assessment.status``."""
        return self.assessment.status
