"""Media inputs reach each provider in the shape its API documents, or not at all.

An attachment that the researcher was told went to the model has to have gone to the
model. These tests read what the adapter actually put on the wire through a fake
transport: the image is a data URL for OpenAI and a base64 `image` block for Anthropic,
the PDF is `input_file` / `document`, the bytes survive the encoding unchanged, and a
provider that declares no media inputs is never handed any (attachments design SS5).
"""

from __future__ import annotations

import base64
from typing import Any

from research_harness.providers.models import (
    AnthropicProvider,
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    OpenAIProvider,
    default_local_capabilities,
)
from research_harness.providers.models.media import MediaPart
from research_harness.providers.models.scripted import (
    ScriptedProvider,
    default_scripted_capabilities,
)
from tests.contract.providers.conftest import (
    API_KEY,
    CANONICAL_ANSWER,
    CallRecorder,
    Verdict,
    anthropic_body,
    assert_no_hidden_reasoning_request,
    json_response,
    make_transport,
    openai_body,
)
from tests.fixtures.attachments import pdf_bytes, png_bytes

IMAGE = MediaPart(media_type="image/png", data=png_bytes(), filename="figure.png")
DOCUMENT = MediaPart(
    media_type="application/pdf", data=pdf_bytes(), filename="paper.pdf", page_count=2
)


def request_with_media() -> ModelRequest[Verdict]:
    """One neutral request carrying prose, an image, and a PDF, in that order."""
    return ModelRequest(
        role="reader",
        requirements=ModelRequirements(
            structured_output=True,
            context_tokens=100_000,
            reasoning="high",
            input_media={"image/png", "application/pdf"},
        ),
        instructions="Describe what the attachments show.",
        inputs=[
            InputEnvelope(object_id="M0007", kind="message", content="what is in these?"),
            InputEnvelope(object_id="SA0001", kind="attachment", content="figure.png", media=IMAGE),
            InputEnvelope(
                object_id="SA0002", kind="attachment", content="paper.pdf", media=DOCUMENT
            ),
        ],
        response_schema=Verdict,
    )


def content_parts(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    entry = payload[key][0]
    parts: list[dict[str, Any]] = list(entry["content"])
    return parts


# -- OpenAI ------------------------------------------------------------------


def test_openai_sends_an_image_as_a_data_url_and_a_pdf_as_a_file(recorder: CallRecorder) -> None:
    provider = OpenAIProvider(
        "gpt-test-1",
        api_key=API_KEY,
        transport=make_transport(recorder, json_response(openai_body())),
        env={},
    )

    provider.complete(request_with_media())
    parts = content_parts(recorder.last_payload, "input")

    assert [part["type"] for part in parts] == ["input_text", "input_image", "input_file"]
    assert parts[1]["image_url"].startswith("data:image/png;base64,")
    assert base64.b64decode(parts[1]["image_url"].split(",", 1)[1]) == png_bytes()
    assert parts[2]["filename"] == "paper.pdf"
    assert base64.b64decode(parts[2]["file_data"].split(",", 1)[1]) == pdf_bytes()
    assert_no_hidden_reasoning_request(recorder.last_payload)


def test_openai_sends_only_the_text_part_when_nothing_is_attached(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = OpenAIProvider(
        "gpt-test-1",
        api_key=API_KEY,
        transport=make_transport(recorder, json_response(openai_body())),
        env={},
    )

    provider.complete(model_request)

    assert [part["type"] for part in content_parts(recorder.last_payload, "input")] == [
        "input_text"
    ]


# -- Anthropic ---------------------------------------------------------------


def test_anthropic_sends_base64_image_and_document_blocks(recorder: CallRecorder) -> None:
    provider = AnthropicProvider(
        "claude-test-1",
        api_key=API_KEY,
        transport=make_transport(recorder, json_response(anthropic_body())),
        env={},
    )

    provider.complete(request_with_media())
    parts = content_parts(recorder.last_payload, "messages")

    assert [part["type"] for part in parts] == ["text", "image", "document"]
    assert parts[1]["source"] == {
        "type": "base64",
        "media_type": "image/png",
        "data": base64.b64encode(png_bytes()).decode("ascii"),
    }
    assert parts[2]["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(parts[2]["source"]["data"]) == pdf_bytes()
    assert parts[2]["title"] == "paper.pdf"
    assert_no_hidden_reasoning_request(recorder.last_payload)


def test_anthropic_sends_only_the_text_block_when_nothing_is_attached(
    model_request: ModelRequest[Verdict], recorder: CallRecorder
) -> None:
    provider = AnthropicProvider(
        "claude-test-1",
        api_key=API_KEY,
        transport=make_transport(recorder, json_response(anthropic_body())),
        env={},
    )

    provider.complete(model_request)

    assert [part["type"] for part in content_parts(recorder.last_payload, "messages")] == ["text"]


# -- what each adapter declares ----------------------------------------------


def test_the_adapters_declare_the_media_they_can_encode() -> None:
    """A declaration a caller trusts: the check refuses what the encoder cannot send."""
    from research_harness.providers.models import (
        default_anthropic_capabilities,
        default_openai_capabilities,
    )

    for capabilities in (default_openai_capabilities(), default_anthropic_capabilities()):
        assert {"image/png", "image/jpeg", "application/pdf"} <= capabilities.input_media
        assert capabilities.vision is True

    # A local server is assumed to read text only, so nothing is offered to it as media;
    # a text attachment reaches it converted instead.
    assert default_local_capabilities().input_media == frozenset()
    assert default_local_capabilities().vision is False


# -- scripted ----------------------------------------------------------------


def test_a_scripted_vision_model_receives_each_attachment_exactly_once() -> None:
    provider = ScriptedProvider(
        [CANONICAL_ANSWER],
        capabilities=default_scripted_capabilities(input_media={"image/png", "application/pdf"}),
    )

    provider.complete(request_with_media())

    assert [part.filename for part in provider.media] == ["figure.png", "paper.pdf"]
    assert provider.media[0].data == png_bytes()
    assert provider.media[1].page_count == 2
    assert provider.capabilities().vision is True


def test_a_scripted_model_is_blind_by_default_and_records_no_media() -> None:
    provider = ScriptedProvider([CANONICAL_ANSWER])

    assert provider.capabilities().input_media == frozenset()
    assert provider.capabilities().vision is False
    assert provider.media == []
