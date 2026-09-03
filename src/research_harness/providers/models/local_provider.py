"""Local adapter for OpenAI-compatible servers (Ollama, vLLM, LM Studio, llama.cpp).

Real interface, minimal backend (ROADMAP Task 4.4): the same contract as the hosted
adapters, so a role can move on-box without any role or schema change.

Wire format assumptions:

* `POST {base_url}/chat/completions`, the endpoint every OpenAI-compatible server
  exposes; `Authorization: Bearer` only when a key is configured (most local servers
  need none).
* Structured output prefers `response_format = {"type": "json_schema", "json_schema":
  {"name", "strict", "schema"}}`. Servers that reject it answer 4xx, and the adapter
  falls back once to `{"type": "json_object"}` with the schema written into the system
  prompt, then remembers the downgrade for the rest of the session. Validation is the
  shared path either way, so a weaker backend cannot produce a weaker guarantee.
* Usage is read from `usage.prompt_tokens` / `usage.completion_tokens`, with
  `prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens`
  when the server reports them.
* Some local servers emit `message.reasoning_content`. It is deliberately ignored: the
  harness does not read or persist hidden chain-of-thought (Product SS20.5).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from research_harness.providers.models._http import HttpModelProvider, endpoint_host
from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelRequest,
    ProviderCapabilities,
    ProviderResponseError,
    ProviderSettings,
    RawCompletion,
    canonical_json,
    first_mapping,
    iter_mappings,
    render_inputs,
    resolve_api_key,
    usage_from,
)

StructuredOutputMode = Literal["auto", "json_schema", "json_object"]

PROVIDER_NAME = "local"
DEFAULT_BASE_URL = "http://localhost:11434/v1"
API_KEY_ENV_VAR = "LOCAL_MODEL_API_KEY"
DEFAULT_MAX_CONTEXT_TOKENS = 32_768
NO_INPUTS_PROMPT = "No research inputs were provided; answer from the instructions alone."
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK_HOSTS or host.endswith(".local")


def default_local_capabilities(base_url: str = DEFAULT_BASE_URL) -> ProviderCapabilities:
    """Capabilities of a small local model; override per served model in config."""
    host = endpoint_host(base_url)
    loopback = _is_loopback(host)
    return ProviderCapabilities(
        structured_output=True,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        reasoning_levels={"low", "medium"},
        vision=False,
        egress=EgressDeclaration(
            endpoint_host=host,
            sends_source_text=not loopback,
            sends_identifiers=not loopback,
            description=(
                f"Requests go to the local model server at {host}; no content leaves "
                "the workstation."
                if loopback
                else f"Configured endpoint {host} is not loopback: research content and "
                "object IDs leave this workstation."
            ),
        ),
    )


class LocalOpenAICompatibleProvider(HttpModelProvider):
    """Runs neutral `ModelRequest`s against a local OpenAI-compatible server."""

    name = PROVIDER_NAME

    def __init__(
        self,
        model: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
        capabilities: ProviderCapabilities | None = None,
        structured_output_mode: StructuredOutputMode = "auto",
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
            capabilities=capabilities or default_local_capabilities(base_url),
            transport=transport,
        )
        self._configured_mode: StructuredOutputMode = structured_output_mode
        self._mode: Literal["json_schema", "json_object"] = (
            "json_object" if structured_output_mode == "json_object" else "json_schema"
        )

    @property
    def structured_output_mode(self) -> Literal["json_schema", "json_object"]:
        """Mechanism in use; `auto` downgrades to `json_object` after one rejection."""
        return self._mode

    def _execute[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> RawCompletion:
        try:
            body = self._post(
                "/chat/completions",
                self._build_payload(request, schema_json, self._mode),
                self._headers(),
            )
        except ProviderResponseError:
            if self._configured_mode != "auto" or self._mode != "json_schema":
                raise
            self._mode = "json_object"
            body = self._post(
                "/chat/completions",
                self._build_payload(request, schema_json, "json_object"),
                self._headers(),
            )
        return self._read_completion(body)

    def _read_completion(self, body: Mapping[str, Any]) -> RawCompletion:
        choices = list(iter_mappings(body.get("choices")))
        if not choices:
            raise ProviderResponseError("local server returned no choices", provider=self.name)
        message = first_mapping(choices[0].get("message"))
        text = _content_text(message.get("content"))
        if not text:
            raise ProviderResponseError(
                f"local server returned an empty message "
                f"(finish_reason={choices[0].get('finish_reason')!r})",
                provider=self.name,
            )
        usage = first_mapping(body.get("usage"))
        finish_reason = choices[0].get("finish_reason")
        return RawCompletion(
            text=text,
            usage=usage_from(
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                cached_input_tokens=first_mapping(usage.get("prompt_tokens_details")).get(
                    "cached_tokens"
                ),
                reasoning_tokens=first_mapping(usage.get("completion_tokens_details")).get(
                    "reasoning_tokens"
                ),
            ),
            model=str(body.get("model") or self.settings.model),
            stop_reason=finish_reason if isinstance(finish_reason, str) else None,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        key = self._api_key()
        if key is not None:
            headers["authorization"] = f"Bearer {key}"
        return headers

    def _build_payload[T: BaseModel](
        self,
        request: ModelRequest[T],
        schema_json: dict[str, Any],
        mode: Literal["json_schema", "json_object"],
    ) -> dict[str, Any]:
        system = request.instructions
        if mode == "json_object":
            system = (
                f"{request.instructions}\n\n"
                "Reply with one JSON object and nothing else. It must validate against "
                f"this JSON Schema:\n{canonical_json(schema_json)}"
            )
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": render_inputs(request.inputs) or NO_INPUTS_PROMPT},
            ],
        }
        if mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name(),
                    "strict": True,
                    "schema": schema_json,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.requirements.max_output_tokens is not None:
            payload["max_tokens"] = request.requirements.max_output_tokens
        return payload


def _content_text(content: Any) -> str:
    """Read message content, accepting both the string and the content-parts shapes."""
    if isinstance(content, str):
        return content
    return "".join(
        part["text"]
        for part in iter_mappings(content)
        if part.get("type") in {"text", "output_text"} and isinstance(part.get("text"), str)
    )
