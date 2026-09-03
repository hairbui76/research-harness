"""Claim relation and supersession capabilities, awaiting a merge into `CAPABILITY_HANDLERS`.

`claim.create` writes a whole Claim and `claim.audit` writes only an assessment, so neither
can change a claim's evidence relations once the claim exists, and nothing retires a claim.
Product 10.4 needs both: relations are many-to-many and aspect-scoped, so the same evidence
may support a claim on one aspect and qualify it on another, and the set is edited as the
reading of a paper sharpens.

The three handlers here have exactly the contract every handler in `handlers.py` has - one
atomic mutation, one semantic event, one stale set (ADR-001, ADR-004, ADR-008) - and are
listed in :data:`CLAIM_EXTENSION_HANDLERS` so the registry can absorb them in one line.

A relation change never rewrites the claim's assessment. The audit that produced it read a
different relation set, so the honest record is a claim whose assessment is now older than
its relations; `ClaimService.show` reports that, and re-auditing is a researcher action
(ADR-008: derived state goes stale, it is not recomputed behind the researcher's back).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.diff import semantic_diff
from research_harness.capabilities.dto import (
    CapabilityRequest,
    MutationResult,
    ValidationReport,
)
from research_harness.capabilities.handlers import _apply, _event, _require
from research_harness.domain.claim import Claim, ClaimEvidenceRelation, Coverage
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimStatus,
    ResearchEventType,
)
from research_harness.domain.errors import AuthorityError
from research_harness.domain.ids import ClaimId, EvidenceId
from research_harness.domain.research import ResearchEvent
from research_harness.domain.transitions import supersede_claim as supersede_claim_transition
from research_harness.workspace.repository import WorkspaceRepository, WorkspaceTransaction

__all__ = [
    "CLAIM_EXTENSION_HANDLERS",
    "RELATE_CAPABILITY",
    "SUPERSEDE_CAPABILITY",
    "UNRELATE_CAPABILITY",
    "UPDATE_COVERAGE_CAPABILITY",
    "RelateClaimEvidenceRequest",
    "SupersedeClaimRequest",
    "UnrelateClaimEvidenceRequest",
    "UpdateClaimCoverageRequest",
    "relate_claim_evidence",
    "supersede_claim",
    "unrelate_claim_evidence",
    "update_claim_coverage",
]

RELATE_CAPABILITY = "claim.relate"
UNRELATE_CAPABILITY = "claim.unrelate"
SUPERSEDE_CAPABILITY = "claim.supersede"
UPDATE_COVERAGE_CAPABILITY = "claim.update_coverage"


# -- requests ----------------------------------------------------------------


class RelateClaimEvidenceRequest(CapabilityRequest):
    """`claim.relate`: add one directed claim-evidence edge (Product 10.4)."""

    claim_id: ClaimId
    relation: ClaimEvidenceRelation


class UnrelateClaimEvidenceRequest(CapabilityRequest):
    """`claim.unrelate`: remove the edge named by evidence, relation, and aspect."""

    claim_id: ClaimId
    evidence: EvidenceId
    relation: ClaimEvidenceRelationType
    aspect: str | None = None


class SupersedeClaimRequest(CapabilityRequest):
    """`claim.supersede`: retire a claim, optionally naming the claim that replaces it."""

    claim_id: ClaimId
    reason: str
    superseded_by: ClaimId | None = None


class UpdateClaimCoverageRequest(CapabilityRequest):
    """`claim.update_coverage`: record the search funnel a claim's scope rests on.

    The `Coverage` is computed by `discovery.coverage_for` from recorded `SearchRun`s and
    handed here already deterministic (Tier 0); this capability persists it and checks that
    every run it names actually exists, so a coverage record can always be reproduced from
    the runs behind it (Product 18).
    """

    claim_id: ClaimId
    coverage: Coverage


# -- handlers ----------------------------------------------------------------


def relate_claim_evidence(
    ctx: CapabilityContext, request: RelateClaimEvidenceRequest
) -> MutationResult:
    """`claim.relate`: link one evidence object to a claim under one relation and aspect.

    The edge set is many-to-many: the same evidence may appear repeatedly under different
    relations or different aspects. Only the exact triple (evidence, relation, aspect) is
    refused as a duplicate, because a second identical edge would double-count support.
    """
    capability = RELATE_CAPABILITY
    claim = _require(lambda: ctx.repo.get_claim(request.claim_id), capability)
    link = request.relation
    errors: list[str] = []
    if claim.status is ClaimStatus.SUPERSEDED:
        errors.append(f"{claim.id} is superseded; relations of a retired claim do not change")
    if _find(claim, link.evidence, link.relation, link.aspect) is not None:
        errors.append(
            f"{claim.id} already records {link.evidence} as {link.relation.value}"
            f"{_aspect_suffix(link.aspect)}"
        )
    if not _evidence_exists(ctx.repo, link.evidence):
        errors.append(
            f"no accepted evidence {link.evidence} in this workspace; an unresolvable id "
            "supports nothing"
        )
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)

    related = claim.touch(relations=(*claim.relations, link))
    event = _event(
        ctx,
        ResearchEventType.CLAIM_RELATION_CHANGED,
        subjects=(claim.id, link.evidence),
        summary=(
            f"linked {link.evidence} to {claim.id} as {link.relation.value}"
            f"{_aspect_suffix(link.aspect)}"
        ),
        payload={
            "change": "related",
            "evidence": str(link.evidence),
            "relation": link.relation.value,
            "aspect": link.aspect,
            "note": link.note,
            "relations": len(related.relations),
        },
    )
    return _commit(ctx, capability, claim, related, event)


def unrelate_claim_evidence(
    ctx: CapabilityContext, request: UnrelateClaimEvidenceRequest
) -> MutationResult:
    """`claim.unrelate`: drop exactly the edge named; the claim's other edges are untouched."""
    capability = UNRELATE_CAPABILITY
    claim = _require(lambda: ctx.repo.get_claim(request.claim_id), capability)
    link = _find(claim, request.evidence, request.relation, request.aspect)
    errors: list[str] = []
    if claim.status is ClaimStatus.SUPERSEDED:
        errors.append(f"{claim.id} is superseded; relations of a retired claim do not change")
    if link is None:
        errors.append(
            f"{claim.id} does not record {request.evidence} as {request.relation.value}"
            f"{_aspect_suffix(request.aspect)}"
        )
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)

    remaining = tuple(item for item in claim.relations if item is not link)
    unrelated = claim.touch(relations=remaining)
    event = _event(
        ctx,
        ResearchEventType.CLAIM_RELATION_CHANGED,
        subjects=(claim.id, request.evidence),
        summary=(
            f"unlinked {request.evidence} from {claim.id} as {request.relation.value}"
            f"{_aspect_suffix(request.aspect)}"
        ),
        payload={
            "change": "unrelated",
            "evidence": str(request.evidence),
            "relation": request.relation.value,
            "aspect": request.aspect,
            "relations": len(remaining),
        },
    )
    return _commit(ctx, capability, claim, unrelated, event)


def supersede_claim(ctx: CapabilityContext, request: SupersedeClaimRequest) -> MutationResult:
    """`claim.supersede`: retire a claim; superseded is terminal and human-only.

    The replacing claim is recorded on the event rather than on the claim: a Claim has no
    field for its successor, and inventing one would put a link nothing else reads into
    canonical state. The event log is where the succession stays auditable (Product 19.3).
    """
    capability = SUPERSEDE_CAPABILITY
    if not ctx.is_human:
        raise AuthorityError(f"{capability}: only a human actor may retire a claim")
    claim = _require(lambda: ctx.repo.get_claim(request.claim_id), capability)
    errors: list[str] = []
    if not request.reason.strip():
        errors.append("superseding a claim requires a reason")
    if request.superseded_by is not None:
        if request.superseded_by == claim.id:
            errors.append(f"{claim.id} cannot supersede itself")
        elif not _claim_exists(ctx.repo, request.superseded_by):
            errors.append(f"no claim {request.superseded_by} in this workspace")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)

    superseded = supersede_claim_transition(claim, actor=ctx.actor)
    event = _event(
        ctx,
        ResearchEventType.CLAIM_SUPERSEDED,
        subjects=(claim.id,),
        summary=f"superseded claim {claim.id}",
        payload={
            "reason": request.reason,
            "superseded_by": str(request.superseded_by) if request.superseded_by else None,
            "previous_status": claim.status.value,
        },
    )
    return _commit(ctx, capability, claim, superseded, event)


#: The handlers this module adds, ready to be merged into `CAPABILITY_HANDLERS`.
def update_claim_coverage(
    ctx: CapabilityContext, request: UpdateClaimCoverageRequest
) -> MutationResult:
    """`claim.update_coverage`: persist the funnel `research coverage` computed.

    Two commands used to compute the same quantity and disagree, and the one the audit read
    was always zero, so every literature-wide claim was capped at L1 for a plumbing reason
    (dogfood F2). This is the write half of the fix: the coverage the discovery record
    supports is recorded *on the claim*, where `claim.audit` reads it.

    Nothing here decides anything. The counts arrive computed; the only rule enforced is
    that each `SearchRun` the record names is one this workspace actually holds, because a
    coverage record that cannot be reproduced from its runs is not a coverage record.
    """
    capability = UPDATE_COVERAGE_CAPABILITY
    claim = _require(lambda: ctx.repo.get_claim(request.claim_id), capability)
    recorded = {run.id for run in ctx.repo.list_search_runs()}
    missing = sorted(str(run) for run in request.coverage.search_runs if run not in recorded)
    errors: list[str] = []
    if missing:
        errors.append(
            f"no search run {', '.join(missing)} in this workspace; coverage names the runs "
            "it was read off, and a run that is not recorded cannot be reproduced"
        )
    if claim.status is ClaimStatus.SUPERSEDED:
        errors.append(f"{claim.id} is superseded; a retired claim's coverage does not change")
    validation = ValidationReport.of(tuple(errors))
    validation.raise_for_errors(capability)

    updated = claim.touch(coverage=request.coverage)
    coverage = request.coverage
    event = _event(
        ctx,
        ResearchEventType.CLAIM_COVERAGE_RECORDED,
        subjects=(claim.id,),
        summary=(
            f"recorded coverage for {claim.id}: {coverage.examined_works} of "
            f"{coverage.relevant_works} relevant works examined"
        ),
        payload={
            "relevant_works": coverage.relevant_works,
            "examined_works": coverage.examined_works,
            "unresolved_works": coverage.unresolved_works,
            "overturn_risk": coverage.overturn_risk.value,
            "search_runs": ", ".join(str(run) for run in coverage.search_runs) or None,
            "cutoff": None if coverage.cutoff is None else coverage.cutoff.isoformat(),
        },
    )

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(updated)
        return (str(updated.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(claim, updated),
        validation=validation,
        changed_ids=(str(updated.id),),
        write=write,
    )


CLAIM_EXTENSION_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], MutationResult]] = (
    MappingProxyType(
        {
            RELATE_CAPABILITY: relate_claim_evidence,
            UNRELATE_CAPABILITY: unrelate_claim_evidence,
            SUPERSEDE_CAPABILITY: supersede_claim,
            UPDATE_COVERAGE_CAPABILITY: update_claim_coverage,
        }
    )
)


# -- helpers -----------------------------------------------------------------


def _commit(
    ctx: CapabilityContext,
    capability: str,
    before: Claim,
    after: Claim,
    event: ResearchEvent,
) -> MutationResult:
    """Write ``after`` and report the mutation the way every capability reports one."""

    def write(tx: WorkspaceTransaction) -> tuple[str, ...]:
        tx.put(after)
        return (str(after.id),)

    return _apply(
        ctx,
        capability=capability,
        event=event,
        diff=semantic_diff(before, after),
        validation=ValidationReport(),
        changed_ids=(str(after.id),),
        write=write,
    )


def _find(
    claim: Claim,
    evidence: EvidenceId,
    relation: ClaimEvidenceRelationType,
    aspect: str | None,
) -> ClaimEvidenceRelation | None:
    """The edge with exactly this evidence, relation, and aspect, or ``None``."""
    for link in claim.relations:
        if link.evidence == evidence and link.relation is relation and link.aspect == aspect:
            return link
    return None


def _aspect_suffix(aspect: str | None) -> str:
    return "" if aspect is None else f" on {aspect!r}"


def _evidence_exists(repo: WorkspaceRepository, evidence: EvidenceId) -> bool:
    """True when the workspace holds accepted evidence with this id."""
    return any(
        item.id == evidence for work in repo.list_works() for item in repo.iter_evidence(work.id)
    )


def _claim_exists(repo: WorkspaceRepository, claim: ClaimId) -> bool:
    return any(item.id == claim for item in repo.list_claims())
