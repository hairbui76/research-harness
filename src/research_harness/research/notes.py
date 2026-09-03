"""Quick capture and promotion of research notes (Product 31).

A note is the lowest-authority object in the product: no stable research id, no evidence
relations, no acceptance fields, so it can never be cited as support. What it *can* do is
become something that can — a Claim, a Question, or a Decision — and that promotion raises
authority, so it is a researcher act and never a model's (ADR-003, ADR-007).

The service refuses a promotion before it creates anything: a non-human actor and an
already-promoted note are both rejected up front, so a refused promotion never leaves an
orphan Claim behind that nothing points at.

    notes = NoteService(ctx)
    note, _ = notes.capture("byte-level tokenization keeps showing up", source="cli")
    promotion = notes.promote_to_question(note.key, question)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AddNoteRequest,
    CreateClaimRequest,
    CreateQuestionRequest,
    MutationResult,
    PromoteNoteRequest,
)
from research_harness.capabilities.extra_handlers import (
    DiscardNoteRequest,
    discard_note_mutation,
)
from research_harness.capabilities.handlers import (
    accept_decision,
    add_note,
    create_claim,
    create_question,
    promote_note,
)
from research_harness.domain.claim import Claim
from research_harness.domain.enums import NoteStatus
from research_harness.domain.errors import AuthorityError, CapabilityError, TransitionError
from research_harness.domain.ids import ClaimId, DecisionId, QuestionId
from research_harness.domain.research import Decision, ResearchNote, ResearchQuestion
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "DISCARD_CAPABILITY",
    "NotePromotion",
    "NoteService",
    "PromotionTarget",
    "next_claim_id",
]

PromotionTarget = ClaimId | QuestionId | DecisionId

NoteList = list[ResearchNote]
"""Alias used inside `NoteService`, whose `list` method shadows the builtin in class scope."""

DISCARD_CAPABILITY = "note.discard"
"""Name reported by :meth:`NoteService.discard`.

The discard is committed by `capabilities.extra_handlers.discard_note_mutation`; this
service only decides *whether* a note may be discarded and hands the capability the
reason. Nothing in `research/` opens a workspace transaction of its own (ADR-004).
"""


@dataclass(frozen=True, slots=True)
class NotePromotion:
    """One promotion: the promoted note, what it became, and both mutations."""

    note: ResearchNote
    target: PromotionTarget
    created: MutationResult
    promoted: MutationResult

    @property
    def mutations(self) -> tuple[MutationResult, MutationResult]:
        """The create and the promote, in the order they were committed."""
        return (self.created, self.promoted)


class NoteService:
    """Capture, promote, discard, and list research notes for one workspace."""

    def __init__(self, ctx: CapabilityContext) -> None:
        self._ctx = ctx

    @property
    def ctx(self) -> CapabilityContext:
        """The capability context every mutation runs through."""
        return self._ctx

    # -- capture -------------------------------------------------------------

    def capture(
        self, text: str, *, source: str | None = None, key: str | None = None
    ) -> tuple[ResearchNote, MutationResult]:
        """Capture ``text`` as a note; ``source`` records where it came from, nothing more."""
        result = add_note(self._ctx, AddNoteRequest(text=text, key=key, source=source))
        return self.get(_note_key_of(result)), result

    # -- promotion -----------------------------------------------------------

    def promote_to_claim(self, note_key: str, claim: Claim) -> NotePromotion:
        """Register ``claim`` and record that the note became it."""
        note = self._promotable(note_key)
        created = create_claim(self._ctx, CreateClaimRequest(claim=claim))
        return self._promote(note, claim.id, created)

    def promote_to_question(self, note_key: str, question: ResearchQuestion) -> NotePromotion:
        """Register ``question`` and record that the note became it."""
        note = self._promotable(note_key)
        created = create_question(self._ctx, CreateQuestionRequest(question=question))
        return self._promote(note, question.id, created)

    def promote_to_decision(self, note_key: str, decision: Decision) -> NotePromotion:
        """Accept ``decision`` and record that the note became it."""
        note = self._promotable(note_key)
        created = accept_decision(self._ctx, AcceptDecisionRequest(decision=decision))
        return self._promote(note, decision.id, created)

    def _promote(
        self, note: ResearchNote, target: PromotionTarget, created: MutationResult
    ) -> NotePromotion:
        promoted = promote_note(
            self._ctx, PromoteNoteRequest(note_key=_require_key(note), target=target)
        )
        return NotePromotion(
            note=self.get(_require_key(note)),
            target=target,
            created=created,
            promoted=promoted,
        )

    # -- discard -------------------------------------------------------------

    def discard(
        self, note_key: str, *, reason: str | None = None
    ) -> tuple[ResearchNote, MutationResult]:
        """Discard a captured note; discarded is terminal and nothing downstream moves.

        ``reason`` is recorded in the `note.discarded` event. The write itself belongs to
        `note.discard` in `capabilities/`, which is the only surface that may open a
        workspace transaction (ADR-004).
        """
        note = self._captured(note_key, action="discarded")
        result = discard_note_mutation(
            self._ctx, DiscardNoteRequest(note_key=_require_key(note), reason=reason)
        )
        return self.get(_require_key(note)), result

    # -- reads ---------------------------------------------------------------

    def get(self, note_key: str) -> ResearchNote:
        """The note with ``note_key``; raises `CapabilityError` when there is none."""
        for note in self._ctx.repo.iter_notes():
            if note.key == note_key:
                return note
        raise CapabilityError(f"no note {note_key!r} in {self._ctx.root}")

    def list(self, status: NoteStatus | None = None) -> NoteList:
        """Notes in capture order, optionally filtered by status."""
        return [note for note in self._iter() if status is None or note.status is status]

    def captured(self) -> NoteList:
        """Notes still awaiting promotion or discard."""
        return self.list(NoteStatus.CAPTURED)

    def _iter(self) -> Iterator[ResearchNote]:
        return iter(sorted(self._ctx.repo.iter_notes(), key=_capture_order))

    # -- guards --------------------------------------------------------------

    def _promotable(self, note_key: str) -> ResearchNote:
        """The note, if this actor may promote it and it has not been promoted already."""
        if not self._ctx.is_human:
            raise AuthorityError(
                f"{self._ctx.actor}: only a human actor may promote a research note"
            )
        return self._captured(note_key, action="promoted")

    def _captured(self, note_key: str, *, action: str) -> ResearchNote:
        note = self.get(note_key)
        if note.status is not NoteStatus.CAPTURED:
            raise TransitionError(
                f"note {note_key!r} is {note.status.value}; only a captured note can be {action}"
            )
        return note


def next_claim_id(repo: WorkspaceRepository) -> ClaimId:
    """The id the next `claim.create` will write, ids already on disk included."""
    on_disk = ClaimId.next(str(claim.id) for claim in repo.list_claims())
    return ClaimId.make(max(on_disk.number, repo.config.counter(ClaimId.prefix) + 1))


def _capture_order(note: ResearchNote) -> tuple[datetime, str]:
    return (note.created_at, note.key or "")


def _note_key_of(result: MutationResult) -> str:
    """The key `note.add` announced in its event payload."""
    key = result.event.payload.get("note")
    if not isinstance(key, str) or not key:
        raise CapabilityError("note.add did not report the key of the note it captured")
    return key


def _require_key(note: ResearchNote) -> str:
    if note.key is None:  # pragma: no cover - a stored note always has a key
        raise CapabilityError("a stored research note always carries a key")
    return note.key
