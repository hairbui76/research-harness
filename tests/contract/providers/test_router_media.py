"""Routing on media: the last line between an attachment and a model that cannot read it.

`attachment.check_send` is the pre-flight — it runs before a person presses send, and it
can name a model that *would* take the file. This is the line behind it: by the time a
request exists, the media it carries is a fact, and the router refuses an entry that does
not accept it rather than letting the adapter discover it while encoding. The two questions
are the same question; the difference is that only one of them can still be answered with
"pick another model".

Configuration is the other half. `CapabilityOverrides` now carries `input_media`, and the
merge re-validates rather than copying, so `vision` and `input_media` cannot drift apart in
a workspace file the way they could when only one of them was configurable.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from research_harness.providers.models.base import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    ProviderCapabilities,
)
from research_harness.providers.models.media import (
    DOCUMENT_MEDIA_TYPES,
    IMAGE_MEDIA_TYPES,
    MediaPart,
)
from research_harness.providers.models.router import (
    ModelRouter,
    NoCapableProviderError,
    ProviderEntry,
    RouterConfig,
    build_router,
    entry_capabilities,
)
from research_harness.providers.models.streaming import ChatReply
from tests.contract.providers.conftest import StubProvider

PNG = MediaPart(media_type="image/png", data=b"\x89PNG-not-really", filename="figure.png")
PDF = MediaPart(media_type="application/pdf", data=b"%PDF-1.7", filename="paper.pdf")


def capabilities(**media: Any) -> ProviderCapabilities:
    """A stub entry's declaration; `input_media` and `vision` stay two spellings of one fact."""
    return ProviderCapabilities(
        structured_output=True,
        max_context_tokens=200_000,
        reasoning_levels={"low", "medium", "high"},
        egress={
            "endpoint_host": "example.test",
            "sends_source_text": True,
            "sends_identifiers": True,
            "description": "test double",
        },
        **media,
    )


def requirements(**overrides: Any) -> ModelRequirements:
    values: dict[str, Any] = {"context_tokens": 1_000, "reasoning": "low"}
    values.update(overrides)
    return ModelRequirements(**values)


def carrying(*parts: MediaPart) -> ModelRequest[ChatReply]:
    """One conversation turn whose inputs carry media, and which declares none."""
    return ModelRequest[ChatReply](
        role="conversation",
        requirements=requirements(),
        instructions="read the attachments",
        inputs=[
            InputEnvelope(kind="message", content="what do these show?"),
            *(
                InputEnvelope(kind="attachment", content=part.filename, media=part)
                for part in parts
            ),
        ],
        response_schema=ChatReply,
    )


def router(*entries: tuple[str, ProviderCapabilities]) -> ModelRouter:
    return ModelRouter(
        [
            ProviderEntry(
                provider=StubProvider(name, declared, model=name, answer={"text": "answered"}),
                model=name,
                priority=index,
            )
            for index, (name, declared) in enumerate(entries)
        ]
    )


# -- the request's own bytes decide -------------------------------------------


def test_a_request_carrying_a_pdf_routes_past_a_model_that_takes_only_images() -> None:
    """The job declared no media; the inputs carry one, and that is what is checked."""
    table = router(
        ("images-only", capabilities(input_media=IMAGE_MEDIA_TYPES)),
        ("reads-documents", capabilities(input_media=IMAGE_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES)),
    )

    entry = table.select(requirements(), "conversation", media=[PDF.media_type, PNG.media_type])

    assert entry.model == "reads-documents"


def test_a_blind_model_is_refused_with_the_media_it_cannot_take_named() -> None:
    table = router(("text-only", capabilities(input_media=frozenset())))

    with pytest.raises(NoCapableProviderError) as raised:
        table.select(requirements(), "conversation", media=["image/png"])

    message = str(raised.value)
    assert "image/png not accepted" in message
    assert "no media input" in message


def test_completing_a_request_reads_the_media_off_its_own_inputs() -> None:
    """`ModelRouter.complete` is where a request that grew an attachment is caught."""
    table = router(("text-only", capabilities(input_media=frozenset())))

    with pytest.raises(NoCapableProviderError, match="application/pdf"):
        table.complete(carrying(PDF))


def test_a_request_with_no_media_still_routes_to_a_text_only_model() -> None:
    table = router(("text-only", capabilities(input_media=frozenset())))

    assert table.complete(carrying()).provider == "text-only"


def test_a_declared_media_need_is_refused_even_when_no_bytes_are_attached_yet() -> None:
    """A job may state what it will send; the router answers before the file exists."""
    table = router(("images-only", capabilities(input_media=IMAGE_MEDIA_TYPES)))

    with pytest.raises(NoCapableProviderError, match="application/pdf"):
        table.select(requirements(input_media={"application/pdf"}), "conversation")


def test_vision_switched_off_in_configuration_refuses_an_image_at_the_router() -> None:
    """`accepts_media` reads both facts, so an override that means "blind" means it here."""
    table = router(("no-vision", capabilities(input_media=IMAGE_MEDIA_TYPES, vision=False)))

    with pytest.raises(NoCapableProviderError, match="image/png"):
        table.select(requirements(), "conversation", media=["image/png"])


# -- configuration: `input_media` as a workspace override ---------------------


def entry(**overrides: Any) -> Any:
    config = RouterConfig.model_validate(
        {
            "providers": [
                {
                    "name": "served",
                    "kind": "local_openai_compatible",
                    "model": "llava-test",
                    "capabilities": overrides,
                }
            ]
        }
    )
    return config.providers[0]


def test_a_workspace_can_declare_the_media_a_served_model_accepts() -> None:
    declared = entry_capabilities(entry(input_media=["image/png", "application/pdf"]))

    assert declared.input_media == frozenset({"image/png", "application/pdf"})
    assert declared.vision is True, "declaring an image type means the model can see"


def test_declaring_only_documents_does_not_make_a_model_sighted() -> None:
    declared = entry_capabilities(entry(input_media=["application/pdf"]))

    assert declared.input_media == frozenset({"application/pdf"})
    assert declared.vision is False


def test_switching_vision_on_still_carries_the_image_types() -> None:
    """The regression `capabilities/attachments.py` used to patch around, fixed at the source."""
    declared = entry_capabilities(entry(vision=True))

    assert declared.vision is True
    assert declared.input_media >= IMAGE_MEDIA_TYPES


def test_switching_vision_off_removes_the_image_types_and_keeps_the_documents() -> None:
    config = RouterConfig.model_validate(
        {
            "providers": [
                {
                    "name": "hosted",
                    "kind": "anthropic",
                    "model": "claude-test-1",
                    "capabilities": {"vision": False},
                }
            ]
        }
    )
    declared = entry_capabilities(config.providers[0])

    assert declared.vision is False
    assert not (declared.input_media & IMAGE_MEDIA_TYPES)
    assert declared.input_media >= DOCUMENT_MEDIA_TYPES


def test_stating_both_spellings_leaves_them_exactly_as_written() -> None:
    declared = entry_capabilities(entry(input_media=["image/png"], vision=False))

    assert declared.input_media == frozenset({"image/png"})
    assert declared.vision is False


def test_a_media_type_the_harness_cannot_encode_is_refused_in_configuration() -> None:
    """A typo becomes a loud configuration error, not a model that silently takes nothing."""
    with pytest.raises(ValidationError, match="unsupported input media"):
        entry(input_media=["image/pmg"])


def test_a_declared_media_type_is_normalized_like_every_other() -> None:
    declared = entry_capabilities(entry(input_media=["IMAGE/JPG", "image/jpeg"]))

    assert declared.input_media == frozenset({"image/jpeg"})


def test_the_declared_media_reaches_a_built_router() -> None:
    config = RouterConfig.model_validate(
        {
            "providers": [
                {
                    "name": "served",
                    "kind": "local_openai_compatible",
                    "model": "llava-test",
                    "capabilities": {"input_media": ["image/png"]},
                }
            ]
        }
    )

    built = build_router(config, env={})

    assert built.entries[0].provider.capabilities().input_media == frozenset({"image/png"})
    assert built.select(requirements(), "conversation", media=["image/png"]).model == "llava-test"
