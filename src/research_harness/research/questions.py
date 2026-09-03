"""Research questions: what is still open, and everything currently bearing on it.

A `ResearchQuestion` is the unit that outlives a single paper (Product 31): it links the
Claims, SearchRuns, and supporting/counter Evidence that speak to it, and it keeps the
uncertainty that is left in one honest field rather than in the researcher's head.

Status moves through the domain transition table, so `answered -> blocked` is legal and
`open -> open` is not; the capability layer writes the file and journals the event.

    questions = QuestionService(ctx)
    question, _ = questions.create("Do detectors survive encryption?")
    questions.link(question.id, QuestionLinks(claims=(ClaimId("C0001"),)))
    questions.resolve(question.id, "No: every accepted result assumes plaintext headers.")
"""

from __future__ import annotations

from dataclasses import dataclass

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    CreateQuestionRequest,
    MutationResult,
    UpdateQuestionRequest,
)
from research_harness.capabilities.handlers import create_question, update_question
from research_harness.domain.enums import QuestionStatus
from research_harness.domain.ids import ClaimId, EvidenceId, QuestionId, SearchRunId
from research_harness.domain.research import ResearchQuestion
from research_harness.research.notes import NoteService
from research_harness.workspace.repository import WorkspaceRepository

__all__ = ["QuestionLinks", "QuestionService", "next_question_id"]

QuestionList = list[ResearchQuestion]
"""Alias used inside `QuestionService`, whose `list` shadows the builtin in class scope."""


@dataclass(frozen=True, slots=True)
class QuestionLinks:
    """Everything that bears on a question: claims, searches, and both sides of the evidence.

    Supporting and counter evidence are separate tuples on purpose: a question whose
    counter-evidence is invisible reads as more settled than it is (Product 31).
    """

    claims: tuple[ClaimId, ...] = ()
    search_runs: tuple[SearchRunId, ...] = ()
    supporting_evidence: tuple[EvidenceId, ...] = ()
    counter_evidence: tuple[EvidenceId, ...] = ()

    @classmethod
    def of(cls, question: ResearchQuestion) -> QuestionLinks:
        """The links a stored question already carries."""
        return cls(
            claims=question.claims,
            search_runs=question.search_runs,
            supporting_evidence=question.supporting_evidence,
            counter_evidence=question.counter_evidence,
        )

    def merged_with(self, other: QuestionLinks) -> QuestionLinks:
        """This set plus ``other``, keeping declaration order and dropping duplicates."""
        return QuestionLinks(
            claims=_extend(self.claims, other.claims),
            search_runs=_extend(self.search_runs, other.search_runs),
            supporting_evidence=_extend(self.supporting_evidence, other.supporting_evidence),
            counter_evidence=_extend(self.counter_evidence, other.counter_evidence),
        )

    @property
    def is_empty(self) -> bool:
        """True when nothing is linked at all."""
        return not (
            self.claims or self.search_runs or self.supporting_evidence or self.counter_evidence
        )


class QuestionService:
    """Create, link, and move research questions for one workspace."""

    def __init__(self, ctx: CapabilityContext) -> None:
        self._ctx = ctx

    @property
    def ctx(self) -> CapabilityContext:
        """The capability context every mutation runs through."""
        return self._ctx

    # -- create --------------------------------------------------------------

    def create(
        self,
        text: str,
        *,
        links: QuestionLinks | None = None,
        remaining_uncertainty: str | None = None,
        question_id: QuestionId | None = None,
    ) -> tuple[ResearchQuestion, MutationResult]:
        """Register an open question and whatever already bears on it."""
        chosen = links or QuestionLinks()
        question = ResearchQuestion(
            id=question_id or next_question_id(self._ctx.repo),
            question=text,
            status=QuestionStatus.OPEN,
            claims=chosen.claims,
            search_runs=chosen.search_runs,
            supporting_evidence=chosen.supporting_evidence,
            counter_evidence=chosen.counter_evidence,
            remaining_uncertainty=remaining_uncertainty,
            provenance=self._ctx.provenance(workflow="question"),
        )
        result = create_question(self._ctx, CreateQuestionRequest(question=question))
        return self.get(question.id), result

    # -- update --------------------------------------------------------------

    def link(
        self, question_id: QuestionId, links: QuestionLinks, *, replace_links: bool = False
    ) -> tuple[ResearchQuestion, MutationResult]:
        """Add ``links`` to a question, or replace its links when ``replace_links``."""
        current = self.get(question_id)
        merged = links if replace_links else QuestionLinks.of(current).merged_with(links)
        return self._update(
            UpdateQuestionRequest(
                question_id=question_id,
                claims=merged.claims,
                search_runs=merged.search_runs,
                supporting_evidence=merged.supporting_evidence,
                counter_evidence=merged.counter_evidence,
            )
        )

    def set_status(
        self, question_id: QuestionId, status: QuestionStatus, *, note: str | None = None
    ) -> tuple[ResearchQuestion, MutationResult]:
        """Move a question's status; ``note`` records what is still unresolved.

        `remaining_uncertainty` is the question's only free-text field, so a status note
        goes there rather than into an invented one.
        """
        return self._update(
            UpdateQuestionRequest(
                question_id=question_id, status=status, remaining_uncertainty=note
            )
        )

    def resolve(
        self, question_id: QuestionId, answer_note: str
    ) -> tuple[ResearchQuestion, MutationResult]:
        """Answer a question: status `answered`, no uncertainty left, answer captured.

        The answer itself is captured as a `ResearchNote` rather than written onto the
        question: a question has no answer field, and inventing one would give a sentence
        the authority of accepted state without any evidence behind it (Product 31).
        """
        question = self.get(question_id)
        NoteService(self._ctx).capture(f"{question.id} answered: {answer_note}")
        return self._update(
            UpdateQuestionRequest(
                question_id=question_id,
                status=QuestionStatus.ANSWERED,
                remaining_uncertainty="",
            )
        )

    def block(
        self, question_id: QuestionId, *, note: str | None = None
    ) -> tuple[ResearchQuestion, MutationResult]:
        """Block a question, recording what is blocking it."""
        return self.set_status(question_id, QuestionStatus.BLOCKED, note=note)

    def unblock(
        self, question_id: QuestionId, *, status: QuestionStatus = QuestionStatus.OPEN
    ) -> tuple[ResearchQuestion, MutationResult]:
        """Reopen a blocked question at ``status``."""
        return self.set_status(question_id, status)

    def _update(self, request: UpdateQuestionRequest) -> tuple[ResearchQuestion, MutationResult]:
        result = update_question(self._ctx, request)
        return self.get(request.question_id), result

    # -- reads ---------------------------------------------------------------

    def get(self, question_id: QuestionId) -> ResearchQuestion:
        """One question by id."""
        return self._ctx.repo.get_question(question_id)

    def list(self, status: QuestionStatus | None = None) -> QuestionList:
        """Questions by id, optionally filtered by status."""
        questions = sorted(self._ctx.repo.list_questions(), key=lambda item: str(item.id))
        return [item for item in questions if status is None or item.status is status]

    def open_questions(self) -> QuestionList:
        """Questions that are not answered yet: open, partially answered, or blocked."""
        unfinished = {
            QuestionStatus.OPEN,
            QuestionStatus.PARTIALLY_ANSWERED,
            QuestionStatus.BLOCKED,
        }
        return [item for item in self.list() if item.status in unfinished]


def next_question_id(repo: WorkspaceRepository) -> QuestionId:
    """The id `question.create` will write, read the way the capability layer reads it.

    Both the ids already on disk and the `research.yaml` counter are consulted, so a
    hand-authored `RQ0007` can never be handed out a second time.
    """
    on_disk = QuestionId.next(str(question.id) for question in repo.list_questions())
    return QuestionId.make(max(on_disk.number, repo.config.counter(QuestionId.prefix) + 1))


def _extend[T: str](values: tuple[T, ...], extra: tuple[T, ...]) -> tuple[T, ...]:
    merged = list(values)
    merged.extend(value for value in extra if value not in merged)
    return tuple(merged)
