"""Provider-neutral model contract: requests, structured responses, capabilities.

Every semantic job is expressed as a `ModelRequest`: the role that asked for it, the
`ModelRequirements` it needs from a model, instructions, the research inputs it may
read, and the Pydantic schema the answer must satisfy. Adapters translate that into a
vendor wire format and translate the reply back; no vendor concept may appear above
this package (Product SS20.1).

Structured output is handled here, once, for every adapter: an adapter returns raw
text, `complete()` parses it and validates it against the caller's schema, and any
failure raises `StructuredOutputError`. A partially valid object is never returned, so
invalid model output cannot reach staging (ROADMAP Task 4.1).

`ModelResponse` deliberately has no field for hidden chain-of-thought. The harness
neither asks providers for reasoning content nor stores it (Product SS20.5): a response
carries the validated object plus the raw text it was parsed from. Where a rationale is
scientifically useful it belongs in the caller's own response schema as a concise,
model-authored field, so it becomes reviewable canonical state rather than an opaque
trace. The requested `reasoning` level therefore influences *routing* only; it is not
translated into a vendor "give me your thinking" knob.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

logger = logging.getLogger(__name__)

ReasoningLevel = Literal["low", "medium", "high"]

DEFAULT_MAX_OUTPUT_TOKENS = 16000
"""Output ceiling used when a request states none; large enough that a schema-shaped
answer is not truncated into invalid JSON, small enough to stay a non-streaming call."""


# --------------------------------------------------------------------------- errors


class ProviderError(Exception):
    """Root of every provider failure; carries the adapter name for triage."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider


class ProviderAuthError(ProviderError):
    """Credentials missing, rejected, or not permitted for the model (HTTP 401/403)."""


class ProviderRateLimitError(ProviderError):
    """Provider throttled the call (HTTP 429); the caller may retry later."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after_seconds = retry_after_seconds


class ProviderTransportError(ProviderError):
    """Network failure, timeout, or provider-side 5xx: nothing was decided."""


class ProviderResponseError(ProviderError):
    """Provider answered, but not with a usable completion (4xx, refusal, odd body)."""


class StructuredOutputError(ProviderError):
    """Model output was not valid JSON for the requested schema.

    Raised instead of returning a partial object, so unvalidated model text can never
    be mistaken for a research result.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        raw_text: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.raw_text = raw_text


# ----------------------------------------------------------------------- contract


class ModelRequirements(BaseModel):
    """What a job needs from a model, in capability terms (Product SS20.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    structured_output: bool = True
    context_tokens: int = Field(gt=0)
    reasoning: ReasoningLevel
    vision: bool = False
    max_output_tokens: int | None = Field(default=None, gt=0)


class InputEnvelope(BaseModel):
    """One piece of research content plus the object it came from.

    `object_id` is the harness ID of the source object (`None` for content that has no
    canonical object yet); `kind` labels what the content is for the model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str | None = None
    kind: str
    content: str


class ModelRequest[T: BaseModel](BaseModel):
    """A provider-neutral semantic job, reproducible from its fingerprint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    requirements: ModelRequirements
    instructions: str
    inputs: list[InputEnvelope] = Field(default_factory=list)
    response_schema: type[T]
    temperature: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    def fingerprint(self) -> str:
        """sha256 over the canonical JSON of everything that shapes the answer.

        Covers role, instructions, inputs, the normalized response schema, the
        capability requirements and the model settings; it excludes `metadata`, which is
        caller bookkeeping and must not change the identity of the job. The same request
        fingerprints identically on every provider, which is what makes cross-provider
        verification comparable (Product SS20.4).
        """
        payload = {
            "role": self.role,
            "instructions": self.instructions,
            "inputs": [envelope.model_dump(mode="json") for envelope in self.inputs],
            "requirements": self.requirements.model_dump(mode="json"),
            "response_schema": normalize_json_schema(self.response_schema.model_json_schema()),
            "settings": {"temperature": self.temperature},
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def wire_schema(self) -> dict[str, Any]:
        """The response schema, normalized for strict structured-output backends."""
        return normalize_json_schema(self.response_schema.model_json_schema())

    def schema_name(self) -> str:
        """Stable schema name for wire formats that require one."""
        return self.response_schema.__name__


class Usage(BaseModel):
    """Token accounting normalized across providers; `None` means "not reported"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None


class ModelResponse[T: BaseModel](BaseModel):
    """A validated answer plus the reproducibility metadata Product SS20.5 requires.

    There is no hidden-reasoning field by design: `raw_text` is the text the object was
    parsed from, not a chain of thought, and nothing else about the model's internal
    deliberation is requested or kept.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    parsed: T
    raw_text: str
    usage: Usage
    provider: str
    model: str
    latency_ms: int
    request_fingerprint: str
    stop_reason: str | None = None


class EgressDeclaration(BaseModel):
    """What leaves the workstation when this provider is called (Product SS34)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint_host: str
    sends_source_text: bool
    sends_identifiers: bool
    description: str


class ProviderCapabilities(BaseModel):
    """What a configured provider/model can do, and what it discloses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    structured_output: bool
    max_context_tokens: int
    reasoning_levels: set[str]
    vision: bool
    egress: EgressDeclaration


class ProviderSettings(BaseModel):
    """Connection settings for one adapter.

    The API key is a `SecretStr` excluded from `model_dump()`/`model_dump_json()` and
    from `repr()`, so credentials cannot reach logs, traces, or canonical files
    (Product SS34).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    base_url: str
    timeout_seconds: float = 60.0
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)


@dataclass(frozen=True)
class RawCompletion:
    """An adapter's un-validated result, before shared structured-output handling."""

    text: str
    usage: Usage
    model: str
    stop_reason: str | None = None


# ------------------------------------------------------------------------ helpers


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no incidental whitespace, UTF-8 preserved."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$comment",
        "contains",
        "default",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "patternProperties",
        "uniqueItems",
    }
)
"""Validation keywords that strict structured-output backends reject or ignore.

They are dropped from the wire schema only; the caller's Pydantic model still enforces
them when the reply is validated, so nothing is actually relaxed.
"""

_SUBSCHEMA_MAP_KEYWORDS = frozenset({"$defs", "definitions", "properties"})
"""Keywords whose value maps *names* to schemas; the names are never keywords."""

_SUBSCHEMA_LIST_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})

_SUBSCHEMA_KEYWORDS = frozenset(
    {"additionalProperties", "else", "if", "items", "not", "propertyNames", "then"}
)


def normalize_json_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite a Pydantic JSON schema into the strict subset every backend accepts.

    Deterministic and purely structural: every object gets `additionalProperties: false`
    and lists all of its properties in `required`, `oneOf` becomes `anyOf`, and
    unsupported validation keywords are removed. Fields with defaults therefore become
    required on the wire -- the model must emit them, and the caller's own model still
    applies its constraints on validation.
    """
    normalized = _normalize_node(schema)
    if not isinstance(normalized, dict):  # pragma: no cover - top level is always object
        raise TypeError("a JSON schema document must be an object")
    return normalized


def _normalize_node(node: Any) -> Any:
    """Walk only the positions that hold sub-schemas.

    Property and `$defs` names are data, not keywords: a field called `pattern` or
    `default` must survive untouched, and so must `enum`/`const` values.
    """
    if not isinstance(node, Mapping):
        return node

    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in _UNSUPPORTED_SCHEMA_KEYWORDS:
            continue
        target = "anyOf" if key == "oneOf" else key
        if key in _SUBSCHEMA_LIST_KEYWORDS and isinstance(value, list):
            result[target] = [_normalize_node(item) for item in value]
        elif key in _SUBSCHEMA_MAP_KEYWORDS and isinstance(value, Mapping):
            result[target] = {name: _normalize_node(sub) for name, sub in value.items()}
        elif key in _SUBSCHEMA_KEYWORDS and isinstance(value, Mapping):
            result[target] = _normalize_node(value)
        else:
            result[target] = value

    properties = result.get("properties")
    if isinstance(properties, dict):
        result.setdefault("type", "object")
        result["required"] = list(properties)
        result["additionalProperties"] = False
    elif result.get("type") == "object":
        result["additionalProperties"] = False
    return result


def render_inputs(inputs: Sequence[InputEnvelope]) -> str:
    """Render input envelopes into one deterministic, provider-independent block.

    Every adapter sends the same rendering, so a request means the same thing to every
    provider and object IDs stay attached to the text they came from.
    """
    blocks: list[str] = []
    for index, envelope in enumerate(inputs, start=1):
        header = f"[input {index}] kind={envelope.kind}"
        if envelope.object_id is not None:
            header = f"{header} object_id={envelope.object_id}"
        blocks.append(f"{header}\n{envelope.content}")
    return "\n\n".join(blocks)


def parse_structured_output[T: BaseModel](
    text: str, schema: type[T], *, provider: str | None = None
) -> T:
    """Parse model text as JSON and validate it against `schema`, or raise.

    Never returns a partially valid object: either the reply satisfies the schema or a
    `StructuredOutputError` is raised with the raw text attached for debugging.
    """
    candidate = _strip_code_fence(text)
    try:
        data = json.loads(candidate)
    except ValueError as exc:
        raise StructuredOutputError(
            f"model output was not valid JSON: {exc}", provider=provider, raw_text=text
        ) from exc
    if not isinstance(data, dict):
        raise StructuredOutputError(
            f"model output was JSON but not an object (got {type(data).__name__})",
            provider=provider,
            raw_text=text,
        )
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise StructuredOutputError(
            f"model output did not satisfy {schema.__name__}: {exc}",
            provider=provider,
            raw_text=text,
        ) from exc


def _strip_code_fence(text: str) -> str:
    """Remove a single surrounding markdown fence, which local models like to add."""
    stripped = text.strip()
    if not stripped.startswith("```") or not stripped.endswith("```"):
        return stripped
    body = stripped[3:-3]
    newline = body.find("\n")
    if newline == -1:
        return body.strip()
    first_line = body[:newline].strip()
    if first_line and not first_line.isalnum():
        return body.strip()
    return body[newline + 1 :].strip()


def resolve_api_key(
    explicit: str | None,
    env_var: str,
    env: Mapping[str, str] | None = None,
) -> SecretStr | None:
    """Take the explicit key, else the environment variable; never log either."""
    if explicit:
        return SecretStr(explicit)
    source: Mapping[str, str] = os.environ if env is None else env
    value = source.get(env_var)
    return SecretStr(value) if value else None


def usage_from(
    *,
    input_tokens: Any,
    output_tokens: Any,
    cached_input_tokens: Any = None,
    reasoning_tokens: Any = None,
) -> Usage:
    """Build `Usage` from loosely-typed provider JSON, defaulting missing counts."""
    return Usage(
        input_tokens=_as_int(input_tokens) or 0,
        output_tokens=_as_int(output_tokens) or 0,
        cached_input_tokens=_as_int(cached_input_tokens),
        reasoning_tokens=_as_int(reasoning_tokens),
    )


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def first_mapping(values: Any) -> Mapping[str, Any]:
    """Return `values` when it is a JSON object, else an empty mapping."""
    return values if isinstance(values, Mapping) else {}


def iter_mappings(values: Any) -> Iterable[Mapping[str, Any]]:
    """Yield the JSON objects in a list, skipping anything else."""
    if not isinstance(values, list):
        return
    for item in values:
        if isinstance(item, Mapping):
            yield item


@runtime_checkable
class TraceSink(Protocol):
    """Anything that can absorb a disposable provider trace (Product SS19.3).

    Structural on purpose: `providers/` states the shape it needs and never imports the
    writer, so a trace is optional plumbing rather than a dependency.
    `research_harness.privacy.traces.TraceWriter` satisfies it.
    """

    def record(
        self,
        kind: str,
        *,
        provider: str,
        model: str,
        request_fingerprint: str,
        payload: Mapping[str, Any],
    ) -> object:
        """Persist one trace; the return value, if any, is the caller's business."""


def trace_payload[T: BaseModel](
    request: ModelRequest[T], response: ModelResponse[T]
) -> dict[str, Any]:
    """What a completion trace contains: the job, and the answer it produced.

    The source-text fields are exactly the ones `privacy.traces` knows how to redact
    (`inputs[*].content`, `raw_text`), so a redacted trace still carries the shape of the
    call without carrying the corpus.
    """
    return {
        "role": request.role,
        "instructions": request.instructions,
        "inputs": [envelope.model_dump(mode="json") for envelope in request.inputs],
        "requirements": request.requirements.model_dump(mode="json"),
        "temperature": request.temperature,
        "metadata": dict(request.metadata),
        "response": {
            "parsed": response.parsed.model_dump(mode="json"),
            "raw_text": response.raw_text,
            "usage": response.usage.model_dump(mode="json"),
            "stop_reason": response.stop_reason,
            "latency_ms": response.latency_ms,
        },
    }


# ----------------------------------------------------------------------- provider


class ModelProvider(ABC):
    """One model backend behind the neutral contract.

    Subclasses implement `_execute` (wire format, error mapping, usage normalization);
    `complete` adds the shared structured-output validation and reproducibility
    metadata so every provider behaves identically at the seam.
    """

    name: str

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """What this configured provider/model can do and what it sends off-box."""

    @abstractmethod
    def _execute[T: BaseModel](
        self, request: ModelRequest[T], schema_json: dict[str, Any]
    ) -> RawCompletion:
        """Perform the vendor call and return its raw text plus normalized usage."""

    def complete[T: BaseModel](
        self, request: ModelRequest[T], *, trace: TraceSink | None = None
    ) -> ModelResponse[T]:
        """Run the job and return a validated, provenance-carrying response.

        `trace` is optional diagnostics: when a sink is given the call is written to it
        after the answer validates. A trace has no scientific authority and a failure to
        write one never fails the call.
        """
        started = time.perf_counter()
        completion = self._execute(request, request.wire_schema())
        parsed = parse_structured_output(
            completion.text, request.response_schema, provider=self.name
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response = ModelResponse(
            parsed=parsed,
            raw_text=completion.text,
            usage=completion.usage,
            provider=self.name,
            model=completion.model,
            latency_ms=latency_ms,
            request_fingerprint=request.fingerprint(),
            stop_reason=completion.stop_reason,
        )
        if trace is not None:
            self._trace(trace, request, response)
        return response

    def _trace[T: BaseModel](
        self, sink: TraceSink, request: ModelRequest[T], response: ModelResponse[T]
    ) -> None:
        """Best-effort trace; a disposable diagnostic never breaks a completed call."""
        try:
            sink.record(
                "completion",
                provider=self.name,
                model=response.model,
                request_fingerprint=response.request_fingerprint,
                payload=trace_payload(request, response),
            )
        except Exception:
            logger.warning("could not write a %s completion trace", self.name, exc_info=True)
