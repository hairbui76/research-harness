"""The strict review gate: the one place a staged candidate becomes accepted Evidence.

Everything a researcher can do to a candidate lives here — Accept, Accept with
qualification, Edit, Reject, Defer, Request more evidence, and the partial acceptance that
splits a source fact from the interpretation attached to it (Product §24.3). Three rules
hold for all of them:

**Acceptance goes through `capabilities/`.** This module never opens a workspace
transaction and never writes a canonical file. It reads staging, decides what to ask for,
and calls `evidence.accept` / `evidence.reject` / `note.add`, so the review gate, the
journalled event, and dependency invalidation keep exactly one enforcement point
(ADR-004).

**Authority is the handler's to refuse.** A model actor reaching this service does not get
a softer path: `transition_evidence` refuses acceptance for a non-human actor under the
default strict policy, and refuses it for an interpretive or Tier-2 candidate under any
policy (ADR-003, ADR-007, Product §42 H).

**Batch acceptance is deterministic or it does not happen.** Every condition in
:meth:`EvidenceReviewService.accept_batch` is a fact about the candidate, the anchor, the
corpus, or a recorded rejection. Model confidence is not a condition, is not read, and is
not stored anywhere this module can reach (§24.4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptEvidenceRequest,
    AddNoteRequest,
    MutationResult,
    RejectEvidenceRequest,
)
from research_harness.capabilities.handlers import (
    accept_evidence,
    add_note,
    next_evidence_id,
    reject_evidence,
)
from research_harness.domain.base import Provenance, utc_now
from research_harness.domain.enums import (
    ACCEPTING_REVIEW_ACTIONS,
    EvidenceOrigin,
    EvidenceStatus,
    EvidenceStrength,
    ReviewAction,
    ReviewPolicy,
    ReviewTier,
    VerificationVerdict,
)
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.evidence import (
    Evidence,
    EvidenceContent,
    Interpretation,
    VerificationRecord,
)
from research_harness.domain.ids import EvidenceId, WorkId
from research_harness.domain.transitions import BatchPolicyConditions
from research_harness.evidence.conflicts import (
    ConflictChoice,
    ConflictRecord,
    ConflictStore,
)
from research_harness.evidence.review import (
    ReviewItem,
    ReviewQueue,
    build_inbox,
    stored_document,
    stored_documents,
)
from research_harness.evidence.staging import (
    PROVISIONAL_EVIDENCE_ID,
    CandidateStatus,
    EvidenceCandidate,
    StagingStore,
    candidate_id_for,
)
from research_harness.parsing.anchors import AnchorValidationStatus, validate_anchor

logger = logging.getLogger(__name__)

__all__ = [
    "FACT_ORIGINS",
    "INTERPRETATION_FIELD_SUFFIX",
    "LOW_RISK_TIERS",
    "BatchResult",
    "EvidenceReviewService",
    "SplitAcceptance",
]

#: Origins a *source fact* may carry. An interpretation is never one of these: reading
#: meaning into a span is a separate object with its own review (Product §9.1, §24.3).
FACT_ORIGINS: frozenset[EvidenceOrigin] = frozenset(
    {EvidenceOrigin.SOURCE_OBSERVED, EvidenceOrigin.AUTHOR_CLAIMED}
)

#: Tiers a policy batch may touch. Tier 2 is deep review by definition (§24.1).
LOW_RISK_TIERS: frozenset[ReviewTier] = frozenset({ReviewTier.TIER_0, ReviewTier.TIER_1})

INTERPRETATION_FIELD_SUFFIX = ":interpretation"
"""Field suffix a split interpretation is staged under, so it never competes with the fact."""


@dataclass(frozen=True, slots=True)
class SplitAcceptance:
    """What one partial acceptance did: one accepted fact, one interpretation elsewhere."""

    accepted: MutationResult
    """The `evidence.accept` mutation for the source fact — always exactly one."""

    evidence: EvidenceId
    interpretation_candidate: str | None = None
    """Staging id of the interpretation, when it was staged for its own Tier-2 review."""

    rejected: MutationResult | None = None
    """The `evidence.reject` mutation, when the interpretation was refused instead."""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "evidence": str(self.evidence),
            "accepted": self.accepted.as_dict(),
            "interpretation_candidate": self.interpretation_candidate,
            "rejected": None if self.rejected is None else self.rejected.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class BatchResult:
    """What a policy batch accepted, and why it refused everything else."""

    accepted: tuple[str, ...] = ()
    """Candidate ids accepted, or — under `dry_run` — the ids that would be."""

    skipped: dict[str, str] = field(default_factory=dict)
    """Candidate id -> every deterministic condition it failed, so the refusal is auditable."""

    mutations: tuple[MutationResult, ...] = ()
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "dry_run": self.dry_run,
            "accepted": list(self.accepted),
            "skipped": dict(sorted(self.skipped.items())),
            "mutations": [mutation.as_dict() for mutation in self.mutations],
        }


class EvidenceReviewService:
    """Researcher review actions over one workspace's staged candidates.

    The context carries the actor, so a transport does not get to decide who is reviewing;
    the staging store carries the candidates, which stay in staging after the decision so
    the inbox can show what was already answered.
    """

    def __init__(
        self,
        ctx: CapabilityContext,
        staging: StagingStore,
        conflicts: ConflictStore | None = None,
    ) -> None:
        self._ctx = ctx
        self._staging = staging
        self._conflicts = (
            conflicts if conflicts is not None else ConflictStore(staging.research_dir)
        )

    def __repr__(self) -> str:
        return f"EvidenceReviewService(actor={self._ctx.actor!r}, root={str(self._ctx.root)!r})"

    @property
    def ctx(self) -> CapabilityContext:
        """The capability context every mutation runs through."""
        return self._ctx

    @property
    def staging(self) -> StagingStore:
        """The candidate store this service reviews."""
        return self._staging

    @property
    def conflicts(self) -> ConflictStore:
        """The materialized conflicts this service resolves."""
        return self._conflicts

    # -- the six review actions ---------------------------------------------

    def accept(
        self,
        candidate_id: str,
        *,
        action: ReviewAction = ReviewAction.ACCEPT,
        qualification: str | None = None,
        edited: Evidence | None = None,
        verdict: VerificationVerdict | None = None,
        rationale: str | None = None,
        batch_conditions: BatchPolicyConditions | None = None,
    ) -> MutationResult:
        """Accept one candidate as canonical Evidence (`evidence.accept`).

        The staged candidate carries `PROVISIONAL_EVIDENCE_ID`; its real `EvidenceId` is
        allocated here, at the moment it gains authority, from the ids already written to
        canonical `evidence.jsonl`. Deleting `.research/` therefore cannot renumber accepted
        evidence: staging never held the id.

        Accepting the same span twice is idempotent, and the guard is on canonical state
        rather than on this store: `evidence.accept` answers a repeat with the Evidence
        that already records the span, so a crash between the canonical commit and
        :meth:`StagingStore.mark_reviewed` - or a deleted `.research/` - cannot mint a
        second `EvidenceId` for one anchor.
        """
        candidate = self._reviewable(candidate_id)
        evidence_id = self._next_evidence_id()
        target = candidate.evidence if edited is None else edited
        request = AcceptEvidenceRequest(
            candidate=candidate.evidence.touch(id=evidence_id),
            review_action=action,
            qualification=qualification,
            edited=None if edited is None else edited.touch(id=evidence_id),
            verdict=verdict if verdict is not None else self._verdict_of(candidate, target),
            rationale=rationale,
            batch_conditions=batch_conditions,
        )
        result = accept_evidence(self._ctx, request)
        self._staging.mark_reviewed(candidate_id, action)
        # The handler answers a repeat acceptance with the Evidence that already records
        # the span, so the id it wrote is the id to log - never the one peeked above.
        logger.info("accepted candidate %s as %s", candidate_id, result.objects[0])
        return result

    def reject(self, candidate_id: str, reason: str) -> MutationResult:
        """Refuse one candidate (`evidence.reject`); it never becomes canonical Evidence.

        The candidate stays in staging as `reviewed`/`reject` so the inbox can show what was
        already answered, and the durable record goes to the Work's `rejections.jsonl`.
        """
        candidate = self._staging.get(candidate_id)
        result = reject_evidence(
            self._ctx,
            RejectEvidenceRequest(
                candidate=candidate.evidence,
                reason=reason,
                candidate_id=candidate_id,
                field=candidate.field,
            ),
        )
        self._staging.mark_reviewed(candidate_id, ReviewAction.REJECT)
        return result

    def defer(self, candidate_id: str, note: str) -> EvidenceCandidate:
        """Put one candidate aside without deciding it; staging only.

        Deferral changes nothing canonical — there is nothing to record but the researcher's
        own note, which is kept on the candidate. The status stays reviewable, so the item
        remains in the inbox rather than quietly leaving it (Product §24.3).
        """
        return self._note_action(candidate_id, ReviewAction.DEFER, note)

    def request_more_evidence(self, candidate_id: str, note: str) -> MutationResult:
        """Ask for more evidence: staging records the request, `note.add` makes it durable.

        A request that lives only in staging dies with the next `.research/` deletion, and a
        question worth asking should outlive a rebuild — so it is captured as a low-authority
        `ResearchNote`, which a researcher can later promote into a `ResearchQuestion`
        (Product §31).
        """
        candidate = self._note_action(candidate_id, ReviewAction.REQUEST_MORE_EVIDENCE, note)
        return add_note(
            self._ctx,
            AddNoteRequest(
                text=(
                    f"more evidence requested for candidate {candidate_id} "
                    f"(field {candidate.field!r}, work {candidate.work}): {note}"
                )
            ),
        )

    # -- partial acceptance --------------------------------------------------

    def split_accept(
        self,
        candidate_id: str,
        *,
        fact: Evidence,
        interpretation: Interpretation | None = None,
        reject_interpretation_reason: str | None = None,
    ) -> SplitAcceptance:
        """Accept the source fact and deal with its interpretation separately (§24.3).

        This is the acceptance test of ADR-007: a candidate that mixes what the source says
        with what it is taken to mean must be splittable, and exactly one accepted Evidence
        may result. The fact keeps the candidate's anchor and must carry a source origin;
        the interpretation is either staged as its own Tier-2 candidate — under a distinct
        field, so it never competes with the fact it was split from — or refused with a
        reason, which is recorded in `rejections.jsonl` like any other refusal.
        """
        candidate = self._reviewable(candidate_id)
        self._check_split(candidate, fact, interpretation, reject_interpretation_reason)

        edited = None if _same_content(candidate.evidence, fact) else fact
        accepted = self.accept(
            candidate_id,
            action=ReviewAction.ACCEPT if edited is None else ReviewAction.EDIT,
            edited=edited,
            rationale="source fact accepted; the attached interpretation was split out",
        )
        evidence_id = EvidenceId(accepted.objects[0])

        derived = self._derive_interpretation(candidate, fact, interpretation, evidence_id)
        if interpretation is not None:
            self._staging.put(derived)
            logger.info(
                "split candidate %s: accepted %s, staged interpretation %s",
                candidate_id,
                evidence_id,
                derived.candidate_id,
            )
            return SplitAcceptance(
                accepted=accepted,
                evidence=evidence_id,
                interpretation_candidate=derived.candidate_id,
            )

        rejected = reject_evidence(
            self._ctx,
            RejectEvidenceRequest(
                candidate=derived.evidence,
                reason=reject_interpretation_reason or "",
                candidate_id=derived.candidate_id,
                field=derived.field,
            ),
        )
        return SplitAcceptance(accepted=accepted, evidence=evidence_id, rejected=rejected)

    # -- batch acceptance ----------------------------------------------------

    def accept_batch(
        self,
        *,
        conditions: BatchPolicyConditions | None = None,
        work: WorkId | None = None,
        dry_run: bool = False,
    ) -> BatchResult:
        """Accept every candidate that satisfies the Product §24.4 conditions, and no other.

        Permitted only where a policy says so: the workspace's `review_policy` is
        `policy_batch`, or the caller passes the deterministic conditions explicitly. Under
        the default strict policy, with no conditions, this raises — that is the point of
        the default (ADR-007).

        Each condition below is a fact, checked per candidate at this moment: the verifier
        said `supported`, the anchor still replays against the stored blocks, no competing
        candidate answers the same field, the field is low risk (Tier <= 1, not numeric, no
        absence state), no accepted Evidence reads the same span differently, and the span
        was not previously rejected. Confidence is not among them and never will be.
        """
        self._authorize_batch(conditions)
        queue = self._queue(work)
        accepted: list[str] = []
        skipped: dict[str, str] = {}
        mutations: list[MutationResult] = []
        for item in queue:
            failures = _batch_failures(item)
            if failures:
                skipped[item.candidate_id] = "; ".join(failures)
                continue
            accepted.append(item.candidate_id)
            if not dry_run:
                mutations.append(
                    self.accept(
                        item.candidate_id,
                        rationale="accepted under the policy batch conditions of Product 24.4",
                        batch_conditions=_SATISFIED,
                    )
                )
        return BatchResult(
            accepted=tuple(accepted),
            skipped=skipped,
            mutations=tuple(mutations),
            dry_run=dry_run,
        )

    # -- conflicts -----------------------------------------------------------

    def resolve_conflict(
        self,
        candidate_id: str,
        choice: ConflictChoice,
        reason: str,
        *,
        conflict_id: str | None = None,
    ) -> MutationResult | None:
        """Resolve a conflict the researcher's way; the reason is recorded either way.

        Nothing here prefers a provider, a verdict, or the newer proposal: a conflict is a
        question for a person, and `choice` is their answer (Product §25, Task 13.2). Any
        materialized `ConflictRecord` about this candidate is closed with the same choice,
        reason, and actor — `conflict_id` names one when several are open — and the record
        is closed only after the action it describes actually succeeded, so a refused
        acceptance leaves the conflict where a researcher can still see it.
        """
        if not reason.strip():
            raise CapabilityError("resolving a conflict requires a reason")
        if not self._ctx.is_human:
            raise AuthorityError(
                f"actor {self._ctx.actor!r} cannot resolve a conflict; a disagreement about "
                "scientific state is answered by a researcher, never by a model"
            )
        records = self._open_conflicts(candidate_id, conflict_id)
        result = self._apply_resolution(candidate_id, choice, reason)
        for record in records:
            self._conflicts.resolve(record.conflict_id, choice, reason, self._ctx.actor)
        return result

    def _apply_resolution(
        self, candidate_id: str, choice: ConflictChoice, reason: str
    ) -> MutationResult | None:
        """The existing review path the researcher's choice maps onto."""
        match choice:
            case "accept":
                return self.accept(candidate_id, rationale=reason)
            case "reject":
                return self.reject(candidate_id, reason)
            case "defer":
                self.defer(candidate_id, reason)
                return None
            case _:  # pragma: no cover - the Literal keeps this unreachable for typed callers
                raise CapabilityError(f"unknown conflict resolution {choice!r}")

    def _open_conflicts(
        self, candidate_id: str, conflict_id: str | None
    ) -> tuple[ConflictRecord, ...]:
        """The records this resolution closes: the named one, else every open one."""
        if conflict_id is None:
            return tuple(self._conflicts.open_for(candidate_id))
        record = self._conflicts.get(conflict_id)
        if record.subject != candidate_id:
            raise CapabilityError(
                f"conflict {conflict_id} is about {record.subject!r}, not candidate "
                f"{candidate_id!r}"
            )
        return (record,)

    # -- reads ---------------------------------------------------------------

    def inbox(self, work: WorkId | None = None) -> ReviewQueue:
        """The review queue this service acts on, anchors replayed against stored blocks."""
        return self._queue(work)

    # -- internals -----------------------------------------------------------

    def _queue(self, work: WorkId | None) -> ReviewQueue:
        works = [work] if work is not None else self._staging.works()
        return build_inbox(
            self._staging,
            self._ctx.repo,
            work=work,
            parsed=stored_documents(self._ctx.repo, works),
        )

    def _reviewable(self, candidate_id: str) -> EvidenceCandidate:
        """The candidate, refusing one that has already been accepted."""
        candidate = self._staging.get(candidate_id)
        if (
            candidate.status is CandidateStatus.REVIEWED
            and candidate.review_action in ACCEPTING_REVIEW_ACTIONS
        ):
            raise CapabilityError(
                f"candidate {candidate_id} was already accepted "
                f"({candidate.review_action}); it cannot be accepted twice"
            )
        return candidate

    def _next_evidence_id(self) -> EvidenceId:
        """The next free `EvidenceId`, from the one allocator the capability layer uses.

        `evidence.accept` allocates the same id for a caller that does not, so this is only
        an early read: the service names the id in its log line and in `SplitAcceptance`
        before the mutation returns. Both paths ask `capabilities.next_evidence_id`, so
        they cannot disagree and nothing is allocated twice.
        """
        return next_evidence_id(self._ctx.repo)

    def _note_action(self, candidate_id: str, action: ReviewAction, note: str) -> EvidenceCandidate:
        """Record a non-deciding review action on the candidate; it stays reviewable."""
        if not note.strip():
            raise CapabilityError(f"review action {action.value!r} requires a note")
        candidate = self._staging.get(candidate_id)
        evidence = candidate.evidence.touch(
            verification=candidate.evidence.verification.touch(
                rationale=note, reviewed_at=utc_now()
            )
        )
        updated = candidate.touch(evidence=evidence, review_action=action)
        self._staging.put(updated)
        return updated

    def _verdict_of(
        self, candidate: EvidenceCandidate, target: Evidence | None = None
    ) -> VerificationVerdict | None:
        """The verdict `evidence.accept` needs when the object being accepted is `proposed`.

        It comes from the verification result the candidate actually carries — never from
        the reviewer's optimism and never invented. An unverified candidate still has none,
        and the handler refuses the acceptance for exactly that reason.
        """
        accepted = candidate.evidence if target is None else target
        if accepted.status is not EvidenceStatus.PROPOSED:
            return None
        return None if candidate.verification is None else candidate.verification.verdict

    def _authorize_batch(self, conditions: BatchPolicyConditions | None) -> None:
        policy = self._ctx.repo.review_policy
        if conditions is None:
            if policy is not ReviewPolicy.POLICY_BATCH:
                raise AuthorityError(
                    f"batch acceptance under review policy {policy.value!r} needs the Product "
                    "24.4 conditions stated explicitly; strict review is the default and a "
                    "batch is an exception a researcher declares"
                )
            return
        unmet = conditions.unsatisfied()
        if unmet:
            raise AuthorityError(
                "batch acceptance requires every deterministic condition; not declared: "
                f"{', '.join(unmet)}"
            )

    def _check_split(
        self,
        candidate: EvidenceCandidate,
        fact: Evidence,
        interpretation: Interpretation | None,
        reason: str | None,
    ) -> None:
        """Refuse a split that would produce no accepted fact, or two, or an unanchored one."""
        if (interpretation is None) == (reason is None or not reason.strip()):
            raise CapabilityError(
                "a partial acceptance either stages the interpretation for its own review or "
                "rejects it with a reason; give exactly one"
            )
        if fact.origin not in FACT_ORIGINS:
            allowed = ", ".join(sorted(origin.value for origin in FACT_ORIGINS))
            raise CapabilityError(
                f"the accepted half of a split is a source fact ({allowed}), not "
                f"{fact.origin.value!r}; stage the interpretation instead"
            )
        if fact.source != candidate.evidence.source:
            raise CapabilityError(
                "a split accepts the candidate's own span; changing the anchor would make it "
                "new evidence read from somewhere else"
            )
        status = self._anchor_status(candidate)
        if status is not AnchorValidationStatus.VALID:
            raise CapabilityError(
                f"candidate {candidate.candidate_id} has a {status.value} anchor; a source "
                "fact with no valid anchor is not evidence"
            )
        if interpretation is not None and interpretation.origin is EvidenceOrigin.SOURCE_OBSERVED:
            # Unreachable through the domain model, which already refuses it; kept as the
            # explicit statement of the rule this method exists to enforce.
            raise CapabilityError("an interpretation is never source_observed")

    def _anchor_status(self, candidate: EvidenceCandidate) -> AnchorValidationStatus:
        """Replay the candidate's anchor against the Work's stored blocks."""
        document = stored_document(self._ctx.repo, candidate.work, candidate.artifact)
        if document is None:
            return candidate.anchor_status
        return validate_anchor(candidate.evidence.source, document).status

    def _derive_interpretation(
        self,
        candidate: EvidenceCandidate,
        fact: Evidence,
        interpretation: Interpretation | None,
        accepted: EvidenceId,
    ) -> EvidenceCandidate:
        """The interpretation half of a split, as a Tier-2 candidate with no authority.

        It keeps the fact's anchor — the span is what was interpreted — but answers a
        different field, so the inbox reads it as a separate question rather than as a
        competing answer to the one just accepted. Only the interpretation's `text` and
        `origin` are read: it has no id and no evidence links until it is itself accepted,
        and the fact it was split from is recorded in its provenance note.
        """
        text = (
            interpretation.text
            if interpretation is not None
            else candidate.evidence.content.exact_text or fact.content.exact_text
        )
        origin = (
            interpretation.origin if interpretation is not None else EvidenceOrigin.MODEL_PROPOSED
        )
        derived_field = f"{candidate.field}{INTERPRETATION_FIELD_SUFFIX}"
        evidence = Evidence(
            id=PROVISIONAL_EVIDENCE_ID,
            source=fact.source,
            content=EvidenceContent(exact_text=text, field=derived_field),
            origin=origin,
            evidence_type=fact.evidence_type,
            strength=EvidenceStrength.DERIVED,
            verification=VerificationRecord(
                status=EvidenceStatus.PROPOSED,
                extractor=candidate.evidence.verification.extractor,
            ),
            review_tier=ReviewTier.TIER_2,
            provenance=Provenance(
                source=candidate.evidence.provenance.source,
                actor=candidate.evidence.provenance.actor,
                workflow="review",
                note=f"split out of the source fact accepted as {accepted}",
            ),
        )
        return EvidenceCandidate(
            candidate_id=candidate_id_for(
                candidate.work,
                candidate.artifact,
                derived_field,
                fact.source.block,
                fact.source.text_hash,
                text,
            ),
            work=candidate.work,
            artifact=candidate.artifact,
            field=derived_field,
            evidence=evidence,
            extraction=candidate.extraction.touch(
                rationale="split out of the source fact by the researcher"
            ),
            anchor_status=candidate.anchor_status,
            status=CandidateStatus.PROPOSED,
        )


# ------------------------------------------------------------------------ conditions

_SATISFIED = BatchPolicyConditions(
    verifier_supported=True,
    anchor_valid=True,
    no_competing_candidate=True,
    low_risk_field=True,
    no_accepted_state_conflict=True,
)
"""Every Product §24.4 condition observed; only built once each one has been checked."""


def _batch_failures(item: ReviewItem) -> tuple[str, ...]:
    """Every §24.4 condition this item does not satisfy, named so the skip is auditable."""
    content = item.candidate.evidence.content
    failures: list[str] = []
    if item.verdict != VerificationVerdict.SUPPORTED.value:
        failures.append(f"verdict is {item.verdict or 'missing'}, not supported")
    if item.anchor_status is not AnchorValidationStatus.VALID:
        failures.append(f"anchor is {item.anchor_status.value}")
    if item.competing:
        failures.append(f"{len(item.competing)} competing candidate(s) for the same field")
    if item.tier not in LOW_RISK_TIERS:
        failures.append(f"tier {int(item.tier)} needs deep review")
    if content.numeric is not None:
        failures.append("numeric evidence is never low risk")
    if content.negative_state is not None:
        failures.append("an absence state is never low risk")
    if item.accepted_conflict is not None:
        failures.append(f"conflicts with accepted evidence {item.accepted_conflict}")
    if item.previously_rejected:
        failures.append("an identical span was previously rejected")
    return tuple(failures)


def _same_content(evidence: Evidence, fact: Evidence) -> bool:
    """True when the researcher's fact says exactly what the candidate said."""
    return evidence.content == fact.content and evidence.origin is fact.origin
