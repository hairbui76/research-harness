"""Native streaming for the hosted adapters, over fake `text/event-stream` transports.

Four properties, and each of them is a thing a conversation actually depends on:

1. **Order and completeness.** Several deltas arrive in the order the server sent them,
   and concatenating them reproduces the answer exactly — the property that lets the
   transcript claim it holds what the model wrote.
2. **Accounting.** The last delta carries the model, the stop reason, and the token usage,
   which both APIs report only at the end of a stream.
3. **Interruption.** Abandoning the iterator closes the HTTP response part way through, so
   an interrupted turn stops the call rather than draining it. The fake stream records how
   many chunks it was actually asked for, which is how that is measured rather than assumed.
4. **Prose, not JSON.** A streamed turn requests no schema; a schema-shaped request is
   routed back to the ordinary validated call by `NativeStream`.

No network and no key: every byte comes from `httpx.MockTransport`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
import pytest

from research_harness.providers.models import AnthropicProvider, OpenAIProvider
from research_harness.providers.models.base import (
    ModelProvider,
    ModelRequest,
    ProviderResponseError,
)
from research_harness.providers.models.streaming import (
    ChatReply,
    NativeStream,
    StreamDelta,
    chat_request,
    streaming_provider,
)
from tests.contract.providers.conftest import (
    CallRecorder,
    Verdict,
    anthropic_body,
    json_response,
    make_transport,
)

ANSWER_PARTS = ("Batching ", "reduces tail latency ", "across the pilot corpus.")
ANSWER = "".join(ANSWER_PARTS)

INPUT_TOKENS = 812
OUTPUT_TOKENS = 41
CACHED_TOKENS = 128


class RecordingStream(httpx.SyncByteStream):
    """A byte stream that remembers how much of itself was actually read."""

    def __init__(self, chunks: Sequence[bytes]) -> None:
        self._chunks = list(chunks)
        self.sent: list[bytes] = []
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.sent.append(chunk)
            yield chunk

    def close(self) -> None:
        self.closed = True


def sse(*events: str) -> RecordingStream:
    """One `text/event-stream` body, each event its own chunk so reads are countable."""
    return RecordingStream([f"{event}\n\n".encode() for event in events])


def sse_transport(recorder: CallRecorder, stream: RecordingStream) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    return httpx.MockTransport(handler)


def _chunk(**fields: Any) -> str:
    """One `data:` line of a chat-completions stream."""
    body = {"id": "c", "object": "chat.completion.chunk", "model": "gpt-test-1", **fields}
    return f"data: {json.dumps(body)}"


def openai_events() -> list[str]:
    """The chat-completions stream: three content chunks, a finish, usage, then `[DONE]`."""
    return [
        _chunk(choices=[{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]),
        *(
            _chunk(choices=[{"index": 0, "delta": {"content": part}, "finish_reason": None}])
            for part in ANSWER_PARTS
        ),
        _chunk(choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]),
        _chunk(
            choices=[],
            usage={
                "prompt_tokens": INPUT_TOKENS,
                "completion_tokens": OUTPUT_TOKENS,
                "prompt_tokens_details": {"cached_tokens": CACHED_TOKENS},
            },
        ),
        "data: [DONE]",
    ]


def _event(name: str, **fields: Any) -> str:
    """One named Messages event, as the API frames it: an `event:` line and a `data:` line."""
    return f"event: {name}\ndata: {json.dumps({'type': name, **fields})}"


def anthropic_events() -> list[str]:
    """The Messages stream: start, three text deltas, a thinking delta, delta, stop."""
    return [
        _event(
            "message_start",
            message={
                "id": "msg",
                "model": "claude-test-1",
                "usage": {
                    "input_tokens": INPUT_TOKENS,
                    "output_tokens": 1,
                    "cache_read_input_tokens": CACHED_TOKENS,
                },
            },
        ),
        _event("content_block_start", index=0, content_block={"type": "text", "text": ""}),
        *(
            _event("content_block_delta", index=0, delta={"type": "text_delta", "text": part})
            for part in ANSWER_PARTS
        ),
        _event(
            "content_block_delta",
            index=0,
            delta={"type": "thinking_delta", "thinking": "never stored"},
        ),
        _event("content_block_stop", index=0),
        _event(
            "message_delta",
            delta={"stop_reason": "end_turn"},
            usage={"output_tokens": OUTPUT_TOKENS},
        ),
        _event("message_stop"),
    ]


def turn() -> ModelRequest[ChatReply]:
    return chat_request(instructions="answer the researcher", context_tokens=8000)


def openai(recorder: CallRecorder, stream: RecordingStream) -> OpenAIProvider:
    return OpenAIProvider(
        "gpt-test-1", api_key="k", transport=sse_transport(recorder, stream), env={}
    )


def anthropic(recorder: CallRecorder, stream: RecordingStream) -> AnthropicProvider:
    return AnthropicProvider(
        "claude-test-1", api_key="k", transport=sse_transport(recorder, stream), env={}
    )


# -- 1 and 2: order, completeness, and the accounting on the final delta ------


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_a_stream_arrives_as_several_deltas_that_reassemble_the_answer(
    recorder: CallRecorder, vendor: str
) -> None:
    stream = sse(*(openai_events() if vendor == "openai" else anthropic_events()))
    provider: ModelProvider = (
        openai(recorder, stream) if vendor == "openai" else anthropic(recorder, stream)
    )

    deltas = list(provider.stream(turn()))  # type: ignore[attr-defined]

    text = [delta.text for delta in deltas if delta.text]
    assert text == list(ANSWER_PARTS), "each server chunk is one delta, in order"
    assert "".join(delta.text for delta in deltas) == ANSWER
    assert [delta.index for delta in deltas if delta.text] == [0, 1, 2]
    assert [delta.final for delta in deltas[:-1]] == [False] * (len(deltas) - 1)


@pytest.mark.parametrize(
    ("vendor", "model"), [("openai", "gpt-test-1"), ("anthropic", "claude-test-1")]
)
def test_the_final_delta_carries_the_model_stop_reason_and_usage(
    recorder: CallRecorder, vendor: str, model: str
) -> None:
    """Both APIs report the accounting at the end, so the contract does too."""
    stream = sse(*(openai_events() if vendor == "openai" else anthropic_events()))
    provider: Any = openai(recorder, stream) if vendor == "openai" else anthropic(recorder, stream)

    final = list(provider.stream(turn()))[-1]

    assert final.final and final.text == ""
    assert final.model == model
    assert final.stop_reason == ("stop" if vendor == "openai" else "end_turn")
    assert final.usage is not None
    assert final.usage.input_tokens == INPUT_TOKENS
    assert final.usage.output_tokens == OUTPUT_TOKENS
    assert final.usage.cached_input_tokens == CACHED_TOKENS


def test_no_thinking_delta_ever_reaches_the_transcript(recorder: CallRecorder) -> None:
    """Product 20.5: the harness neither requests nor stores hidden reasoning."""
    provider = anthropic(recorder, sse(*anthropic_events()))

    deltas = list(provider.stream(turn()))

    assert "never stored" not in "".join(delta.text for delta in deltas)


# -- 4: a streamed turn is prose ---------------------------------------------


def test_the_openai_stream_asks_for_prose_and_reports_usage(recorder: CallRecorder) -> None:
    provider = openai(recorder, sse(*openai_events()))

    list(provider.stream(turn()))

    assert recorder.last.url.path.endswith("/chat/completions")
    payload = recorder.last_payload
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert "response_format" not in payload and "text" not in payload
    assert payload["messages"][0]["role"] == "system"


def test_the_anthropic_stream_asks_for_prose_with_no_output_config(
    recorder: CallRecorder,
) -> None:
    provider = anthropic(recorder, sse(*anthropic_events()))

    list(provider.stream(turn()))

    assert recorder.last.url.path.endswith("/v1/messages")
    payload = recorder.last_payload
    assert payload["stream"] is True
    assert "output_config" not in payload
    assert payload["system"] == "answer the researcher"


# -- 3: interruption ---------------------------------------------------------


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_abandoning_the_iterator_stops_the_call_instead_of_draining_it(
    recorder: CallRecorder, vendor: str
) -> None:
    """Conversation design SS8: what arrived is kept, and nothing more is asked for."""
    events = openai_events() if vendor == "openai" else anthropic_events()
    stream = sse(*events)
    provider: Any = openai(recorder, stream) if vendor == "openai" else anthropic(recorder, stream)

    received: list[str] = []
    deltas = provider.stream(turn())
    for delta in deltas:
        if delta.text:
            received.append(delta.text)
        if len(received) == 2:
            break
    deltas.close()

    assert received == list(ANSWER_PARTS[:2])
    assert len(stream.sent) < len(events), "the rest of the stream was never read"
    assert stream.closed


# -- the wrapper: schema fallback, model label, and the trace ----------------


class Recorder:
    """A trace sink that keeps what it was handed."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        kind: str,
        *,
        provider: str,
        model: str,
        request_fingerprint: str,
        payload: Any,
    ) -> None:
        self.records.append(
            {
                "kind": kind,
                "provider": provider,
                "model": model,
                "fingerprint": request_fingerprint,
                "payload": dict(payload),
            }
        )


def test_streaming_provider_uses_the_adapters_own_stream(recorder: CallRecorder) -> None:
    """`session.send` picks native streaming the moment an adapter offers it."""
    provider = openai(recorder, sse(*openai_events()))

    assert isinstance(streaming_provider(provider), NativeStream)
    assert isinstance(streaming_provider(provider, chunk_words=3), NativeStream)


def test_the_wrapper_stamps_the_routing_entrys_model_on_the_final_delta(
    recorder: CallRecorder,
) -> None:
    """Which configured entry answered is reproducibility metadata (Product 20.5)."""
    provider = openai(recorder, sse(*openai_events()))
    wrapped = streaming_provider(provider, model="gpt-configured")

    deltas: list[StreamDelta] = list(wrapped.stream(turn()))

    assert deltas[-1].model == "gpt-configured"
    assert "".join(delta.text for delta in deltas) == ANSWER


def test_a_completed_stream_is_traced_once_with_its_usage(recorder: CallRecorder) -> None:
    sink = Recorder()
    provider = openai(recorder, sse(*openai_events()))

    list(streaming_provider(provider, model="gpt-configured", trace=sink).stream(turn()))

    assert [item["kind"] for item in sink.records] == ["completion"]
    written = sink.records[0]
    assert written["model"] == "gpt-configured"
    assert written["payload"]["response"]["raw_text"] == ANSWER
    assert written["payload"]["response"]["usage"]["output_tokens"] == OUTPUT_TOKENS
    assert written["payload"]["response"]["stop_reason"] == "stop"


def test_an_interrupted_stream_writes_no_completion_trace(recorder: CallRecorder) -> None:
    """A trace says a call completed; an abandoned one did not, and the run records it."""
    sink = Recorder()
    provider = openai(recorder, sse(*openai_events()))

    deltas = streaming_provider(provider, trace=sink).stream(turn())
    next(deltas)
    deltas.close()

    assert sink.records == []


def test_a_schema_shaped_request_is_run_as_the_ordinary_validated_call(
    recorder: CallRecorder,
) -> None:
    """Streaming answers in prose, so a job that needs a validated object does not stream."""
    transport = make_transport(recorder, json_response(anthropic_body()))
    provider = AnthropicProvider("claude-test-1", api_key="k", transport=transport, env={})
    job: ModelRequest[Verdict] = ModelRequest(
        role="evidence_verifier",
        requirements=turn().requirements,
        instructions="decide",
        inputs=[],
        response_schema=Verdict,
    )

    deltas = list(NativeStream(provider, model="claude-configured").stream(job))

    assert len(deltas) == 1 and deltas[0].final
    assert recorder.last.url.path.endswith("/v1/messages")
    assert "output_config" in recorder.last_payload, "the schema call is the one that was made"


def test_an_error_event_fails_the_stream_rather_than_truncating_it(
    recorder: CallRecorder,
) -> None:
    stream = sse(
        _event(
            "message_start",
            message={
                "id": "m",
                "model": "claude-test-1",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        ),
        _event("error", error={"type": "overloaded_error", "message": "overloaded"}),
    )
    provider = anthropic(recorder, stream)

    with pytest.raises(ProviderResponseError, match="overloaded"):
        list(provider.stream(turn()))


def test_an_http_failure_on_a_stream_is_the_same_provider_error_as_on_a_call(
    recorder: CallRecorder,
) -> None:
    """A refused stream must not look like an empty answer (conversation design SS8)."""
    from research_harness.providers.models.base import ProviderAuthError

    transport = make_transport(recorder, json_response({"error": "no"}, status_code=401))
    provider = OpenAIProvider("gpt-test-1", api_key="k", transport=transport, env={})

    with pytest.raises(ProviderAuthError):
        list(provider.stream(turn()))
