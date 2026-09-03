"""OpenAI adapter: the neutral contract over the Responses API.

Wire format assumptions, so a future change is easy to spot and correct:

* `POST {base_url}/responses` with `Authorization: Bearer <key>`.
* Structured output is requested with
  `text.format = {"type": "json_schema", "name": ..., "strict": true, "schema": ...}`;
  the schema is normalized to the strict subset first (`normalize_json_schema`).
* Output text is read defensively: the top-level `output_text` convenience string when
  a server provides one, otherwise every `output_text` part of the first `message` item
  in `output`. Reasoning items in `output` are ignored -- the harness never requests
  reasoning content (`include` is not sent) and never stores it.
* Usage is read from `usage.input_tokens` / `usage.output_tokens`, with
  `input_tokens_details.cached_tokens` and `output_tokens_details.reasoning_tokens`
  when present; `reasoning_tokens` is accounting only, not reasoning content.
* `store: false` is sent so a research call is not retained server-side (Product SS34).
* Media inputs are content parts beside the rendered text: an image is `input_image`
  with a `data:` URL, a PDF is `input_file` with `file_data` plus its display filename.
  The encoding lives in `providers/models/media.py`, not here.

Streaming is a second, narrower wire format, and deliberately not the Responses API:

* `POST {base_url}/chat/completions` with `stream: true` and
  `stream_options.include_usage`, the shape every OpenAI-compatible server implements.
* Each `data:` line is one chunk object; new text is `choices[0].delta.content`, the stop
  reason is `choices[0].finish_reason`, and a final chunk with no choices carries `usage`.
  The stream ends at `data: [DONE]`.
* No `response_format` is sent: a streamed conversation turn is prose, and prose arriving
  in order is the point. A schema-shaped answer still goes through `complete()`, which is
  what `NativeStream` routes it to.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import httpx
from pydantic import BaseModel

from research_harness.providers.models._http import HttpModelProvider, endpoint_host
from research_harness.providers.models.base import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    EgressDeclaration,
    ModelRequest,
    ProviderCapabilities,
    ProviderResponseError,
    ProviderSettings,
    RawCompletion,
    Usage,
    first_mapping,
    iter_mappings,
    render_inputs,
    resolve_api_key,
    usage_from,
)
from research_harness.providers.models.media import (
    DOCUMENT_MEDIA_TYPES,
    IMAGE_MEDIA_TYPES,
    MediaClass,
    MediaPart,
    UnsupportedMediaError,
    data_url,
    media_parts,
    openai_media_part,
)
from research_harness.providers.models.streaming import StreamDelta

PROVIDER_NAME = "openai"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
STREAM_PATH = "/chat/completions"
DONE = "[DONE]"
"""The sentinel every OpenAI-compatible chat-completions stream ends with."""
API_KEY_ENV_VAR = "OPENAI_API_KEY"
DEFAULT_MAX_CONTEXT_TOKENS = 400_000
NO_INPUTS_PROMPT = "No research inputs were provided; answer from the instructions alone."


def default_openai_capabilities(base_url: str = DEFAULT_BASE_URL) -> ProviderCapabilities:
    """Capabilities of a current OpenAI model; override per model in workspace config."""
    return ProviderCapabilities(
        structured_output=True,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        reasoning_levels={"low", "medium", "high"},
        vision=True,
        input_media=IMAGE_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES,
        egress=EgressDeclaration(
            endpoint_host=endpoint_host(base_url),
            sends_source_text=True,
            sends_identifiers=True,
            description=(
                "Instructions, rendered research inputs and the object IDs attached to "
                "them are sent to the OpenAI Responses API; the call asks the provider "
                "not to store the response (store=false)."
            ),
        ),
    )


class OpenAIProvider(HttpModelProvider):
    """Runs neutral `ModelRequest`s against the OpenAI Responses API."""

    name = PROVIDER_NAME

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
        capabilities: ProviderCapabilities | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        settings = ProviderSettings(
            provider=PROVIDER_NAME,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout,
            api_key=resolve_api_key(api_key, API_KEY_ENV_VAR, env),
        )
        super().__init__(
            settings,
            capabilities=capabilities or default_openai_capabilities(base_url),
            transport=transport,
        )

    def _execute[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> RawCompletion:
        payload = self._build_payload(request, schema_json)
        body = self._post("/responses", payload, self._headers())
        text = _extract_output_text(body)
        if not text:
            raise ProviderResponseError(
                f"OpenAI response contained no output text (status={body.get('status')!r})",
                provider=self.name,
            )
        usage = first_mapping(body.get("usage"))
        return RawCompletion(
            text=text,
            usage=usage_from(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cached_input_tokens=first_mapping(usage.get("input_tokens_details")).get(
                    "cached_tokens"
                ),
                reasoning_tokens=first_mapping(usage.get("output_tokens_details")).get(
                    "reasoning_tokens"
                ),
            ),
            model=str(body.get("model") or self.settings.model),
            stop_reason=_stop_reason(body),
        )

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Yield the model's prose as it arrives, then one final delta with the accounting.

        Prose, not structured output: no `response_format` is sent, so the deltas are the
        answer rather than fragments of a JSON document. Abandoning this iterator closes
        the HTTP response, which is how an interrupted turn stops the call instead of
        draining it (conversation design SS8).
        """
        payload = self._build_stream_payload(request)
        index = 0
        model = self.settings.model
        stop_reason: str | None = None
        usage = Usage()
        with self._post_stream(STREAM_PATH, payload, self._headers()) as events:
            for _, data in events:
                if data == DONE:
                    break
                chunk = first_mapping(data)
                if not chunk:
                    continue
                model = str(chunk.get("model") or model)
                reported = first_mapping(chunk.get("usage"))
                if reported:
                    usage = _stream_usage(reported)
                for choice in iter_mappings(chunk.get("choices")):
                    finish = choice.get("finish_reason")
                    if isinstance(finish, str):
                        stop_reason = finish
                    text = first_mapping(choice.get("delta")).get("content")
                    if isinstance(text, str) and text:
                        yield StreamDelta(text=text, index=index)
                        index += 1
        yield StreamDelta(
            text="", index=index, final=True, model=model, stop_reason=stop_reason, usage=usage
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self._api_key()
        if key is not None:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def _build_stream_payload(self, request: ModelRequest[Any]) -> dict[str, Any]:
        """The chat-completions body for a streamed turn: prose, with usage reported."""
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": request.instructions},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": render_inputs(request.inputs) or NO_INPUTS_PROMPT,
                        },
                        *(_chat_media_part(part) for part in media_parts(request.inputs)),
                    ],
                },
            ],
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": request.requirements.max_output_tokens
            or DEFAULT_MAX_OUTPUT_TOKENS,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    def _build_payload[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "instructions": request.instructions,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": render_inputs(request.inputs) or NO_INPUTS_PROMPT,
                        },
                        # Media follows the rendered text so the attachments arrive in the
                        # order the receipt lists them, after the prose that refers to them.
                        *(openai_media_part(part) for part in media_parts(request.inputs)),
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name(),
                    "strict": True,
                    "schema": schema_json,
                }
            },
            "store": False,
            "max_output_tokens": request.requirements.max_output_tokens
            or DEFAULT_MAX_OUTPUT_TOKENS,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload


def _chat_media_part(part: MediaPart) -> dict[str, Any]:
    """One `MediaPart` as a chat-completions content part.

    The chat-completions content vocabulary differs from the Responses API's: an image is
    `image_url` with a `{"url": ...}` object, and a PDF is `file` with `file_data`. The
    encoding of the bytes themselves still comes from `media.py`.
    """
    match part.media_class:
        case MediaClass.IMAGE:
            return {"type": "image_url", "image_url": {"url": data_url(part)}}
        case MediaClass.DOCUMENT:
            return {
                "type": "file",
                "file": {"filename": part.filename, "file_data": data_url(part)},
            }
        case MediaClass.TEXT:
            return {"type": "text", "text": part.text()}
        case _:
            raise UnsupportedMediaError(
                f"the OpenAI chat completions API takes no {part.media_type} input "
                f"({part.filename})",
            )


def _stream_usage(usage: Mapping[str, Any]) -> Usage:
    """Chat-completions usage, normalized the way `_execute` normalizes the other spelling."""
    return usage_from(
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        cached_input_tokens=first_mapping(usage.get("prompt_tokens_details")).get("cached_tokens"),
        reasoning_tokens=first_mapping(usage.get("completion_tokens_details")).get(
            "reasoning_tokens"
        ),
    )


def _extract_output_text(body: Mapping[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    parts: list[str] = []
    for item in iter_mappings(body.get("output")):
        if item.get("type") != "message":
            continue
        for block in iter_mappings(item.get("content")):
            if block.get("type") == "output_text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "".join(parts)


def _stop_reason(body: Mapping[str, Any]) -> str | None:
    incomplete = first_mapping(body.get("incomplete_details")).get("reason")
    if isinstance(incomplete, str):
        return incomplete
    status = body.get("status")
    return status if isinstance(status, str) else None
