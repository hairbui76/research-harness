"""Fakes shared by the provider contract tests.

No test here touches a network or a real key: every adapter is driven through
`httpx.MockTransport`, which also lets the tests assert on what would have been sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from research_harness.providers.models import (
    AnthropicProvider,
    InputEnvelope,
    LocalOpenAICompatibleProvider,
    ModelProvider,
    ModelRequest,
    ModelRequirements,
    OpenAIProvider,
    RawCompletion,
    Usage,
    canonical_json,
)

API_KEY = "test-key-do-not-log"

SOURCE_TEXT = (
    "Table 3 reports a mean throughput of 1.4 Gbps for the proposed detector on the "
    "CIC-IDS2017 corpus, measured over five runs."
)


class Verdict(BaseModel):
    """Schema fixture: what a verification role must return.

    `rationale` is the sanctioned place for a model-authored explanation -- it is part
    of the caller's schema, reviewable and persisted as ordinary structured state, not
    a provider chain-of-thought.
    """

    model_config = ConfigDict(extra="forbid")

    supported: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_ids: list[str]


CANONICAL_ANSWER: dict[str, Any] = {
    "supported": True,
    "confidence": 0.82,
    "rationale": "Table 3 states the throughput directly.",
    "evidence_ids": ["ev-001", "ev-002"],
}
CANONICAL_JSON = json.dumps(CANONICAL_ANSWER)
EXPECTED_VERDICT = Verdict.model_validate(CANONICAL_ANSWER)

INPUT_TOKENS = 1200
OUTPUT_TOKENS = 95
CACHED_TOKENS = 400
REASONING_TOKENS = 64


@pytest.fixture
def model_request() -> ModelRequest[Verdict]:
    """One neutral request, reused across every provider."""
    return ModelRequest(
        role="evidence_verifier",
        requirements=ModelRequirements(
            structured_output=True,
            context_tokens=100_000,
            reasoning="high",
            vision=False,
            max_output_tokens=2048,
        ),
        instructions="Decide whether the source supports the candidate evidence.",
        inputs=[
            InputEnvelope(object_id="work:0a1b2c", kind="source_text", content=SOURCE_TEXT),
            InputEnvelope(object_id=None, kind="candidate_evidence", content="throughput=1.4 Gbps"),
        ],
        response_schema=Verdict,
        temperature=0.0,
        metadata={"workflow": "verify-evidence", "run": "42"},
    )


# ------------------------------------------------------------------ fake transports


@dataclass
class CallRecorder:
    """Captures what an adapter put on the wire."""

    requests: list[httpx.Request] = field(default_factory=list)

    def record(self, request: httpx.Request) -> None:
        self.requests.append(request)

    @property
    def last(self) -> httpx.Request:
        assert self.requests, "no request was sent"
        return self.requests[-1]

    def payload(self, index: int = -1) -> dict[str, Any]:
        body = json.loads(self.requests[index].content)
        assert isinstance(body, dict)
        return body

    @property
    def last_payload(self) -> dict[str, Any]:
        return self.payload()


@pytest.fixture
def recorder() -> CallRecorder:
    return CallRecorder()


def json_response(body: Mapping[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=dict(body))


def make_transport(
    recorder: CallRecorder, *responses: httpx.Response | Exception
) -> httpx.MockTransport:
    """Fake transport replying with `responses` in order; the last one repeats."""
    assert responses, "at least one canned response is required"

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.record(request)
        reply = responses[min(len(recorder.requests) - 1, len(responses) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return httpx.MockTransport(handler)


# ------------------------------------------------------------- provider fake bodies


def openai_body(text: str = CANONICAL_JSON, *, status: str = "completed") -> dict[str, Any]:
    """A realistic Responses API reply, including a reasoning item we must ignore."""
    return {
        "id": "resp_test",
        "object": "response",
        "model": "gpt-test-1",
        "status": status,
        "output": [
            {"type": "reasoning", "id": "rs_test", "summary": []},
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            },
        ],
        "usage": {
            "input_tokens": INPUT_TOKENS,
            "input_tokens_details": {"cached_tokens": CACHED_TOKENS},
            "output_tokens": OUTPUT_TOKENS,
            "output_tokens_details": {"reasoning_tokens": REASONING_TOKENS},
            "total_tokens": INPUT_TOKENS + OUTPUT_TOKENS,
        },
    }


def anthropic_body(text: str = CANONICAL_JSON, *, stop_reason: str = "end_turn") -> dict[str, Any]:
    """A realistic Messages API reply."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-test-1",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": INPUT_TOKENS,
            "output_tokens": OUTPUT_TOKENS,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": CACHED_TOKENS,
        },
    }


def local_body(text: str = CANONICAL_JSON, *, finish_reason: str = "stop") -> dict[str, Any]:
    """A realistic OpenAI-compatible chat/completions reply."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "local-test-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": INPUT_TOKENS,
            "completion_tokens": OUTPUT_TOKENS,
            "prompt_tokens_details": {"cached_tokens": CACHED_TOKENS},
            "completion_tokens_details": {"reasoning_tokens": REASONING_TOKENS},
        },
    }


# ---------------------------------------------------------------- provider matrix


@dataclass(frozen=True)
class ProviderCase:
    """One adapter plus the fake wire traffic it understands."""

    id: str
    build: Callable[[httpx.BaseTransport], ModelProvider]
    body: Callable[[str], dict[str, Any]]
    provider_name: str
    model: str
    path: str
    auth_header: str
    reasoning_tokens: int | None


def build_openai(transport: httpx.BaseTransport) -> ModelProvider:
    return OpenAIProvider("gpt-test-1", api_key=API_KEY, transport=transport, env={})


def build_anthropic(transport: httpx.BaseTransport) -> ModelProvider:
    return AnthropicProvider("claude-test-1", api_key=API_KEY, transport=transport, env={})


def build_local(transport: httpx.BaseTransport) -> ModelProvider:
    return LocalOpenAICompatibleProvider(
        "local-test-1", api_key=API_KEY, transport=transport, env={}
    )


PROVIDER_CASES: tuple[ProviderCase, ...] = (
    ProviderCase(
        id="openai",
        build=build_openai,
        body=lambda text: openai_body(text),
        provider_name="openai",
        model="gpt-test-1",
        path="/v1/responses",
        auth_header="authorization",
        reasoning_tokens=REASONING_TOKENS,
    ),
    ProviderCase(
        id="anthropic",
        build=build_anthropic,
        body=lambda text: anthropic_body(text),
        provider_name="anthropic",
        model="claude-test-1",
        path="/v1/messages",
        auth_header="x-api-key",
        # Anthropic bills thinking inside output_tokens and reports no separate counter.
        reasoning_tokens=None,
    ),
    ProviderCase(
        id="local",
        build=build_local,
        body=lambda text: local_body(text),
        provider_name="local",
        model="local-test-1",
        path="/v1/chat/completions",
        auth_header="authorization",
        reasoning_tokens=REASONING_TOKENS,
    ),
)


@pytest.fixture(params=PROVIDER_CASES, ids=[case.id for case in PROVIDER_CASES])
def provider_case(request: pytest.FixtureRequest) -> ProviderCase:
    case = request.param
    assert isinstance(case, ProviderCase)
    return case


# --------------------------------------------------------------------- stub provider


class StubProvider(ModelProvider):
    """In-memory provider for routing tests: declared capabilities, canned answer."""

    def __init__(
        self,
        name: str,
        capabilities: Any,
        *,
        model: str = "stub-model",
        answer: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = name
        self._capabilities = capabilities
        self._model = model
        self._answer = dict(answer or CANONICAL_ANSWER)
        self.calls: list[ModelRequest[Any]] = []

    def capabilities(self) -> Any:
        return self._capabilities

    def _execute(self, request: ModelRequest[Any], schema_json: dict[str, Any]) -> RawCompletion:
        self.calls.append(request)
        return RawCompletion(
            text=json.dumps(self._answer),
            usage=Usage(input_tokens=1, output_tokens=1),
            model=self._model,
            stop_reason="stop",
        )


# ------------------------------------------------------------------------- assertions

_HIDDEN_REASONING_KEYS = ("include", "thinking", "reasoning", "reasoning_effort")
_HIDDEN_REASONING_MARKERS = ("encrypted_content", "reasoning_content", "chain_of_thought")


def assert_no_hidden_reasoning_request(payload: Mapping[str, Any]) -> None:
    """The harness must never ask a provider for its hidden chain-of-thought."""
    for key in _HIDDEN_REASONING_KEYS:
        assert key not in payload, f"request asked for provider reasoning via {key!r}"
    serialized = canonical_json(payload)
    for marker in _HIDDEN_REASONING_MARKERS:
        assert marker not in serialized, f"request mentioned {marker!r}"


def assert_inputs_present(serialized: str, inputs: Sequence[InputEnvelope]) -> None:
    """Every input envelope reaches the provider with its object ID attached."""
    for envelope in inputs:
        assert envelope.content in serialized
        if envelope.object_id is not None:
            assert envelope.object_id in serialized
