"""Bounded role contracts: what a semantic role may read, call, produce, and write.

A role is a configuration, not an agent (Product 23): an objective, the input objects it
may read, the capabilities it may call, the schema its answer must satisfy, the model
requirements it needs, and exactly one write scope. Roles hold no memory between calls and
have no authority: everything they produce is a candidate until a researcher accepts it
(ADR-003).

Two rules are enforced here rather than trusted to prompts. First, a role can only read
what its contract lists, which is how the verifier is kept away from the extractor's
rationale: agreement between the two carries information only when the second one did not
see the first one's reasoning (ADR-003, Product 43). Second, `build_request` strips any
``reasoning``/``chain_of_thought``-shaped field out of content handed to the next role, so a
prior role's private deliberation cannot travel forward as if it were a source fact.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from research_harness.domain.base import NonEmptyStr
from research_harness.domain.errors import AuthorityError
from research_harness.providers.models.base import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    canonical_json,
)

__all__ = [
    "HIDDEN_REASONING_FIELDS",
    "HUMAN_ONLY_CAPABILITIES",
    "RATIONALE_MAX_CHARS",
    "InputKind",
    "Rationale",
    "RoleContract",
    "RoleInput",
    "RoleInputContent",
    "RoleRequest",
    "WriteScope",
    "assert_can_read",
    "assert_can_write",
    "assert_capability_allowed",
    "build_request",
    "json_schema_fingerprint",
]


class InputKind(StrEnum):
    """Object kinds a role may be given. A role reads nothing outside its contract."""

    SOURCE_DOCUMENT = "source_document"
    DOCUMENT_BLOCKS = "document_blocks"
    CANDIDATE_EVIDENCE = "candidate_evidence"
    ACCEPTED_EVIDENCE = "accepted_evidence"
    ACCEPTED_CLAIMS = "accepted_claims"
    ACCEPTED_DECISIONS = "accepted_decisions"
    TAXONOMY = "taxonomy"
    RETRIEVAL_RESULTS = "retrieval_results"
    MANUSCRIPT_TEXT = "manuscript_text"
    INTERROGATION_SCHEMA = "interrogation_schema"
    SEARCH_RUN = "search_run"


_INPUT_KIND_ORDER: dict[InputKind, int] = {kind: index for index, kind in enumerate(InputKind)}
"""Declaration order, used to render a request's envelopes deterministically."""


class WriteScope(StrEnum):
    """The single staging area a role may write into.

    There is deliberately no scope for accepted Evidence, Claims, or Decisions. Accepted
    state is reachable only through human review in the capability layer
    (`review.inbox`, `evidence.accept`, ...): no value of this enum can name it, so no
    role contract can be configured to grant it (ADR-003, ADR-007, Product 8.3, 24).
    """

    NONE = "none"
    STAGING_EVIDENCE = "staging_evidence"
    VERIFICATION_RESULT = "verification_result"
    AUDIT_RESULT = "audit_result"
    SYNTHESIS_CANDIDATE = "synthesis_candidate"
    MANUSCRIPT_CANDIDATE = "manuscript_candidate"


RATIONALE_MAX_CHARS = 600

Rationale = Annotated[
    str, StringConstraints(min_length=1, max_length=RATIONALE_MAX_CHARS, strip_whitespace=True)
]
"""A short, model-authored justification that becomes reviewable state.

Bounded on purpose: a concise rationale is persisted with the structured output
(Product 20.5), while hidden chain-of-thought is neither requested nor kept. The cap is
what keeps "rationale" from becoming a place to smuggle a reasoning trace.
"""

HIDDEN_REASONING_FIELDS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "hidden_reasoning",
        "internal_reasoning",
        "reasoning",
        "reasoning_content",
        "scratchpad",
        "thinking",
        "thoughts",
    }
)
"""Field names that never travel from one role to the next.

The harness does not persist hidden reasoning (Product 20.5) and a downstream role must
not treat an upstream role's deliberation as a source fact (Product 43). Anything shaped
like a reasoning trace is dropped from request content and reported to the caller.
"""

HUMAN_ONLY_CAPABILITIES: frozenset[str] = frozenset(
    {
        "decision.*",
        "evidence.accept",
        "evidence.reject",
        "review.accept_batch",
        "review.resolve_conflict",
    }
)
"""Capabilities no role may ever call: acceptance, rejection, review, and Decisions.

`decision.*` names no capability in the Product 22 registry yet; forbidding the whole
namespace ahead of time is the safe direction, because recording a research Decision is a
researcher act (Product 38).
"""


def json_schema_fingerprint(schema: type[BaseModel]) -> str:
    """sha256 (hex) over the canonical JSON of a model's JSON schema.

    Persisted with a role's output so a stored result can be tied to the exact schema it
    was validated against (Product 20.5). Same shape as `ModelRequest.fingerprint()`.
    """
    return hashlib.sha256(canonical_json(schema.model_json_schema()).encode("utf-8")).hexdigest()


RoleInputContent = str | Mapping[str, Any] | Sequence[Any] | BaseModel
"""Content a caller may hand to a role: text, structured data, or a Pydantic object."""


@dataclass(frozen=True, slots=True)
class RoleInput:
    """One object offered to a role, labelled with the kind the contract checks."""

    kind: InputKind
    object_id: str | None = None
    content: RoleInputContent = ""


@dataclass(frozen=True, slots=True)
class RoleRequest[T: BaseModel]:
    """A built request plus the hidden-reasoning fields removed while building it.

    `stripped_fields` is empty in the normal case. When it is not, the caller handed a
    prior role's raw output forward; the request is still usable, and the names say what
    was withheld so the workflow can log it rather than discover it later.
    """

    request: ModelRequest[T]
    stripped_fields: tuple[str, ...] = ()


class RoleContract(BaseModel):
    """The complete, frozen configuration of one bounded semantic role (Product 23)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: NonEmptyStr
    objective: NonEmptyStr
    allowed_inputs: frozenset[InputKind]
    allowed_capabilities: frozenset[str] = frozenset()
    forbidden: frozenset[str] = frozenset()
    output_schema: type[BaseModel]
    write_scope: WriteScope
    requirements: ModelRequirements
    template_version: NonEmptyStr
    system_prompt: NonEmptyStr

    @model_validator(mode="after")
    def _allowed_capabilities_are_not_forbidden(self) -> RoleContract:
        """A capability may not be granted and denied by the same contract."""
        conflicts = sorted(
            capability
            for capability in self.allowed_capabilities
            if _matches_any(capability, self.forbidden)
        )
        if conflicts:
            raise ValueError(f"role {self.name!r} both allows and forbids: {', '.join(conflicts)}")
        return self

    def can_read(self, kind: InputKind) -> bool:
        """True when this role is permitted to be shown that kind of object."""
        return kind in self.allowed_inputs

    def can_write(self, scope: WriteScope) -> bool:
        """True when `scope` is exactly this role's one write scope (never `none`)."""
        return scope is not WriteScope.NONE and scope is self.write_scope

    def is_capability_allowed(self, capability: str) -> bool:
        """True when the capability is granted and not denied; denial always wins."""
        if _matches_any(capability, self.forbidden):
            return False
        return _matches_any(capability, self.allowed_capabilities)

    def output_schema_fingerprint(self) -> str:
        """Fingerprint of this role's output schema, for reproducibility metadata."""
        return json_schema_fingerprint(self.output_schema)


def assert_can_read(contract: RoleContract, kind: InputKind) -> None:
    """Raise `AuthorityError` unless the role may be shown that kind of object."""
    if not contract.can_read(kind):
        allowed = ", ".join(sorted(item.value for item in contract.allowed_inputs)) or "nothing"
        raise AuthorityError(
            f"role {contract.name!r} may not read {kind.value!r}; it may read: {allowed}"
        )


def assert_can_write(contract: RoleContract, scope: WriteScope) -> None:
    """Raise `AuthorityError` unless `scope` is exactly the role's own write scope."""
    if not contract.can_write(scope):
        raise AuthorityError(
            f"role {contract.name!r} may not write {scope.value!r}; "
            f"its only write scope is {contract.write_scope.value!r}"
        )


def assert_capability_allowed(contract: RoleContract, capability: str) -> None:
    """Raise `AuthorityError` unless the role may call that named capability."""
    if _matches_any(capability, contract.forbidden):
        raise AuthorityError(
            f"role {contract.name!r} is forbidden to call capability {capability!r}"
        )
    if not _matches_any(capability, contract.allowed_capabilities):
        allowed = ", ".join(sorted(contract.allowed_capabilities)) or "no capability"
        raise AuthorityError(
            f"role {contract.name!r} may not call capability {capability!r}; it may call: {allowed}"
        )


def build_request(
    contract: RoleContract,
    inputs: Sequence[RoleInput],
    *,
    extra_instructions: str | None = None,
) -> RoleRequest[BaseModel]:
    """Turn a role contract plus its inputs into a provider-neutral `ModelRequest`.

    Every input kind is checked against the contract, hidden-reasoning fields are removed
    from structured content, and envelopes are ordered canonically (by input kind, then
    object id, then call order) so that the same material fingerprints identically no
    matter how the caller ordered it.
    """
    for role_input in inputs:
        assert_can_read(contract, role_input.kind)

    stripped: list[str] = []
    ordered = sorted(
        enumerate(inputs),
        key=lambda pair: (
            _INPUT_KIND_ORDER[pair[1].kind],
            pair[1].object_id or "",
            pair[0],
        ),
    )
    envelopes = [
        InputEnvelope(
            object_id=role_input.object_id,
            kind=role_input.kind.value,
            content=_render_content(role_input.content, stripped),
        )
        for _, role_input in ordered
    ]

    instructions = contract.system_prompt
    if extra_instructions and extra_instructions.strip():
        instructions = f"{instructions}\n\n{extra_instructions.strip()}"

    request: ModelRequest[BaseModel] = ModelRequest(
        role=contract.name,
        requirements=contract.requirements,
        instructions=instructions,
        inputs=envelopes,
        response_schema=contract.output_schema,
        metadata={"role": contract.name, "template_version": contract.template_version},
    )
    return RoleRequest(request=request, stripped_fields=tuple(sorted(set(stripped))))


# ------------------------------------------------------------------------- helpers


def _matches_any(capability: str, patterns: frozenset[str]) -> bool:
    """True when `capability` is listed exactly or matched by a `namespace.*` pattern."""
    if capability in patterns:
        return True
    return any(
        pattern.endswith(".*") and capability.startswith(pattern[:-1]) for pattern in patterns
    )


def _render_content(content: RoleInputContent, stripped: list[str]) -> str:
    """Render input content as text, dropping hidden-reasoning fields on the way."""
    if isinstance(content, str):
        return content
    return canonical_json(_without_hidden_reasoning(content, "", stripped))


def _without_hidden_reasoning(value: Any, path: str, stripped: list[str]) -> Any:
    """Copy JSON-shaped data without any reasoning-trace field, recording what went.

    Paths are relative to the content root, so a top-level key is reported by its bare
    name and a nested one as ``candidates.0.reasoning``.
    """
    if isinstance(value, BaseModel):
        return _without_hidden_reasoning(value.model_dump(mode="json"), path, stripped)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}" if path else name
            if _is_hidden_reasoning(name):
                stripped.append(child)
                continue
            result[name] = _without_hidden_reasoning(item, child, stripped)
        return result
    if isinstance(value, list | tuple):
        return [
            _without_hidden_reasoning(item, f"{path}.{index}" if path else str(index), stripped)
            for index, item in enumerate(value)
        ]
    return value


def _is_hidden_reasoning(name: str) -> bool:
    """Match reasoning-trace field names regardless of spacing, case, or separator."""
    normalized = name.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in HIDDEN_REASONING_FIELDS
