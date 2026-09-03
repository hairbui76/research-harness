"""Work / Version / Artifact identity and pre-acceptance candidates (Product 13, 14).

A scholarly work is not a file. Citations reference a `Work`; evidence references the
exact `Version` and immutable `Artifact` it was read from.
"""

from __future__ import annotations

import datetime

from pydantic import Field, model_validator

from research_harness.domain.base import (
    CanonicalObject,
    DomainModel,
    NonEmptyStr,
    Sha256,
    TrackedObject,
    UtcDatetime,
    utc_now,
)
from research_harness.domain.enums import (
    ArtifactKind,
    IdentityResolutionOutcome,
    ProvenanceSource,
    ScreeningState,
    VersionKind,
)
from research_harness.domain.ids import ArtifactId, VersionId, WorkId

__all__ = [
    "Artifact",
    "CandidateMetadata",
    "IdentifierField",
    "Version",
    "Work",
    "WorkCandidate",
    "WorkIdentifiers",
]


class IdentifierField(DomainModel):
    """One metadata value with field-level provenance (Product 13).

    Identity resolution must never erase where a conflicting value came from.
    """

    value: NonEmptyStr
    source: ProvenanceSource
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = None
    """Where the value was found, e.g. ``"pdf_metadata:title"`` or ``"page1:regex"``.

    The source vocabulary says *who* produced a value; the note says *which* part of the
    artifact it was read from, which is what a researcher needs to override it.
    """


class WorkIdentifiers(DomainModel):
    """External identifiers, each carrying its own provenance."""

    doi: IdentifierField | None = None
    arxiv: IdentifierField | None = None
    dblp: IdentifierField | None = None
    semantic_scholar: IdentifierField | None = None
    openalex: IdentifierField | None = None


class Work(CanonicalObject):
    """A scholarly work, independent of any particular file or revision."""

    id: WorkId
    title: NonEmptyStr
    authors: tuple[str, ...] = ()
    year: int | None = Field(default=None, ge=1400, le=2200)
    venue: str | None = None
    identifiers: WorkIdentifiers = WorkIdentifiers()
    screening: ScreeningState = ScreeningState.DISCOVERED
    exclusion_reason: str | None = None
    """Why this work was excluded. Kept for readers written before `screening_reason`."""
    screening_reason: str | None = None
    """Why this work was screened the way it was, whatever the decision (dogfood F9).

    An exclusion writes the same text into `exclusion_reason` as well, so every existing
    reader keeps working; an inclusion has only this field, because there was nowhere to
    record why a paper was kept.
    """
    versions: tuple[VersionId, ...] = ()
    artifacts: tuple[ArtifactId, ...] = ()

    @model_validator(mode="after")
    def _screening_reason_is_persisted(self) -> Work:
        """Product 14: an exclusion persists a reason, and `exclusion_reason` names only one."""
        if self.screening is ScreeningState.EXCLUDED and not (
            self.exclusion_reason or self.screening_reason
        ):
            raise ValueError("an excluded work must persist a reason")
        if self.screening is not ScreeningState.EXCLUDED and self.exclusion_reason:
            raise ValueError(
                "exclusion_reason is only valid for excluded works; record any other "
                "screening decision's reason in screening_reason"
            )
        if self.screening is ScreeningState.DISCOVERED and self.screening_reason:
            raise ValueError("a work that has not been screened has no screening reason")
        return self

    @property
    def screening_note(self) -> str | None:
        """The recorded reason for this work's screening decision, whichever field holds it."""
        return self.screening_reason or self.exclusion_reason


class Version(CanonicalObject):
    """One revision of a Work: arXiv v1/v2, camera-ready, publisher, author manuscript."""

    id: VersionId
    work: WorkId
    kind: VersionKind
    label: str | None = None
    date: datetime.date | None = None
    identifiers: WorkIdentifiers = WorkIdentifiers()


class Artifact(CanonicalObject):
    """An immutable file belonging to a Version.

    Artifacts are registered once and never edited: a new file is a new Artifact, so an
    evidence anchor can always be replayed against the exact bytes it was accepted from.
    """

    id: ArtifactId
    work: WorkId
    version: VersionId
    kind: ArtifactKind
    file_hash: Sha256
    original_filename: NonEmptyStr
    mime_type: NonEmptyStr
    size_bytes: int = Field(ge=0)
    ingested_at: UtcDatetime = Field(default_factory=utc_now)


class CandidateMetadata(DomainModel):
    """Candidate bibliographic metadata, every field carrying its own provenance."""

    title: IdentifierField | None = None
    authors: tuple[IdentifierField, ...] = ()
    year: IdentifierField | None = None
    venue: IdentifierField | None = None
    identifiers: WorkIdentifiers = WorkIdentifiers()


class WorkCandidate(TrackedObject):
    """A discovered or ingested record that is not yet corpus state (Product 8.3, 14).

    Candidates deliberately have no stable research ID: discovery results and staged
    ingests carry no scientific authority until screening and identity resolution
    complete and a `Work` is created.
    """

    metadata: CandidateMetadata = CandidateMetadata()
    candidate_file_hash: Sha256 | None = None
    original_filename: str | None = None
    resolution: IdentityResolutionOutcome = IdentityResolutionOutcome.UNRESOLVED
    matched_work: WorkId | None = None
    matched_version: VersionId | None = None
    matched_artifact: ArtifactId | None = None
    screening: ScreeningState = ScreeningState.DISCOVERED
    exclusion_reason: str | None = None
    screening_reason: str | None = None
    """Why this candidate was screened the way it was, whatever the decision (dogfood F9)."""
    source_query: str | None = None

    @model_validator(mode="after")
    def _resolution_matches_links(self) -> WorkCandidate:
        """Each resolution outcome requires exactly the links that outcome asserts."""
        outcome = self.resolution
        required: tuple[str, ...]
        if outcome is IdentityResolutionOutcome.SAME_ARTIFACT:
            required = ("matched_work", "matched_version", "matched_artifact")
        elif outcome is IdentityResolutionOutcome.SAME_VERSION:
            required = ("matched_work", "matched_version")
        elif outcome is IdentityResolutionOutcome.SAME_WORK:
            required = ("matched_work",)
        else:
            required = ()
        for name in required:
            if getattr(self, name) is None:
                raise ValueError(f"resolution {outcome.value!r} requires {name}")
        for name in ("matched_work", "matched_version", "matched_artifact"):
            if name not in required and getattr(self, name) is not None:
                raise ValueError(f"resolution {outcome.value!r} must not set {name}")
        if self.screening is ScreeningState.EXCLUDED and not (
            self.exclusion_reason or self.screening_reason
        ):
            raise ValueError("an excluded candidate must persist a reason")
        return self

    @property
    def screening_note(self) -> str | None:
        """The recorded reason for this candidate's screening decision, whichever field holds it."""
        return self.screening_reason or self.exclusion_reason
