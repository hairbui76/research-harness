"""Typed inputs and results for the capability layer (Product 36; ADR-004).

Every capability takes one frozen, closed request model and returns one
:class:`MutationResult` carrying the four things Product 36 requires of a mutation: a
validation result, a semantic diff, the semantic event that was appended, and the
dependency invalidation set. Transports (CLI, HTTP, MCP) speak these types and nothing
else.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from research_harness.capabilities.diff import SemanticDiff
from research_harness.domain.claim import Claim, Coverage
from research_harness.domain.document import ParsedDocument
from research_harness.domain.enums import (
    ACCEPTING_REVIEW_ACTIONS,
    ArtifactKind,
    ClaimScope,
    ClaimStatus,
    QuestionStatus,
    ReviewAction,
    ReviewPolicy,
    VerificationVerdict,
    VersionKind,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    DecisionId,
    EvidenceId,
    QuestionId,
    ResearchId,
    SearchRunId,
    VersionId,
    WorkId,
)
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.domain.research import (
    Decision,
    ResearchEvent,
    ResearchQuestion,
    SearchRun,
    SynthesisMatrix,
    Taxonomy,
)
from research_harness.domain.transitions import BatchPolicyConditions
from research_harness.domain.work import WorkCandidate, WorkIdentifiers
from research_harness.projection.dependencies import StaleMark

__all__ = [
    "EDITING_REVIEW_ACTIONS",
    "PROMOTION_TARGETS",
    "PROVISIONAL_CLAIM_ID",
    "PROVISIONAL_DECISION_ID",
    "PROVISIONAL_QUESTION_ID",
    "PROVISIONAL_SEARCH_RUN_ID",
    "AcceptDecisionRequest",
    "AcceptEvidenceRequest",
    "AddArtifactRequest",
    "AddNoteRequest",
    "AttachManuscriptAnchorRequest",
    "AuditClaimRequest",
    "CapabilityRequest",
    "CreateClaimRequest",
    "CreateQuestionRequest",
    "IngestLocalPdfRequest",
    "InitProjectRequest",
    "InitProjectResult",
    "MutationResult",
    "OverrideClaimStrengthRequest",
    "ParseWorkRequest",
    "PromoteNoteRequest",
    "PutMatrixRequest",
    "PutTaxonomyRequest",
    "RecordSearchRunRequest",
    "RegisterWorkRequest",
    "RejectEvidenceRequest",
    "StoreParsedDocumentRequest",
    "UpdateQuestionRequest",
    "ValidationReport",
]

#: Review actions this layer accepts on `evidence.accept`: the two accepting actions of
#: Product 24.3 plus `edit`, which accepts the researcher's corrected text.
EDITING_REVIEW_ACTIONS: frozenset[ReviewAction] = ACCEPTING_REVIEW_ACTIONS | {ReviewAction.EDIT}

#: Research objects a captured note may be promoted into (Product 31).
PROMOTION_TARGETS: tuple[type[ResearchId], ...] = (ClaimId, QuestionId, DecisionId)

#: Ids a caller uses to say "allocate one for me". A client that has to guess the next
#: `C####` guesses wrong the moment two clients run at once, so every capability that
#: creates a numbered object accepts an object with no id at all and allocates under the
#: workspace lock. Number 0 is never allocated, which is what makes it safe to mean
#: "unassigned" (the same trick `PROVISIONAL_EVIDENCE_ID` plays for staged candidates).
PROVISIONAL_CLAIM_ID: ClaimId = ClaimId.make(0)
PROVISIONAL_QUESTION_ID: QuestionId = QuestionId.make(0)
PROVISIONAL_DECISION_ID: DecisionId = DecisionId.make(0)
PROVISIONAL_SEARCH_RUN_ID: SearchRunId = SearchRunId.make(0)


def _provisional(data: Any, field: str, provisional: ResearchId) -> Any:
    """Fill a nested object's missing ``id`` with ``provisional`` before validation.

    The nested models require an id, so "omit it" has to become "carry the placeholder"
    before Pydantic sees the payload; the handler then allocates the real one.
    """
    if not isinstance(data, Mapping):
        return data
    nested = data.get(field)
    if not isinstance(nested, Mapping) or nested.get("id"):
        return data
    return {**data, field: {**nested, "id": str(provisional)}}


# -- results -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The validation result Product 36 requires of every mutation.

    ``errors`` are refusals: a handler raises before touching the workspace. ``warnings``
    record what the handler had to fall back on, so the researcher can see it later.
    """

    ok: bool = True
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def of(cls, errors: tuple[str, ...] = (), warnings: tuple[str, ...] = ()) -> ValidationReport:
        """Report whose ``ok`` follows from whether anything failed."""
        return cls(ok=not errors, errors=errors, warnings=warnings)

    def raise_for_errors(self, capability: str) -> None:
        """Refuse the mutation when validation failed, naming every reason at once."""
        if self.errors:
            raise CapabilityError(f"{capability}: {'; '.join(self.errors)}")

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings)}


@dataclass(frozen=True, slots=True)
class MutationResult:
    """What one accepted-state mutation did: objects, event, diff, stale set, validation."""

    capability: str
    objects: tuple[str, ...]
    event: ResearchEvent
    diff: SemanticDiff
    stale: tuple[StaleMark, ...] = ()
    validation: ValidationReport = field(default_factory=ValidationReport)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for transports and `--json` output."""
        return {
            "capability": self.capability,
            "objects": list(self.objects),
            "event": self.event.model_dump(mode="json"),
            "diff": self.diff.as_dict(),
            "stale": [
                {
                    "object_id": mark.object_id,
                    "reason": mark.reason,
                    "priority": int(mark.priority),
                    "source_change": mark.source_change,
                }
                for mark in self.stale
            ],
            "validation": self.validation.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class InitProjectResult:
    """What `project.init` created. Initialization changes no research object, so it
    carries no semantic event (Product 19.3 events describe research state changes)."""

    root: Path
    name: str
    policy: ReviewPolicy
    validation: ValidationReport = field(default_factory=ValidationReport)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "root": str(self.root),
            "name": self.name,
            "policy": self.policy.value,
            "validation": self.validation.as_dict(),
        }


# -- requests ----------------------------------------------------------------


class CapabilityRequest(BaseModel):
    """Frozen, closed request model; unknown fields are a caller error, not a default."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class InitProjectRequest(CapabilityRequest):
    """`project.init`: create a workspace at ``root``."""

    root: Path
    name: str | None = None
    policy: ReviewPolicy = ReviewPolicy.STRICT

    def resolved_name(self) -> str:
        """Project name, defaulting to the directory name."""
        return self.name or self.root.resolve().name


class RegisterWorkRequest(CapabilityRequest):
    """`work.register`: a resolved candidate becomes a Work, Version, and Artifact."""

    candidate: WorkCandidate
    artifact_path: Path
    version_kind: VersionKind = VersionKind.OTHER
    version_label: str | None = None
    title: str | None = None
    """Overrides the candidate's extracted title; the filename stem is the last resort."""
    mime_type: str | None = None
    artifact_kind: ArtifactKind | None = None
    version_identifiers: WorkIdentifiers | None = None
    """Identifiers that pin this exact revision (an arXiv `vN`), not the work."""


class AddArtifactRequest(CapabilityRequest):
    """`work.add_artifact`: a new immutable file for an existing Work.

    With ``version`` the file joins that revision; without it a new Version is registered.
    An existing Artifact is never overwritten (ADR-002).
    """

    work: WorkId
    artifact_path: Path
    version: VersionId | None = None
    version_kind: VersionKind = VersionKind.OTHER
    version_label: str | None = None
    mime_type: str | None = None
    artifact_kind: ArtifactKind | None = None
    identifiers: WorkIdentifiers | None = None
    """Merged work identifiers from identity resolution; existing values are never dropped."""
    version_identifiers: WorkIdentifiers | None = None


class StoreParsedDocumentRequest(CapabilityRequest):
    """`work.store_blocks`: persist a parse so anchors resolve without re-parsing."""

    document: ParsedDocument
    work: WorkId | None = None


class AcceptEvidenceRequest(CapabilityRequest):
    """`evidence.accept`: a reviewed candidate becomes accepted Evidence (Product 24.3)."""

    candidate: Evidence
    review_action: ReviewAction = ReviewAction.ACCEPT
    qualification: str | None = None
    edited: Evidence | None = None
    """The researcher's corrected candidate; only read when the action is `edit`."""
    verdict: VerificationVerdict | None = None
    """Required for a candidate that is still `proposed`: the reviewer is its verifier."""
    rationale: str | None = None
    batch_conditions: BatchPolicyConditions | None = None
    """Deterministic Product 24.4 conditions; confidence is never one of them."""

    candidate_id: str | None = None
    """Staging id of the reviewed proposal, when the caller has one.

    Given, the handler marks that candidate reviewed after the canonical write, so a
    transport that posts the staged `Evidence` verbatim drains the review queue exactly as
    the candidate-keyed `review.*` capabilities do. Absent, nothing in staging is touched:
    a hand-built acceptance has no queue entry to close.
    """

    @model_validator(mode="after")
    def _action_and_payload_agree(self) -> AcceptEvidenceRequest:
        if self.review_action not in EDITING_REVIEW_ACTIONS:
            allowed = ", ".join(sorted(action.value for action in EDITING_REVIEW_ACTIONS))
            raise ValueError(f"evidence.accept needs an accepting review action ({allowed})")
        if self.review_action is ReviewAction.EDIT and self.edited is None:
            raise ValueError("review action 'edit' requires the edited candidate")
        if self.review_action is not ReviewAction.EDIT and self.edited is not None:
            raise ValueError("an edited candidate is only read for review action 'edit'")
        if self.review_action is ReviewAction.ACCEPT_WITH_QUALIFICATION and not self.qualification:
            raise ValueError("accept_with_qualification requires a qualification")
        if self.edited is not None and self.edited.id != self.candidate.id:
            raise ValueError("the edited candidate must keep the candidate's evidence id")
        return self


class RejectEvidenceRequest(CapabilityRequest):
    """`evidence.reject`: a candidate is refused and never becomes canonical Evidence.

    The refusal is written to the Work's `rejections.jsonl`, so `candidate_id` and `field`
    travel with it: they are what lets the Review Inbox recognise the same proposal if a
    later interrogation run makes it again.
    """

    candidate: Evidence
    reason: str
    candidate_id: str | None = None
    """Staging id of the refused proposal; a hand-built rejection may have none."""

    field: str | None = None
    """Interrogation field the proposal answered; defaults to the candidate's own."""


class CreateClaimRequest(CapabilityRequest):
    """`claim.create`: register a structured claim (Product 10).

    ``claim.id`` is optional: omit it (or send `C0000`) and the handler allocates the next
    free `ClaimId` under the workspace lock, so an HTTP or MCP client never has to guess
    one. A caller that already holds an id - the CLI, a replayed export - sends it and it
    is used unchanged.
    """

    claim: Claim

    @model_validator(mode="before")
    @classmethod
    def _id_is_optional(cls, data: Any) -> Any:
        return _provisional(data, "claim", PROVISIONAL_CLAIM_ID)


class AuditClaimRequest(CapabilityRequest):
    """`claim.audit`: record what the evidence allows, never what was asked for."""

    claim_id: ClaimId
    status: ClaimStatus
    allowed_strength: ClaimScope
    maximum_defensible_wording: str | None = None
    coverage: Coverage | None = None


class AcceptDecisionRequest(CapabilityRequest):
    """`decision.accept`: a proposed researcher decision becomes accepted (Product 38).

    ``decision.id`` is optional for a decision this workspace has not seen: the handler
    allocates the next free `DecisionId` under the lock. An override is a Decision before it
    is a claim edit, so the client that wants to write one no longer has to predict its id.
    """

    decision: Decision

    @model_validator(mode="before")
    @classmethod
    def _id_is_optional(cls, data: Any) -> Any:
        return _provisional(data, "decision", PROVISIONAL_DECISION_ID)


class OverrideClaimStrengthRequest(CapabilityRequest):
    """`claim.override_strength`: apply an accepted epistemic override to a claim."""

    claim_id: ClaimId
    decision_id: DecisionId


class CreateQuestionRequest(CapabilityRequest):
    """`question.create`: register a research question (Product 31).

    ``question.id`` is optional; the handler allocates the next free `RQ####`.
    """

    question: ResearchQuestion

    @model_validator(mode="before")
    @classmethod
    def _id_is_optional(cls, data: Any) -> Any:
        return _provisional(data, "question", PROVISIONAL_QUESTION_ID)


class UpdateQuestionRequest(CapabilityRequest):
    """`question.update`: move a question's status and relink what bears on it."""

    question_id: QuestionId
    status: QuestionStatus | None = None
    claims: tuple[ClaimId, ...] | None = None
    search_runs: tuple[SearchRunId, ...] | None = None
    supporting_evidence: tuple[EvidenceId, ...] | None = None
    counter_evidence: tuple[EvidenceId, ...] | None = None
    remaining_uncertainty: str | None = None

    def links(self) -> dict[str, Any]:
        """The link fields this request actually sets."""
        names = ("claims", "search_runs", "supporting_evidence", "counter_evidence")
        updates: dict[str, Any] = {
            name: getattr(self, name) for name in names if getattr(self, name) is not None
        }
        if self.remaining_uncertainty is not None:
            updates["remaining_uncertainty"] = self.remaining_uncertainty
        return updates


class AddNoteRequest(CapabilityRequest):
    """`note.add`: capture a low-authority note (Product 31).

    ``source`` names the capture host (a chat host, the CLI, an editor). It is provenance,
    not content: writing it into the note text would put it in the scientific record, so
    the handler stores it in the note's `Provenance.note` instead.
    """

    text: str
    key: str | None = None
    source: str | None = None


class PromoteNoteRequest(CapabilityRequest):
    """`note.promote`: record the research object a captured note became."""

    note_key: str
    target: ResearchId

    @model_validator(mode="after")
    def _target_is_promotable(self) -> PromoteNoteRequest:
        if not isinstance(self.target, PROMOTION_TARGETS):
            allowed = ", ".join(kind.__name__ for kind in PROMOTION_TARGETS)
            raise ValueError(f"a note is promoted into one of: {allowed}")
        return self


class AttachManuscriptAnchorRequest(CapabilityRequest):
    """`manuscript.attach_claim`: bind a manuscript sentence to a Claim (Product 30.1)."""

    anchor: ManuscriptAnchor


class RecordSearchRunRequest(CapabilityRequest):
    """`search_run.record`: persist a reproducible discovery operation (Product 18).

    ``search_run.id`` is optional; the handler allocates the next free `SR####`.
    """

    search_run: SearchRun

    @model_validator(mode="before")
    @classmethod
    def _id_is_optional(cls, data: Any) -> Any:
        return _provisional(data, "search_run", PROVISIONAL_SEARCH_RUN_ID)


class PutTaxonomyRequest(CapabilityRequest):
    """`taxonomy.put`: write a taxonomy authorised by an accepted taxonomy Decision."""

    taxonomy: Taxonomy
    decision: Decision


class PutMatrixRequest(CapabilityRequest):
    """`synthesis.build_matrix`: persist a cross-paper comparison (Product 7.1)."""

    matrix: SynthesisMatrix


class IngestLocalPdfRequest(CapabilityRequest):
    """`corpus.ingest`: hash, inspect, resolve, and register one local file."""

    path: Path
    as_new: bool = False
    """Register a new Work even when identity resolution matched an existing one."""
    attach_to: WorkId | None = None
    """Attach the file to this Work instead of resolving its identity."""

    @model_validator(mode="after")
    def _one_override_at_most(self) -> IngestLocalPdfRequest:
        if self.as_new and self.attach_to is not None:
            raise ValueError("--as-new and --attach-to are mutually exclusive")
        return self


class ParseWorkRequest(CapabilityRequest):
    """`work.parse`: parse a Work's artifact into structural blocks (Product 16)."""

    work: WorkId
    artifact: ArtifactId | None = None
