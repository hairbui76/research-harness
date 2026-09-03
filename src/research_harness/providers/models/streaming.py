"""Streaming on top of the neutral model contract, without touching an adapter.

A conversation turn is prose, not a structured research object, so it is expressed as an
ordinary :class:`~research_harness.providers.models.base.ModelRequest` whose response
schema is :class:`ChatReply` -- one ``text`` field. That keeps every existing guarantee:
the answer is validated before it is used, the request fingerprints like any other job,
and no vendor concept appears above `providers/`.

Streaming itself is a *wrapper*, deliberately:

* :class:`StreamingModelProvider` is the protocol a caller depends on;
* :class:`CompletionStream` turns any non-streaming provider into a one-delta stream, so a
  caller never has to ask whether a backend streams;
* :class:`ChunkedStream` splits a completed answer into several deltas, which is how the
  scripted provider exercises multi-delta streams and interruption offline.

Interruption is the consumer's business: :meth:`StreamingModelProvider.stream` returns an
iterator, and abandoning it stops the stream. Whatever was already yielded has been
persisted by the caller, which is what makes an interrupted answer *incomplete* rather
than lost (conversation design SS8).

Native streaming for the hosted adapters is a follow-up: it belongs inside
`openai_provider.py` / `anthropic_provider.py` as a `stream()` method, and
:func:`streaming_provider` will pick it up the moment it exists, with no change here or in
`conversation/`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from research_harness.providers.models.base import (
    InputEnvelope,
    ModelProvider,
    ModelRequest,
    ModelRequirements,
    TraceSink,
)

__all__ = [
    "DEFAULT_CHUNK_WORDS",
    "ChatReply",
    "ChunkedStream",
    "CompletionStream",
    "StreamDelta",
    "StreamingModelProvider",
    "chat_request",
    "streaming_provider",
]

DEFAULT_CHUNK_WORDS = 8
"""Words per delta when a completed answer is split. Deterministic, so tests can count."""

_WORDS = re.compile(r"\S+\s*")


class ChatReply(BaseModel):
    """The response schema of a conversation turn: the prose the model wrote.

    Mathematics stays inside `text` exactly as the model wrote it, so what the transcript
    stores and what a renderer receives are the same bytes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(default="")


@dataclass(frozen=True, slots=True)
class StreamDelta:
    """One appended chunk of a streamed answer.

    `text` is *new* text, never the accumulated answer: a consumer appends it. The final
    delta carries the model identity and stop reason, which a provider only knows once the
    answer is complete.
    """

    text: str
    index: int = 0
    final: bool = False
    model: str | None = None
    stop_reason: str | None = None


@runtime_checkable
class StreamingModelProvider(Protocol):
    """A backend that can answer a `ModelRequest` incrementally."""

    name: str

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Yield the answer in order. Abandoning the iterator interrupts the call."""


class CompletionStream:
    """The fallback: any provider, as a stream of exactly one delta.

    Nothing is faked. The wrapped provider runs its ordinary `complete()` -- structured
    output validated, usage recorded, trace written -- and the whole answer arrives as one
    chunk. A caller therefore writes one code path, and a backend that cannot stream is
    simply a stream of length one.
    """

    def __init__(
        self,
        provider: ModelProvider,
        *,
        model: str | None = None,
        trace: TraceSink | None = None,
    ) -> None:
        self._provider = provider
        self.name = provider.name
        self._model = model
        self._trace = trace

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"CompletionStream({self.name!r})"

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Run the call and yield its whole answer as one final delta."""
        response = self._provider.complete(request, trace=self._trace)
        text = _reply_text(response.parsed)
        yield StreamDelta(
            text=text,
            index=0,
            final=True,
            model=self._model or response.model,
            stop_reason=response.stop_reason,
        )


class ChunkedStream:
    """A completed answer, split into several deltas.

    This is what makes the scripted provider a *streaming* provider offline: the reply is
    produced by the ordinary contract and then delivered in pieces, so an interruption test
    stops a real iterator part way through instead of mocking one.
    """

    def __init__(
        self,
        provider: ModelProvider,
        *,
        chunk_words: int = DEFAULT_CHUNK_WORDS,
        model: str | None = None,
        trace: TraceSink | None = None,
    ) -> None:
        if chunk_words < 1:
            raise ValueError("chunk_words must be at least 1")
        self._provider = provider
        self._chunk_words = chunk_words
        self.name = provider.name
        self._model = model
        self._trace = trace

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"ChunkedStream({self.name!r}, chunk_words={self._chunk_words})"

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Yield the answer `chunk_words` at a time, the last delta marked final."""
        response = self._provider.complete(request, trace=self._trace)
        model = self._model or response.model
        chunks = split_text(_reply_text(response.parsed), self._chunk_words)
        for index, chunk in enumerate(chunks):
            last = index == len(chunks) - 1
            yield StreamDelta(
                text=chunk,
                index=index,
                final=last,
                model=model if last else None,
                stop_reason=response.stop_reason if last else None,
            )


def split_text(text: str, chunk_words: int) -> list[str]:
    """Split ``text`` into whitespace-preserving chunks of ``chunk_words`` words.

    Concatenating the result reproduces the input exactly, which is the property that lets
    a receipt claim the transcript holds what the model sent.
    """
    words = [match.group(0) for match in _WORDS.finditer(text)]
    if not words:
        return [text] if text else [""]
    return [
        "".join(words[start : start + chunk_words]) for start in range(0, len(words), chunk_words)
    ]


def streaming_provider(
    provider: ModelProvider | StreamingModelProvider,
    *,
    chunk_words: int | None = None,
    model: str | None = None,
    trace: TraceSink | None = None,
) -> StreamingModelProvider:
    """The streaming face of ``provider``: itself when it streams, else a wrapper.

    ``chunk_words`` asks a non-streaming provider to be delivered in pieces; without it the
    whole answer arrives as one delta. ``trace`` is the workspace's trace sink, so a
    conversation turn is recorded under `.research/traces/` like every other model call.
    Either way the caller sees one protocol.
    """
    if not isinstance(provider, ModelProvider):
        return provider
    if hasattr(provider, "stream"):  # pragma: no cover - until an adapter streams natively
        return cast(StreamingModelProvider, provider)
    if chunk_words is not None:
        return ChunkedStream(provider, chunk_words=chunk_words, model=model, trace=trace)
    return CompletionStream(provider, model=model, trace=trace)


def chat_request(
    *,
    instructions: str,
    inputs: Sequence[InputEnvelope] = (),
    context_tokens: int,
    role: str = "conversation",
    temperature: float | None = None,
    metadata: dict[str, str] | None = None,
    vision: bool = False,
) -> ModelRequest[ChatReply]:
    """One conversation turn as a `ModelRequest`.

    `context_tokens` is the budget the pack was assembled under, so routing refuses a model
    whose window cannot hold what was packed rather than truncating it silently.
    """
    return ModelRequest[ChatReply](
        role=role,
        requirements=ModelRequirements(
            structured_output=True,
            context_tokens=max(context_tokens, 1),
            reasoning="medium",
            vision=vision,
        ),
        instructions=instructions,
        inputs=list(inputs),
        response_schema=ChatReply,
        temperature=temperature,
        metadata=dict(metadata or {}),
    )


def _reply_text(parsed: BaseModel) -> str:
    """The prose out of a validated reply, whatever schema the caller used."""
    if isinstance(parsed, ChatReply):
        return parsed.text
    value = getattr(parsed, "text", None)  # pragma: no cover - non-ChatReply schemas
    return value if isinstance(value, str) else parsed.model_dump_json()
