"""The plugin service provider interface: the eight things a plugin may contribute.

Every type here is data or a narrow callable. A plugin never receives a
`WorkspaceRepository`, a `CapabilityContext`, a database handle, or a path into the
workspace; it receives its own parsed contributions and one `CapabilityGateway`. That is
the whole of its reach into the harness, which is what makes Product 32.2 ("must not write
directly to canonical files", "must not write directly to SQLite as scientific state")
enforceable instead of advisory.

Three choices are worth naming because they carry the authority boundary rather than
merely implementing it:

* A plugin role must name one of the *core* output schemas. It cannot invent the shape of
  its own answer, so the epistemic rules baked into those schemas — no `researcher_inferred`
  from a model, no `absent` from an extraction, a verdict that is categorical and never a
  confidence score — apply to plugin roles for free (ADR-003).
* A validator is a pure function over a plain dict. It is handed JSON-shaped data, and
  `LoadedValidator.run` refuses to pass anything else, so there is no object graph for a
  validator to walk back into the repository through.
* A writing policy is fixed at `candidate_only` authority and must preserve every core
  protected span kind. A style pass may change wording; it may not change what the
  manuscript claims (Product 30.4, ROADMAP Task 15.2).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

from research_harness.domain.enums import ClaimType, EvidenceType
from research_harness.evidence.interrogation import (
    DEFAULT_SCHEMA,
    InterrogationField,
    InterrogationSchema,
    ValueKind,
)
from research_harness.manuscript.protected import ProtectedSpanKind
from research_harness.plugins.manifest import (
    PLUGIN_ALLOWED_CAPABILITIES,
    PluginBoundaryError,
    PluginManifest,
    PluginPermissions,
    RelativePath,
    is_denied_capability,
)
from research_harness.providers.models.base import ModelRequirements
from research_harness.providers.search.base import SearchProvider
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    RoleContract,
    WriteScope,
)
from research_harness.roles.schemas import (
    ClaimAuditOutput,
    ExtractionOutput,
    SkepticOutput,
    SynthesisOutput,
    VerificationOutput,
    WriterOutput,
)

__all__ = [
    "CORE_PROTECTED_SPAN_KINDS",
    "PLUGIN_ROLE_OUTPUT_SCHEMAS",
    "PLUGIN_ROLE_WRITE_SCOPES",
    "CapabilityGateway",
    "InterrogationContribution",
    "IssueSeverity",
    "LoadedValidator",
    "PermissionedGateway",
    "PluginRuntime",
    "PluginVocabulary",
    "RoleContribution",
    "SchemaContribution",
    "SearchProviderContribution",
    "SearchProviderFactory",
    "UiExtensionDescriptor",
    "ValidationIssue",
    "ValidatorContribution",
    "VocabularyField",
    "VocabularyTerm",
    "WordingConstraint",
    "WorkflowFragmentContribution",
    "WorkflowStageDescriptor",
    "WritingPolicyContribution",
    "ensure_plain_data",
    "merge_interrogation",
]

Label = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]

PlainData = str | int | float | bool | None | Sequence[Any] | Mapping[str, Any]
"""What a validator may be handed: JSON-shaped values, never harness objects."""

CORE_PROTECTED_SPAN_KINDS: frozenset[ProtectedSpanKind] = frozenset(ProtectedSpanKind)
"""Every span a style pass must leave byte-identical; a policy may add, never subtract."""

PLUGIN_ROLE_OUTPUT_SCHEMAS: Mapping[str, type[BaseModel]] = MappingProxyType(
    {
        "claim_audit": ClaimAuditOutput,
        "extraction": ExtractionOutput,
        "skeptic": SkepticOutput,
        "synthesis": SynthesisOutput,
        "verification": VerificationOutput,
        "writer": WriterOutput,
    }
)
"""Output shapes a plugin role may declare, by name.

A plugin names one of these; it does not supply a schema. The epistemic constraints these
models enforce are precisely what a domain plugin must not be able to relax.
"""

PLUGIN_ROLE_WRITE_SCOPES: frozenset[WriteScope] = frozenset(WriteScope) - {WriteScope.NONE}
"""Candidate scopes a plugin role may write. `WriteScope` cannot name accepted state at
all, so this set is every scope except "writes nothing"."""


# ---------------------------------------------------------------------- validators


class IssueSeverity(StrEnum):
    """How a validator's finding should be treated by review."""

    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    """One domain-specific finding about a candidate (Product 32.1, category 3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: Label
    message: Label
    severity: IssueSeverity = IssueSeverity.ERROR


ValidateFn = Callable[[Mapping[str, object]], object]
"""The one function a validator module must expose: candidate dict in, findings out."""


def ensure_plain_data(value: object, path: str = "candidate") -> PlainData:
    """Return `value` unchanged if it is JSON-shaped; otherwise refuse to hand it over.

    Plugin code gets data, never objects. A `Work`, an open repository, or a capability
    context reaching a validator would be a way back into canonical state that no static
    scan could see, so the transfer itself is checked (Product 32.2).
    """
    if isinstance(value, str | int | float | bool | None):
        return value
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PluginBoundaryError(
                    f"{path}: plugin data keys must be strings, got {type(key).__name__}"
                )
            ensure_plain_data(item, f"{path}.{key}")
        return value
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            ensure_plain_data(item, f"{path}[{index}]")
        return value
    raise PluginBoundaryError(
        f"{path}: plugin code receives plain data only, not {type(value).__name__}"
    )


@dataclass(frozen=True, slots=True)
class LoadedValidator:
    """A plugin validator, already scanned and executed, wrapped in its data boundary."""

    name: str
    plugin: str
    source: Path
    function: ValidateFn

    def run(self, candidate: Mapping[str, object]) -> tuple[ValidationIssue, ...]:
        """Validate one candidate. Raises `PluginBoundaryError` for non-plain input."""
        ensure_plain_data(candidate)
        return _as_issues(self.function(candidate), self.name)


def _as_issues(returned: object, validator: str) -> tuple[ValidationIssue, ...]:
    """Coerce a validator's return value into issues, refusing anything else.

    Validators return plain mappings or `(field, message[, severity])` tuples so that a
    validator module never has to import the harness to describe a finding.
    """
    if returned is None:
        return ()
    if not isinstance(returned, list | tuple):
        raise PluginBoundaryError(
            f"validator {validator!r} must return a list of findings, not {type(returned).__name__}"
        )
    issues: list[ValidationIssue] = []
    for item in returned:
        issues.append(_as_issue(item, validator))
    return tuple(issues)


def _as_issue(item: object, validator: str) -> ValidationIssue:
    if isinstance(item, ValidationIssue):
        return item
    try:
        if isinstance(item, Mapping):
            return ValidationIssue.model_validate(dict(item))
        if isinstance(item, list | tuple) and len(item) in {2, 3}:
            field, message, *rest = item
            severity = rest[0] if rest else IssueSeverity.ERROR
            return ValidationIssue(field=field, message=message, severity=IssueSeverity(severity))
    except ValueError as exc:
        raise PluginBoundaryError(
            f"validator {validator!r} returned an invalid finding: {exc}"
        ) from exc
    raise PluginBoundaryError(
        f"validator {validator!r} returned {type(item).__name__}; expected a mapping or a "
        "(field, message[, severity]) tuple"
    )


class ValidatorContribution(BaseModel):
    """Declaration of one validator module inside the plugin directory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    module: RelativePath


# ---------------------------------------------------------------------- vocabulary


class VocabularyTerm(BaseModel):
    """One plugin-namespaced label added beside a core enum, never inside it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: Label
    description: Label


class VocabularyField(BaseModel):
    """One plugin-namespaced domain field, with its controlled values when it has any."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    description: Label
    value_kind: ValueKind = ValueKind.TEXT
    categories: tuple[Label, ...] = ()
    multi_label: bool = False
    """True when a Work may carry several values, as hybrid representations require."""

    @model_validator(mode="after")
    def _categories_belong_to_categorical_fields(self) -> VocabularyField:
        if self.value_kind is ValueKind.CATEGORICAL and not self.categories:
            raise ValueError(f"categorical field {self.name!r} must list its categories")
        if self.value_kind is not ValueKind.CATEGORICAL and self.categories:
            raise ValueError(f"field {self.name!r} lists categories but is not categorical")
        return self


class SchemaContribution(BaseModel):
    """A domain vocabulary extension (Product 32.1, category 1).

    Additive by construction: labels live in a `PluginVocabulary`, so `EvidenceType` and
    `ClaimType` keep exactly the members the core declares. A plugin widens what a project
    can *say*; it cannot change what Evidence, Claim, or Decision *mean* (ADR-010).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: Label
    evidence_types: tuple[VocabularyTerm, ...] = ()
    claim_types: tuple[VocabularyTerm, ...] = ()
    fields: tuple[VocabularyField, ...] = ()

    def labels(self) -> tuple[str, ...]:
        """Every label and field name this contribution declares."""
        return (
            *(term.label for term in self.evidence_types),
            *(term.label for term in self.claim_types),
            *(field.name for field in self.fields),
        )


class PluginVocabulary(BaseModel):
    """The plugin-contributed labels a validator or UI may consult.

    Read beside the core enums, never merged into them: `resolve_evidence_type` returns
    the core member when one exists and the plugin term otherwise, so a project taxonomy
    term and a core evidence type can never be confused for each other.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_types: tuple[VocabularyTerm, ...] = ()
    claim_types: tuple[VocabularyTerm, ...] = ()
    fields: tuple[VocabularyField, ...] = ()

    @classmethod
    def of(cls, contributions: Sequence[SchemaContribution]) -> PluginVocabulary:
        """Merge several schema contributions into one registry."""
        return cls(
            evidence_types=tuple(term for item in contributions for term in item.evidence_types),
            claim_types=tuple(term for item in contributions for term in item.claim_types),
            fields=tuple(field for item in contributions for field in item.fields),
        )

    def labels(self) -> frozenset[str]:
        """Every label this registry knows."""
        return frozenset(
            (
                *(term.label for term in self.evidence_types),
                *(term.label for term in self.claim_types),
                *(field.name for field in self.fields),
            )
        )

    def field(self, name: str) -> VocabularyField | None:
        """The plugin field called `name`, or None."""
        return next((item for item in self.fields if item.name == name), None)

    def resolve_evidence_type(self, label: str) -> EvidenceType | VocabularyTerm | None:
        """The core member for `label` if there is one, else the plugin term, else None."""
        if label in {member.value for member in EvidenceType}:
            return EvidenceType(label)
        return next((term for term in self.evidence_types if term.label == label), None)

    def resolve_claim_type(self, label: str) -> ClaimType | VocabularyTerm | None:
        """The core member for `label` if there is one, else the plugin term, else None."""
        if label in {member.value for member in ClaimType}:
            return ClaimType(label)
        return next((term for term in self.claim_types if term.label == label), None)


# -------------------------------------------------------------------- interrogation


class InterrogationContribution(BaseModel):
    """Extra questions a domain asks of every relevant paper (Product 32.1, category 2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_name: Label
    version: Label = "1.0.0"
    fields: tuple[InterrogationField, ...]

    @field_validator("fields")
    @classmethod
    def _not_empty(cls, value: tuple[InterrogationField, ...]) -> tuple[InterrogationField, ...]:
        if not value:
            raise ValueError("an interrogation contribution must add at least one field")
        return value


def merge_interrogation(
    plugin: str,
    contribution: InterrogationContribution,
    *,
    base: InterrogationSchema = DEFAULT_SCHEMA,
) -> InterrogationSchema:
    """Build `<plugin>:<schema_name>` from the base schema plus the plugin's fields.

    `base` is read and copied, never mutated: `DEFAULT_SCHEMA` after a load is the same
    object with the same fingerprint it had before (ROADMAP Task 14.3).
    """
    return InterrogationSchema(
        name=f"{plugin}:{contribution.schema_name}",
        version=contribution.version,
        fields=(*base.fields, *contribution.fields),
    )


# ------------------------------------------------------------------------ workflows


class WorkflowStageDescriptor(BaseModel):
    """One stage of a plugin workflow fragment and the capabilities it calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    description: Label = "-"
    capabilities: tuple[Label, ...] = ()
    role: Label | None = None
    idempotent: bool = True


class WorkflowFragmentContribution(BaseModel):
    """Optional DAG steps built from core capabilities (Product 32.1, category 4).

    Data, not code: the fragment names stages and the capabilities each stage calls, and
    the host composes `workflows.engine` stages from it. A plugin therefore cannot smuggle
    a stage that reaches past the capability layer, because it never supplies the stage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    version: Label = "1.0.0"
    description: Label
    stages: tuple[WorkflowStageDescriptor, ...]

    @field_validator("stages")
    @classmethod
    def _stages_are_named_once(
        cls, value: tuple[WorkflowStageDescriptor, ...]
    ) -> tuple[WorkflowStageDescriptor, ...]:
        if not value:
            raise ValueError("a workflow fragment needs at least one stage")
        names = [stage.name for stage in value]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate stage names: {', '.join(duplicates)}")
        return value

    def capability_names(self) -> frozenset[str]:
        """Every capability any stage of this fragment declares it will call."""
        return frozenset(name for stage in self.stages for name in stage.capabilities)

    def role_names(self) -> frozenset[str]:
        """Every role any stage of this fragment names."""
        return frozenset(stage.role for stage in self.stages if stage.role is not None)


# ---------------------------------------------------------------------------- roles


class RoleContribution(BaseModel):
    """A bounded domain role (Product 32.1, category 5), expressed as data.

    `output_schema` names a core schema rather than supplying one, and `write_scope` is a
    core `WriteScope`, which has no value for accepted state. A plugin therefore configures
    a role; it cannot define a new kind of authority for one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    objective: Label
    allowed_inputs: frozenset[InputKind]
    allowed_capabilities: frozenset[str] = frozenset()
    output_schema: Label
    write_scope: WriteScope
    requirements: ModelRequirements
    template_version: Label = "1.0.0"
    system_prompt: Label

    @field_validator("output_schema")
    @classmethod
    def _names_a_core_schema(cls, value: str) -> str:
        if value not in PLUGIN_ROLE_OUTPUT_SCHEMAS:
            known = ", ".join(sorted(PLUGIN_ROLE_OUTPUT_SCHEMAS))
            raise ValueError(f"unknown output schema {value!r}; a plugin role may use: {known}")
        return value

    @field_validator("write_scope")
    @classmethod
    def _writes_a_candidate_scope(cls, value: WriteScope) -> WriteScope:
        if value not in PLUGIN_ROLE_WRITE_SCOPES:
            allowed = ", ".join(sorted(scope.value for scope in PLUGIN_ROLE_WRITE_SCOPES))
            raise ValueError(f"a plugin role must write a candidate scope, one of: {allowed}")
        return value

    @field_validator("allowed_inputs")
    @classmethod
    def _reads_something(cls, value: frozenset[InputKind]) -> frozenset[InputKind]:
        if not value:
            raise ValueError("a role must be allowed to read at least one kind of input")
        return value

    @model_validator(mode="after")
    def _asks_for_no_human_capability(self) -> RoleContribution:
        denied = sorted(name for name in self.allowed_capabilities if is_denied_capability(name))
        if denied:
            raise ValueError(
                f"role {self.name!r} may not call human-only capabilities: {', '.join(denied)}"
            )
        return self

    @property
    def schema_type(self) -> type[BaseModel]:
        """The core output model this role's answers are validated against."""
        return PLUGIN_ROLE_OUTPUT_SCHEMAS[self.output_schema]

    @property
    def forbidden(self) -> frozenset[str]:
        """What the built contract denies: every human-only capability, always."""
        return HUMAN_ONLY_CAPABILITIES


# ----------------------------------------------------------------- search providers


class SearchProviderContribution(BaseModel):
    """A venue/database connector (Product 32.1, category 6) plus its disclosure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    module: RelativePath
    endpoint_host: Label
    """Must match one of the manifest's declared egress hosts (Product 34)."""


@dataclass(frozen=True, slots=True)
class SearchProviderFactory:
    """Deferred construction of one plugin search provider.

    Building is lazy so that loading a plugin never opens a socket, and the provider's own
    egress declaration is checked against the manifest at build time: a connector that
    talks to a host the manifest did not disclose is refused rather than logged.
    """

    name: str
    plugin: str
    source: Path
    endpoint_host: str
    declared_hosts: frozenset[str]
    build_fn: Callable[[Mapping[str, str]], object]

    def build(self, env: Mapping[str, str]) -> SearchProvider:
        """Construct the provider and check that its egress was declared."""
        provider = self.build_fn(env)
        if not isinstance(provider, SearchProvider):
            raise PluginBoundaryError(
                f"search provider {self.name!r} of plugin {self.plugin!r} built "
                f"{type(provider).__name__}, not a SearchProvider"
            )
        host = provider.capabilities().egress.endpoint_host
        if host not in self.declared_hosts:
            raise PluginBoundaryError(
                f"search provider {self.name!r} of plugin {self.plugin!r} contacts {host!r}, "
                f"which its manifest does not declare; declared: "
                f"{', '.join(sorted(self.declared_hosts)) or 'nothing'}"
            )
        return provider


# --------------------------------------------------------------------- writing policy


class WordingConstraint(BaseModel):
    """One wording rule a manuscript candidate is checked against."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    pattern: Label
    message: Label
    severity: IssueSeverity = IssueSeverity.WARNING


class WritingPolicyContribution(BaseModel):
    """Venue or project manuscript constraints (Product 32.1, category 7).

    `authority` is a one-valued field on purpose. A writing policy produces a manuscript
    *candidate*: it may constrain wording, and it may not upgrade scientific authority,
    add a citation, or change what a sentence claims (ROADMAP Task 15.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    description: Label
    authority: Literal["candidate_only"] = "candidate_only"
    protected_spans: frozenset[ProtectedSpanKind] = CORE_PROTECTED_SPAN_KINDS
    """Defaults to every core kind. Dropping one is a boundary violation, refused by
    `validation.check_writing_policy` rather than here, so the error says what it is."""

    wording_constraints: tuple[WordingConstraint, ...] = ()
    style_rules: tuple[Label, ...] = ()

    def dropped_protections(self) -> frozenset[ProtectedSpanKind]:
        """Core protected span kinds this policy fails to preserve."""
        return CORE_PROTECTED_SPAN_KINDS - self.protected_spans


# --------------------------------------------------------------------- ui extensions


class UiExtensionDescriptor(BaseModel):
    """A domain panel or matrix view (Product 32.1, category 8), described as data only.

    No code, no template, no callback: a UI extension says which fields a view shows, and
    the cockpit decides how to show them. Nothing here can execute in a frontend.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Label
    title: Label
    view: Literal["matrix", "panel", "table"]
    fields: tuple[Label, ...]

    @field_validator("fields")
    @classmethod
    def _shows_something(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("a UI extension must name at least one field")
        return value


# ------------------------------------------------------------------ capability gateway


@runtime_checkable
class CapabilityGateway(Protocol):
    """The only way a plugin reaches the harness: named capabilities, plain requests.

    Deliberately narrow. There is no `repository`, no `context`, no `session`, and no way
    to ask for one, so ADR-004's rule that `capabilities/` is the single mutation surface
    holds for plugin code by construction as well as by policy.
    """

    def call(self, name: str, request: BaseModel, *, actor: str) -> object:
        """Invoke the named capability on behalf of `actor`."""
        ...


class PermissionedGateway:
    """A gateway bounded by one plugin's permissions, and by the core deny list.

    Three refusals, in order: a capability that mutates accepted state is refused however
    the manifest reads; a capability outside the plugin surface is refused; a capability
    the manifest did not declare is refused. The first check exists because a manifest is
    a declaration, not a permission — a hand-built or hand-edited one must not become one.
    """

    def __init__(self, inner: CapabilityGateway, permissions: PluginPermissions) -> None:
        self._inner = inner
        self._permissions = permissions

    @property
    def permissions(self) -> PluginPermissions:
        """The permissions this gateway enforces."""
        return self._permissions

    def allows(self, name: str) -> bool:
        """True when `name` would be forwarded rather than refused."""
        if is_denied_capability(name):
            return False
        if name not in PLUGIN_ALLOWED_CAPABILITIES:
            return False
        return name in self._permissions.capabilities

    def call(self, name: str, request: BaseModel, *, actor: str) -> object:
        """Forward one permitted capability call, or raise `PluginBoundaryError`."""
        if is_denied_capability(name):
            raise PluginBoundaryError(
                f"capability {name!r} changes accepted state and is never available to a "
                "plugin; accepted state is reached only through human review"
            )
        if name not in PLUGIN_ALLOWED_CAPABILITIES:
            raise PluginBoundaryError(
                f"capability {name!r} is not part of the plugin surface; a plugin may call: "
                f"{', '.join(sorted(PLUGIN_ALLOWED_CAPABILITIES))}"
            )
        if name not in self._permissions.capabilities:
            granted = ", ".join(sorted(self._permissions.capabilities)) or "no capability"
            raise PluginBoundaryError(
                f"capability {name!r} is not declared in this plugin's manifest; it declares: "
                f"{granted}"
            )
        return self._inner.call(name, request, actor=actor)


# ------------------------------------------------------------------------- runtime


@dataclass(frozen=True, slots=True)
class PluginRuntime:
    """Everything one loaded plugin exposes, plus the gateway it is allowed to use."""

    manifest: PluginManifest
    directory: Path
    vocabulary: PluginVocabulary
    interrogation_schemas: Mapping[str, InterrogationSchema]
    validators: Mapping[str, LoadedValidator]
    workflow_fragments: Mapping[str, WorkflowFragmentContribution]
    roles: Mapping[str, RoleContract]
    search_providers: Mapping[str, SearchProviderFactory]
    writing_policies: Mapping[str, WritingPolicyContribution]
    ui_extensions: Mapping[str, UiExtensionDescriptor]
    gateway: PermissionedGateway

    @property
    def name(self) -> str:
        """The plugin's kebab-case name."""
        return self.manifest.name

    @property
    def version(self) -> str:
        """The plugin's own version, not the core's."""
        return self.manifest.version
