"""The canonical record of a refused evidence candidate (Product 24.3, ADR-003).

A rejection is a scientific act: the researcher looked at a proposal, at its source span,
and decided the source does not establish it. That decision has to survive the staging tree
it was taken against, or the same wrong proposal comes back on the next interrogation run
with nothing to say it was already refused.

So a rejection is written to `corpus/works/W####/rejections.jsonl` — append-only, beside the
`evidence.jsonl` it was kept *out of*. It is deliberately not an `Evidence` object: a
rejected candidate never becomes canonical evidence, and giving it an `EvidenceId` would
say the opposite. It carries the exact anchor instead, which is what lets the Review Inbox
recognise a re-proposed candidate as previously rejected.
"""

from __future__ import annotations

from pydantic import Field

from research_harness.domain.base import SCHEMA_VERSION, DomainModel, NonEmptyStr, UtcDatetime
from research_harness.domain.enums import (
    EvidenceOrigin,
    EvidenceType,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.evidence import SourceAnchor
from research_harness.domain.ids import WorkId

__all__ = ["REJECTIONS_FILENAME", "RejectionRecord"]

REJECTIONS_FILENAME = "rejections.jsonl"


class RejectionRecord(DomainModel):
    """One refused evidence candidate, kept with the Work it was proposed for.

    `candidate_id` is the staging id the proposal carried; `anchor` is the span it quoted.
    Either identifies a repeat proposal, which is why both are recorded: staging is
    disposable, so a rebuilt candidate id is only recognisable while the anchor matches.
    """

    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    candidate_id: NonEmptyStr
    anchor: SourceAnchor
    field: str | None = None
    """Interrogation field the proposal answered, when it came from a schema question."""

    reason: NonEmptyStr
    actor: NonEmptyStr
    rejected_at: UtcDatetime
    verdict: VerificationVerdict | None = None
    """The verifier's verdict at the time of rejection, when the candidate had one."""

    origin: EvidenceOrigin
    evidence_type: EvidenceType
    review_tier: ReviewTier = ReviewTier.TIER_1

    @property
    def work(self) -> WorkId:
        """The Work whose `rejections.jsonl` holds this record."""
        return self.anchor.work

    @property
    def text_hash(self) -> str:
        """Hash of the exact span that was rejected."""
        return self.anchor.text_hash
