"""The candidate staging store: regenerable runtime state with no scientific authority.

Everything here lives under `.research/staging/evidence/` and can be deleted without losing
a conclusion (ADR-001, ADR-003). A staged candidate is a *proposal*: it carries the source
anchor it was read from, the model that proposed it, an independent verification result once
one exists, and a review action once a researcher has taken one — and none of that makes it
accepted. Acceptance happens in the capability layer, writes canonical `evidence.jsonl`, and
allocates the real `EvidenceId`; until then a candidate carries `PROVISIONAL_EVIDENCE_ID`,
which the id allocator never hands out.

The store is a directory of JSON files rather than a table, for the same reason the canonical
tree is files: a researcher can read, diff, and delete it, and a crashed writer leaves either
the old bytes or the new ones (atomic replace via `workspace.atomic`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Iterator, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr, UtcDatetime, utc_now
from research_harness.domain.enums import EvidenceStatus, ReviewAction
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ArtifactId, EvidenceId, WorkId
from research_harness.domain.transitions import transition_evidence
from research_harness.parsing.anchors import AnchorValidationStatus
from research_harness.roles.schemas import VerificationOutput
from research_harness.workspace.atomic import atomic_write_text, clean_partials

logger = logging.getLogger(__name__)

__all__ = [
    "CANDIDATE_ID_PATTERN",
    "PROVISIONAL_EVIDENCE_ID",
    "STAGING_EVIDENCE_DIRNAME",
    "CandidateNotFoundError",
    "CandidateStatus",
    "EvidenceCandidate",
    "ExtractionProvenance",
    "StagingError",
    "StagingStore",
    "apply_verification",
    "candidate_id_for",
    "new_candidate_id",
]

STAGING_EVIDENCE_DIRNAME = "staging/evidence"
CANDIDATE_ID_PATTERN = r"^cand_[0-9a-f]{16}$"
_CANDIDATE_ID = re.compile(CANDIDATE_ID_PATTERN)
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

CandidateList = list["EvidenceCandidate"]
"""Alias used inside `StagingStore`, whose `list` method shadows the builtin in class scope."""

PathList = list[Path]
WorkIdList = list[WorkId]

PROVISIONAL_EVIDENCE_ID: EvidenceId = EvidenceId.make(0)
"""`E0000`, the id every staged candidate carries.

Canonical allocation starts at 1, so this value can never collide with an accepted
`EvidenceId`; a candidate's real identity is its `candidate_id`, and its canonical id is
allocated at acceptance.
"""


class StagingError(ResearchHarnessError):
    """A staged candidate could not be read, written, or updated."""


class CandidateNotFoundError(StagingError):
    """No candidate with that id exists in this store."""


class CandidateStatus(StrEnum):
    """Where a candidate sits in the staging pipeline (Product §8.3).

    None of these is authority: `reviewed` records that a researcher acted, and the accepted
    object itself is written to canonical state by the capability layer.
    """

    PROPOSED = "proposed"
    INVALID = "invalid"
    VERIFIED = "verified"
    REVIEWED = "reviewed"


def new_candidate_id() -> str:
    """A fresh `cand_<16 hex>` id, for candidates with no content to derive one from."""
    return f"cand_{secrets.token_hex(8)}"


def candidate_id_for(*parts: object) -> str:
    """A content-addressed `cand_<16 hex>` id: the same evidence always gets the same id.

    Identity follows what the candidate says and where it came from, never which model
    proposed it. Two providers that read the same span therefore produce the same candidate,
    which is what keeps a provider swap for one field from churning ids and invalidating
    unrelated stages (Product §19.1).
    """
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8"))
    return f"cand_{digest.hexdigest()[:16]}"


class ExtractionProvenance(DomainModel):
    """Reproducibility metadata for the proposal itself (Product §20.5).

    `rationale` is the model's own short justification. It is persisted for the reviewer and
    deliberately never shown to the verifier: agreement carries information only when the
    second reader did not see the first one's reasoning (ADR-003).
    """

    run_id: NonEmptyStr
    provider: NonEmptyStr
    model: NonEmptyStr
    template_version: NonEmptyStr
    request_fingerprint: NonEmptyStr
    response_schema_fingerprint: NonEmptyStr
    rationale: str | None = None


class EvidenceCandidate(DomainModel):
    """One proposed evidence object in staging, with everything a reviewer needs.

    The `Evidence` inside is a real domain object with a real anchor, so a reviewer sees the
    span, and acceptance is a transition rather than a re-parse. Its status is `proposed` or
    `verified`: a candidate that were already `accepted` would mean staging had authority.
    """

    candidate_id: str = Field(default_factory=new_candidate_id, pattern=CANDIDATE_ID_PATTERN)
    work: WorkId
    artifact: ArtifactId
    field: NonEmptyStr
    evidence: Evidence
    extraction: ExtractionProvenance
    verification: VerificationOutput | None = None
    verifier: str | None = None
    anchor_status: AnchorValidationStatus = AnchorValidationStatus.VALID
    status: CandidateStatus = CandidateStatus.PROPOSED
    review_action: ReviewAction | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    updated_at: UtcDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _staging_never_holds_accepted_evidence(self) -> EvidenceCandidate:
        if self.evidence.status not in {EvidenceStatus.PROPOSED, EvidenceStatus.VERIFIED}:
            raise ValueError(
                f"candidate {self.candidate_id} holds {self.evidence.status.value!r} evidence; "
                "staging holds proposed or verified candidates only"
            )
        return self

    @model_validator(mode="after")
    def _status_matches_what_has_happened(self) -> EvidenceCandidate:
        if self.status is CandidateStatus.VERIFIED and (
            self.verification is None or not self.verifier
        ):
            raise ValueError("a verified candidate needs a verification result and a verifier")
        if self.status is CandidateStatus.REVIEWED and self.review_action is None:
            raise ValueError("a reviewed candidate needs the review action taken")
        return self

    @property
    def verdict(self) -> str | None:
        """The verification verdict as a string, or None while unverified."""
        return None if self.verification is None else self.verification.verdict.value

    @property
    def review_tier(self) -> int:
        """Review depth this candidate needs (Product §24.1)."""
        return int(self.evidence.review_tier)


def apply_verification(
    candidate: EvidenceCandidate, output: VerificationOutput, verifier: str
) -> EvidenceCandidate:
    """Attach an independent verification result, transitioning the evidence to `verified`.

    The status change goes through `transition_evidence`, so an illegal move raises rather
    than being written; verification is metadata for review and grants no authority.

    A candidate that is already `verified` is not transitioned again — its status is not
    changing — and the new verdict replaces the recorded one. Two providers that disagree
    should become a Review Inbox conflict rather than a silent overwrite; that object arrives
    with cross-model verification (Product §13.2, Task 13.2), so until then a second opinion
    has to be asked for explicitly.
    """
    if candidate.evidence.status is EvidenceStatus.VERIFIED:
        evidence = candidate.evidence.touch(
            verification=candidate.evidence.verification.touch(
                verdict=output.verdict, verifier=verifier, rationale=output.rationale
            )
        )
    else:
        evidence = transition_evidence(
            candidate.evidence,
            EvidenceStatus.VERIFIED,
            actor=verifier,
            verdict=output.verdict,
            rationale=output.rationale,
        )
    return candidate.touch(
        evidence=evidence,
        verification=output,
        verifier=verifier,
        status=CandidateStatus.VERIFIED,
    )


class StagingStore:
    """Candidate files under `<research_dir>/staging/evidence/<work>/<candidate_id>.json`.

    Regenerable by construction: deleting the tree loses proposals, never conclusions.
    """

    def __init__(self, research_dir: Path) -> None:
        self._research_dir = Path(research_dir)

    def __repr__(self) -> str:
        return f"StagingStore({str(self._research_dir)!r})"

    @property
    def research_dir(self) -> Path:
        """Root of regenerable runtime state; nothing is written outside it."""
        return self._research_dir

    @property
    def root(self) -> Path:
        """`<research_dir>/staging/evidence` — the whole candidate tree."""
        return self._research_dir / "staging" / "evidence"

    def work_dir(self, work: WorkId) -> Path:
        return self.root / _segment(str(work))

    def path_for(self, work: WorkId, candidate_id: str) -> Path:
        return self.work_dir(work) / f"{_candidate_id(candidate_id)}.json"

    # -- writes --------------------------------------------------------------

    def put(self, candidate: EvidenceCandidate) -> Path:
        """Write (or replace) one candidate atomically; returns its path."""
        path = self.path_for(candidate.work, candidate.candidate_id)
        atomic_write_text(path, _dump(candidate))
        return path

    def put_all(self, candidates: Sequence[EvidenceCandidate]) -> PathList:
        """Stage several candidates; each write is individually atomic."""
        return [self.put(candidate) for candidate in candidates]

    def mark_verified(
        self, candidate_id: str, output: VerificationOutput, verifier: str
    ) -> EvidenceCandidate:
        """Record an independent verification result against a staged candidate."""
        updated = apply_verification(self.get(candidate_id), output, verifier)
        self.put(updated)
        return updated

    def mark_invalid(self, candidate_id: str, reason: str) -> EvidenceCandidate:
        """Mark a candidate unusable (typically a stale or missing anchor)."""
        candidate = self.get(candidate_id)
        logger.info("candidate %s marked invalid: %s", candidate_id, reason)
        updated = candidate.touch(status=CandidateStatus.INVALID)
        self.put(updated)
        return updated

    def mark_reviewed(self, candidate_id: str, action: ReviewAction) -> EvidenceCandidate:
        """Record the review action a researcher took; the accepted object is written
        to canonical state by the capability layer, never here."""
        updated = self.get(candidate_id).touch(
            status=CandidateStatus.REVIEWED, review_action=action
        )
        self.put(updated)
        return updated

    def delete(self, candidate_id: str) -> bool:
        """Remove a candidate; True when one was there. Canonical state is untouched."""
        for path in self._paths():
            if path.stem == candidate_id:
                path.unlink(missing_ok=True)
                return True
        return False

    # -- reads ---------------------------------------------------------------

    def get(self, candidate_id: str, *, work: WorkId | None = None) -> EvidenceCandidate:
        """One candidate by id; raises `CandidateNotFoundError` when absent."""
        wanted = _candidate_id(candidate_id)
        if work is not None:
            return _read(self.path_for(work, wanted))
        for path in self._paths():
            if path.stem == wanted:
                return _read(path)
        raise CandidateNotFoundError(f"no staged candidate {candidate_id} under {self.root}")

    def list(
        self,
        work: WorkId | None = None,
        status: CandidateStatus | None = None,
        field: str | None = None,
    ) -> CandidateList:
        """Staged candidates, ordered by work then candidate id, filtered as asked."""
        return [
            candidate
            for candidate in self._iter(work)
            if (status is None or candidate.status is status)
            and (field is None or candidate.field == field)
        ]

    def works(self) -> WorkIdList:
        """Works that currently have staged candidates."""
        if not self.root.is_dir():
            return []
        return [WorkId(path.name) for path in sorted(self.root.iterdir()) if path.is_dir()]

    def _iter(self, work: WorkId | None) -> Iterator[EvidenceCandidate]:
        for path in self._paths(work):
            try:
                yield _read(path)
            except StagingError:
                logger.warning("ignoring unreadable staged candidate %s", path)

    def _paths(self, work: WorkId | None = None) -> PathList:
        directories = [self.work_dir(work)] if work is not None else _subdirectories(self.root)
        paths: PathList = []
        for directory in directories:
            clean_partials(directory)
            paths.extend(sorted(directory.glob("cand_*.json")))
        return paths


# ------------------------------------------------------------------------- helpers


def _subdirectories(root: Path) -> PathList:
    if not root.is_dir():
        return []
    return [path for path in sorted(root.iterdir()) if path.is_dir()]


def _dump(candidate: EvidenceCandidate) -> str:
    return (
        json.dumps(candidate.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def _read(path: Path) -> EvidenceCandidate:
    if not path.is_file():
        raise CandidateNotFoundError(f"no staged candidate at {path}")
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError(f"cannot read staged candidate {path}: {exc}") from exc
    try:
        return EvidenceCandidate.model_validate(payload)
    except ValidationError as exc:
        raise StagingError(f"invalid staged candidate {path}: {exc}") from exc


def _segment(name: str) -> str:
    if not _SAFE_SEGMENT.match(name):
        raise StagingError(f"unsafe path segment {name!r}")
    return name


def _candidate_id(value: str) -> str:
    if not _CANDIDATE_ID.match(value):
        raise StagingError(f"{value!r} is not a candidate id ({CANDIDATE_ID_PATTERN})")
    return value
