"""Task 8.1: notes are captured with no authority, and promoted only by a researcher.

Product 31 makes a note the cheapest object in the product and a promotion the moment it
stops being cheap. These tests hold both ends: a note carries no evidence relations and
cannot be cited, and turning one into a Claim, Question, or Decision is an explicit
human transition that happens exactly once (ADR-003, ADR-007).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.dto import InitProjectRequest
from research_harness.capabilities.handlers import init_project
from research_harness.cli.commands.research import register
from research_harness.domain.base import Provenance
from research_harness.domain.claim import (
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimScopeSpec,
    ClaimSemantics,
)
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimType,
    DecisionStatus,
    DecisionType,
    NoteStatus,
    QuestionStatus,
    ResearchEventType,
)
from research_harness.domain.errors import AuthorityError, TransitionError
from research_harness.domain.ids import ClaimId, DecisionId, EvidenceId, QuestionId, SearchRunId
from research_harness.domain.research import Decision, ResearchQuestion
from research_harness.domain.transitions import HUMAN_ACTOR, transition_question
from research_harness.research import (
    NoteService,
    QuestionLinks,
    QuestionService,
    next_claim_id,
    next_question_id,
)
from research_harness.research.notes import DISCARD_CAPABILITY

MODEL_ACTOR = "vendor-a/model-x"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[CapabilityContext]:
    """An initialized workspace opened as the researcher."""
    result = init_project(InitProjectRequest(root=tmp_path / "project", name="task-8-1"))
    yield open_context(result.root, HUMAN_ACTOR)


def make_claim(ctx: CapabilityContext, statement: str) -> Claim:
    """A claim whose scope and assessment are explicit, as Product 10 requires."""
    return Claim(
        id=next_claim_id(ctx.repo),
        statement=statement,
        type=ClaimType.DESCRIPTIVE,
        semantics=ClaimSemantics(subject="detectors", predicate="assume", object="plaintext"),
        scope=ClaimScopeSpec(level=ClaimScope.OBSERVED_SUBSET, corpus="task-8-1"),
        relations=(
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0001"), relation=ClaimEvidenceRelationType.SUPPORTS
            ),
        ),
        assessment=ClaimAssessment(
            requested_strength=ClaimScope.OBSERVED_SUBSET,
            allowed_strength=ClaimScope.OBSERVED_SUBSET,
        ),
        provenance=Provenance.human(),
    )


def make_question(ctx: CapabilityContext, text: str) -> ResearchQuestion:
    return ResearchQuestion(
        id=next_question_id(ctx.repo), question=text, provenance=Provenance.human()
    )


def make_decision(ctx: CapabilityContext, rationale: str) -> Decision:
    return Decision(
        id=DecisionId.next(str(decision.id) for decision in ctx.repo.list_decisions()),
        type=DecisionType.METHODOLOGY,
        status=DecisionStatus.PROPOSED,
        rationale=rationale,
        provenance=Provenance.human(),
    )


# -- capture -----------------------------------------------------------------


def test_a_captured_note_carries_no_authority_and_no_evidence_relations(
    project: CapabilityContext,
) -> None:
    note, result = NoteService(project).capture("byte-level tokenization keeps recurring")

    assert note.status is NoteStatus.CAPTURED
    assert note.promoted_to is None
    assert not hasattr(note, "relations")
    assert result.event.event is ResearchEventType.NOTE_CAPTURED
    assert result.validation.ok


def test_a_capture_source_is_provenance_and_never_note_content(
    project: CapabilityContext,
) -> None:
    """Where a note came from is provenance; putting it in the text would fake a quote."""
    text = "the encrypted-traffic papers all assume header visibility"
    note, _ = NoteService(project).capture(text, source="chat-host")

    assert note.text == text
    assert note.provenance.note is not None
    assert "chat-host" in note.provenance.note


def test_notes_are_listed_by_status(project: CapabilityContext) -> None:
    notes = NoteService(project)
    kept, _ = notes.capture("keep this one")
    dropped, _ = notes.capture("drop this one")
    notes.discard(str(dropped.key))

    assert [note.key for note in notes.list(NoteStatus.CAPTURED)] == [kept.key]
    assert [note.key for note in notes.list(NoteStatus.DISCARDED)] == [dropped.key]
    assert len(notes.list()) == 2


# -- promotion ---------------------------------------------------------------


def test_a_note_is_promoted_into_a_question_it_became(project: CapabilityContext) -> None:
    notes = NoteService(project)
    note, _ = notes.capture("does field-based framing survive encryption?")
    question = make_question(project, note.text)

    promotion = notes.promote_to_question(str(note.key), question)

    assert promotion.note.status is NoteStatus.PROMOTED
    assert promotion.note.promoted_to == question.id
    assert project.repo.get_question(question.id).question == note.text
    assert promotion.promoted.event.event is ResearchEventType.NOTE_PROMOTED


def test_a_note_is_promoted_into_a_claim_it_became(project: CapabilityContext) -> None:
    notes = NoteService(project)
    note, _ = notes.capture("detectors assume plaintext headers")
    claim = make_claim(project, note.text)

    promotion = notes.promote_to_claim(str(note.key), claim)

    assert promotion.target == claim.id
    assert project.repo.get_claim(claim.id).statement == note.text
    assert notes.get(str(note.key)).promoted_to == claim.id


def test_a_note_is_promoted_into_an_accepted_decision_it_became(
    project: CapabilityContext,
) -> None:
    notes = NoteService(project)
    note, _ = notes.capture("exclude works without a released dataset")
    decision = make_decision(project, note.text)

    promotion = notes.promote_to_decision(str(note.key), decision)

    stored = project.repo.get_decision(decision.id)
    assert stored.status is DecisionStatus.ACCEPTED
    assert promotion.note.promoted_to == decision.id


def test_a_note_cannot_be_promoted_twice(project: CapabilityContext) -> None:
    """Promoted is terminal: a note that already became something cannot become another."""
    notes = NoteService(project)
    note, _ = notes.capture("worth turning into a question")
    notes.promote_to_question(str(note.key), make_question(project, note.text))

    second = make_question(project, "a different question")
    with pytest.raises(TransitionError):
        notes.promote_to_question(str(note.key), second)

    assert [str(item.id) for item in project.repo.list_questions()] == ["RQ0001"]


def test_a_discarded_note_is_terminal_and_cannot_be_promoted(
    project: CapabilityContext,
) -> None:
    notes = NoteService(project)
    note, _ = notes.capture("not worth keeping")

    discarded, result = notes.discard(str(note.key))

    assert discarded.status is NoteStatus.DISCARDED
    assert result.event.event is ResearchEventType.NOTE_DISCARDED
    assert result.event in list(project.repo.iter_events())
    with pytest.raises(TransitionError):
        notes.promote_to_question(str(note.key), make_question(project, note.text))


def test_a_discard_carries_the_researchers_reason_into_the_event(
    project: CapabilityContext,
) -> None:
    """The service decides *whether*; `note.discard` in `capabilities/` does the writing."""
    notes = NoteService(project)
    note, _ = notes.capture("superseded by the coverage audit")

    discarded, result = notes.discard(str(note.key), reason="answered by the coverage audit")

    assert discarded.status is NoteStatus.DISCARDED
    assert result.capability == DISCARD_CAPABILITY
    assert result.event.payload["reason"] == "answered by the coverage audit"


def test_a_discard_without_a_reason_still_works(project: CapabilityContext) -> None:
    """A note carries no authority to withdraw, so the reason is optional."""
    notes = NoteService(project)
    note, _ = notes.capture("just noise")
    _, result = notes.discard(str(note.key))
    assert "reason" not in result.event.payload


def test_a_model_actor_cannot_promote_a_note_and_creates_nothing(
    project: CapabilityContext,
) -> None:
    """Promotion raises authority, so it is human-only - and refused before anything exists."""
    notes = NoteService(project)
    note, _ = notes.capture("a model may capture, but never promote")
    as_model = open_context(project.root, MODEL_ACTOR)
    question = make_question(project, note.text)

    with pytest.raises(AuthorityError):
        NoteService(as_model).promote_to_question(str(note.key), question)

    assert project.repo.list_questions() == []
    assert notes.get(str(note.key)).status is NoteStatus.CAPTURED


# -- questions ---------------------------------------------------------------


def test_a_question_links_claims_search_runs_and_both_sides_of_the_evidence(
    project: CapabilityContext,
) -> None:
    questions = QuestionService(project)
    question, _ = questions.create(
        "does field-based framing survive encryption?",
        remaining_uncertainty="no accepted result covers TLS 1.3",
    )

    linked, result = questions.link(
        question.id,
        QuestionLinks(
            claims=(ClaimId("C0001"),),
            search_runs=(SearchRunId("SR0001"),),
            supporting_evidence=(EvidenceId("E0001"),),
            counter_evidence=(EvidenceId("E0002"),),
        ),
    )

    assert linked.claims == (ClaimId("C0001"),)
    assert linked.search_runs == (SearchRunId("SR0001"),)
    assert linked.supporting_evidence == (EvidenceId("E0001"),)
    assert linked.counter_evidence == (EvidenceId("E0002"),)
    assert linked.remaining_uncertainty == "no accepted result covers TLS 1.3"
    assert result.event.event is ResearchEventType.QUESTION_UPDATED


def test_linking_the_same_object_twice_does_not_duplicate_it(
    project: CapabilityContext,
) -> None:
    questions = QuestionService(project)
    question, _ = questions.create("is the corpus wide enough?")
    links = QuestionLinks(claims=(ClaimId("C0001"),))

    questions.link(question.id, links)
    linked, _ = questions.link(question.id, links)

    assert linked.claims == (ClaimId("C0001"),)


def test_question_status_moves_through_the_transition_table_including_blocked(
    project: CapabilityContext,
) -> None:
    questions = QuestionService(project)
    question, _ = questions.create("do the reported metrics compare at all?")

    blocked, _ = questions.block(question.id, note="waiting on two full texts")
    assert blocked.status is QuestionStatus.BLOCKED
    assert blocked.remaining_uncertainty == "waiting on two full texts"

    reopened, _ = questions.unblock(question.id)
    assert reopened.status is QuestionStatus.OPEN

    partial, _ = questions.set_status(question.id, QuestionStatus.PARTIALLY_ANSWERED)
    assert partial.status is QuestionStatus.PARTIALLY_ANSWERED


def test_the_status_a_question_already_has_is_a_no_op_not_a_transition(
    project: CapabilityContext,
) -> None:
    """The table forbids `open -> open`; asking for the current status changes nothing."""
    questions = QuestionService(project)
    question, _ = questions.create("does the taxonomy still fit?")

    with pytest.raises(TransitionError):
        transition_question(question, QuestionStatus.OPEN, actor=HUMAN_ACTOR)

    unchanged, result = questions.set_status(question.id, QuestionStatus.OPEN)
    assert unchanged.status is QuestionStatus.OPEN
    assert result.validation.ok


def test_resolving_a_question_clears_the_uncertainty_and_captures_the_answer(
    project: CapabilityContext,
) -> None:
    """A question has no answer field, so the answer is captured as a note, not invented."""
    questions = QuestionService(project)
    question, _ = questions.create(
        "does field-based framing survive encryption?",
        remaining_uncertainty="no accepted result covers TLS 1.3",
    )

    answered, _ = questions.resolve(question.id, "No: every accepted result assumes headers.")

    assert answered.status is QuestionStatus.ANSWERED
    assert not answered.remaining_uncertainty
    captured = [note.text for note in NoteService(project).list()]
    assert any(str(question.id) in text and "assumes headers" in text for text in captured)


def test_open_questions_exclude_answered_ones(project: CapabilityContext) -> None:
    questions = QuestionService(project)
    first, _ = questions.create("still open")
    second, _ = questions.create("about to be answered")
    questions.resolve(second.id, "answered in the ablation table")

    assert [item.id for item in questions.open_questions()] == [first.id]
    assert [item.id for item in questions.list(QuestionStatus.ANSWERED)] == [second.id]


def test_question_ids_are_allocated_without_colliding(project: CapabilityContext) -> None:
    questions = QuestionService(project)
    first, _ = questions.create("first")
    second, _ = questions.create("second")

    assert (first.id, second.id) == (QuestionId("RQ0001"), QuestionId("RQ0002"))


# -- the CLI (Task 8.3) ------------------------------------------------------

cli = typer.Typer()
register(cli)
runner = CliRunner()


def run(*args: str) -> Result:
    return runner.invoke(cli, list(args))


def test_the_cli_captures_lists_and_promotes_a_note(project: CapabilityContext) -> None:
    root = str(project.root)
    added = run("note", "add", "encrypted traffic keeps coming up", "-w", root, "--json")
    assert added.exit_code == 0, added.stdout
    key = json.loads(added.stdout)["note"]["key"]

    listed = run("note", "list", "-w", root)
    assert listed.exit_code == 0 and key in listed.stdout

    promoted = run("note", "promote", key, "--to", "question", "-w", root, "--json")
    assert promoted.exit_code == 0, promoted.stdout
    payload = json.loads(promoted.stdout)
    assert payload["target"] == "RQ0001"
    assert payload["note"]["status"] == "promoted"
    assert project.repo.get_question(QuestionId("RQ0001")).question == (
        "encrypted traffic keeps coming up"
    )


def test_the_cli_refuses_to_invent_a_claim_out_of_a_note(project: CapabilityContext) -> None:
    """A claim needs scope, semantics, and an assessment; the CLI never fills them in."""
    root = str(project.root)
    added = run("note", "add", "detectors assume plaintext", "-w", root, "--json")
    key = json.loads(added.stdout)["note"]["key"]

    refused = run("note", "promote", key, "--to", "claim", "-w", root)

    assert refused.exit_code == 1
    assert project.repo.list_claims() == []


def test_the_cli_creates_lists_and_resolves_a_question(project: CapabilityContext) -> None:
    root = str(project.root)
    created = run("question", "create", "does framing survive encryption?", "-w", root, "--json")
    assert created.exit_code == 0, created.stdout
    question_id = json.loads(created.stdout)["question"]["id"]

    listed = run("question", "list", "--open", "-w", root)
    assert listed.exit_code == 0 and question_id in listed.stdout

    resolved = run("question", "resolve", question_id, "no, all assume headers", "-w", root)
    assert resolved.exit_code == 0, resolved.stdout
    assert "answered" in resolved.stdout
    assert project.repo.get_question(QuestionId(question_id)).status is QuestionStatus.ANSWERED
