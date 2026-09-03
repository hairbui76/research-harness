"""Media inputs: the binary part of a model request, and how each API expects it.

A `ModelRequest` used to be text only, which is exactly what a research attachment is
not: a page image, a figure, or a PDF has to reach the model as bytes or not at all
(attachments design SS5). `MediaPart` is that byte-carrying half of an `InputEnvelope`,
and this module owns two things and nothing else:

* the **vocabulary** — which media types the harness understands, which class each one
  belongs to, and how a declared type is normalized before anything compares it;
* the **encodings** — the one place that knows an image reaches OpenAI as a data URL
  inside `input_image` and Anthropic as a base64 `image` block, so an adapter never
  invents a second answer.

Nothing here decides *whether* a file may be sent. That is a research question about the
project's egress policy and the attachment's visibility, and it is answered in
`conversation/attachments.py` before a request is built (ADR-018: egress is decided at
provider selection, never inside an adapter).

The module deliberately imports nothing from `providers.models.base`: `base` imports
`MediaPart` from here, so the dependency runs one way and the contract stays importable
without dragging in an HTTP client.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from research_harness.domain.errors import ProviderError

__all__ = [
    "DOCUMENT_MEDIA_TYPES",
    "IMAGE_MEDIA_TYPES",
    "SUPPORTED_MEDIA_TYPES",
    "TEXT_MEDIA_TYPES",
    "MediaClass",
    "MediaPart",
    "UnsupportedMediaError",
    "accepts_media",
    "anthropic_media_block",
    "data_url",
    "media_class",
    "media_parts",
    "normalize_media_type",
    "openai_media_part",
]


class UnsupportedMediaError(ProviderError):
    """An adapter was asked to encode a media type its API does not take."""


class MediaClass(StrEnum):
    """What kind of thing a media type is, for size limits and presentation."""

    IMAGE = "image"
    DOCUMENT = "document"
    TEXT = "text"
    OTHER = "other"


IMAGE_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)
"""Images every current vision model accepts; the harness adds none of its own."""

DOCUMENT_MEDIA_TYPES: frozenset[str] = frozenset({"application/pdf"})

TEXT_MEDIA_TYPES: frozenset[str] = frozenset(
    {"text/plain", "text/markdown", "text/csv", "application/json"}
)
"""Plain text a model reads as text. A text file can therefore be *converted* -- inlined
into the prompt -- when the selected model takes no media at all, which an image cannot."""

SUPPORTED_MEDIA_TYPES: frozenset[str] = IMAGE_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES | TEXT_MEDIA_TYPES

#: Spellings that mean a supported type. `image/jpg` is not a registered media type but is
#: what browsers and file pickers hand over, and refusing it would be pedantry.
_ALIASES: dict[str, str] = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
    "image/x-png": "image/png",
    "text/x-markdown": "text/markdown",
    "text/md": "text/markdown",
    "application/x-pdf": "application/pdf",
    "text/json": "application/json",
}


def normalize_media_type(value: str | None) -> str:
    """Lowercase a declared media type, drop its parameters, and resolve known aliases.

    `Content-Type: image/JPG; charset=binary` and `image/jpeg` must compare equal, or an
    attachment gets refused for the way a browser spelled it.
    """
    if not value:
        return ""
    base = value.split(";", 1)[0].strip().lower()
    return _ALIASES.get(base, base)


def media_class(media_type: str) -> MediaClass:
    """Which class ``media_type`` belongs to; anything unknown is `other`."""
    normalized = normalize_media_type(media_type)
    if normalized in IMAGE_MEDIA_TYPES:
        return MediaClass.IMAGE
    if normalized in DOCUMENT_MEDIA_TYPES:
        return MediaClass.DOCUMENT
    if normalized in TEXT_MEDIA_TYPES:
        return MediaClass.TEXT
    return MediaClass.OTHER


class MediaPart(BaseModel):
    """One binary input travelling with a model request, plus what it is.

    `data` accepts raw bytes or a base64 string and always *holds* bytes; it serializes
    back to base64, so a request fingerprint covers the media deterministically and a
    trace never tries to decode arbitrary bytes as UTF-8.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    media_type: str
    data: bytes
    filename: str
    size_bytes: int = Field(default=0, ge=0)
    page_count: int | None = Field(default=None, ge=1)

    @field_validator("media_type")
    @classmethod
    def _normalize(cls, value: str) -> str:
        normalized = normalize_media_type(value)
        if not normalized:
            raise ValueError("a media part must name its media type")
        return normalized

    @field_validator("data", mode="before")
    @classmethod
    def _decode_base64(cls, value: Any) -> Any:
        """A string is base64, never UTF-8 text: this field carries bytes of any kind."""
        if isinstance(value, str):
            try:
                return base64.b64decode(value, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"media data is not valid base64: {exc}") from exc
        return value

    @field_serializer("data", when_used="json")
    def _encode_base64(self, value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    def model_post_init(self, context: Any, /) -> None:
        """Fill in `size_bytes` from the data, and refuse a size that contradicts it."""
        actual = len(self.data)
        if self.size_bytes == 0 and actual:
            object.__setattr__(self, "size_bytes", actual)
        elif self.size_bytes != actual:
            raise ValueError(
                f"media part {self.filename!r} says {self.size_bytes} bytes but carries {actual}"
            )

    @property
    def media_class(self) -> MediaClass:
        """Image, document, text, or other."""
        return media_class(self.media_type)

    @property
    def base64_data(self) -> str:
        """The payload as base64 ASCII, which is what every current API takes."""
        return base64.b64encode(self.data).decode("ascii")

    def text(self) -> str:
        """A text media part decoded as UTF-8, for inlining it into the prompt.

        Raises `UnsupportedMediaError` for anything that is not a text media type: a PNG
        decoded as text is not a fallback, it is corruption presented as content.
        """
        if self.media_class is not MediaClass.TEXT:
            raise UnsupportedMediaError(
                f"{self.filename}: {self.media_type} is not text and cannot be inlined"
            )
        try:
            return self.data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedMediaError(
                f"{self.filename}: declared {self.media_type} but the bytes are not UTF-8"
            ) from exc


def data_url(part: MediaPart) -> str:
    """`data:<media type>;base64,<payload>` — the form both HTTP APIs accept inline."""
    return f"data:{part.media_type};base64,{part.base64_data}"


def media_parts(inputs: Sequence[Any]) -> list[MediaPart]:
    """Every media part carried by a sequence of input envelopes, in order."""
    return [
        envelope.media
        for envelope in inputs
        if getattr(envelope, "media", None) is not None and isinstance(envelope.media, MediaPart)
    ]


def accepts_media(capabilities: Any, media_type: str) -> bool:
    """Whether a provider's declared capabilities take ``media_type`` as an input.

    Two facts, not one: the type must be listed in `input_media`, and an *image* also
    needs `vision`. Workspace configuration can switch `vision` off for a model that the
    adapter defaults describe as sighted (`CapabilityOverrides.vision`), and that override
    has to mean something here or it would only be honoured by the router.
    """
    normalized = normalize_media_type(media_type)
    declared: Iterable[str] = getattr(capabilities, "input_media", ()) or ()
    if normalized not in set(declared):
        return False
    if media_class(normalized) is MediaClass.IMAGE:
        return bool(getattr(capabilities, "vision", False))
    return True


# -- provider encodings ------------------------------------------------------


def openai_media_part(part: MediaPart) -> dict[str, Any]:
    """One `MediaPart` as a Responses API content part.

    Images travel as `input_image` with a data URL; PDFs as `input_file` with the same
    data URL under `file_data` plus the display filename, which is what the API uses to
    label the document to the model. Text is inlined as `input_text` rather than uploaded,
    because a text attachment is prompt content, not a file the model has to open.
    """
    match part.media_class:
        case MediaClass.IMAGE:
            return {"type": "input_image", "image_url": data_url(part)}
        case MediaClass.DOCUMENT:
            return {
                "type": "input_file",
                "filename": part.filename,
                "file_data": data_url(part),
            }
        case MediaClass.TEXT:
            return {"type": "input_text", "text": _labelled_text(part)}
        case _:
            raise UnsupportedMediaError(
                f"the OpenAI Responses API takes no {part.media_type} input ({part.filename})",
            )


def anthropic_media_block(part: MediaPart) -> dict[str, Any]:
    """One `MediaPart` as a Messages API content block.

    Images are `image` blocks and PDFs are `document` blocks, both with a base64 source;
    text is a plain `text` block for the same reason as above.
    """
    match part.media_class:
        case MediaClass.IMAGE:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": part.media_type,
                    "data": part.base64_data,
                },
            }
        case MediaClass.DOCUMENT:
            return {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": part.media_type,
                    "data": part.base64_data,
                },
                "title": part.filename,
            }
        case MediaClass.TEXT:
            return {"type": "text", "text": _labelled_text(part)}
        case _:
            raise UnsupportedMediaError(
                f"the Anthropic Messages API takes no {part.media_type} input ({part.filename})",
            )


def _labelled_text(part: MediaPart) -> str:
    """Inlined text, headed by the filename so the model can refer to it by name."""
    return f"[attachment {part.filename} ({part.media_type})]\n{part.text()}"
