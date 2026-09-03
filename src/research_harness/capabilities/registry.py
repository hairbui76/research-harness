"""The named capability registry: discovery, permissions, and one typed invocation path.

Product 22 says clients and agent hosts call *named capabilities* rather than
implementation details, and that capabilities enforce permissions and state transitions
server-side. This module is that enforcement point. It adds discovery and a permission
model on top of the Phase 1 handlers; it is deliberately not a second business-logic layer
(ADR-004), so every spec here points at a handler that already exists.

    registry = build_default_registry()
    response = registry.invoke("claim.audit", ctx, payload, principal=Principal.human())

A capability whose implementation does not exist yet is *not* registered with a stub. It is
recorded as :meth:`CapabilityRegistry.planned`, so `describe()` tells a host the difference
between "this name will refuse you" and "this name is not built yet".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import (
    AcceptDecisionRequest,
    AcceptEvidenceRequest,
    AddArtifactRequest,
    AddNoteRequest,
    AttachManuscriptAnchorRequest,
    AuditClaimRequest,
    CreateClaimRequest,
    CreateQuestionRequest,
    InitProjectResult,
    MutationResult,
    OverrideClaimStrengthRequest,
    PromoteNoteRequest,
    PutMatrixRequest,
    PutTaxonomyRequest,
    RecordSearchRunRequest,
    RegisterWorkRequest,
    RejectEvidenceRequest,
    StoreParsedDocumentRequest,
    UpdateQuestionRequest,
)
from research_harness.capabilities.handlers import CAPABILITY_HANDLERS
from research_harness.capabilities.permissions import (
    HUMAN_AUTHORITY,
    CapabilityNotFound,
    InvalidRequest,
    Permission,
    PermissionDenied,
    Principal,
)
from research_harness.domain.enums import ReviewPolicy
from research_harness.domain.research import ResearchEvent

__all__ = [
    "CapabilityDescriptor",
    "CapabilityRegistry",
    "CapabilitySpec",
    "InitProjectResponse",
    "MutationResponse",
    "PlannedCapability",
    "StaleBody",
    "ValidationBody",
    "build_default_registry",
    "mutation_spec",
]

logger = logging.getLogger(__name__)


# -- transport-neutral response envelopes ------------------------------------


class ValidationBody(BaseModel):
    """The validation result Product 36 requires of every mutation, in JSON form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool = True
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class StaleBody(BaseModel):
    """One object the mutation made stale, and why (Product 37, ADR-008)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str
    reason: str
    priority: int
    source_change: str


class MutationResponse(BaseModel):
    """What one accepted-state mutation did, identically over every transport.

    This is the JSON face of :class:`~research_harness.capabilities.dto.MutationResult`:
    the four things Product 36 requires of a mutation, plus the objects it wrote.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str
    objects: tuple[str, ...] = ()
    event: ResearchEvent
    diff: dict[str, Any] = Field(default_factory=dict)
    stale: tuple[StaleBody, ...] = ()
    validation: ValidationBody = Field(default_factory=ValidationBody)

    @classmethod
    def of(cls, result: MutationResult) -> MutationResponse:
        """Render a handler's :class:`MutationResult` as the wire response."""
        return cls(
            capability=result.capability,
            objects=result.objects,
            event=result.event,
            diff=result.diff.as_dict(),
            stale=tuple(
                StaleBody(
                    object_id=mark.object_id,
                    reason=mark.reason,
                    priority=int(mark.priority),
                    source_change=mark.source_change,
                )
                for mark in result.stale
            ),
            validation=ValidationBody(
                ok=result.validation.ok,
                errors=result.validation.errors,
                warnings=result.validation.warnings,
            ),
        )


class InitProjectResponse(BaseModel):
    """What `project.init` created. Initialization changes no research object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path
    name: str
    policy: ReviewPolicy
    validation: ValidationBody = Field(default_factory=ValidationBody)

    @classmethod
    def of(cls, result: InitProjectResult) -> InitProjectResponse:
        """Render the handler's result as the wire response."""
        return cls(
            root=result.root,
            name=result.name,
            policy=result.policy,
            validation=ValidationBody(
                ok=result.validation.ok,
                errors=result.validation.errors,
                warnings=result.validation.warnings,
            ),
        )


# -- specs -------------------------------------------------------------------

CapabilityHandler = Callable[[CapabilityContext, Any], BaseModel]


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """One named capability: what it does, who may call it, and what it takes and returns."""

    name: str
    """The Product 22 name. Hosts depend on it, so it is an expensive commitment."""

    summary: str
    permission: Permission
    scientific_semantics: str
    """One sentence naming what this capability may change, in scientific terms."""

    request_model: type[BaseModel]
    response_model: type[BaseModel]
    handler: CapabilityHandler
    human_only: bool = False
    """True when the call needs the researcher even though its permission would not say so."""

    long_running: bool = False
    """True when the call returns a durable run id and finishes in the background."""

    def descriptor(self) -> CapabilityDescriptor:
        """The JSON-able description a host reads before calling."""
        return CapabilityDescriptor(
            name=self.name,
            summary=self.summary,
            permission=self.permission,
            scientific_semantics=self.scientific_semantics,
            request_schema=self.request_model.model_json_schema(),
            response_schema=self.response_model.model_json_schema(mode="serialization"),
            human_only=self.human_only or self.permission in {Permission.MUTATE, Permission.ADMIN},
            long_running=self.long_running,
        )

    def validate_request(self, request: BaseModel | Mapping[str, Any]) -> BaseModel:
        """Coerce ``request`` into this capability's request model, or refuse it."""
        if isinstance(request, self.request_model):
            return request
        payload = request.model_dump() if isinstance(request, BaseModel) else dict(request)
        try:
            return self.request_model.model_validate(payload)
        except ValidationError as exc:
            raise InvalidRequest(f"{self.name}: {_validation_detail(exc)}") from exc


class CapabilityDescriptor(BaseModel):
    """One capability as a host sees it: name, authority, and both JSON schemas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    summary: str
    permission: Permission
    scientific_semantics: str
    request_schema: dict[str, Any]
    response_schema: dict[str, Any]
    human_only: bool
    long_running: bool


class PlannedCapability(BaseModel):
    """A Product 22 name with no implementation in this build, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    reason: str


class CapabilityRegistry:
    """Named capabilities, their permissions, and the one path that invokes them."""

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        self._planned: dict[str, str] = {}

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)

    def __iter__(self) -> Iterator[CapabilitySpec]:
        return iter(self._specs[name] for name in self.names())

    def register(self, spec: CapabilitySpec) -> CapabilitySpec:
        """Add a capability; a duplicate name is a wiring bug, not a silent override."""
        if spec.name in self._specs:
            raise ValueError(f"capability {spec.name!r} is already registered")
        self._specs[spec.name] = spec
        self._planned.pop(spec.name, None)
        return spec

    def register_all(self, specs: Iterable[CapabilitySpec]) -> None:
        """Register several capabilities in order."""
        for spec in specs:
            self.register(spec)

    def plan(self, name: str, reason: str) -> None:
        """Record a Product 22 name that has no implementation here yet."""
        if name in self._specs:
            raise ValueError(f"{name} is registered; it cannot also be planned")
        self._planned[name] = reason

    def get(self, name: str) -> CapabilitySpec:
        """The spec for ``name``; raises :class:`CapabilityNotFound` when there is none."""
        spec = self._specs.get(name)
        if spec is not None:
            return spec
        reason = self._planned.get(name)
        detail = "" if reason is None else f"; it is planned but not implemented: {reason}"
        raise CapabilityNotFound(f"no capability named {name!r}{detail}")

    def names(self) -> tuple[str, ...]:
        """Every registered capability name, sorted."""
        return tuple(sorted(self._specs))

    def planned(self) -> tuple[PlannedCapability, ...]:
        """Product 22 names this build does not implement, with the reason, sorted."""
        return tuple(
            PlannedCapability(name=name, reason=reason)
            for name, reason in sorted(self._planned.items())
        )

    def describe(self) -> list[CapabilityDescriptor]:
        """Every capability as a host sees it, in name order."""
        return [self._specs[name].descriptor() for name in self.names()]

    def invoke(
        self,
        name: str,
        ctx: CapabilityContext,
        request: BaseModel | Mapping[str, Any],
        *,
        principal: Principal,
    ) -> BaseModel:
        """Authorize, validate, run, and return one capability's typed response.

        Every transport goes through exactly this method, so the permission check and the
        request validation cannot be skipped by reaching a handler another way (ADR-004).
        """
        spec = self.get(name)
        principal.authorize(name, spec.permission, human_only=spec.human_only)
        _require_matching_actor(spec, ctx, principal)
        validated = spec.validate_request(request)
        logger.info("capability %s invoked by %s", name, principal.label)
        return spec.handler(ctx, validated)


def _require_matching_actor(
    spec: CapabilitySpec, ctx: CapabilityContext, principal: Principal
) -> None:
    """A human-authority call must also run under a human actor.

    The principal says who asked; the context says whose authority the handler will record.
    Letting those disagree would put a researcher's name on a host's mutation.
    """
    needs_human = spec.human_only or spec.permission in HUMAN_AUTHORITY
    if needs_human and not ctx.is_human:
        raise PermissionDenied(
            f"{spec.name}: the workspace context acts as {ctx.actor!r}, which is not the "
            "researcher; accepted-state mutation records human authority"
        )


def _validation_detail(exc: ValidationError) -> str:
    """Every field error on one line, so a caller sees all of them at once."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
        for error in exc.errors()
    )


# -- the default registry ----------------------------------------------------


def mutation_spec(
    name: str,
    *,
    summary: str,
    semantics: str,
    request_model: type[BaseModel],
    permission: Permission = Permission.MUTATE,
    human_only: bool = False,
    handlers: Mapping[str, Callable[[CapabilityContext, Any], Any]] = CAPABILITY_HANDLERS,
) -> CapabilitySpec:
    """A spec around an existing `MutationResult` handler, adapted to `MutationResponse`."""
    handler = handlers[name]

    def run(ctx: CapabilityContext, request: Any) -> MutationResponse:
        return MutationResponse.of(handler(ctx, request))

    return CapabilitySpec(
        name=name,
        summary=summary,
        permission=permission,
        scientific_semantics=semantics,
        request_model=request_model,
        response_model=MutationResponse,
        handler=run,
        human_only=human_only,
    )


def build_default_registry() -> CapabilityRegistry:
    """Every Product 22 capability this build implements, plus the names it does not.

    Import failures are not fatal: a workspace built without the optional packages still
    gets a working registry, one capability short, and the missing name shows up under
    :meth:`CapabilityRegistry.planned` rather than as a handler that lies.
    """
    from research_harness.capabilities import extra_handlers as extra

    registry = CapabilityRegistry()
    registry.register_all(_core_mutations())
    extra.register_into(registry)
    for name, reason in _PLANNED.items():
        if name not in registry:
            registry.plan(name, reason)
    return registry


def _core_mutations() -> list[CapabilitySpec]:
    """The Phase 1 handlers, named and permissioned. No new business logic (ADR-004)."""
    return [
        mutation_spec(
            "work.register",
            summary="Register a resolved candidate as a Work, Version, and Artifact.",
            semantics="creates corpus identity from a resolved candidate; writes no evidence",
            request_model=RegisterWorkRequest,
        ),
        mutation_spec(
            "work.add_artifact",
            summary="Attach a new immutable file to an existing Work.",
            semantics="adds an Artifact (and a Version when needed); never overwrites one",
            request_model=AddArtifactRequest,
        ),
        mutation_spec(
            "work.store_blocks",
            summary="Persist a parse so anchors resolve without re-parsing.",
            semantics="stores derived document blocks; changes no evidence or claim",
            request_model=StoreParsedDocumentRequest,
        ),
        mutation_spec(
            "evidence.accept",
            summary="Accept a reviewed candidate as canonical Evidence.",
            semantics=(
                "creates accepted Evidence from a reviewed candidate; requires a human actor"
            ),
            request_model=AcceptEvidenceRequest,
            human_only=True,
        ),
        mutation_spec(
            "evidence.reject",
            summary="Refuse a candidate and record why.",
            semantics=(
                "records a refusal so the same proposal is recognised again; creates no Evidence"
            ),
            request_model=RejectEvidenceRequest,
            human_only=True,
        ),
        mutation_spec(
            "claim.create",
            summary="Register a structured Claim.",
            semantics=(
                "creates a Claim at its requested strength; the audit decides what it may say"
            ),
            request_model=CreateClaimRequest,
        ),
        mutation_spec(
            "claim.audit",
            summary="Record what the evidence allows a Claim to say.",
            semantics=(
                "writes the Claim's assessment: status, allowed strength, defensible wording"
            ),
            request_model=AuditClaimRequest,
        ),
        mutation_spec(
            "claim.override_strength",
            summary="Apply an accepted epistemic override to a Claim.",
            semantics="raises or lowers a Claim's allowed strength under a recorded Decision",
            request_model=OverrideClaimStrengthRequest,
            human_only=True,
        ),
        mutation_spec(
            "decision.accept",
            summary="Accept a proposed researcher Decision.",
            semantics="moves a Decision to accepted; a researcher act (Product 38)",
            request_model=AcceptDecisionRequest,
            human_only=True,
        ),
        mutation_spec(
            "question.create",
            summary="Register a research question.",
            semantics="creates an open ResearchQuestion; answers nothing",
            request_model=CreateQuestionRequest,
        ),
        mutation_spec(
            "question.update",
            summary="Move a question's status and relink what bears on it.",
            semantics="changes a ResearchQuestion's status and links; writes no evidence",
            request_model=UpdateQuestionRequest,
        ),
        mutation_spec(
            "note.add",
            summary="Capture a low-authority research note.",
            semantics="creates a note that can never be cited as support until it is promoted",
            request_model=AddNoteRequest,
        ),
        mutation_spec(
            "note.promote",
            summary="Record the research object a captured note became.",
            semantics="raises a note's authority into a Claim, Question, or Decision; human-only",
            request_model=PromoteNoteRequest,
            human_only=True,
        ),
        mutation_spec(
            "manuscript.attach_claim",
            summary="Bind a manuscript sentence to a Claim.",
            semantics=(
                "creates the manuscript anchor that makes a sentence auditable (Product 30.1)"
            ),
            request_model=AttachManuscriptAnchorRequest,
            human_only=True,
        ),
        mutation_spec(
            "search_run.record",
            summary="Persist a reproducible discovery operation.",
            semantics="records what was searched, where, and when; adds nothing to the corpus",
            request_model=RecordSearchRunRequest,
        ),
        mutation_spec(
            "taxonomy.put",
            summary="Write a taxonomy authorised by an accepted Decision.",
            semantics="replaces a classification vocabulary; downstream classifications go stale",
            request_model=PutTaxonomyRequest,
        ),
        mutation_spec(
            "synthesis.build_matrix",
            summary="Persist a cross-paper comparison matrix.",
            semantics="writes a synthesis matrix over accepted evidence; proposes no new facts",
            request_model=PutMatrixRequest,
        ),
    ]


#: Product 22 names with no implementation in this build. Never a stub handler: a host that
#: asks gets "not built yet", not a fabricated answer.
_PLANNED: Mapping[str, str] = {
    "synthesis.find_pattern": "no pattern-finding service exists yet (Phase 14)",
    "project.init": (
        "creating a workspace is an admin action on an arbitrary filesystem path; the "
        "daemon is bound to one existing workspace, so it stays a CLI capability"
    ),
}
