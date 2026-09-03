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
"""

from __future__ import annotations

from collections.abc import Mapping
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

PROVIDER_NAME = "anthropic"
DEFAULT_BASE_URL = "https://api.anthropic.com"
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
        body = self._post(
            "/v1/messages", self._build_payload(request, schema_json), self._headers()
        )
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

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        key = self._api_key()
        if key is not None:
            headers["x-api-key"] = key
        return headers

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
                        }
                    ],
                }
            ],
            "output_config": {"format": {"type": "json_schema", "schema": schema_json}},
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload


def _extract_text(body: Mapping[str, Any]) -> str:
    return "".join(
        block["text"]
        for block in iter_mappings(body.get("content"))
        if block.get("type") == "text" and isinstance(block.get("text"), str)
    )
