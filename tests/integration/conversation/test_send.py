"""Sending, against a real store and a real (scripted) provider.

The properties here are the ones a researcher notices when something goes wrong: the
transcript is never corrupted, a partial answer is kept and labelled, a retry keeps the
attempt it retries, and the receipt is readable after the fact.
"""

from __future__ import annotations

import shutil

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.send import STREAM_STAGE, StreamState
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import (
    AttemptStatus,
    ContextClass,
    EgressClass,
    MessageRole,
    OmissionReason,
    ReferenceBlock,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import MessageId
from research_harness.providers.models.base import ProviderTransportError
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.workspace.runs import RunStore
from tests.integration.conversation.conftest import ANSWER, service_for
from tests.unit.conversation.conftest import say, write_claim


def run_to_completion(service: ConversationService, session: object, text: str) -> object:
    started = service.send(session, text)  # type: ignore[arg-type]
    assert service.wait(started.run_id, 10), "the streaming thread must finish"
    return started


# -- the happy path ----------------------------------------------------------


def test_a_complete_send_writes_a_question_an_answer_and_a_receipt(
    answering: ConversationService,
) -> None:
    session = answering.create("Latency study")
    started = run_to_completion(answering, session.id, "What did we learn about latency?")

    page = answering.transcript(session.id)
    assert [message.role for message in page.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    answer = page.messages[1]
    assert answer.text() == ANSWER
    assert answer.attempt.status is AttemptStatus.COMPLETE
    assert answer.context_pack == started.context_pack
    assert answer.model is not None and answer.model.model == "scripted-1"


def test_every_delta_is_persisted_before_it_is_emitted(
    answering: ConversationService, ctx: CapabilityContext
) -> None:
    session = answering.create("Latency study")
    started = run_to_completion(answering, session.id, "What did we learn about latency?")

    runs = RunStore(ctx.repo.layout.research_dir)
    state = StreamState.of(runs.load_checkpoint(started.run_id, STREAM_STAGE))
    assert state is not None
    assert len(state.deltas) > 1, "a chunked stream must reach the run as several deltas"
    assert state.text == ANSWER
    assert state.message == str(started.assistant_message)


def test_the_receipt_is_readable_after_the_response(answering: ConversationService) -> None:
    session = answering.create("Latency study")
    started = run_to_completion(answering, session.id, "What did we learn about latency?")

    pack = answering.read_pack(session.id, started.context_pack)
    assert pack.message == started.assistant_message
    assert pack.egress is EgressClass.LOCAL
    assert pack.receipt.total_tokens() > 0
    assert ContextClass.POLICY in pack.receipt.tokens_by_class()
    assert answering.packs(session.id) == [started.context_pack]


def test_a_resolved_reference_becomes_a_structured_block_and_unresolved_text_is_reported(
    answering: ConversationService, ctx: CapabilityContext
) -> None:
    write_claim(ctx.repo, "C0001", "Batching reduces tail latency across the corpus.")
    session = answering.create("Latency study")
    started = answering.send(session.id, "Does @C0001 still hold? What about @C9999?")
    assert answering.wait(started.run_id, 10)

    question = answering.transcript(session.id).messages[0]
    references = [block for block in question.blocks if isinstance(block, ReferenceBlock)]
    assert [str(block.target) for block in references] == ["C0001"]
    assert "C9999" in question.text(), "an unresolved token stays in the prose, verbatim"
    assert started.unresolved == ("C9999",)


# -- failure and interruption ------------------------------------------------


def test_provider_unavailability_leaves_the_transcript_intact(
    ctx: CapabilityContext,
) -> None:
    service = service_for(ctx, ScriptedProvider([ProviderTransportError("no route to host")]))
    session = service.create("Latency study")
    started = run_to_completion(service, session.id, "What did we learn about latency?")

    page = service.transcript(session.id)
    assert [message.role for message in page.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    answer = page.messages[1]
    assert answer.attempt.status is AttemptStatus.FAILED
    assert answer.text() == ""
    assert "no route to host" in (answer.attempt.error or "")
    outcome = service.outcome(started.run_id)
    assert outcome.state == "failed"
    assert service.read_pack(session.id, started.context_pack) is not None


def test_a_stream_that_stops_part_way_keeps_what_arrived_and_says_it_is_incomplete(
    ctx: CapabilityContext,
) -> None:
    class Partial:
        """A stream that yields two deltas and then loses the connection."""

        name = "partial"

        def stream(self, request: object) -> object:
            from research_harness.providers.models.streaming import StreamDelta

            def generate() -> object:
                yield StreamDelta(text="Batching reduced ", index=0)
                yield StreamDelta(text="tail latency ", index=1)
                raise ProviderTransportError("connection reset")

            return generate()

    from research_harness.conversation.context import ProviderProfile
    from research_harness.conversation.send import ProviderSelector, Selection

    class Selector:
        def select(self, ctx: CapabilityContext, *, model: object, budget: object) -> Selection:
            return Selection(
                provider=Partial(),  # type: ignore[arg-type]
                profile=ProviderProfile(
                    provider="partial", model="partial-1", egress=EgressClass.LOCAL
                ),
            )

    selector: ProviderSelector = Selector()
    service = ConversationService(ctx, providers=selector)
    session = service.create("Latency study")
    started = run_to_completion(service, session.id, "What did we learn about latency?")

    answer = service.transcript(session.id).messages[1]
    assert answer.text() == "Batching reduced tail latency "
    assert answer.attempt.status is AttemptStatus.INTERRUPTED
    assert answer.incomplete
    assert service.outcome(started.run_id).state == "incomplete"


def test_stopping_a_running_stream_marks_the_message_incomplete(
    ctx: CapabilityContext,
) -> None:
    """The realistic shape: the run id exists, and Stop arrives mid-stream."""
    from research_harness.conversation.context import ProviderProfile
    from research_harness.conversation.send import Selection
    from research_harness.providers.models.streaming import StreamDelta

    runs = RunStore(ctx.repo.layout.research_dir)

    class Interruptible:
        name = "interruptible"

        def stream(self, request: object) -> object:
            def generate() -> object:
                yield StreamDelta(text="Batching reduced ", index=0)
                # Whoever is watching pressed Stop between deltas.
                for run in runs.list_runs():
                    runs.request_cancel(run.run_id)
                yield StreamDelta(text="tail latency ", index=1)
                yield StreamDelta(text="by nine percent.", index=2, final=True)

            return generate()

    class Selector:
        def select(self, ctx: CapabilityContext, *, model: object, budget: object) -> Selection:
            return Selection(
                provider=Interruptible(),  # type: ignore[arg-type]
                profile=ProviderProfile(
                    provider="interruptible", model="i-1", egress=EgressClass.LOCAL
                ),
            )

    service = ConversationService(ctx, providers=Selector())
    session = service.create("Latency study")
    started = service.send(session.id, "What did we learn?", background=False)

    answer = service.transcript(session.id).messages[1]
    assert answer.text() == "Batching reduced tail latency ", (
        "a delta the provider already handed over was received, so it is kept"
    )
    assert not answer.text().endswith("nine percent."), "and the stream stopped promptly"
    assert answer.attempt.status is AttemptStatus.INTERRUPTED
    assert answer.attempt.error, "an interrupted answer says why it is partial"
    assert service.outcome(started.run_id).state == "cancelled"


# -- retry -------------------------------------------------------------------


def test_a_retry_is_a_new_attempt_and_the_failed_one_is_kept(ctx: CapabilityContext) -> None:
    provider = ScriptedProvider([ProviderTransportError("no route to host"), {"text": ANSWER}])
    service = service_for(ctx, provider)
    session = service.create("Latency study")
    run_to_completion(service, session.id, "What did we learn about latency?")

    failed = service.transcript(session.id).messages[1]
    assert failed.attempt.status is AttemptStatus.FAILED

    retried = service.retry(failed.id, background=False)
    page = service.transcript(session.id)
    assert len(page.messages) == 3, "a retry adds a message; it never rewrites one"
    kept = page.messages[1]
    assert kept.id == failed.id and kept.attempt.status is AttemptStatus.FAILED
    answer = page.messages[2]
    assert answer.attempt.number == 2
    assert answer.attempt.retry_of == failed.id
    assert answer.text() == ANSWER
    assert answer.context_pack != failed.context_pack
    assert retried.attempt == 2


def test_a_completed_message_cannot_be_retried(answering: ConversationService) -> None:
    session = answering.create("Latency study")
    run_to_completion(answering, session.id, "What did we learn about latency?")
    answer = answering.transcript(session.id).messages[1]

    with pytest.raises(CapabilityError, match="nothing to retry"):
        answering.retry(answer.id, background=False)


def test_retrying_something_that_is_not_a_model_message_is_refused(
    answering: ConversationService,
) -> None:
    session = answering.create("Latency study")
    run_to_completion(answering, session.id, "What did we learn about latency?")
    question = answering.transcript(session.id).messages[0]

    with pytest.raises(CapabilityError, match="model message"):
        answering.retry(question.id, background=False)

    with pytest.raises(CapabilityError, match="no message"):
        answering.retry(MessageId("M9999"), background=False)


# -- durability --------------------------------------------------------------


def test_the_transcript_and_cross_session_retrieval_survive_deleting_research(
    ctx: CapabilityContext,
) -> None:
    service = service_for(ctx, ScriptedProvider([{"text": ANSWER}, {"text": ANSWER}]))
    earlier = service.create("Earlier latency work")
    service.send(earlier.id, "What did the pilot corpus show about latency?", background=False)
    current = service.create("Today")

    shutil.rmtree(ctx.repo.layout.research_dir)

    page = service.transcript(earlier.id)
    assert len(page.messages) == 2, "a deleted projection may not lose a transcript"
    assert service.search("latency"), "search reads the transcripts directly"

    fresh = service_for(ctx, ScriptedProvider([{"text": ANSWER}]))
    started = fresh.send(
        current.id, "What did the pilot corpus show about latency?", background=False
    )
    pack = fresh.read_pack(current.id, started.context_pack)
    prior = [
        item for item in pack.receipt.included if item.context_class is ContextClass.PRIOR_SESSIONS
    ]
    assert prior, "cross-session retrieval still works through the direct transcript scan"


def test_a_send_with_no_provider_configured_fails_before_it_writes_a_run(
    ctx: CapabilityContext,
) -> None:
    service = ConversationService(ctx)
    session = service.create("Latency study")

    with pytest.raises(CapabilityError, match="no model providers configured"):
        service.send(session.id, "anything", background=False)

    assert service.transcript(session.id).total == 0, "nothing is appended before a provider"
    assert RunStore(ctx.repo.layout.research_dir).list_runs() == []


def test_an_omitted_item_is_explained_rather_than_dropped(ctx: CapabilityContext) -> None:
    from research_harness.domain.conversation import Visibility

    service = service_for(ctx, ScriptedProvider([{"text": ANSWER}]), egress=EgressClass.EXTERNAL)
    earlier = service.create("Private earlier work")
    service.store.append_message(
        earlier.id, say(earlier.id, "unreleased latency numbers from the pilot corpus")
    )
    session = service.store.create_session(
        title="Today", provenance=ctx.provenance(), visibility=Visibility.PROJECT
    )
    started = service.send(
        session.id, "what were the pilot corpus latency numbers", background=False
    )

    pack = service.read_pack(session.id, started.context_pack)
    blocked = [
        item for item in pack.receipt.omitted if item.reason is OmissionReason.EGRESS_BLOCKED
    ]
    assert blocked, "an external send must report the private material it withheld"


def test_a_private_session_refuses_an_external_provider(ctx: CapabilityContext) -> None:
    """An empty pack would look like an answer; a refusal says what to do instead."""
    from research_harness.privacy.policy import EgressDeniedError

    service = service_for(ctx, ScriptedProvider([{"text": ANSWER}]), egress=EgressClass.EXTERNAL)
    session = service.create("Private study")

    with pytest.raises(EgressDeniedError, match="visibility project"):
        service.send(session.id, "what did we learn", background=False)

    assert service.transcript(session.id).total == 0
    assert RunStore(ctx.repo.layout.research_dir).list_runs() == []
