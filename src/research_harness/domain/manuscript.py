"""Manuscript anchors and audit findings (Product 30).

The manuscript is downstream of the accepted research graph: every substantive sentence
should resolve to a Claim, and every Claim to evidence at an exact source location.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from research_harness.domain.base import (
    DomainModel,
    NonEmptyStr,
    Sha256,
    TrackedObject,
)
from research_harness.domain.enums import (
    FindingSeverity,
    ManuscriptAnchorStatus,
    ManuscriptFindingKind,
    StaleState,
)
from research_harness.domain.ids import ClaimId, ResearchId

__all__ = ["FindingLocation", "ManuscriptAnchor", "ManuscriptAuditFinding"]


class ManuscriptAnchor(TrackedObject):
    """A mapping from one manuscript sentence to the Claim it asserts (Product 30.1).

    ``file`` is an opaque workspace-relative path string; the domain layer never touches
    the filesystem. The sentence fingerprint detects edits that invalidate the anchor.
    """

    file: NonEmptyStr
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(default=0, ge=0)
    sentence: NonEmptyStr
    sentence_fingerprint: Sha256
    claim: ClaimId
    citation_keys: tuple[str, ...] = ()
    status: ManuscriptAnchorStatus = ManuscriptAnchorStatus.VALID
    stale: StaleState = StaleState.FRESH

    @model_validator(mode="after")
    def _spans_are_ordered(self) -> ManuscriptAnchor:
        if self.line_end < self.line_start:
            raise ValueError("line_end must not precede line_start")
        if self.char_end < self.char_start:
            raise ValueError("char_end must not precede char_start")
        return self


class FindingLocation(DomainModel):
    """Where in the manuscript a finding was raised, structurally rather than in prose.

    A finding about an unattached sentence carries no anchor, so without this the only
    record of *where* it happened is the ``"<file>:<line>: "`` prefix of the message. An
    editor should not have to parse prose to place a diagnostic (Product 28, 30.3).
    """

    file: NonEmptyStr
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    char_start: int = Field(default=0, ge=0)
    char_end: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _spans_are_ordered(self) -> FindingLocation:
        if self.line_end < self.line_start:
            raise ValueError("line_end must not precede line_start")
        if self.char_end < self.char_start:
            raise ValueError("char_end must not precede char_start")
        return self

    def covers_line(self, line: int) -> bool:
        """True when ``line`` falls inside this location's line range."""
        return self.line_start <= line <= self.line_end

    def overlaps(self, *, line_start: int, line_end: int) -> bool:
        """True when this location shares at least one line with ``[start, end]``."""
        return self.line_start <= line_end and line_start <= self.line_end


class ManuscriptAuditFinding(DomainModel):
    """One manuscript audit result (Product 30.3).

    Findings are reported, never auto-corrected: unresolved support becomes a visible
    warning rather than a fabricated citation.
    """

    kind: ManuscriptFindingKind
    severity: FindingSeverity = FindingSeverity.WARNING
    message: NonEmptyStr
    anchor: ManuscriptAnchor | None = None
    related: tuple[ResearchId, ...] = ()
    location: FindingLocation | None = None
    """Where the finding was raised. Absent only for a finding no sentence produced."""
    sentence: str | None = None
    """The manuscript sentence the finding is about, verbatim.

    A finding with an anchor already carries its sentence through that anchor; one raised
    against an unattached sentence carries no anchor at all, and the only record of what
    the audit was reading was a truncated copy quoted inside the message. A reader is owed
    their own prose before a verdict on it, so the sentence is a field like ``location`` is
    rather than something a client has to recover from prose.
    """
