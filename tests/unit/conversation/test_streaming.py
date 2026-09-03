"""Streaming over the neutral model contract: chunks, one-delta fallback, interruption."""

from __future__ import annotations

import pytest

from research_harness.providers.models.base import ProviderTransportError
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.providers.models.streaming import (
    ChatReply,
    ChunkedStream,
    CompletionStream,
    StreamingModelProvider,
    chat_request,
    split_text,
    streaming_provider,
)

ANSWER = "Batching reduced tail latency by nine percent across the pilot corpus of forty runs."


def request() -> object:
    return chat_request(instructions="answer", context_tokens=1000)


def test_split_text_reassembles_the_original_exactly() -> None:
    for size in (1, 3, 8, 100):
        assert "".join(split_text(ANSWER, size)) == ANSWER
    assert split_text("", 4) == [""]


def test_a_chunked_stream_delivers_the_whole_answer_in_several_deltas() -> None:
    provider = ScriptedProvider([{"text": ANSWER}])
    stream = ChunkedStream(provider, chunk_words=3)

    deltas = list(stream.stream(request()))  # type: ignore[arg-type]
    assert len(deltas) > 1
    assert "".join(delta.text for delta in deltas) == ANSWER
    assert [delta.index for delta in deltas] == list(range(len(deltas)))
    assert deltas[-1].final and deltas[-1].model == "scripted-1"
    assert not any(delta.final for delta in deltas[:-1])


def test_the_fallback_delivers_a_whole_answer_as_one_delta() -> None:
    provider = ScriptedProvider([{"text": ANSWER}])

    deltas = list(CompletionStream(provider).stream(request()))  # type: ignore[arg-type]
    assert [delta.text for delta in deltas] == [ANSWER]
    assert deltas[0].final


def test_abandoning_the_iterator_keeps_what_already_arrived() -> None:
    """Interruption is the consumer's business: whatever was yielded is what was received."""
    provider = ScriptedProvider([{"text": ANSWER}])
    received: list[str] = []

    for delta in ChunkedStream(provider, chunk_words=2).stream(request()):  # type: ignore[arg-type]
        received.append(delta.text)
        if len(received) == 2:
            break

    partial = "".join(received)
    assert partial and ANSWER.startswith(partial)
    assert partial != ANSWER


def test_a_provider_failure_propagates_rather_than_becoming_an_empty_answer() -> None:
    provider = ScriptedProvider([ProviderTransportError("no route to host")])

    with pytest.raises(ProviderTransportError):
        list(ChunkedStream(provider).stream(request()))  # type: ignore[arg-type]


def test_a_reply_that_does_not_satisfy_the_schema_is_refused() -> None:
    """Streaming does not weaken structured output: the answer is validated as ever."""
    from research_harness.providers.models.base import StructuredOutputError

    provider = ScriptedProvider(["not json at all"])
    with pytest.raises(StructuredOutputError):
        list(CompletionStream(provider).stream(request()))  # type: ignore[arg-type]


def test_streaming_provider_wraps_a_non_streaming_adapter() -> None:
    provider = ScriptedProvider([{"text": ANSWER}])
    assert isinstance(streaming_provider(provider), CompletionStream)
    assert isinstance(streaming_provider(provider, chunk_words=4), ChunkedStream)


def test_a_native_streaming_backend_is_used_as_it_is() -> None:
    class Native:
        name = "native"

        def stream(self, request: object) -> object:
            return iter(())

    native = Native()
    assert streaming_provider(native) is native  # type: ignore[arg-type]
    assert isinstance(native, StreamingModelProvider)


def test_the_chat_request_asks_for_prose_and_a_window_that_fits_the_pack() -> None:
    job = chat_request(instructions="answer", context_tokens=4321, role="conversation")
    assert job.role == "conversation"
    assert job.response_schema is ChatReply
    assert job.requirements.context_tokens == 4321


def test_a_zero_chunk_size_is_refused() -> None:
    with pytest.raises(ValueError, match="chunk_words"):
        ChunkedStream(ScriptedProvider([]), chunk_words=0)
