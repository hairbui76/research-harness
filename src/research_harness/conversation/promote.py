"""Promotion: the only path from a message to research state, and it copies.

Four targets, and each one goes through the capability that already owns its rule
(ADR-004): `note.add`, `question.create`, `claim.create`, and — for a decision — the
drafting step that `decision.accept` then reviews. Nothing here writes a canonical file
itself, and nothing here accepts anything.

Two properties are the point of the module:

* **The message is untouched.** Promotion reads an excerpt and writes a *new* object with
  provenance naming the session and the message it came from. The transcript is not
  edited, not deleted, and not re-labelled (conversation design SS6).
* **Review is not bypassed.** A promoted Claim is created unverified at the weakest
  allowed strength, so `claim.audit` still decides what it may say. A promoted Decision is
  *drafted*, not accepted: accepting it is `decision.accept`, a human-authority capability,
  and this module deliberately does not call it. The draft is captured as a low-authority
  note at the same time, so the proposal is durable while it waits.

Evidence is not a target and cannot be one. Prose has no artifact and no exact anchor, so
`evidence` is refused here with :class:`EvidenceRequiresAnchorError` telling the caller to
attach an anchor instead (Product 42 M; conversation design SS6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    PROVISIONAL_CLAIM_ID,
    PROVISIONAL_QUESTION_ID,
    AddNoteRequest,
    CreateClaimRequest,
    CreateQuestionRequest,
    MutationResult,
)
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.conversation import Message, PromotionRequest, PromotionTarget
from research_harness.domain.enums import (
    ClaimScope,
    ClaimStatus,
    ClaimType,
    DecisionStatus,
    DecisionType,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import DecisionId
from research_harness.domain.research import Decision, ResearchQuestion
from research_harness.workspace.conversations import ConversationStore

__all__ = [
    "EVIDENCE_TARGETS",
    "ClaimProposal",
    "EvidenceRequiresAnchorError",
    "Promotion",
    "PromotionService",
]

logger = logging.getLogger(__name__)

EVIDENCE_TARGETS: frozenset[str] = frozenset({"evidence", "evidence_candidate"})
"""What a caller might name when it means "make this evidence". All of it is refused."""

_ANCHOR_ADVICE = (
    "evidence cannot be created from prose: it needs an Artifact and an exact resolvable "
    "anchor, so the claim can be reopened at its source (Product 9, 42 M). Save the source "
    "to the corpus, then propose evidence against a block of it — `corpus.ingest` and "
    "`work.parse` give you the anchor, and `evidence.accept` reviews the result. Promote "
    "the passage to a note, question, or claim candidate instead."
)


class EvidenceRequiresAnchorError(CapabilityError):
    """A caller asked for evidence-from-prose. Typed, so a UI can offer the anchor picker."""


@dataclass(frozen=True, slots=True)
class ClaimProposal:
    """The structure a claim candidate needs and prose does not have.

    A claim is a proposition with a subject, a predicate, an object, and a scope — not a
    sentence with citations (Product 10). The composer collects these on the promotion
    form; without them the promotion is refused rather than guessed at.
    """

    subject: str
    predicate: str
    object: str
    claim_type: ClaimType = ClaimType.DESCRIPTIVE
    scope: ClaimScope = ClaimScope.INDIVIDUAL
    corpus: str | None = None
    publication_until: str | None = None


@dataclass(frozen=True, slots=True)
class Promotion:
    """What one promotion produced, and what still has to happen to it."""

    target: PromotionTarget
    session: str
    message: str
    object_id: str | None = None
    note_key: str | None = None
    accepted: bool = False
    """Always false: promotion creates working or candidate state, never accepted state."""

    review: str = ""
    """The next step in the researcher's own words: what reviews this, and how."""

    decision: Decision | None = None
    """The drafted, *unaccepted* Decision, for a `decision_candidate` promotion."""

    mutation: MutationResult | None = None


class PromotionService:
    """Turns part of a message into reviewable research state, through the capabilities."""

    def __init__(self, ctx: CapabilityContext, *, store: ConversationStore | None = None) -> None:
        self._ctx = ctx
        self._store = store or ConversationStore.for_repository(ctx.repo)

    def promote(
        self,
        request: PromotionRequest,
        *,
        claim: ClaimProposal | None = None,
        decision_type: DecisionType = DecisionType.OTHER,
        title: str | None = None,
    ) -> Promotion:
        """Promote ``request.excerpt`` to its target. The message itself is not touched."""
        message = self._message(request)
        excerpt = request.excerpt.strip() or message.text().strip()
        if not excerpt:
            raise CapabilityError(
                f"session.promote: {request.message} has no text to promote; a promotion "
                "copies an excerpt, and there is nothing to copy"
            )
        if request.target is PromotionTarget.NOTE:
            return self._promote_note(request, excerpt)
        if request.target is PromotionTarget.QUESTION:
            return self._promote_question(request, excerpt)
        if request.target is PromotionTarget.CLAIM_CANDIDATE:
            return self._promote_claim(request, excerpt, claim)
        return self._promote_decision(request, excerpt, decision_type, title)

    @staticmethod
    def refuse_evidence(target: str) -> None:
        """Refuse `evidence` as a promotion target, with the fix in the message."""
        if target.strip().lower() in EVIDENCE_TARGETS:
            raise EvidenceRequiresAnchorError(f"session.promote: {_ANCHOR_ADVICE}")

    # -- targets -------------------------------------------------------------

    def _promote_note(self, request: PromotionRequest, excerpt: str) -> Promotion:
        from research_harness.capabilities.handlers import add_note

        result = add_note(
            self._ctx,
            AddNoteRequest(text=excerpt, source=self._source(request)),
        )
        return Promotion(
            target=request.target,
            session=str(request.session),
            message=str(request.message),
            object_id=result.objects[0] if result.objects else None,
            note_key=self._note_key(result),
            review="a note carries no authority; promote it further with `note.promote`",
            mutation=result,
        )

    def _promote_question(self, request: PromotionRequest, excerpt: str) -> Promotion:
        from research_harness.capabilities.handlers import create_question

        question = ResearchQuestion(
            id=PROVISIONAL_QUESTION_ID,
            question=excerpt,
            remaining_uncertainty=request.rationale,
            provenance=self._provenance(request),
        )
        result = create_question(self._ctx, CreateQuestionRequest(question=question))
        return Promotion(
            target=request.target,
            session=str(request.session),
            message=str(request.message),
            object_id=result.objects[0] if result.objects else None,
            review="an open question; nothing is answered until evidence and claims say so",
            mutation=result,
        )

    def _promote_claim(
        self, request: PromotionRequest, excerpt: str, proposal: ClaimProposal | None
    ) -> Promotion:
        from research_harness.capabilities.handlers import create_claim

        if proposal is None:
            raise CapabilityError(
                "session.promote: a claim candidate needs the proposition behind the prose "
                "— subject, predicate, object, and the scope it is asserted at. A claim is "
                "not a sentence with citations (Product 10.2)."
            )
        candidate = Claim(
            id=PROVISIONAL_CLAIM_ID,
            statement=excerpt,
            type=proposal.claim_type,
            semantics=ClaimSemantics(
                subject=proposal.subject, predicate=proposal.predicate, object=proposal.object
            ),
            scope=ClaimScopeSpec(
                level=proposal.scope,
                corpus=proposal.corpus,
                publication_until=proposal.publication_until,
            ),
            assessment=ClaimAssessment(
                requested_strength=proposal.scope,
                allowed_strength=ClaimScope.INDIVIDUAL,
                status=ClaimStatus.UNVERIFIED,
            ),
            provenance=self._provenance(request),
        )
        result = create_claim(self._ctx, CreateClaimRequest(claim=candidate))
        return Promotion(
            target=request.target,
            session=str(request.session),
            message=str(request.message),
            object_id=result.objects[0] if result.objects else None,
            review=(
                "created unverified at L0; `claim.audit` decides what the evidence allows "
                "it to say, and the review gate still applies"
            ),
            mutation=result,
        )

    def _promote_decision(
        self,
        request: PromotionRequest,
        excerpt: str,
        decision_type: DecisionType,
        title: str | None,
    ) -> Promotion:
        """Draft a proposed Decision and capture it as a note. Acceptance is a separate act.

        `decision.accept` is the only capability that writes a Decision, and it *accepts*
        what it is given. Calling it here would turn a promotion into a researcher decision
        without review, which is exactly what the gate forbids. So the candidate is drafted
        with the id acceptance will use, captured as a durable low-authority note, and
        handed back for the reviewer to accept explicitly.
        """
        from research_harness.capabilities.handlers import add_note
        from research_harness.claims.service import next_decision_id

        decision_id: DecisionId = next_decision_id(self._ctx)
        candidate = Decision(
            id=decision_id,
            type=decision_type,
            status=DecisionStatus.PROPOSED,
            title=title or f"decision proposed from {request.message}",
            rationale=excerpt,
            claim=request.claim,
            provenance=self._provenance(request),
        )
        note = add_note(
            self._ctx,
            AddNoteRequest(
                text=f"Decision candidate {decision_id}: {excerpt}",
                source=self._source(request),
            ),
        )
        return Promotion(
            target=request.target,
            session=str(request.session),
            message=str(request.message),
            object_id=str(decision_id),
            note_key=self._note_key(note),
            review=(
                f"drafted as {decision_id} and captured as a note; it becomes a Decision "
                "only when the researcher accepts it with `decision.accept`"
            ),
            decision=candidate,
            mutation=note,
        )

    # -- helpers -------------------------------------------------------------

    def _message(self, request: PromotionRequest) -> Message:
        """The message being promoted; reading it also proves the promotion names a real one."""
        return self._store.get_message(request.session, request.message)

    def _source(self, request: PromotionRequest) -> str:
        """Where the excerpt came from, as the note's capture provenance records it."""
        return f"session {request.session}/{request.message}"

    def _provenance(self, request: PromotionRequest) -> Provenance:
        """Provenance pointing back at the session and message, on the created object."""
        return self._ctx.provenance(
            workflow="session.promote",
            note=f"promoted from rh://session/{request.session}?message={request.message}",
        )

    @staticmethod
    def _note_key(result: MutationResult) -> str | None:
        """The `note.add` key, out of the event the mutation journalled."""
        payload: Any = result.event.payload
        value = payload.get("note") if isinstance(payload, dict) else None
        return None if value is None else str(value)
