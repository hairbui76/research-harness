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

PROVIDER_NAME = "openai"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
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

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self._api_key()
        if key is not None:
            headers["authorization"] = f"Bearer {key}"
        return headers

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
                        }
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
