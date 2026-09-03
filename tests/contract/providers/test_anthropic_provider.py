"""Anthropic adapter contract: Messages API wire format, structured output, errors."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.providers.models import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    AnthropicProvider,
    ModelRequest,
    ProviderResponseError,
    normalize_json_schema,
)
from tests.contract.providers.conftest import (
    API_KEY,
    CACHED_TOKENS,
    CANONICAL_JSON,
    EXPECTED_VERDICT,
    INPUT_TOKENS,
    OUTPUT_TOKENS,
    CallRecorder,
    Verdict,
    anthropic_body,
    json_response,
    make_transport,
)


def _provider(recorder: CallRecorder, *bodies: dict[str, Any]) -> AnthropicProvider:
    responses = [json_response(body) for body in bodies] or [json_response(anthropic_body())]
    return AnthropicProvider(
        "claude-test-1", api_key=API_KEY, transport=make_transport(recorder, *responses), env={}
    )


def test_posts_to_messages_with_the_documented_headers(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)

    sent = recorder.last
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    assert sent.headers["x-api-key"] == API_KEY
    assert sent.headers["anthropic-version"] == "2023-06-01"
    assert sent.headers["content-type"] == "application/json"


def test_requests_json_schema_structured_output(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)
    output_format = recorder.last_payload["output_config"]["format"]

    assert output_format["type"] == "json_schema"
    assert output_format["schema"] == normalize_json_schema(Verdict.model_json_schema())
    assert output_format["schema"]["additionalProperties"] is False


def test_sends_instructions_as_system_and_inputs_as_a_user_turn(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)
    payload = recorder.last_payload

    assert payload["model"] == "claude-test-1"
    assert payload["system"] == model_request.instructions
    block = payload["messages"][0]["content"][0]
    assert payload["messages"][0]["role"] == "user"
    assert block["type"] == "text"
    assert "object_id=work:0a1b2c" in block["text"]
    assert payload["max_tokens"] == 2048
    assert payload["temperature"] == 0.0


def test_never_requests_thinking_blocks(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)

    assert "thinking" not in recorder.last_payload


def test_max_tokens_is_always_sent(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    """The Messages API requires `max_tokens`; a missing ceiling must not omit it."""
    request = model_request.model_copy(
        update={
            "requirements": model_request.requirements.model_copy(
                update={"max_output_tokens": None}
            )
        }
    )

    _provider(recorder).complete(request)

    assert recorder.last_payload["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


def test_parses_text_blocks_and_normalizes_usage(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    response = _provider(recorder).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.raw_text == CANONICAL_JSON
    assert response.model == "claude-test-1"
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == INPUT_TOKENS
    assert response.usage.output_tokens == OUTPUT_TOKENS
    assert response.usage.cached_input_tokens == CACHED_TOKENS
    assert response.usage.reasoning_tokens is None


def test_a_refusal_is_a_response_error_not_a_parsed_object(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = anthropic_body(text="", stop_reason="refusal")

    with pytest.raises(ProviderResponseError, match="declined"):
        _provider(recorder, body).complete(model_request)


def test_an_error_shaped_body_is_a_response_error(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "overloaded"}}

    with pytest.raises(ProviderResponseError, match="overloaded"):
        _provider(recorder, body).complete(model_request)


def test_a_reply_without_text_blocks_is_a_response_error(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = anthropic_body()
    body["content"] = [{"type": "tool_use", "id": "toolu_x", "name": "noop", "input": {}}]

    with pytest.raises(ProviderResponseError, match="no text block"):
        _provider(recorder, body).complete(model_request)


def test_declares_its_egress(recorder: CallRecorder) -> None:
    capabilities = _provider(recorder).capabilities()

    assert capabilities.structured_output is True
    assert capabilities.egress.endpoint_host == "api.anthropic.com"
    assert capabilities.egress.sends_source_text is True
    assert capabilities.egress.sends_identifiers is True


def test_base_url_override_is_respected(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = AnthropicProvider(
        "claude-test-1",
        base_url="https://gateway.internal.test/anthropic",
        transport=make_transport(recorder, json_response(anthropic_body())),
        env={},
    )

    provider.complete(model_request)

    assert str(recorder.last.url) == "https://gateway.internal.test/anthropic/v1/messages"
