"""The only supported mutation surface for accepted scientific state (ADR-004).

Every accepted-state change in the product goes through exactly one function here,
whatever transport asked for it: CLI today, HTTP/MCP/Web in Phase 10. No other package
may write canonical state, and nothing in `cli/`, `server/`, or `protocol/` may open a
workspace transaction of its own.

Each handler does the same five things, in this order:

1. **validate** through domain constructors, the transition tables, and the actor
   authority rules (`Product` 24, ADR-003, ADR-007);
2. **diff** the result against what is currently canonical;
3. **build the semantic event** that describes the change (`Product` 19.3);
4. **write** inside one `WorkspaceRepository.transaction`, so the canonical files and the
   event commit together or not at all (`Product` 8.2, ADR-001);
5. **invalidate** the dependency set the change reaches, marking it stale rather than
   rewriting it (`Product` 37, ADR-008).

Nothing here imports a parser or a model provider: Gate P1 populates a workspace through
these handlers with no SQLite, no parser, and no provider present.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from secrets import token_hex
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.diff import ChangeKind, SemanticDiff, semantic_diff
from research_harness.capabilities.dto import (
    PROVISIONAL_CLAIM_ID,
    PROVISIONAL_DECISION_ID,
    PROVISIONAL_QUESTION_ID,
    PROVISIONAL_SEARCH_RUN_ID,
    AcceptDecisionRequest,
    AcceptEvidenceRequest,
    AddArtifactRequest,
    AddNoteRequest,
    AttachManuscriptAnchorRequest,
    AuditClaimRequest,
    CreateClaimRequest,
    CreateQuestionRequest,
    IngestLocalPdfRequest,
    InitProjectRequest,
    InitProjectResult,
    MutationResult,
    OverrideClaimStrengthRequest,
    ParseWorkRequest,
    PromoteNoteRequest,
    PutMatrixRequest,
    PutTaxonomyRequest,
    RecordSearchRunRequest,
    RegisterWorkRequest,
    RejectEvidenceRequest,
    StoreParsedDocumentRequest,
    UpdateQuestionRequest,
    ValidationReport,
)
from research_harness.domain.claim import Claim
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    ArtifactKind,
    ClaimStatus,
    DecisionStatus,
    DecisionType,
    EvidenceStatus,
    ProvenanceSource,
    ResearchEventType,
    ReviewAction,
)
from research_harness.domain.errors import AuthorityError, CapabilityError
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
from research_harness.domain.research import (
    MAX_EVENT_PAYLOAD_VALUE_CHARS,
    Decision,
    ResearchEvent,
    ResearchNote,
    ResearchQuestion,
    SearchRun,
)
from research_harness.domain.transitions import (
    audit_claim as audit_claim_transition,
)
from research_harness.domain.transitions import (
    override_claim_strength as override_claim_strength_transition,
)
from research_harness.domain.transitions import (
    promote_note as promote_note_transition,
)
from research_harness.domain.transitions import (
    transition_decision,
    transition_evidence,
    transition_question,
)
from research_harness.domain.work import (
    Artifact,
    IdentifierField,
    Version,
    Work,
    WorkIdentifiers,
)
from research_harness.projection.rows import node_id_for, taxonomy_node_id
from research_harness.workspace.events import content_digest, digest_key
from research_harness.workspace.layout import note_key
from research_harness.workspace.rejections import RejectionRecord
from research_harness.workspace.repository import (
    ObjectNotFoundError,
    WorkspaceRepository,
    WorkspaceTransaction,
)

if TYPE_CHECKING:  # imported lazily at runtime so this layer stays parser-free
    from research_harness.ingest.service import IngestResult, ParseResult

__all__ = [
    "CAPABILITY_HANDLERS",
    "CORE_CAPABILITY_HANDLERS",
    "DEFAULT_MIME_TYPE",
    "PROJECT_INIT",
    "PROVISIONAL_EVIDENCE_ID",
    "accept_decision",
    "accept_evidence",
    "add_note",
    "add_version_artifact",
    "attach_manuscript_anchor",
    "audit_claim",
    "create_claim",
    "create_question",
    "ingest_local_pdf",
    "init_project",
    "next_evidence_id",
    "override_claim_strength",
    "parse_work",
    "promote_note",
    "put_matrix",
    "put_taxonomy",
    "record_search_run",
    "register_work",
    "reject_evidence",
    "store_parsed_document",
    "update_question",
]

logger = logging.getLogger(__name__)

DEFAULT_MIME_TYPE = "application/octet-stream"

#: `project.init` is not an accepted-state mutation: it has no context to run in and no
#: research object to change, so it is registered apart from `CAPABILITY_HANDLERS`.
PROJECT_INIT = "project.init"

#: The id a staged candidate carries before it is accepted, the same value as
#: `evidence.staging.PROVISIONAL_EVIDENCE_ID`. Spelled out rather than imported so this
#: layer stays parser-free (Gate P1); a contract test asserts the two cannot drift. Real
#: allocation starts at 1, so `E0000` can never collide with an accepted `EvidenceId`.
PROVISIONAL_EVIDENCE_ID: EvidenceId = EvidenceId.make(0)

#: Media types whose artifact kind this layer can name without the ingest package, which
#: pulls in a PDF library. Anything else is `other` until a caller says otherwise.
_ARTIFACT_KINDS: Mapping[str, ArtifactKind] = MappingProxyType(
    {
        "application/pdf": ArtifactKind.PDF,
        "text/html": ArtifactKind.HTML,
        "application/xhtml+xml": ArtifactKind.HTML,
    }
)


# -- project -----------------------------------------------------------------


def init_project(request: InitProjectRequest) -> InitProjectResult:
    """`project.init`: create the Product 8.1 workspace layout at ``request.root``."""
    repo = WorkspaceRepository.init(request.root, request.resolved_name(), policy=request.policy)
    logger.info("initialized %s at %s", repo.config.name, repo.root)
    return InitProjectResult(
        root=repo.root,
        name=repo.config.name,
        policy=repo.review_policy,
        validation=ValidationReport(),
    )


# -- corpus ------------------------------------------------------------------


def register_work(ctx: CapabilityContext, request: RegisterWorkRequest) -> MutationResult:
    """`work.register`: a resolved candidate becomes a Work, its Version, and its Artifact."""
    capability = "work.register"
    candidate = request.candidate
    data = _read_artifact(request.artifact_path, capability)
    digest = content_digest(data)
    errors: list[str] = []
    warnings: list[str] = []
    if candidate.candidate_file_hash is not None and candidate.candidate_file_hash != digest:
        errors.append(
            f"candidate hash {candidate.candidate_file_hash} does not match "
            f"{request.artifact_path} ({digest})"
        )
    title = _work_title(request, warnings)
    validation = ValidationReport.of(tuple(errors), tuple(warnings))
    validation.raise_for_errors(capability)

    mime_type = _media_type(request.artifact_path, request.mime_type)
    kind = request.artifact_kind or _artifact_kind(mime_type)
    provenance = ctx.provenance(workflow="ingest")
    with ctx.repo.lock():
        work_id = _peek_id(ctx.repo, WorkId)
        version_id = VersionId.next_in_scope(work_id.number, ())
        artifact_id = ArtifactId.next_in_scope(work_id.number, ())
        work = Work(
            id=work_id,
            title=title,
            authors=tuple(field.value for field in candidate.metadata.authors),
            year=_candidate_year(candidate.metadata.year),
            identifiers=candidate.metadata.identifiers,
            screening=candidate.screening,
            exclusion_reason=candidate.exclusion_reason,
            versions=(version_id,),
            artifacts=(artifact_id,),
            provenance=provenance,
        )
        version = Version(
            id=version_id,
            work=work_id,
            kind=request.version_kind,
            label=request.version_label,
            identifiers=request.version_identifiers or WorkIdentifiers(),
            provenance=provenance,
        )
        artifact = Artifact(
            id=artifact_id,
            work=work_id,
            version=version_id,
            kind=kind,
            file_hash=digest,
            original_filename=candidate.original_filename or request.artifact_path.name,
            mime_type=mime_type,
            size_bytes=len(data),
            ingested_at=ctx.now(),
            provenance=provenance,
        )
        event = _event(
            ctx,
            ResearchEventType.WORK_INGESTED,
            subjects=(work_id, version_id, artifact_id),
            summary=f"registered {work_id} from {artifact.original_filename}",
            payload={
                "title": work.title,
                "file_hash": digest,
                "mime_type": mime_type,
                "size_bytes": artifact.size_bytes,
                "version_kind": version.kind.value,
                "artifact_kind": artifact.kind.value,
                "resolution": candidate.resolution.value,
            },
        )

        def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
            _confirm_id(tx, WorkId, work_id)
            _confirm_id(tx, VersionId, version_id, work=work_id)
            _confirm_id(tx, ArtifactId, artifact_id, work=work_id)
            tx.put(work)
            tx.put(version)
            tx.put(artifact)
            tx.store_artifact_bytes(artifact, data)
            return (str(work_id), str(version_id), str(artifact_id))

        return _apply(
            ctx,
            capability=capability,
            event=event,
            diff=semantic_diff(None, work),
            validation=validation,
            changed_ids=(str(work_id), str(version_id), str(artifact_id)),
            write=write,
        )


def add_version_artifact(ctx: CapabilityContext, request: AddArtifactRequest) -> MutationResult:
    """`work.add_artifact`: register new bytes for an existing Work (ADR-002).

    A new revision is a new Artifact, and a new Version when the request does not name one.
    Nothing already registered is rewritten.
    """
    capability = "work.add_artifact"
    data = _read_artifact(request.artifact_path, capability)
    digest = content_digest(data)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        work = ctx.repo.get_work(request.work)
    except ObjectNotFoundError as exc:
        raise CapabilityError(f"{capability}: {exc}") from exc
    artifacts = ctx.repo.list_artifacts(work.id)
    duplicate = next((item for item in artifacts if item.file_hash == digest), None)
    if duplicate is not None:
        errors.append(
            f"these bytes are already registered as {duplicate.id}; re-ingesting the same "
            "file is idempotent, so there is nothing to add"
        )
    if request.version is not None and all(
        version.id != request.version for version in ctx.repo.list_versions(work.id)
    ):
        errors.append(f"{work.id} has no version {request.version}")
    validation = ValidationReport.of(tuple(errors), tuple(warnings))
    validation.raise_for_errors(capability)

    mime_type = _media_type(request.artifact_path, request.mime_type)
    kind = request.artifact_kind or _artifact_kind(mime_type)
    provenance = ctx.provenance(workflow="ingest")
    with ctx.repo.lock():
        new_version: Version | None = None
        version_id = request.version
        if version_id is None:
            version_id = _peek_id(ctx.repo, VersionId, work=work.id)
            new_version = Version(
                id=version_id,
                work=work.id,
                kind=request.version_kind,
                label=request.version_label,
                identifiers=request.version_identifiers or WorkIdentifiers(),
                provenance=provenance,
            )
        artifact_id = _peek_id(ctx.repo, ArtifactId, work=work.id)
        artifact = Artifact(
            id=artifact_id,
            work=work.id,
            version=version_id,
            kind=kind,
            file_hash=digest,
            original_filename=request.artifact_path.name,
            mime_type=mime_type,
            size_bytes=len(data),
            ingested_at=ctx.now(),
            provenance=provenance,
        )
        updated = work.touch(
            versions=_appended(work.versions, version_id),
            artifacts=_appended(work.artifacts, artifact_id),
            identifiers=request.identifiers or work.identifiers,
        )
        subjects: tuple[ResearchId, ...] = (
            (work.id, version_id, artifact_id) if new_version else (work.id, artifact_id)
        )
        event = _event(
            ctx,
            (
                ResearchEventType.VERSION_REGISTERED
                if new_version
                else ResearchEventType.ARTIFACT_REGISTERED
            ),
            subjects=subjects,
            summary=(
                f"registered {artifact_id} for {work.id} "
                f"({'new version ' + str(version_id) if new_version else str(version_id)})"
            ),
            payload={
                "file_hash": digest,
                "mime_type": mime_type,
                "size_bytes": artifact.size_bytes,
                "artifact_kind": artifact.kind.value,
                "original_filename": artifact.original_filename,
            },
        )

        def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
            written = [str(work.id)]
            if new_version is not None:
                _confirm_id(tx, VersionId, new_version.id, work=work.id)
                tx.put(new_version)
                written.append(str(new_version.id))
            _confirm_id(tx, ArtifactId, artifact_id, work=work.id)
            tx.put(artifact)
            tx.store_artifact_bytes(artifact, data)
            tx.put(updated)
            written.append(str(artifact_id))
            return tuple(written)

        return _apply(
            ctx,
            capability=capability,
            event=event,
            diff=semantic_diff(work, updated),
            validation=validation,
            changed_ids=(str(work.id), str(version_id), str(artifact_id)),
            write=write,
        )


def store_parsed_document(
    ctx: CapabilityContext, request: StoreParsedDocumentRequest
) -> MutationResult:
    """`work.store_blocks`: persist one parse so anchors resolve without re-parsing."""
    capability = "work.store_blocks"
    document = request.document
    errors: list[str] = []
    warnings: list[str] = []
    try:
        artifact = ctx.repo.get_artifact(document.artifact, work=request.work)
    except ObjectNotFoundError as exc:
        raise CapabilityError(f"{capability}: {exc}") from exc
    file_hash = document.file_hash
    if file_hash != artifact.file_hash:
        errors.append(
            f"parse was taken from {file_hash} but {artifact.id} holds {artifact.file_hash}"
        )
    errors.extend(_document_ownership_errors(document, artifact))
    validation = ValidationReport.of(tuple(errors), tuple(warnings))
    validation.raise_for_errors(capability)

    key = digest_key(document)
    existing = tuple(ctx.repo.iter_blocks(document.artifact, work=artifact.work))
    event = _event(
        ctx,
        ResearchEventType.WORK_PARSED,
        subjects=(artifact.work, artifact.version, artifact.id),
        summary=(
            f"parsed {artifact.id} into {len(document.blocks)} blocks "
            f"across {document.page_count} pages"
        ),
        payload={
            "parser": f"{document.parser_name}@{document.parser_version}",
            "page_count": document.page_count,
            "block_count": len(document.blocks),
            "file_hash": file_hash,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put_blocks(document, work=artifact.work)
        return (key,)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=_blocks_diff(existing, document, key),
        validation=validation,
        changed_ids=(str(artifact.id),),
        write=write,
    )


# -- evidence ----------------------------------------------------------------


def accept_evidence(ctx: CapabilityContext, request: AcceptEvidenceRequest) -> MutationResult:
    """`evidence.accept`: a reviewed candidate becomes accepted Evidence (Product 24.3).

    The real `EvidenceId` is allocated *here*, at the moment the candidate gains authority,
    whenever it still carries `PROVISIONAL_EVIDENCE_ID`. Doing it in the handler rather
    than in one caller is what makes an HTTP or MCP client that posts a staged candidate
    verbatim get a correct id instead of `E0000`; a caller that already allocated one hands
    over a real id and nothing is allocated twice.

    Interpretive and Tier-2 candidates require a human actor (ADR-007). A candidate that
    is still `proposed` needs a verification verdict, which the accepting researcher may
    supply as its verifier; nothing here invents one. Review action `edit` accepts the
    researcher's corrected candidate and is recorded as an acceptance with a rationale
    saying so, because the domain's accepting actions are `accept` and
    `accept_with_qualification`.
    """
    capability = "evidence.accept"
    proposed = request.candidate
    candidate = request.candidate
    if request.review_action is ReviewAction.EDIT:
        if request.edited is None:  # pragma: no cover - the request model guarantees it
            raise CapabilityError(f"{capability}: review action 'edit' needs the edited candidate")
        candidate = request.edited
    if candidate.id == PROVISIONAL_EVIDENCE_ID:
        evidence_id = next_evidence_id(ctx.repo)
        candidate = candidate.touch(id=evidence_id)
        proposed = proposed.touch(id=evidence_id)
    if candidate.is_interpretive and not ctx.is_human:
        raise AuthorityError(
            f"{capability}: {candidate.id} is interpretive (tier "
            f"{int(candidate.review_tier)}, origin {candidate.origin.value}); only a human "
            "actor may accept it"
        )

    already = _accepted_duplicate(ctx.repo, candidate)
    if already is not None:
        return _acceptance_already_recorded(ctx, capability, already, request)

    errors = list(_anchor_errors(ctx.repo, candidate))
    warnings: list[str] = []
    if request.review_action is ReviewAction.EDIT:
        if candidate.source != proposed.source:
            errors.append("an edit may correct the content, never the source anchor")
        warnings.append("content replaced by the researcher's edit before acceptance")
    if candidate.status is EvidenceStatus.PROPOSED and request.verdict is None:
        errors.append(
            "a proposed candidate needs a verification verdict before acceptance; verify it "
            "first, or record the verdict of your own reading"
        )
    validation = ValidationReport.of(tuple(errors), tuple(warnings))
    validation.raise_for_errors(capability)

    rationale = request.rationale or (
        "accepted after researcher edit" if request.review_action is ReviewAction.EDIT else None
    )
    verified = candidate
    if candidate.status is EvidenceStatus.PROPOSED and request.verdict is not None:
        verified = transition_evidence(
            candidate,
            EvidenceStatus.VERIFIED,
            actor=ctx.actor,
            policy=ctx.repo.review_policy,
            verdict=request.verdict,
            rationale=rationale,
        )
    accepted = transition_evidence(
        verified,
        EvidenceStatus.ACCEPTED,
        actor=ctx.actor,
        policy=ctx.repo.review_policy,
        review_action=(
            ReviewAction.ACCEPT
            if request.review_action is ReviewAction.EDIT
            else request.review_action
        ),
        batch_conditions=request.batch_conditions,
        qualification=request.qualification,
        rationale=rationale,
    )
    anchor = accepted.source
    event = _event(
        ctx,
        ResearchEventType.EVIDENCE_ACCEPTED,
        subjects=(accepted.id, anchor.work, anchor.artifact),
        summary=f"accepted evidence {accepted.id} anchored in {anchor.artifact}",
        payload={
            "review_action": request.review_action.value,
            "origin": accepted.origin.value,
            "evidence_type": accepted.evidence_type.value,
            "strength": accepted.strength.value,
            "review_tier": int(accepted.review_tier),
            "verdict": accepted.verification.verdict.value
            if accepted.verification.verdict
            else None,
            "qualification": accepted.qualification,
            **_anchor_payload(accepted),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.append_evidence(accepted)
        return (str(accepted.id),)

    result = _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(proposed, accepted),
        validation=validation,
        changed_ids=(str(accepted.id),),
        write=write,
    )
    _mark_candidate_reviewed(ctx, request.candidate_id, request.review_action)
    return result


def reject_evidence(ctx: CapabilityContext, request: RejectEvidenceRequest) -> MutationResult:
    """`evidence.reject`: refuse a candidate; it never becomes canonical Evidence.

    The refusal is itself canonical. It is appended to the Work's `rejections.jsonl` — the
    file beside the `evidence.jsonl` it was kept out of — carrying the exact anchor, the
    reason, the actor, and the verdict the candidate held when it was refused. That is what
    makes a rejection survive a deleted staging tree: the Review Inbox can recognise the
    same span proposed again and flag it as previously rejected instead of asking the
    researcher the same question twice (Product 24.3, ADR-003).

    A rejected candidate is never written into `evidence.jsonl`; the transition to
    `rejected` is computed only for the semantic diff the mutation reports.
    """
    capability = "evidence.reject"
    candidate = request.candidate
    if not request.reason.strip():
        ValidationReport.of(("a rejection needs a reason",)).raise_for_errors(capability)
    rejected = transition_evidence(
        candidate,
        EvidenceStatus.REJECTED,
        actor=ctx.actor,
        policy=ctx.repo.review_policy,
        review_action=ReviewAction.REJECT,
        rationale=request.reason,
    )
    anchor = candidate.source
    record = RejectionRecord(
        candidate_id=request.candidate_id or str(candidate.id),
        anchor=anchor,
        field=request.field or candidate.content.field,
        reason=request.reason,
        actor=ctx.actor,
        rejected_at=ctx.now(),
        verdict=candidate.verification.verdict,
        origin=candidate.origin,
        evidence_type=candidate.evidence_type,
        review_tier=candidate.review_tier,
    )
    key = digest_key(record)
    event = _event(
        ctx,
        ResearchEventType.EVIDENCE_REJECTED,
        subjects=(candidate.id, anchor.work, anchor.artifact),
        summary=f"rejected evidence candidate {record.candidate_id}",
        payload={
            "reason": request.reason,
            "candidate_id": record.candidate_id,
            "field": record.field,
            "origin": candidate.origin.value,
            "evidence_type": candidate.evidence_type.value,
            "review_tier": int(candidate.review_tier),
            "verdict": None if record.verdict is None else record.verdict.value,
            **_anchor_payload(candidate),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.append_rejection(record)
        return (key,)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(candidate, rejected),
        validation=ValidationReport(),
        changed_ids=(),
        write=write,
    )


# -- claims, decisions, questions --------------------------------------------


def create_claim(ctx: CapabilityContext, request: CreateClaimRequest) -> MutationResult:
    """`claim.create`: register a structured claim with its scope and relations.

    A request that carries no id (or the provisional `C0000`) has one allocated here, under
    the workspace lock, and the allocation is confirmed inside the transaction: two clients
    creating a claim at the same moment therefore cannot be handed the same number, which is
    what a client-side "probe for the next free id" could never guarantee.
    """
    capability = "claim.create"
    if request.claim.id == PROVISIONAL_CLAIM_ID:
        with ctx.repo.lock():
            claim_id = _peek_id(ctx.repo, ClaimId)
            return _write_new_claim(ctx, capability, request.claim.touch(id=claim_id), True)
    return _write_new_claim(ctx, capability, request.claim, False)


def _write_new_claim(
    ctx: CapabilityContext, capability: str, claim: Claim, allocated: bool
) -> MutationResult:
    """Commit one new Claim, confirming the id when this call allocated it."""
    errors: list[str] = []
    if not allocated and _exists(lambda: ctx.repo.get_claim(claim.id)):
        errors.append(f"{claim.id} already exists; audit or supersede it instead")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)
    event = _event(
        ctx,
        ResearchEventType.CLAIM_CREATED,
        subjects=(claim.id,),
        summary=f"created claim {claim.id}",
        payload={
            "type": claim.type.value,
            "requested_strength": claim.requested_strength.value,
            "allowed_strength": claim.allowed_strength.value,
            "status": claim.status.value,
            "relations": len(claim.relations),
            "statement": claim.statement,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        if allocated:
            _confirm_id(tx, ClaimId, claim.id)
        tx.put(claim)
        return (str(claim.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(None, claim),
        validation=validation,
        changed_ids=(str(claim.id),),
        write=write,
    )


def audit_claim(ctx: CapabilityContext, request: AuditClaimRequest) -> MutationResult:
    """`claim.audit`: record the strength the evidence allows, never the one requested."""
    capability = "claim.audit"
    claim = _require(lambda: ctx.repo.get_claim(request.claim_id), capability)
    audited = audit_claim_transition(
        claim,
        status=request.status,
        allowed_strength=request.allowed_strength,
        actor=ctx.actor,
        maximum_defensible_wording=request.maximum_defensible_wording,
        coverage=request.coverage,
    )
    event = _event(
        ctx,
        (
            ResearchEventType.CLAIM_QUALIFIED
            if request.status is ClaimStatus.QUALIFIED
            else ResearchEventType.CLAIM_AUDITED
        ),
        subjects=(claim.id,),
        summary=(f"audited {claim.id}: {request.status.value} at {request.allowed_strength.label}"),
        payload={
            "status": request.status.value,
            "requested_strength": claim.requested_strength.value,
            "allowed_strength": request.allowed_strength.value,
            "maximum_defensible_wording": audited.assessment.maximum_defensible_wording,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(audited)
        return (str(audited.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(claim, audited),
        validation=ValidationReport(),
        changed_ids=(str(claim.id),),
        write=write,
    )


def accept_decision(ctx: CapabilityContext, request: AcceptDecisionRequest) -> MutationResult:
    """`decision.accept`: a proposed researcher decision becomes accepted (Product 38).

    A taxonomy revision reports `taxonomy.revised` rather than `decision.accepted`: one
    atomic mutation carries exactly one semantic event, and the payload keeps the decision
    type so nothing about the change is lost.

    A decision sent with no id has one allocated here, so a client writing an override does
    not have to predict the number `GET /overview` would have told it.
    """
    capability = "decision.accept"
    if request.decision.id == PROVISIONAL_DECISION_ID:
        with ctx.repo.lock():
            decision_id = _peek_id(ctx.repo, DecisionId)
            return _accept_decision(ctx, capability, request.decision.touch(id=decision_id), True)
    return _accept_decision(ctx, capability, request.decision, False)


def _accept_decision(
    ctx: CapabilityContext, capability: str, decision: Decision, allocated: bool
) -> MutationResult:
    """Commit one accepted Decision, confirming the id when this call allocated it."""
    errors: list[str] = []
    if decision.status is not DecisionStatus.PROPOSED:
        errors.append(
            f"{decision.id} is {decision.status.value}; only a proposed decision is accepted here"
        )
    if not ctx.is_human:
        raise AuthorityError(f"{capability}: only a human actor may accept {decision.id}")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)
    before = None if allocated else _current(lambda: ctx.repo.get_decision(decision.id))
    accepted = transition_decision(decision, DecisionStatus.ACCEPTED, actor=ctx.actor)
    taxonomy_revision = decision.type is DecisionType.TAXONOMY_REVISION
    subjects: tuple[ResearchId, ...] = (
        (decision.id, decision.claim) if decision.claim is not None else (decision.id,)
    )
    event = _event(
        ctx,
        (
            ResearchEventType.TAXONOMY_REVISED
            if taxonomy_revision
            else ResearchEventType.DECISION_ACCEPTED
        ),
        subjects=subjects,
        summary=f"accepted {decision.type.value} decision {decision.id}",
        payload={
            "decision_type": decision.type.value,
            "rationale": decision.rationale,
            "auditor_recommendation": (
                decision.auditor_recommendation.value if decision.auditor_recommendation else None
            ),
            "researcher_selected": (
                decision.researcher_selected.value if decision.researcher_selected else None
            ),
            "taxonomy_terms": ", ".join(decision.taxonomy_terms) or None,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        if allocated:
            _confirm_id(tx, DecisionId, accepted.id)
        tx.put(accepted)
        return (str(accepted.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(before, accepted),
        validation=validation,
        changed_ids=(str(accepted.id),),
        write=write,
    )


def override_claim_strength(
    ctx: CapabilityContext, request: OverrideClaimStrengthRequest
) -> MutationResult:
    """`claim.override_strength`: apply an accepted epistemic override to a claim.

    The researcher keeps authority over claim strength, and the override stays visible as
    the Decision that authorised it (Product 38, ADR-007).
    """
    capability = "claim.override_strength"
    if not ctx.is_human:
        raise AuthorityError(f"{capability}: only a human actor may override claim strength")
    claim = _require(lambda: ctx.repo.get_claim(request.claim_id), capability)
    decision = _require(
        lambda: ctx.repo.get_decision(request.decision_id),
        capability,
        hint="an override needs an accepted epistemic_override Decision",
    )
    overridden = override_claim_strength_transition(claim, decision)
    event = _event(
        ctx,
        ResearchEventType.CLAIM_OVERRIDDEN,
        subjects=(claim.id, decision.id),
        summary=(
            f"researcher override on {claim.id}: "
            f"{claim.allowed_strength.label} -> {overridden.allowed_strength.label}"
        ),
        payload={
            "decision": str(decision.id),
            "auditor_recommendation": claim.allowed_strength.value,
            "researcher_selected": overridden.allowed_strength.value,
            "rationale": decision.rationale,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(overridden)
        return (str(overridden.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(claim, overridden),
        validation=ValidationReport(),
        changed_ids=(str(claim.id),),
        write=write,
    )


def create_question(ctx: CapabilityContext, request: CreateQuestionRequest) -> MutationResult:
    """`question.create`: register a research question (Product 31).

    A request with no id has one allocated under the workspace lock, as `claim.create` does.
    """
    capability = "question.create"
    if request.question.id == PROVISIONAL_QUESTION_ID:
        with ctx.repo.lock():
            question_id = _peek_id(ctx.repo, QuestionId)
            return _write_new_question(
                ctx, capability, request.question.touch(id=question_id), True
            )
    return _write_new_question(ctx, capability, request.question, False)


def _write_new_question(
    ctx: CapabilityContext, capability: str, question: ResearchQuestion, allocated: bool
) -> MutationResult:
    """Commit one new ResearchQuestion, confirming the id when this call allocated it."""
    errors: list[str] = []
    if not allocated and _exists(lambda: ctx.repo.get_question(question.id)):
        errors.append(f"{question.id} already exists; update it instead")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)
    event = _event(
        ctx,
        ResearchEventType.QUESTION_CREATED,
        subjects=(question.id,),
        summary=f"created research question {question.id}",
        payload={"question": question.question, "status": question.status.value},
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        if allocated:
            _confirm_id(tx, QuestionId, question.id)
        tx.put(question)
        return (str(question.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(None, question),
        validation=validation,
        changed_ids=(str(question.id),),
        write=write,
    )


def update_question(ctx: CapabilityContext, request: UpdateQuestionRequest) -> MutationResult:
    """`question.update`: move a question's status and relink what bears on it."""
    capability = "question.update"
    question = _require(lambda: ctx.repo.get_question(request.question_id), capability)
    updated = question
    if request.status is not None and request.status is not question.status:
        updated = transition_question(updated, request.status, actor=ctx.actor)
    links = request.links()
    if links:
        updated = updated.touch(**links)
    event = _event(
        ctx,
        ResearchEventType.QUESTION_UPDATED,
        subjects=(question.id,),
        summary=f"updated research question {question.id}",
        payload={
            "status": updated.status.value,
            "claims": len(updated.claims),
            "supporting_evidence": len(updated.supporting_evidence),
            "counter_evidence": len(updated.counter_evidence),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(updated)
        return (str(updated.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(question, updated),
        validation=ValidationReport(),
        changed_ids=(str(question.id),),
        write=write,
    )


# -- notes, anchors, searches, taxonomy, synthesis ---------------------------


def add_note(ctx: CapabilityContext, request: AddNoteRequest) -> MutationResult:
    """`note.add`: capture a low-authority note; it can never be cited as support.

    ``request.source`` is where the capture came from, and is recorded as provenance
    (`Provenance.note`) rather than as note text: the scientific record says what was
    captured, not which window it was typed into.
    """
    capability = "note.add"
    if request.key is not None and any(item.key == request.key for item in ctx.repo.iter_notes()):
        ValidationReport.of((f"note {request.key!r} already exists",)).raise_for_errors(capability)
    fields: dict[str, Any] = {"workflow": "note"}
    if request.source is not None:
        fields["note"] = f"captured via {request.source}"
    note = ResearchNote(text=request.text, provenance=ctx.provenance(**fields))
    # The key is assigned here rather than by the transaction so the diff and the event
    # name the same note file the capability is about to write.
    note = note.touch(key=request.key or note_key(note.created_at, token_hex(3)))
    key = digest_key(note)
    event = _event(
        ctx,
        ResearchEventType.NOTE_CAPTURED,
        subjects=(),
        summary=f"captured research note {note.key}",
        # The capture source is provenance, not content: it is on the note's
        # `Provenance.note` and stays out of the event, so the same `note.add` over the CLI
        # and over HTTP journals the same event (Task 10.4 parity).
        payload={"note": str(note.key), "text": note.text},
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put_note(note)
        return (key,)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(None, note, object_id=key),
        validation=ValidationReport(),
        changed_ids=(),
        write=write,
    )


def promote_note(ctx: CapabilityContext, request: PromoteNoteRequest) -> MutationResult:
    """`note.promote`: record the research object a captured note became (human only)."""
    capability = "note.promote"
    note = next((item for item in ctx.repo.iter_notes() if item.key == request.note_key), None)
    if note is None:
        raise CapabilityError(f"{capability}: no note {request.note_key!r} in {ctx.root}")
    target = request.target
    if not isinstance(target, ClaimId | QuestionId | DecisionId):  # pragma: no cover - DTO guard
        raise CapabilityError(f"{capability}: a note cannot be promoted into {target}")
    validation = ValidationReport.of(tuple(_promotion_target_errors(ctx, target)))
    validation.raise_for_errors(capability)
    promoted = promote_note_transition(note, promoted_to=target, actor=ctx.actor)
    event = _event(
        ctx,
        ResearchEventType.NOTE_PROMOTED,
        subjects=(target,),
        summary=f"promoted note {note.key} into {target}",
        payload={"note": str(note.key), "text": note.text, "target": str(target)},
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put_note(promoted)
        return (digest_key(promoted),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(note, promoted, object_id=digest_key(promoted)),
        validation=validation,
        changed_ids=(str(target),),
        write=write,
    )


def attach_manuscript_anchor(
    ctx: CapabilityContext, request: AttachManuscriptAnchorRequest
) -> MutationResult:
    """`manuscript.attach_claim`: bind one manuscript sentence to a Claim (Product 30.1).

    A human act, like `evidence.accept`: an anchor is what makes a written sentence
    auditable against the accepted graph, so binding one is the researcher saying "this
    sentence rests on that Claim" (Product 24, 30.1; ADR-007). `ManuscriptService.attach`
    refuses the same call, and keeps its own check for callers that never reach here.
    """
    capability = "manuscript.attach_claim"
    if not ctx.is_human:
        raise AuthorityError(
            f"{capability}: only a human actor may attach a manuscript sentence to a claim"
        )
    anchor = request.anchor
    errors: list[str] = []
    if not _exists(lambda: ctx.repo.get_claim(anchor.claim)):
        errors.append(f"no claim {anchor.claim} in this workspace")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)
    key = digest_key(anchor)
    event = _event(
        ctx,
        ResearchEventType.MANUSCRIPT_CLAIM_ATTACHED,
        subjects=(anchor.claim,),
        summary=f"attached {anchor.claim} to {anchor.file}:{anchor.line_start}",
        payload={
            "file": anchor.file,
            "line_start": anchor.line_start,
            "line_end": anchor.line_end,
            "sentence_fingerprint": anchor.sentence_fingerprint,
            "citation_keys": ", ".join(anchor.citation_keys) or None,
            "status": anchor.status.value,
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put_anchor(anchor)
        return (key,)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(None, anchor, object_id=key),
        validation=validation,
        changed_ids=(node_id_for(anchor),),
        write=write,
    )


def record_search_run(ctx: CapabilityContext, request: RecordSearchRunRequest) -> MutationResult:
    """`search_run.record`: persist a reproducible discovery operation (Product 18).

    A run recorded without an id gets the next free `SR####` here, so a discovery client
    never has to know how many runs the workspace already holds.
    """
    capability = "search_run.record"
    if request.search_run.id == PROVISIONAL_SEARCH_RUN_ID:
        with ctx.repo.lock():
            run_id = _peek_id(ctx.repo, SearchRunId)
            return _write_search_run(ctx, capability, request.search_run.touch(id=run_id), True)
    return _write_search_run(ctx, capability, request.search_run, False)


def _write_search_run(
    ctx: CapabilityContext, capability: str, run: SearchRun, allocated: bool
) -> MutationResult:
    """Commit one SearchRun, confirming the id when this call allocated it."""
    before = None if allocated else _current(lambda: ctx.repo.get_search_run(run.id))
    event = _event(
        ctx,
        ResearchEventType.SEARCH_RUN_RECORDED,
        subjects=(run.id,),
        summary=f"recorded search run {run.id}",
        payload={
            "question": run.question,
            "sources": ", ".join(run.sources) or None,
            "discovered": run.results.discovered,
            "screened": run.results.screened,
            "included": run.results.included,
            "failures": len(run.failures),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        if allocated:
            _confirm_id(tx, SearchRunId, run.id)
        tx.put(run)
        return (str(run.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(before, run),
        validation=ValidationReport(),
        changed_ids=(str(run.id),),
        write=write,
    )


def put_taxonomy(ctx: CapabilityContext, request: PutTaxonomyRequest) -> MutationResult:
    """`taxonomy.put`: write a taxonomy authorised by an accepted taxonomy Decision."""
    capability = "taxonomy.put"
    taxonomy = request.taxonomy
    decision = request.decision
    errors = list(_taxonomy_decision_errors(ctx, decision))
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)
    before = _current(lambda: ctx.repo.get_taxonomy(taxonomy.name))
    key = digest_key(taxonomy)
    event = _event(
        ctx,
        ResearchEventType.TAXONOMY_REVISED,
        subjects=(decision.id,),
        summary=f"wrote taxonomy {taxonomy.name!r} under decision {decision.id}",
        payload={
            "taxonomy": taxonomy.name,
            "terms": len(taxonomy.terms),
            "decision": str(decision.id),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(taxonomy)
        return (key,)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(before, taxonomy, object_id=key),
        validation=validation,
        changed_ids=(taxonomy_node_id(taxonomy.name),),
        write=write,
    )


def put_matrix(ctx: CapabilityContext, request: PutMatrixRequest) -> MutationResult:
    """`synthesis.build_matrix`: persist a cross-paper comparison (Product 7.1)."""
    capability = "synthesis.build_matrix"
    matrix = request.matrix
    before = _current(lambda: ctx.repo.get_matrix(matrix.id))
    event = _event(
        ctx,
        ResearchEventType.MATRIX_BUILT,
        subjects=(matrix.id,),
        summary=f"built synthesis matrix {matrix.id} ({matrix.name})",
        payload={
            "name": matrix.name,
            "taxonomy": matrix.taxonomy,
            "works": len(matrix.works),
            "fields": len(matrix.fields),
            "cells": len(matrix.cells),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(matrix)
        return (str(matrix.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(before, matrix),
        validation=ValidationReport(),
        changed_ids=(str(matrix.id),),
        write=write,
    )


# -- ingest and parsing (delegated, so the layer stays parser-free) ----------


def ingest_local_pdf(ctx: CapabilityContext, request: IngestLocalPdfRequest) -> IngestResult:
    """`corpus.ingest`: hash, inspect, resolve, and register one local file.

    The ingest service is imported here rather than at module scope so that importing the
    capability layer never pulls in a PDF parser (Gate P1).
    """
    from research_harness.ingest.service import IngestService

    return IngestService(ctx).ingest(request)


def parse_work(ctx: CapabilityContext, request: ParseWorkRequest) -> ParseResult:
    """`work.parse`: parse a Work's artifact into blocks and store them."""
    from research_harness.ingest.service import IngestService

    return IngestService(ctx).parse(request)


#: Named capabilities, Product 22 names where they exist. Phase 10 adds discovery and a
#: permission model on top of this mapping; it does not add a second business-logic layer.
#: The Phase 1 handlers, which are the ones defined in this module.
CORE_CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = MappingProxyType(
    {
        "corpus.ingest": ingest_local_pdf,
        "work.register": register_work,
        "work.add_artifact": add_version_artifact,
        "work.parse": parse_work,
        "work.store_blocks": store_parsed_document,
        "evidence.accept": accept_evidence,
        "evidence.reject": reject_evidence,
        "claim.create": create_claim,
        "claim.audit": audit_claim,
        "claim.override_strength": override_claim_strength,
        "decision.accept": accept_decision,
        "question.create": create_question,
        "question.update": update_question,
        "note.add": add_note,
        "note.promote": promote_note,
        "manuscript.attach_claim": attach_manuscript_anchor,
        "search_run.record": record_search_run,
        "taxonomy.put": put_taxonomy,
        "synthesis.build_matrix": put_matrix,
    }
)


class _CapabilityHandlers(Mapping[str, Callable[[CapabilityContext, Any], Any]]):
    """Every capability name that has a handler: the core table plus the extension tables.

    The extension modules (`claims_ext`, `extra_handlers`) reach the registry, which reaches
    this module, so they cannot be imported at module scope here. They are imported the
    first time this mapping is read instead, which is why it is a lazy view rather than a
    plain dict: `CAPABILITY_HANDLERS["claim.relate"]` resolves whether or not the caller
    happened to import `claims_ext` first, and the registry-to-handler correspondence is one
    fact rather than three.

    A core name wins a collision: `corpus.ingest` and `work.parse` appear in both tables,
    and the entry here is the raw handler returning a `MutationResult`, as it always was —
    the registry's own wrapper is what turns it into a wire response.
    """

    def __init__(self) -> None:
        self._merged: dict[str, Callable[[CapabilityContext, Any], Any]] | None = None

    def _resolve(self) -> Mapping[str, Callable[[CapabilityContext, Any], Any]]:
        if self._merged is None:
            from research_harness.capabilities import claims_ext, extra_handlers

            self._merged = {
                **extra_handlers.EXTRA_CAPABILITY_HANDLERS,
                **claims_ext.CLAIM_EXTENSION_HANDLERS,
                **CORE_CAPABILITY_HANDLERS,
            }
        return self._merged

    def __getitem__(self, key: str) -> Callable[[CapabilityContext, Any], Any]:
        return self._resolve()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"CAPABILITY_HANDLERS({sorted(self._resolve())})"


CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = _CapabilityHandlers()


# -- shared plumbing ---------------------------------------------------------


def _apply(
    ctx: CapabilityContext,
    *,
    capability: str,
    event: ResearchEvent,
    diff: SemanticDiff,
    validation: ValidationReport,
    changed_ids: Sequence[str],
    write: Callable[[WorkspaceTransaction], tuple[str, ...]],
) -> MutationResult:
    """Commit one staged mutation and report it exactly as Product 36 requires."""
    with ctx.repo.transaction(event, ctx.actor) as tx:
        objects = write(tx)
    stale = tuple(ctx.invalidate(tuple(changed_ids)))
    return MutationResult(
        capability=capability,
        objects=objects,
        event=tx.event,
        diff=diff,
        stale=stale,
        validation=validation,
    )


def _event(
    ctx: CapabilityContext,
    kind: ResearchEventType,
    *,
    subjects: Sequence[ResearchId],
    summary: str,
    payload: Mapping[str, str | int | float | bool | None] | None = None,
) -> ResearchEvent:
    """A semantic event for ``kind``: ids and small scalars only, never a trace."""
    return ResearchEvent(
        event=kind,
        subjects=tuple(subjects),
        actor=ctx.actor,
        occurred_at=ctx.now(),
        summary=summary,
        payload=_payload(payload or {}),
    )


def _payload(
    values: Mapping[str, str | int | float | bool | None],
) -> dict[str, str | int | float | bool | None]:
    """Drop empty entries and clip long strings to the domain's payload limit."""
    clipped: dict[str, str | int | float | bool | None] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, str) and len(value) > MAX_EVENT_PAYLOAD_VALUE_CHARS:
            value = f"{value[: MAX_EVENT_PAYLOAD_VALUE_CHARS - 1]}…"
        clipped[key] = value
    return clipped


def _peek_id[T: ResearchId](
    repo: WorkspaceRepository, id_type: type[T], *, work: WorkId | None = None
) -> T:
    """The id the next allocation will hand out, read under the workspace lock.

    `WorkspaceTransaction.allocate_id` is the allocator, but a semantic event names its
    subjects and must exist before the transaction opens, so the id is read first and
    confirmed inside the transaction by :func:`_confirm_id`.
    """
    if work is not None:
        return id_type.next_in_scope(work.number, _scoped_ids(repo, id_type, work))
    on_disk = id_type.next(_flat_ids(repo, id_type))
    return id_type.make(max(on_disk.number, repo.config.counter(id_type.prefix) + 1))


def _confirm_id[T: ResearchId](
    tx: WorkspaceTransaction, id_type: type[T], expected: T, *, work: WorkId | None = None
) -> T:
    """Allocate ``id_type`` and refuse the mutation if it is not the id already announced."""
    allocated = tx.allocate_id(id_type, work=work)
    if allocated != expected:
        raise CapabilityError(
            f"id allocation moved under this mutation: announced {expected}, allocated "
            f"{allocated}; retry the capability"
        )
    return allocated


def next_evidence_id(repo: WorkspaceRepository) -> EvidenceId:
    """The id the next accepted Evidence will carry (`evidence.accept` allocates it).

    Read from canonical `evidence.jsonl` rather than from staging, because only accepted
    evidence has an id at all: a candidate that is never accepted never consumes a number,
    and deleting `.research/` therefore cannot renumber accepted evidence.
    """
    return _peek_id(repo, EvidenceId)


def _flat_ids(repo: WorkspaceRepository, id_type: type[ResearchId]) -> list[str]:
    match id_type.prefix:
        case "E":
            return [
                str(record.id)
                for work in repo.list_works()
                for record in repo.iter_evidence(work.id, latest_only=False)
            ]
        case "W":
            return [str(work.id) for work in repo.list_works()]
        case "C":
            return [str(claim.id) for claim in repo.list_claims()]
        case "RQ":
            return [str(question.id) for question in repo.list_questions()]
        case "D":
            return [str(decision.id) for decision in repo.list_decisions()]
        case "S":
            return [str(matrix.id) for matrix in repo.list_matrices()]
        case "SR":
            return [str(run.id) for run in repo.list_search_runs()]
        case _:
            return []


def _scoped_ids(repo: WorkspaceRepository, id_type: type[ResearchId], work: WorkId) -> list[str]:
    if id_type.prefix == "V":
        return [str(version.id) for version in repo.list_versions(work)]
    if id_type.prefix == "A":
        return [str(artifact.id) for artifact in repo.list_artifacts(work)]
    return []


def _read_artifact(path: Path, capability: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CapabilityError(f"{capability}: cannot read {path}: {exc}") from exc


def _media_type(path: Path, declared: str | None) -> str:
    if declared:
        return declared
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or DEFAULT_MIME_TYPE


def _artifact_kind(mime_type: str) -> ArtifactKind:
    return _ARTIFACT_KINDS.get(mime_type.split(";")[0].strip().casefold(), ArtifactKind.OTHER)


def _work_title(request: RegisterWorkRequest, warnings: list[str]) -> str:
    """Title for a new Work; never invented, but never empty either."""
    if request.title:
        return request.title
    extracted = request.candidate.metadata.title
    if extracted is not None:
        return extracted.value
    fallback = (request.candidate.original_filename or request.artifact_path.name).rsplit(".", 1)[0]
    warnings.append(f"no title could be read from the file; used the filename {fallback!r}")
    return fallback or request.artifact_path.name


def _candidate_year(field: IdentifierField | None) -> int | None:
    """The candidate's publication year, when it reads as one; never guessed."""
    if field is None:
        return None
    try:
        return int(field.value.strip())
    except ValueError:
        logger.debug("candidate year is not an integer: %r", field.value)
        return None


def _appended[T: ResearchId](values: tuple[T, ...], value: T) -> tuple[T, ...]:
    return values if value in values else (*values, value)


def _anchor_identity(anchor: Any) -> tuple[Any, ...]:
    """The fields `parsing.anchors.anchor_fingerprint` hashes, as a comparable tuple.

    Spelled out rather than imported so this module stays parser-free (Gate P1). Two
    anchors with equal identity tuples hash to the same fingerprint by construction: the
    fingerprint is a digest of exactly these fields, and of nothing else.
    """
    return (
        anchor.file_hash,
        anchor.page,
        str(anchor.block),
        anchor.text_hash,
        anchor.char_start,
        anchor.char_end,
        None if anchor.bbox is None else anchor.bbox.as_tuple(),
    )


def _accepted_duplicate(repo: WorkspaceRepository, candidate: Evidence) -> Evidence | None:
    """Accepted Evidence already recording this exact span and content, if there is one.

    The guard has to live on canonical state rather than on staging: staging is
    regenerable, so a crash between the canonical commit and `mark_reviewed` - or a deleted
    `.research/` - leaves a candidate that looks unreviewed behind Evidence that exists
    (ADR-001, ADR-003). Accepting it again would mint a second `EvidenceId` for one span,
    and the workspace would be consistent and wrong.
    """
    identity = _anchor_identity(candidate.source)
    content = content_digest(candidate.content.model_dump_json(by_alias=True).encode("utf-8"))
    try:
        recorded = list(repo.iter_evidence(candidate.source.work))
    except ObjectNotFoundError:
        return None
    for item in recorded:
        if item.verification.status is not EvidenceStatus.ACCEPTED:
            continue
        if _anchor_identity(item.source) != identity:
            continue
        digest = content_digest(item.content.model_dump_json(by_alias=True).encode("utf-8"))
        if digest == content:
            return item
    return None


def _acceptance_already_recorded(
    ctx: CapabilityContext,
    capability: str,
    existing: Evidence,
    request: AcceptEvidenceRequest,
) -> MutationResult:
    """Answer a repeat acceptance with the Evidence that already records it.

    Idempotent only when the repeat would record the same thing. A repeat that carries a
    different qualification is a *different* scientific statement about the same span, so
    it is refused by name rather than silently dropped or silently duplicated.
    """
    if (request.qualification or None) != (existing.qualification or None):
        raise CapabilityError(
            f"{capability}: this span is already accepted as {existing.id} with "
            f"qualification {existing.qualification!r}; a different qualification is a new "
            "judgement about the same span - edit the accepted evidence's claim relations "
            "or reject and re-accept it, rather than accepting it twice"
        )
    _mark_candidate_reviewed(ctx, request.candidate_id, request.review_action)
    anchor = existing.source
    return MutationResult(
        capability=capability,
        objects=(str(existing.id),),
        event=_event(
            ctx,
            ResearchEventType.EVIDENCE_ACCEPTED,
            subjects=(existing.id, anchor.work, anchor.artifact),
            summary=(f"evidence {existing.id} already records this span; nothing was written"),
            payload={
                "review_action": request.review_action.value,
                "idempotent": True,
                **_anchor_payload(existing),
            },
        ),
        diff=SemanticDiff(object_id=str(existing.id), change=ChangeKind.UPDATED, fields={}),
        stale=(),
        validation=ValidationReport.of(
            warnings=(
                f"this span and content are already accepted as {existing.id}; the "
                "acceptance was not repeated and no event was journalled",
            )
        ),
    )


def _mark_candidate_reviewed(
    ctx: CapabilityContext, candidate_id: str | None, action: ReviewAction
) -> None:
    """Close the staged candidate behind an acceptance, when the caller named one.

    Canonical first, staging second: the mark is best effort over regenerable state, so a
    candidate that is no longer in staging (deleted `.research/`, a hand-built acceptance)
    is not an error. The import is deferred to keep this module free of the staging tree at
    import time.
    """
    if candidate_id is None:
        return
    from research_harness.evidence.staging import StagingError, StagingStore

    try:
        StagingStore(ctx.repo.layout.research_dir).mark_reviewed(candidate_id, action)
    except StagingError as exc:
        logger.info("candidate %s was not marked reviewed: %s", candidate_id, exc)


def _anchor_payload(evidence: Evidence) -> dict[str, str | int | float | bool | None]:
    """The anchor coordinates that identify a candidate's exact source span."""
    anchor = evidence.source
    return {
        "anchor.version": str(anchor.version),
        "anchor.artifact": str(anchor.artifact),
        "anchor.file_hash": anchor.file_hash,
        "anchor.block": str(anchor.block),
        "anchor.text_hash": anchor.text_hash,
        "anchor.page": anchor.page,
        "anchor.char_start": anchor.char_start,
        "anchor.char_end": anchor.char_end,
    }


def _anchor_errors(repo: WorkspaceRepository, evidence: Evidence) -> list[str]:
    """Refuse evidence whose anchor cannot be replayed against registered bytes (ADR-002)."""
    anchor = evidence.source
    errors: list[str] = []
    try:
        repo.get_work(anchor.work)
    except ObjectNotFoundError:
        errors.append(f"no work {anchor.work} in this workspace")
    try:
        artifact = repo.get_artifact(anchor.artifact, work=anchor.work)
    except ObjectNotFoundError:
        return [*errors, f"no artifact {anchor.artifact} in this workspace"]
    if artifact.file_hash != anchor.file_hash:
        errors.append(
            f"anchor was taken from {anchor.file_hash} but {artifact.id} holds "
            f"{artifact.file_hash}; a changed artifact is a new Artifact, never a reattachment"
        )
    return errors


def _document_ownership_errors(document: ParsedDocument, artifact: Artifact) -> list[str]:
    """A parse is stored for exactly the artifact it was taken from, blocks included."""
    errors: list[str] = []
    if document.work != artifact.work or document.version != artifact.version:
        return [
            f"the parse claims {document.work}/{document.version} but {artifact.id} belongs to "
            f"{artifact.work}/{artifact.version}"
        ]
    for block in document.blocks:
        if block.artifact != artifact.id or block.version != artifact.version:
            errors.append(f"block {block.id} does not belong to {artifact.id}")
            break
        if block.work != artifact.work:
            errors.append(f"block {block.id} belongs to work {block.work}, not {artifact.work}")
            break
    return errors


def _blocks_diff(
    existing: Sequence[DocumentBlock], document: ParsedDocument, key: str
) -> SemanticDiff:
    """Diff one parse against the blocks already stored for the same artifact.

    Blocks are a derived collection rather than a single canonical object, so the diff
    reports the parse identity and a digest over the ordered block text hashes: it changes
    exactly when the parse a reader would resolve an anchor against changes.
    """
    change = ChangeKind.UPDATED if existing else ChangeKind.CREATED
    before_digest = _block_digest(existing) if existing else None
    return SemanticDiff(
        object_id=key,
        change=change,
        fields={
            "parser": (None, f"{document.parser_name}@{document.parser_version}"),
            "page_count": (None, document.page_count),
            "block_count": (len(existing) if existing else None, len(document.blocks)),
            "block_text_hashes": (before_digest, _block_digest(document.blocks)),
        },
    )


def _block_digest(blocks: Sequence[DocumentBlock]) -> str:
    material = "\x1e".join(f"{block.id}:{block.page}:{block.text_hash}" for block in blocks)
    return content_digest(material.encode("utf-8"))


def _promotion_target_errors(
    ctx: CapabilityContext, target: ClaimId | QuestionId | DecisionId
) -> list[str]:
    """A note is only promoted into a research object that exists."""
    match target:
        case ClaimId():
            found = _exists(lambda: ctx.repo.get_claim(target))
        case QuestionId():
            found = _exists(lambda: ctx.repo.get_question(target))
        case DecisionId():
            found = _exists(lambda: ctx.repo.get_decision(target))
    return [] if found else [f"no {target} in this workspace to promote the note into"]


def _taxonomy_decision_errors(ctx: CapabilityContext, decision: Decision) -> list[str]:
    """A taxonomy is project-approved classification: it needs its accepted Decision."""
    errors: list[str] = []
    if decision.type is not DecisionType.TAXONOMY_REVISION:
        errors.append(f"{decision.id} is a {decision.type.value} decision, not a taxonomy revision")
    if decision.status is not DecisionStatus.ACCEPTED:
        errors.append(f"{decision.id} is {decision.status.value}; accept it before it takes effect")
    if decision.provenance.source is not ProvenanceSource.HUMAN:
        errors.append(f"{decision.id} must be authored by the researcher")
    stored = _current(lambda: ctx.repo.get_decision(decision.id))
    if stored is None:
        errors.append(f"{decision.id} is not in this workspace; accept it through decision.accept")
    elif stored.status is not DecisionStatus.ACCEPTED:
        errors.append(f"{decision.id} is {stored.status.value} in this workspace")
    return errors


def _exists[T](read: Callable[[], T]) -> bool:
    return _current(read) is not None


def _current[T](read: Callable[[], T]) -> T | None:
    """The canonical object a read returns, or ``None`` when there is not one yet."""
    try:
        return read()
    except ObjectNotFoundError:
        return None


def _require[T](read: Callable[[], T], capability: str, *, hint: str | None = None) -> T:
    """Read a canonical object the capability needs, as a capability error when it is absent."""
    try:
        return read()
    except ObjectNotFoundError as exc:
        detail = f"{exc}" if hint is None else f"{exc} ({hint})"
        raise CapabilityError(f"{capability}: {detail}") from exc
