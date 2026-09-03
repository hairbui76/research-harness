"""OpenAI adapter contract: Responses API wire format, strict schema, usage, errors."""

from __future__ import annotations

import json
from typing import Any

import pytest

from research_harness.providers.models import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    ModelRequest,
    OpenAIProvider,
    ProviderResponseError,
    normalize_json_schema,
)
from tests.contract.providers.conftest import (
    API_KEY,
    CANONICAL_JSON,
    EXPECTED_VERDICT,
    CallRecorder,
    Verdict,
    json_response,
    make_transport,
    openai_body,
)


def _provider(recorder: CallRecorder, *bodies: dict[str, Any]) -> OpenAIProvider:
    responses = [json_response(body) for body in bodies] or [json_response(openai_body())]
    return OpenAIProvider(
        "gpt-test-1", api_key=API_KEY, transport=make_transport(recorder, *responses), env={}
    )


def test_posts_to_the_responses_endpoint_with_a_bearer_token(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)

    sent = recorder.last
    assert str(sent.url) == "https://api.openai.com/v1/responses"
    assert sent.headers["authorization"] == f"Bearer {API_KEY}"
    assert sent.headers["content-type"] == "application/json"


def test_requests_strict_json_schema_output(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)
    text_format = recorder.last_payload["text"]["format"]

    assert text_format["type"] == "json_schema"
    assert text_format["name"] == "Verdict"
    assert text_format["strict"] is True
    assert text_format["schema"] == normalize_json_schema(Verdict.model_json_schema())
    assert text_format["schema"]["additionalProperties"] is False
    assert text_format["schema"]["required"] == list(Verdict.model_fields)


def test_sends_instructions_inputs_and_settings(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)
    payload = recorder.last_payload

    assert payload["model"] == "gpt-test-1"
    assert payload["instructions"] == model_request.instructions
    content = payload["input"][0]["content"][0]
    assert content["type"] == "input_text"
    assert "object_id=work:0a1b2c" in content["text"]
    assert payload["temperature"] == 0.0
    assert payload["max_output_tokens"] == 2048
    assert payload["store"] is False


def test_output_ceiling_falls_back_to_the_shared_default(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    request = model_request.model_copy(
        update={
            "requirements": model_request.requirements.model_copy(
                update={"max_output_tokens": None}
            )
        }
    )

    _provider(recorder).complete(request)

    assert recorder.last_payload["max_output_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


def test_reads_the_output_text_convenience_field_when_present(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = openai_body("{}")
    body["output_text"] = CANONICAL_JSON

    response = _provider(recorder, body).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT


def test_reads_output_message_blocks_and_ignores_reasoning_items(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    response = _provider(recorder, openai_body()).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.raw_text == CANONICAL_JSON
    assert response.stop_reason == "completed"


def test_incomplete_responses_report_the_provider_reason(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = openai_body(status="incomplete")
    body["incomplete_details"] = {"reason": "max_output_tokens"}

    response = _provider(recorder, body).complete(model_request)

    assert response.stop_reason == "max_output_tokens"


def test_a_response_without_text_is_a_response_error(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = openai_body()
    body["output"] = [{"type": "reasoning", "id": "rs_test", "summary": []}]

    with pytest.raises(ProviderResponseError, match="no output text"):
        _provider(recorder, body).complete(model_request)


def test_usage_is_normalized_and_tolerates_missing_details(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = openai_body()
    body["usage"] = {"input_tokens": 7, "output_tokens": 3}

    usage = _provider(recorder, body).complete(model_request).usage

    assert usage.input_tokens == 7
    assert usage.output_tokens == 3
    assert usage.cached_input_tokens is None
    assert usage.reasoning_tokens is None


def test_declares_its_egress(recorder: CallRecorder) -> None:
    capabilities = _provider(recorder).capabilities()

    assert capabilities.structured_output is True
    assert capabilities.egress.endpoint_host == "api.openai.com"
    assert capabilities.egress.sends_source_text is True
    assert capabilities.egress.sends_identifiers is True


def test_no_authorization_header_without_a_configured_key(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = OpenAIProvider(
        "gpt-test-1",
        transport=make_transport(recorder, json_response(openai_body())),
        env={},
    )

    provider.complete(model_request)

    assert "authorization" not in recorder.last.headers


def test_base_url_override_is_respected(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = OpenAIProvider(
        "gpt-test-1",
        base_url="https://gateway.internal.test/openai/v1",
        transport=make_transport(recorder, json_response(openai_body())),
        env={},
    )

    provider.complete(model_request)

    assert str(recorder.last.url) == "https://gateway.internal.test/openai/v1/responses"
    assert provider.capabilities().egress.endpoint_host == "gateway.internal.test"


def test_request_body_is_json(model_request: ModelRequest[Verdict], recorder: CallRecorder) -> None:
    _provider(recorder).complete(model_request)

    assert json.loads(recorder.last.content)["model"] == "gpt-test-1"
