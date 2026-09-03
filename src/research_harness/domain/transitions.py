"""Table-driven state transitions and authority rules for the research domain.

Product principles enforced here:

* P3/P4 - software enforces invariants; human override is explicit and persisted.
* Product 24 - under the default `strict` policy an interpretive candidate reaches
  `accepted` only through a human review action. Model confidence is never an input to
  acceptance, and no function in this module accepts one.
* Product 42.E - there is no origin-changing transition that promotes a model proposal to
  a source observation. `model_proposed -> source_observed` is refused outright: the
  researcher must re-anchor the statement as new evidence read from the source. Any other
  origin change requires a human actor and a recorded rationale.
* Product 42.F - `not_found`/`not_reported` become `absent` only through an audited
  transition carrying a `Decision` and a human actor. A search with no lexical hits
  yields `not_found` (or `unclear`), never `absent`.
* Product 42.G - an audit may lower but never silently raise claim strength; escalation
  above the auditor recommendation requires an accepted `epistemic_override` Decision.

Every function returns a new frozen object; nothing is mutated in place.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from research_harness.domain.base import DomainModel, utc_now
from research_harness.domain.claim import Claim, Coverage
from research_harness.domain.enums import (
    ACCEPTING_REVIEW_ACTIONS,
    PROMOTABLE_NEGATIVE_STATES,
    ClaimScope,
    ClaimStatus,
    DecisionStatus,
    DecisionType,
    EvidenceOrigin,
    EvidenceStatus,
    NegativeEvidenceState,
    NoteStatus,
    ProvenanceSource,
    QuestionStatus,
    ResearchEventType,
    ReviewAction,
    ReviewPolicy,
    ReviewTier,
    StaleState,
    TransitionKind,
    VerificationVerdict,
)
from research_harness.domain.errors import (
    AuthorityError,
    DomainValidationError,
    TransitionError,
)
from research_harness.domain.evidence import Evidence, Interpretation
from research_harness.domain.ids import ClaimId, DecisionId, QuestionId
from research_harness.domain.research import Decision, ResearchNote, ResearchQuestion

__all__ = [
    "AUDITED_CLAIM_STATUSES",
    "CLAIM_TRANSITIONS",
    "DECISION_TRANSITIONS",
    "EVIDENCE_STATUS_EVENTS",
    "EVIDENCE_TRANSITIONS",
    "HUMAN_ACTOR",
    "NOTE_TRANSITIONS",
    "QUESTION_TRANSITIONS",
    "BatchPolicyConditions",
    "allowed_transitions",
    "audit_claim",
    "discard_note",
    "is_human_actor",
    "negative_state_from_search",
    "override_claim_strength",
    "promote_negative_state",
    "promote_note",
    "reclassify_origin",
    "supersede_claim",
    "transition_decision",
    "transition_evidence",
    "transition_question",
]

HUMAN_ACTOR = "human"
"""Canonical human actor. ``"human:<name>"`` identifies a specific researcher."""


def is_human_actor(actor: str) -> bool:
    """True when ``actor`` is the researcher (``"human"`` or ``"human:<name>"``).

    Anything else - a model identifier, a workflow name, ``"system"`` - is not a human and
    cannot exercise human authority.
    """
    return actor == HUMAN_ACTOR or actor.startswith(f"{HUMAN_ACTOR}:")


# ---------------------------------------------------------------------------
# transition tables
# ---------------------------------------------------------------------------

EVIDENCE_TRANSITIONS: Mapping[EvidenceStatus, frozenset[EvidenceStatus]] = MappingProxyType(
    {
        EvidenceStatus.PROPOSED: frozenset(
            {
                EvidenceStatus.VERIFIED,
                EvidenceStatus.REJECTED,
                EvidenceStatus.DEFERRED,
                EvidenceStatus.SUPERSEDED,
            }
        ),
        EvidenceStatus.VERIFIED: frozenset(
            {
                EvidenceStatus.ACCEPTED,
                EvidenceStatus.REJECTED,
                EvidenceStatus.DEFERRED,
                EvidenceStatus.SUPERSEDED,
            }
        ),
        EvidenceStatus.DEFERRED: frozenset(
            {
                EvidenceStatus.VERIFIED,
                EvidenceStatus.ACCEPTED,
                EvidenceStatus.REJECTED,
                EvidenceStatus.SUPERSEDED,
            }
        ),
        EvidenceStatus.ACCEPTED: frozenset({EvidenceStatus.STALE, EvidenceStatus.SUPERSEDED}),
        EvidenceStatus.STALE: frozenset({EvidenceStatus.ACCEPTED, EvidenceStatus.SUPERSEDED}),
        EvidenceStatus.REJECTED: frozenset({EvidenceStatus.SUPERSEDED}),
        EvidenceStatus.SUPERSEDED: frozenset(),
    }
)

#: The four statuses an audit may conclude with. Each of them may be re-entered: a
#: re-audit that reaches the same verdict is a fresh assessment, not a no-op, so the
#: table carries an explicit self-edge for every audited status. `unverified` is the
#: pre-audit state and is never returned to, and `superseded` stays terminal.
AUDITED_CLAIM_STATUSES: frozenset[ClaimStatus] = frozenset(
    {
        ClaimStatus.SUPPORTED,
        ClaimStatus.QUALIFIED,
        ClaimStatus.CONTESTED,
        ClaimStatus.UNSUPPORTED,
    }
)

CLAIM_TRANSITIONS: Mapping[ClaimStatus, frozenset[ClaimStatus]] = MappingProxyType(
    {
        ClaimStatus.UNVERIFIED: AUDITED_CLAIM_STATUSES | {ClaimStatus.SUPERSEDED},
        ClaimStatus.SUPPORTED: AUDITED_CLAIM_STATUSES | {ClaimStatus.SUPERSEDED},
        ClaimStatus.QUALIFIED: AUDITED_CLAIM_STATUSES | {ClaimStatus.SUPERSEDED},
        ClaimStatus.CONTESTED: AUDITED_CLAIM_STATUSES | {ClaimStatus.SUPERSEDED},
        ClaimStatus.UNSUPPORTED: AUDITED_CLAIM_STATUSES | {ClaimStatus.SUPERSEDED},
        ClaimStatus.SUPERSEDED: frozenset(),
    }
)

NOTE_TRANSITIONS: Mapping[NoteStatus, frozenset[NoteStatus]] = MappingProxyType(
    {
        NoteStatus.CAPTURED: frozenset({NoteStatus.PROMOTED, NoteStatus.DISCARDED}),
        NoteStatus.PROMOTED: frozenset(),
        NoteStatus.DISCARDED: frozenset(),
    }
)

QUESTION_TRANSITIONS: Mapping[QuestionStatus, frozenset[QuestionStatus]] = MappingProxyType(
    {
        QuestionStatus.OPEN: frozenset(
            {QuestionStatus.PARTIALLY_ANSWERED, QuestionStatus.ANSWERED, QuestionStatus.BLOCKED}
        ),
        QuestionStatus.PARTIALLY_ANSWERED: frozenset(
            {QuestionStatus.OPEN, QuestionStatus.ANSWERED, QuestionStatus.BLOCKED}
        ),
        QuestionStatus.ANSWERED: frozenset(
            {QuestionStatus.OPEN, QuestionStatus.PARTIALLY_ANSWERED, QuestionStatus.BLOCKED}
        ),
        QuestionStatus.BLOCKED: frozenset(
            {QuestionStatus.OPEN, QuestionStatus.PARTIALLY_ANSWERED, QuestionStatus.ANSWERED}
        ),
    }
)

DECISION_TRANSITIONS: Mapping[DecisionStatus, frozenset[DecisionStatus]] = MappingProxyType(
    {
        DecisionStatus.PROPOSED: frozenset({DecisionStatus.ACCEPTED, DecisionStatus.SUPERSEDED}),
        DecisionStatus.ACCEPTED: frozenset({DecisionStatus.SUPERSEDED}),
        DecisionStatus.SUPERSEDED: frozenset(),
    }
)

_TABLES: Mapping[TransitionKind, Mapping[Any, frozenset[Any]]] = MappingProxyType(
    {
        TransitionKind.EVIDENCE: EVIDENCE_TRANSITIONS,
        TransitionKind.CLAIM: CLAIM_TRANSITIONS,
        TransitionKind.DECISION: DECISION_TRANSITIONS,
        TransitionKind.NOTE: NOTE_TRANSITIONS,
        TransitionKind.QUESTION: QUESTION_TRANSITIONS,
    }
)

#: Semantic events a caller should emit for a completed transition (Product 19.3).
EVIDENCE_STATUS_EVENTS: Mapping[EvidenceStatus, ResearchEventType] = MappingProxyType(
    {
        EvidenceStatus.PROPOSED: ResearchEventType.EVIDENCE_PROPOSED,
        EvidenceStatus.ACCEPTED: ResearchEventType.EVIDENCE_ACCEPTED,
        EvidenceStatus.REJECTED: ResearchEventType.EVIDENCE_REJECTED,
    }
)


def allowed_transitions(kind: TransitionKind | str) -> Mapping[str, frozenset[str]]:
    """Transition table for ``kind`` as plain strings, for UIs and capability discovery.

    ``StrEnum`` members compare and hash as their values, so callers may still look up
    ``EvidenceStatus.VERIFIED`` in the returned mapping.
    """
    try:
        table = _TABLES[TransitionKind(kind)]
    except ValueError as exc:
        raise DomainValidationError(f"unknown transition kind: {kind!r}") from exc
    return MappingProxyType(
        {
            str(source): frozenset(str(target) for target in targets)
            for source, targets in table.items()
        }
    )


def _require_allowed(
    kind: TransitionKind,
    table: Mapping[Any, frozenset[Any]],
    source: Any,
    target: Any,
) -> None:
    allowed = table.get(source, frozenset())
    if target not in allowed:
        options = ", ".join(sorted(str(value) for value in allowed)) or "none"
        raise TransitionError(
            f"{kind.value}: {source} -> {target} is not allowed (allowed: {options})"
        )


# ---------------------------------------------------------------------------
# evidence lifecycle
# ---------------------------------------------------------------------------


class BatchPolicyConditions(DomainModel):
    """Deterministic preconditions for policy batch acceptance (Product 24.4).

    All conditions must hold. Model confidence is deliberately not one of them.
    """

    verifier_supported: bool = False
    anchor_valid: bool = False
    no_competing_candidate: bool = False
    low_risk_field: bool = False
    no_accepted_state_conflict: bool = False

    def unsatisfied(self) -> tuple[str, ...]:
        """Names of the conditions that are not met."""
        return tuple(name for name in type(self).model_fields if not getattr(self, name))

    @property
    def all_satisfied(self) -> bool:
        """True when every condition holds."""
        return not self.unsatisfied()


def _may_auto_accept(
    candidate: Evidence | Interpretation,
    policy: ReviewPolicy,
    conditions: BatchPolicyConditions | None,
) -> bool:
    """Whether acceptance may happen without a human review action."""
    if candidate.is_interpretive:
        return False
    if candidate.review_tier is ReviewTier.TIER_0:
        return True
    if candidate.review_tier is ReviewTier.TIER_1 and policy is ReviewPolicy.POLICY_BATCH:
        return conditions is not None and conditions.all_satisfied
    return False


def transition_evidence[EvidenceLike: (Evidence, Interpretation)](
    evidence: EvidenceLike,
    to_status: EvidenceStatus,
    *,
    actor: str,
    policy: ReviewPolicy = ReviewPolicy.STRICT,
    verdict: VerificationVerdict | None = None,
    review_action: ReviewAction | None = None,
    batch_conditions: BatchPolicyConditions | None = None,
    qualification: str | None = None,
    rationale: str | None = None,
) -> EvidenceLike:
    """Move an Evidence or Interpretation to ``to_status``, returning a new object.

    Raises `TransitionError` for an illegal transition and `AuthorityError` when the
    actor lacks the authority the target status requires.
    """
    current = evidence.verification.status
    _require_allowed(TransitionKind.EVIDENCE, EVIDENCE_TRANSITIONS, current, to_status)

    if to_status is EvidenceStatus.VERIFIED and verdict is None:
        raise TransitionError("verification requires a verdict")

    if to_status is EvidenceStatus.ACCEPTED:
        if not _may_auto_accept(evidence, policy, batch_conditions):
            if not is_human_actor(actor):
                raise AuthorityError(
                    f"{evidence.id}: acceptance under policy {policy.value!r} requires a human "
                    f"actor (tier {int(evidence.review_tier)}, origin {evidence.origin.value})"
                    + _batch_hint(evidence, policy, batch_conditions)
                )
            if review_action not in ACCEPTING_REVIEW_ACTIONS:
                raise TransitionError(
                    "human acceptance requires review_action accept or accept_with_qualification"
                )
        if review_action is ReviewAction.ACCEPT_WITH_QUALIFICATION and not (
            qualification or evidence.qualification
        ):
            raise TransitionError("accept_with_qualification requires a qualification")

    updates: dict[str, Any] = {"status": to_status}
    if verdict is not None:
        updates["verdict"] = verdict
    if review_action is not None:
        updates["review_action"] = review_action
    if rationale is not None:
        updates["rationale"] = rationale
    if to_status is EvidenceStatus.VERIFIED:
        updates["verifier"] = actor
    if to_status is EvidenceStatus.ACCEPTED:
        updates["accepted_by"] = actor
    if to_status in {
        EvidenceStatus.ACCEPTED,
        EvidenceStatus.REJECTED,
        EvidenceStatus.DEFERRED,
    }:
        updates["reviewed_at"] = utc_now()

    object_updates: dict[str, Any] = {"verification": evidence.verification.touch(**updates)}
    if to_status is EvidenceStatus.STALE:
        object_updates["stale"] = StaleState.STALE
    elif to_status is EvidenceStatus.ACCEPTED:
        object_updates["stale"] = StaleState.FRESH
    if qualification is not None:
        object_updates["qualification"] = qualification
    return evidence.touch(**object_updates)


def _batch_hint(
    evidence: Evidence | Interpretation,
    policy: ReviewPolicy,
    conditions: BatchPolicyConditions | None,
) -> str:
    if policy is not ReviewPolicy.POLICY_BATCH or evidence.review_tier is not ReviewTier.TIER_1:
        return ""
    if conditions is None:
        return "; policy batch needs explicit BatchPolicyConditions"
    return f"; unmet batch conditions: {', '.join(conditions.unsatisfied())}"


def reclassify_origin[EvidenceLike: (Evidence, Interpretation)](
    evidence: EvidenceLike,
    new_origin: EvidenceOrigin,
    *,
    actor: str,
    rationale: str,
    policy: ReviewPolicy = ReviewPolicy.STRICT,
) -> EvidenceLike:
    """Human-only epistemic reclassification of an evidence origin.

    `model_proposed -> source_observed` is always refused, under every policy: a model
    proposal is not an observation, and the researcher must re-anchor the statement as new
    evidence read from the source. Every other change needs a human actor and a rationale,
    both of which are recorded on the verification record.
    """
    del policy  # the refusal below is unconditional; the parameter documents the intent
    if not rationale.strip():
        raise DomainValidationError("reclassifying an origin requires a rationale")
    if not is_human_actor(actor):
        raise AuthorityError(f"{evidence.id}: only a human actor may reclassify an evidence origin")
    if (
        evidence.origin is EvidenceOrigin.MODEL_PROPOSED
        and new_origin is EvidenceOrigin.SOURCE_OBSERVED
    ):
        raise TransitionError(
            "model_proposed may never become source_observed; re-anchor the statement as "
            "new evidence read from the source"
        )
    if isinstance(evidence, Interpretation) and new_origin not in {
        EvidenceOrigin.AUTHOR_INTERPRETED,
        EvidenceOrigin.RESEARCHER_INFERRED,
        EvidenceOrigin.MODEL_PROPOSED,
    }:
        raise TransitionError("an interpretation origin must stay interpretive")
    if evidence.verification.status is EvidenceStatus.SUPERSEDED:
        raise TransitionError("a superseded object cannot be reclassified")
    record = evidence.verification.touch(
        rationale=rationale,
        reviewed_at=utc_now(),
    )
    return evidence.touch(origin=new_origin, verification=record)


# ---------------------------------------------------------------------------
# negative evidence
# ---------------------------------------------------------------------------


def negative_state_from_search(hits: int, exhaustive: bool) -> NegativeEvidenceState:
    """Negative state implied by a lexical/semantic search result (Product 11).

    Zero hits from an exhaustive search is `not_found`; zero hits from a partial search is
    `unclear`. Neither is ever `absent`: that conclusion needs an audited decision.
    """
    if hits < 0:
        raise DomainValidationError("hit count cannot be negative")
    if hits > 0:
        raise DomainValidationError("a search with hits does not produce a negative state")
    return NegativeEvidenceState.NOT_FOUND if exhaustive else NegativeEvidenceState.UNCLEAR


def promote_negative_state(
    evidence: Evidence,
    *,
    to_state: NegativeEvidenceState,
    actor: str,
    decision: DecisionId,
    rationale: str | None = None,
) -> Evidence:
    """Audited promotion of `not_found`/`not_reported` to `absent` (Product 42.F).

    Requires a human actor and the `Decision` that authorised the conclusion; the decision
    id is recorded on the evidence so the absence claim stays auditable.
    """
    current = evidence.content.negative_state
    if current is None:
        raise TransitionError(f"{evidence.id} does not record a negative state")
    if to_state is not NegativeEvidenceState.ABSENT:
        raise TransitionError(
            "only promotion to 'absent' is an audited transition; other negative states "
            "are recorded by the search that produced them"
        )
    if current not in PROMOTABLE_NEGATIVE_STATES:
        options = ", ".join(sorted(state.value for state in PROMOTABLE_NEGATIVE_STATES))
        raise TransitionError(f"only {options} may be promoted to absent, not {current.value}")
    if not is_human_actor(actor):
        raise AuthorityError("promotion to 'absent' requires a human actor")
    content = evidence.content.touch(negative_state=to_state)
    decisions = (
        evidence.decisions if decision in evidence.decisions else (*evidence.decisions, decision)
    )
    record = evidence.verification.touch(
        rationale=rationale or evidence.verification.rationale,
        reviewed_at=utc_now(),
    )
    return evidence.touch(content=content, decisions=decisions, verification=record)


# ---------------------------------------------------------------------------
# claims
# ---------------------------------------------------------------------------


def audit_claim(
    claim: Claim,
    *,
    status: ClaimStatus,
    allowed_strength: ClaimScope,
    actor: str,
    maximum_defensible_wording: str | None = None,
    coverage: Coverage | None = None,
) -> Claim:
    """Record an audit result: status, the strength the evidence allows, and wording.

    An audit never touches `requested_strength` and can never set an
    `allowed_strength` above it - escalation needs `override_claim_strength`. Re-auditing
    a claim into the status it already has is legal (`CLAIM_TRANSITIONS` carries a
    self-edge for every audited status): the assessment is recomputed and re-dated even
    when the verdict does not move.
    """
    del actor  # audit authorship travels on the event/provenance, not the assessment
    _require_allowed(TransitionKind.CLAIM, CLAIM_TRANSITIONS, claim.assessment.status, status)
    requested = claim.assessment.requested_strength
    if allowed_strength > requested:
        raise TransitionError(
            f"audit may not allow {allowed_strength.label} above the requested "
            f"{requested.label}; record an epistemic_override decision instead"
        )
    assessment = claim.assessment.touch(
        status=status,
        allowed_strength=allowed_strength,
        maximum_defensible_wording=(
            maximum_defensible_wording
            if maximum_defensible_wording is not None
            else claim.assessment.maximum_defensible_wording
        ),
        audited_at=utc_now(),
    )
    updates: dict[str, Any] = {"assessment": assessment}
    if coverage is not None:
        updates["coverage"] = coverage
    return claim.touch(**updates)


def supersede_claim(claim: Claim, *, actor: str) -> Claim:
    """Retire a claim; superseded is terminal."""
    del actor
    _require_allowed(
        TransitionKind.CLAIM, CLAIM_TRANSITIONS, claim.assessment.status, ClaimStatus.SUPERSEDED
    )
    return claim.touch(assessment=claim.assessment.touch(status=ClaimStatus.SUPERSEDED))


def override_claim_strength(claim: Claim, decision: Decision) -> Claim:
    """Apply an accepted `epistemic_override` decision to a claim (Product 38).

    The decision must be accepted, human-authored, reference this claim, and agree with
    the auditor recommendation it overrides. The decision id is recorded on the claim so
    the override is visible in the canonical record.
    """
    if decision.type is not DecisionType.EPISTEMIC_OVERRIDE:
        raise TransitionError("claim strength can only be overridden by an epistemic_override")
    if decision.claim != claim.id:
        raise TransitionError(f"decision {decision.id} does not reference claim {claim.id}")
    if decision.status is not DecisionStatus.ACCEPTED:
        raise TransitionError(f"decision {decision.id} must be accepted before it takes effect")
    if decision.provenance.source is not ProvenanceSource.HUMAN:
        raise AuthorityError(f"decision {decision.id} must be authored by the researcher")
    selected = decision.researcher_selected
    recommendation = decision.auditor_recommendation
    if selected is None or recommendation is None:  # pragma: no cover - schema guarantees both
        raise TransitionError("an epistemic_override must record both scopes")
    if recommendation is not claim.assessment.allowed_strength:
        raise TransitionError(
            f"decision {decision.id} overrides {recommendation.label} but the claim now "
            f"allows {claim.assessment.allowed_strength.label}; re-audit before overriding"
        )
    if selected > claim.assessment.requested_strength:
        raise TransitionError(
            f"override to {selected.label} exceeds the requested "
            f"{claim.assessment.requested_strength.label}"
        )
    decisions = (
        claim.decisions if decision.id in claim.decisions else (*claim.decisions, decision.id)
    )
    assessment = claim.assessment.touch(allowed_strength=selected)
    return claim.touch(assessment=assessment, decisions=decisions)


# ---------------------------------------------------------------------------
# notes, questions, decisions
# ---------------------------------------------------------------------------


def promote_note(
    note: ResearchNote,
    *,
    promoted_to: ClaimId | QuestionId | DecisionId,
    actor: str,
) -> ResearchNote:
    """Promote a captured note to the research object it became.

    Promotion raises authority, so it is a human action. The note itself never gains
    evidence relations or acceptance fields; it only records what it turned into.
    """
    _require_allowed(TransitionKind.NOTE, NOTE_TRANSITIONS, note.status, NoteStatus.PROMOTED)
    if not is_human_actor(actor):
        raise AuthorityError("only a human actor may promote a research note")
    return note.touch(status=NoteStatus.PROMOTED, promoted_to=promoted_to)


def discard_note(note: ResearchNote, *, actor: str) -> ResearchNote:
    """Discard a captured note."""
    del actor
    _require_allowed(TransitionKind.NOTE, NOTE_TRANSITIONS, note.status, NoteStatus.DISCARDED)
    return note.touch(status=NoteStatus.DISCARDED)


def transition_question(
    question: ResearchQuestion, to_status: QuestionStatus, *, actor: str
) -> ResearchQuestion:
    """Move a research question between open/partially answered/answered/blocked."""
    del actor
    _require_allowed(TransitionKind.QUESTION, QUESTION_TRANSITIONS, question.status, to_status)
    return question.touch(status=to_status)


def transition_decision(decision: Decision, to_status: DecisionStatus, *, actor: str) -> Decision:
    """Move a decision through proposed -> accepted -> superseded.

    Accepting a decision is a researcher act and requires a human actor.
    """
    _require_allowed(TransitionKind.DECISION, DECISION_TRANSITIONS, decision.status, to_status)
    if to_status is DecisionStatus.ACCEPTED and not is_human_actor(actor):
        raise AuthorityError(f"{decision.id}: only a human actor may accept a decision")
    return decision.touch(status=to_status)
