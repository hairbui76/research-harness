"""Local OpenAI-compatible adapter: same contract, minimal backend, no egress."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.providers.models import (
    LocalOpenAICompatibleProvider,
    ModelRequest,
    ProviderResponseError,
    StructuredOutputError,
    normalize_json_schema,
)
from tests.contract.providers.conftest import (
    CACHED_TOKENS,
    CANONICAL_JSON,
    EXPECTED_VERDICT,
    INPUT_TOKENS,
    OUTPUT_TOKENS,
    REASONING_TOKENS,
    CallRecorder,
    Verdict,
    json_response,
    local_body,
    make_transport,
)


def _provider(recorder: CallRecorder, *bodies: dict[str, Any]) -> LocalOpenAICompatibleProvider:
    responses = [json_response(body) for body in bodies] or [json_response(local_body())]
    return LocalOpenAICompatibleProvider(
        "local-test-1", transport=make_transport(recorder, *responses), env={}
    )


def test_posts_to_chat_completions_without_credentials(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    _provider(recorder).complete(model_request)

    sent = recorder.last
    assert str(sent.url) == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in sent.headers


def test_prefers_json_schema_response_format(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = _provider(recorder)

    response = provider.complete(model_request)
    response_format = recorder.last_payload["response_format"]

    assert response.parsed == EXPECTED_VERDICT
    assert provider.structured_output_mode == "json_schema"
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "Verdict"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == normalize_json_schema(
        Verdict.model_json_schema()
    )


def test_falls_back_to_json_object_when_the_server_rejects_the_schema(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    transport = make_transport(
        recorder,
        json_response({"error": {"message": "response_format json_schema not supported"}}, 400),
        json_response(local_body()),
    )
    provider = LocalOpenAICompatibleProvider("local-test-1", transport=transport, env={})

    response = provider.complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert len(recorder.requests) == 2
    assert recorder.payload(0)["response_format"]["type"] == "json_schema"
    retry = recorder.payload(1)
    assert retry["response_format"] == {"type": "json_object"}
    assert "confidence" in retry["messages"][0]["content"]
    assert model_request.instructions in retry["messages"][0]["content"]
    assert provider.structured_output_mode == "json_object"


def test_the_downgrade_sticks_for_later_calls(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    transport = make_transport(
        recorder,
        json_response({"error": {"message": "unsupported"}}, 400),
        json_response(local_body()),
    )
    provider = LocalOpenAICompatibleProvider("local-test-1", transport=transport, env={})

    provider.complete(model_request)
    provider.complete(model_request)

    assert len(recorder.requests) == 3
    assert recorder.payload(2)["response_format"] == {"type": "json_object"}


def test_a_pinned_mode_is_not_downgraded(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    transport = make_transport(recorder, json_response({"error": "no"}, 400))
    provider = LocalOpenAICompatibleProvider(
        "local-test-1", transport=transport, structured_output_mode="json_schema", env={}
    )

    with pytest.raises(ProviderResponseError):
        provider.complete(model_request)
    assert len(recorder.requests) == 1


def test_json_object_mode_can_be_configured_up_front(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = LocalOpenAICompatibleProvider(
        "local-test-1",
        transport=make_transport(recorder, json_response(local_body())),
        structured_output_mode="json_object",
        env={},
    )

    provider.complete(model_request)

    assert recorder.last_payload["response_format"] == {"type": "json_object"}


def test_validation_is_the_same_shared_path_in_fallback_mode(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    """A weaker backend may not get a weaker guarantee."""
    provider = LocalOpenAICompatibleProvider(
        "local-test-1",
        transport=make_transport(recorder, json_response(local_body('{"supported": true}'))),
        structured_output_mode="json_object",
        env={},
    )

    with pytest.raises(StructuredOutputError):
        provider.complete(model_request)


def test_fenced_output_from_a_small_model_still_validates(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    fenced = f"```json\n{CANONICAL_JSON}\n```"

    response = _provider(recorder, local_body(fenced)).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT


def test_content_parts_shape_is_accepted(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = local_body()
    body["choices"][0]["message"]["content"] = [{"type": "text", "text": CANONICAL_JSON}]

    response = _provider(recorder, body).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT


def test_reasoning_content_from_local_servers_is_ignored(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    body = local_body()
    body["choices"][0]["message"]["reasoning_content"] = "step 1: think about it"

    response = _provider(recorder, body).complete(model_request)

    assert response.raw_text == CANONICAL_JSON
    assert "step 1" not in response.model_dump_json()


def test_usage_is_normalized(model_request: ModelRequest[Verdict], recorder: CallRecorder) -> None:
    usage = _provider(recorder).complete(model_request).usage

    assert usage.input_tokens == INPUT_TOKENS
    assert usage.output_tokens == OUTPUT_TOKENS
    assert usage.cached_input_tokens == CACHED_TOKENS
    assert usage.reasoning_tokens == REASONING_TOKENS


def test_an_empty_message_is_a_response_error(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    with pytest.raises(ProviderResponseError, match="empty message"):
        _provider(recorder, local_body("")).complete(model_request)


def test_loopback_endpoints_declare_no_egress(recorder: CallRecorder) -> None:
    egress = _provider(recorder).capabilities().egress

    assert egress.endpoint_host == "localhost"
    assert egress.sends_source_text is False
    assert egress.sends_identifiers is False
    assert "no content leaves" in egress.description


def test_a_remote_base_url_declares_egress_honestly() -> None:
    provider = LocalOpenAICompatibleProvider(
        "local-test-1", base_url="http://gpu-box.example.test:8000/v1", env={}
    )
    egress = provider.capabilities().egress

    assert egress.endpoint_host == "gpu-box.example.test"
    assert egress.sends_source_text is True
    assert egress.sends_identifiers is True
    assert "not loopback" in egress.description
