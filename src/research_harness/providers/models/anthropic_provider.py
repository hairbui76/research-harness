"""Anthropic adapter: the neutral contract over the Messages API.

Wire format, checked against the current Claude API reference:

* `POST {base_url}/v1/messages` with `x-api-key` and `anthropic-version: 2023-06-01`.
  Structured outputs are generally available, so no `anthropic-beta` header is sent; if
  a future mechanism needs one, add it here and nowhere else.
* Structured output uses `output_config.format = {"type": "json_schema", "schema": ...}`
  (the current parameter; the older top-level `output_format` is deprecated). The reply
  then arrives as ordinary `text` blocks containing the JSON object. Forcing a single
  tool call and reading `tool_use.input` remains the documented fallback and is not
  needed while `output_config.format` is available -- it is also unusable on models that
  reject forced `tool_choice`.
* The schema is normalized first: Anthropic's strict subset rejects numeric/string
  constraints and requires `additionalProperties: false`.
* `max_tokens` is required by this API, so a request without `max_output_tokens` falls
  back to `DEFAULT_MAX_OUTPUT_TOKENS` -- a truncated reply would only show up as invalid
  JSON.
* No `thinking` block is ever requested, so no chain-of-thought is returned or stored;
  thinking tokens, when a model uses them, are billed inside `output_tokens` and there
  is no separate reasoning counter to normalize.
* Usage: `input_tokens`, `output_tokens`, and `cache_read_input_tokens` mapped to
  `cached_input_tokens`.
* Media inputs are content blocks beside the rendered text: an image is an `image` block
  and a PDF a `document` block, both with a base64 `source`. The encoding lives in
  `providers/models/media.py`, not here.

Streaming is the same endpoint with `stream: true` and no `output_config`:

* `content_block_delta` carries new text in `delta.text` (a `thinking_delta` is ignored
  along with every other delta type, because no thinking block is ever requested);
* `message_delta` carries the final `delta.stop_reason` and the cumulative
  `usage.output_tokens`; `message_start` carries the input tokens and the model;
* `message_stop` ends the stream, and an `error` event raises rather than truncating
  silently.
* A streamed conversation turn is prose, so no schema is requested; a schema-shaped answer
  goes through `complete()`, which is what `NativeStream` routes it to.
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
    first_mapping,
    iter_mappings,
    render_inputs,
    resolve_api_key,
    usage_from,
)
from research_harness.providers.models.media import (
    DOCUMENT_MEDIA_TYPES,
    IMAGE_MEDIA_TYPES,
    anthropic_media_block,
    media_parts,
)
from research_harness.providers.models.streaming import StreamDelta

PROVIDER_NAME = "anthropic"
DEFAULT_BASE_URL = "https://api.anthropic.com"
MESSAGES_PATH = "/v1/messages"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_CONTEXT_TOKENS = 200_000
NO_INPUTS_PROMPT = "No research inputs were provided; answer from the instructions alone."


def default_anthropic_capabilities(base_url: str = DEFAULT_BASE_URL) -> ProviderCapabilities:
    """Conservative capabilities for a current Claude model; override in config.

    `max_context_tokens` is the smallest window in the current family, so routing never
    over-promises; long-context models are configured with an explicit override.
    """
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
                "them are sent to the Anthropic Messages API."
            ),
        ),
    )


class AnthropicProvider(HttpModelProvider):
    """Runs neutral `ModelRequest`s against the Anthropic Messages API."""

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
            capabilities=capabilities or default_anthropic_capabilities(base_url),
            transport=transport,
        )

    def _execute[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> RawCompletion:
        body = self._post(MESSAGES_PATH, self._build_payload(request, schema_json), self._headers())
        if body.get("type") == "error":
            detail = first_mapping(body.get("error")).get("message", "unspecified error")
            raise ProviderResponseError(
                f"Anthropic returned an error: {detail}", provider=self.name
            )
        stop_reason = body.get("stop_reason")
        if stop_reason == "refusal":
            raise ProviderResponseError(
                "Anthropic declined the request, so no structured output was produced",
                provider=self.name,
            )
        text = _extract_text(body)
        if not text:
            raise ProviderResponseError(
                f"Anthropic response contained no text block (stop_reason={stop_reason!r})",
                provider=self.name,
            )
        usage = first_mapping(body.get("usage"))
        return RawCompletion(
            text=text,
            usage=usage_from(
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cached_input_tokens=usage.get("cache_read_input_tokens"),
            ),
            model=str(body.get("model") or self.settings.model),
            stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        )

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Yield the model's prose as it arrives, then one final delta with the accounting.

        Prose, not structured output: no `output_config` is sent, so the text deltas are
        the answer rather than fragments of a JSON document. Abandoning this iterator
        closes the HTTP response, which is how an interrupted turn stops the call instead
        of draining it (conversation design SS8).
        """
        payload = {**self._build_stream_payload(request), "stream": True}
        index = 0
        model = self.settings.model
        stop_reason: str | None = None
        input_tokens = 0
        cached_tokens: Any = None
        output_tokens = 0
        with self._post_stream(MESSAGES_PATH, payload, self._headers()) as events:
            for name, data in events:
                event = first_mapping(data)
                kind = str(event.get("type") or name)
                if kind == "error":
                    detail = first_mapping(event.get("error")).get("message", "unspecified error")
                    raise ProviderResponseError(
                        f"Anthropic stream failed: {detail}", provider=self.name
                    )
                if kind == "message_start":
                    message = first_mapping(event.get("message"))
                    model = str(message.get("model") or model)
                    usage = first_mapping(message.get("usage"))
                    input_tokens = _count(usage.get("input_tokens"))
                    cached_tokens = usage.get("cache_read_input_tokens")
                    output_tokens = _count(usage.get("output_tokens"))
                elif kind == "content_block_delta":
                    delta = first_mapping(event.get("delta"))
                    text = delta.get("text")
                    # Only `text_delta` is read: no thinking block is requested, and an
                    # `input_json_delta` belongs to a tool call this adapter never makes.
                    if delta.get("type") == "text_delta" and isinstance(text, str) and text:
                        yield StreamDelta(text=text, index=index)
                        index += 1
                elif kind == "message_delta":
                    reason = first_mapping(event.get("delta")).get("stop_reason")
                    if isinstance(reason, str):
                        stop_reason = reason
                    reported = first_mapping(event.get("usage"))
                    if "output_tokens" in reported:
                        output_tokens = _count(reported.get("output_tokens"))
                elif kind == "message_stop":
                    break
        yield StreamDelta(
            text="",
            index=index,
            final=True,
            model=model,
            stop_reason=stop_reason,
            usage=usage_from(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_tokens,
            ),
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        key = self._api_key()
        if key is not None:
            headers["x-api-key"] = key
        return headers

    def _build_stream_payload(self, request: ModelRequest[Any]) -> dict[str, Any]:
        """The Messages body for a streamed turn: the same call, without a schema."""
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": request.requirements.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
            "system": request.instructions,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": render_inputs(request.inputs) or NO_INPUTS_PROMPT,
                        },
                        *(anthropic_media_block(part) for part in media_parts(request.inputs)),
                    ],
                }
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    def _build_payload[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": request.requirements.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
            "system": request.instructions,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": render_inputs(request.inputs) or NO_INPUTS_PROMPT,
                        },
                        # Media follows the rendered text so the attachments arrive in the
                        # order the receipt lists them, after the prose that refers to them.
                        *(anthropic_media_block(part) for part in media_parts(request.inputs)),
                    ],
                }
            ],
            "output_config": {"format": {"type": "json_schema", "schema": schema_json}},
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload


def _count(value: Any) -> int:
    """One usage counter out of loosely-typed streaming JSON, defaulting to zero."""
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _extract_text(body: Mapping[str, Any]) -> str:
    return "".join(
        block["text"]
        for block in iter_mappings(body.get("content"))
        if block.get("type") == "text" and isinstance(block.get("text"), str)
    )
