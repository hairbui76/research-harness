"""Media inputs: the vocabulary, the `MediaPart` value, and each API's encoding.

The properties worth pinning are the ones a wrong answer would hide: a declared media type
compares equal however a browser spelled it, bytes survive a JSON round trip unchanged, an
image needs `vision` as well as a listed type, and each adapter's encoder produces the
shape that API documents rather than a shape that merely looks plausible.
"""

from __future__ import annotations

import base64

import pytest
from pydantic import BaseModel, ValidationError

from research_harness.providers.models.base import (
    EgressDeclaration,
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    ProviderCapabilities,
)
from research_harness.providers.models.media import (
    DOCUMENT_MEDIA_TYPES,
    IMAGE_MEDIA_TYPES,
    TEXT_MEDIA_TYPES,
    MediaClass,
    MediaPart,
    UnsupportedMediaError,
    accepts_media,
    anthropic_media_block,
    data_url,
    media_class,
    media_parts,
    normalize_media_type,
    openai_media_part,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x01\x02\x03"
PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"


def png(**overrides: object) -> MediaPart:
    fields: dict[str, object] = {
        "media_type": "image/png",
        "data": PNG_BYTES,
        "filename": "figure.png",
    }
    return MediaPart.model_validate({**fields, **overrides})


def pdf() -> MediaPart:
    return MediaPart(
        media_type="application/pdf", data=PDF_BYTES, filename="paper.pdf", page_count=12
    )


def capabilities(**overrides: object) -> ProviderCapabilities:
    fields: dict[str, object] = {
        "structured_output": True,
        "max_context_tokens": 100_000,
        "reasoning_levels": {"low", "high"},
        "egress": EgressDeclaration(
            endpoint_host="api.example.com",
            sends_source_text=True,
            sends_identifiers=True,
            description="a fake provider",
        ),
    }
    return ProviderCapabilities.model_validate({**fields, **overrides})


# -- the vocabulary ----------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("image/JPG", "image/jpeg"),
        ("image/jpeg; charset=binary", "image/jpeg"),
        ("  APPLICATION/PDF ", "application/pdf"),
        ("text/x-markdown", "text/markdown"),
        ("application/octet-stream", "application/octet-stream"),
        (None, ""),
        ("", ""),
    ],
)
def test_a_declared_media_type_normalizes_to_one_spelling(declared: str, expected: str) -> None:
    assert normalize_media_type(declared) == expected


def test_every_supported_type_has_a_class_and_everything_else_is_other() -> None:
    for media_type in IMAGE_MEDIA_TYPES:
        assert media_class(media_type) is MediaClass.IMAGE
    for media_type in DOCUMENT_MEDIA_TYPES:
        assert media_class(media_type) is MediaClass.DOCUMENT
    for media_type in TEXT_MEDIA_TYPES:
        assert media_class(media_type) is MediaClass.TEXT
    assert media_class("application/x-msdownload") is MediaClass.OTHER


# -- the value ---------------------------------------------------------------


def test_a_media_part_holds_bytes_and_serializes_as_base64() -> None:
    part = png()
    payload = part.model_dump(mode="json")

    assert payload["data"] == base64.b64encode(PNG_BYTES).decode("ascii")
    assert MediaPart.model_validate(payload) == part
    assert MediaPart.model_validate(payload).data == PNG_BYTES


def test_a_base64_string_is_decoded_and_never_read_as_utf8_text() -> None:
    """The bytes of a PNG are not text; a string input is base64 or it is refused."""
    part = png(data=base64.b64encode(PNG_BYTES).decode("ascii"))

    assert part.data == PNG_BYTES
    with pytest.raises(ValidationError, match="not valid base64"):
        png(data="not base64 at all!!")


def test_the_size_is_taken_from_the_data_and_a_contradicting_size_is_refused() -> None:
    assert png().size_bytes == len(PNG_BYTES)
    with pytest.raises(ValidationError, match="carries"):
        png(size_bytes=999)


def test_only_text_media_can_be_read_as_text() -> None:
    text = MediaPart(media_type="text/markdown", data=b"# heading", filename="n.md")
    assert text.text() == "# heading"

    with pytest.raises(UnsupportedMediaError, match="not text"):
        png().text()
    with pytest.raises(UnsupportedMediaError, match="not UTF-8"):
        MediaPart(media_type="text/plain", data=b"\xff\xfe\x00", filename="n.txt").text()


def test_media_travels_inside_an_input_envelope_and_is_found_there() -> None:
    envelopes = [
        InputEnvelope(kind="note", content="see the figure"),
        InputEnvelope(kind="attachment", content="figure.png", media=png()),
    ]
    assert media_parts(envelopes) == [png()]
    assert media_parts([]) == []


class Verdict(BaseModel):
    """Minimal response schema, so a request has something to validate against."""

    ok: bool


def test_the_request_fingerprint_covers_the_media_bytes() -> None:
    """Two requests differing only in the attached bytes are not the same job."""

    def request(part: MediaPart) -> ModelRequest[Verdict]:
        return ModelRequest(
            role="reader",
            requirements=ModelRequirements(context_tokens=1000, reasoning="low"),
            instructions="describe it",
            inputs=[InputEnvelope(kind="attachment", content="figure", media=part)],
            response_schema=Verdict,
        )

    assert request(png()).fingerprint() != request(png(data=b"\x89PNG\r\n\x1a\nzzzz")).fingerprint()
    assert request(png()).fingerprint() == request(png()).fingerprint()


# -- capability agreement ----------------------------------------------------


def test_vision_and_input_media_are_two_spellings_of_one_fact() -> None:
    assert capabilities(vision=True).input_media == IMAGE_MEDIA_TYPES
    assert capabilities(input_media={"image/png"}).vision is True
    assert capabilities(input_media={"application/pdf"}).vision is False
    assert capabilities(vision=False).input_media == frozenset()


def test_an_image_needs_vision_as_well_as_a_listed_type() -> None:
    """A configured `vision: false` override must switch images off, not only routing."""
    sighted = capabilities(vision=True, input_media=IMAGE_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES)
    overridden = sighted.model_copy(update={"vision": False})

    assert accepts_media(sighted, "image/PNG") is True
    assert accepts_media(sighted, "application/pdf") is True
    assert accepts_media(overridden, "image/png") is False
    assert accepts_media(overridden, "application/pdf") is True
    assert accepts_media(capabilities(vision=False), "image/png") is False


def test_requirements_derive_vision_from_the_media_a_job_needs() -> None:
    needs_image = ModelRequirements(context_tokens=1000, reasoning="low", input_media={"image/png"})
    needs_pdf = ModelRequirements(
        context_tokens=1000, reasoning="low", input_media={"application/pdf"}
    )

    assert needs_image.vision is True
    assert needs_pdf.vision is False
    assert ModelRequirements(context_tokens=1000, reasoning="low").input_media == frozenset()


# -- the encodings -----------------------------------------------------------


def test_openai_takes_an_image_as_a_data_url_and_a_pdf_as_a_file() -> None:
    assert openai_media_part(png()) == {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{png().base64_data}",
    }
    assert openai_media_part(pdf()) == {
        "type": "input_file",
        "filename": "paper.pdf",
        "file_data": data_url(pdf()),
    }


def test_anthropic_takes_an_image_and_a_pdf_as_base64_source_blocks() -> None:
    assert anthropic_media_block(png()) == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": png().base64_data},
    }
    assert anthropic_media_block(pdf()) == {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf().base64_data},
        "title": "paper.pdf",
    }


def test_text_is_inlined_by_name_rather_than_uploaded() -> None:
    note = MediaPart(media_type="text/plain", data=b"one line", filename="note.txt")

    assert openai_media_part(note) == {
        "type": "input_text",
        "text": "[attachment note.txt (text/plain)]\none line",
    }
    assert anthropic_media_block(note)["type"] == "text"


def test_an_unencodable_media_type_raises_rather_than_being_dropped() -> None:
    """Silence is the failure mode the design forbids: an adapter refuses instead."""
    binary = MediaPart(media_type="application/zip", data=b"PK\x03\x04", filename="code.zip")

    with pytest.raises(UnsupportedMediaError, match="application/zip"):
        openai_media_part(binary)
    with pytest.raises(UnsupportedMediaError, match="application/zip"):
        anthropic_media_block(binary)
