"""What a plugin declares about itself: identity, contributions, egress, permissions.

`plugin.yaml` is the whole of a plugin's self-description (Product 32.3). Nothing is
inferred from the directory and nothing is discovered by importing code: a contribution
that is not listed here is not loaded, and a capability that is not listed here cannot be
called. That is what makes "silently expand model permissions" (Product 32.2) a thing the
loader can refuse rather than a thing a reviewer has to notice.

Two capability sets live here because both are answers to the same question — what may a
plugin do? `PLUGIN_ALLOWED_CAPABILITIES` is the read-and-stage surface a manifest may draw
from; `DENIED_CAPABILITIES` names the accepted-state mutations that stay refused whatever
a manifest says (ADR-003, ADR-010). The error hierarchy sits here too, because every one
of these errors is raised about a declaration or the boundary it promised to respect.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any, Final

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from research_harness.domain.errors import AuthorityError, ResearchHarnessError
from research_harness.roles.contracts import HUMAN_ONLY_CAPABILITIES

__all__ = [
    "DENIED_CAPABILITIES",
    "MANIFEST_FILENAME",
    "PLUGIN_ALLOWED_CAPABILITIES",
    "Contributions",
    "PluginBoundaryError",
    "PluginEgress",
    "PluginError",
    "PluginLoadError",
    "PluginManifest",
    "PluginManifestError",
    "PluginPermissions",
    "RelativePath",
    "core_version_satisfies",
    "is_denied_capability",
    "load_manifest",
    "manifest_paths",
    "namespaces_for",
]

MANIFEST_FILENAME: Final = "plugin.yaml"


# --------------------------------------------------------------------------- errors


class PluginError(ResearchHarnessError):
    """Root of every error raised while declaring, loading, or bounding a plugin."""


class PluginManifestError(PluginError):
    """`plugin.yaml` is missing, malformed, or describes something that cannot exist."""


class PluginBoundaryError(PluginError, AuthorityError):
    """A plugin asked for authority the extension boundary does not grant (Product 32.2).

    Also an `AuthorityError`, so the one ``except AuthorityError`` that already guards
    accepted state catches a plugin overreach without knowing plugins exist.
    """


class PluginLoadError(PluginError):
    """A declared contribution file is missing, unreadable, or does not parse."""


# ----------------------------------------------------------------- capability surface

PLUGIN_ALLOWED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "claim.find_counterevidence",
        "claim.find_support",
        "evidence.extract",
        "evidence.verify",
        "retrieval.resolve_source",
        "retrieval.search",
        "review.inbox",
        "work.get",
    }
)
"""Every capability a plugin may be granted: reading, retrieving, and staging only.

Each name reads accepted state or produces a candidate. None of them accepts, rejects,
promotes, or otherwise changes accepted state, so no manifest — however it is written —
can hand a plugin the review gate (Product 22, ADR-003). Widening this set is a core
decision with a boundary test attached, not a plugin's to make.
"""

DENIED_CAPABILITIES: frozenset[str] = HUMAN_ONLY_CAPABILITIES | frozenset(
    {
        "claim.override_strength",
        "decision.accept",
        "evidence.accept",
        "evidence.reject",
        "manuscript.attach_claim",
        "note.promote",
        "review.accept_batch",
        "search_run.record",
        "state.rebuild",
        "synthesis.build_matrix",
        "taxonomy.put",
        "work.register",
        "work.store_blocks",
    }
)
"""Accepted-state mutations that stay refused however the manifest is written.

Redundant with `PLUGIN_ALLOWED_CAPABILITIES` on purpose: the allowlist is what a manifest
may ask for, this is what the gateway refuses regardless. If someone ever widens the
allowlist by accident, these names are still unreachable from plugin code.
"""


def is_denied_capability(name: str) -> bool:
    """True when `name` is refused to plugins, matching `namespace.*` patterns too."""
    if name in DENIED_CAPABILITIES:
        return True
    return any(
        pattern.endswith(".*") and name.startswith(pattern[:-1]) for pattern in DENIED_CAPABILITIES
    )


# ------------------------------------------------------------------- scalar constraints

NAME_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
VERSION_PATTERN = r"^[0-9]+(\.[0-9]+)*([a-z0-9.\-+]*)$"

PluginName = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
"""Kebab-case plugin name: `structured-traffic`, `academic-writing`, `minimal`."""

PluginVersion = Annotated[str, StringConstraints(pattern=VERSION_PATTERN)]


def _relative_inside_plugin(value: str) -> str:
    """Reject anything that could name a file outside the plugin directory."""
    text = value.strip()
    if not text:
        raise ValueError("a contribution path must not be empty")
    if "\\" in text:
        raise ValueError(f"contribution path {value!r} must use '/' separators")
    path = Path(text)
    if path.is_absolute() or text.startswith("/") or text.startswith("~"):
        raise ValueError(f"contribution path {value!r} must be relative to the plugin directory")
    if any(part in {"..", ""} for part in path.parts):
        raise ValueError(f"contribution path {value!r} must not escape the plugin directory")
    return path.as_posix()


RelativePath = Annotated[
    str, StringConstraints(min_length=1), AfterValidator(_relative_inside_plugin)
]
"""A path inside the plugin directory. Traversal is rejected before anything is opened."""


def namespaces_for(plugin_name: str) -> frozenset[str]:
    """Label prefixes `plugin_name` may claim: its normalized name and its last segment.

    `structured-traffic` may namespace terms `structured_traffic.*` or `traffic.*`;
    `minimal` may use `minimal.*` only. Deriving the prefixes from the name (rather than
    letting the manifest declare one) is what stops two plugins from claiming the same
    vocabulary namespace, and stops any of them from claiming a bare core label.
    """
    normalized = plugin_name.replace("-", "_")
    return frozenset({normalized, normalized.rsplit("_", 1)[-1]})


# --------------------------------------------------------------------------- version


_SPECIFIER_RE = re.compile(r"^(===|==|!=|>=|<=|~=|>|<)\s*([0-9A-Za-z.\-+*]+)$")


def _release(version: str) -> tuple[int, ...]:
    """Numeric release segments of a version, ignoring local and pre-release suffixes."""
    core = version.split("+", 1)[0]
    parts: list[int] = []
    for segment in core.split("."):
        digits = re.match(r"[0-9]+", segment)
        if digits is None:
            break
        parts.append(int(digits.group()))
    if not parts:
        raise PluginManifestError(f"{version!r} has no numeric release segment")
    return tuple(parts)


def _padded(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    width = max(len(left), len(right))
    return (
        left + (0,) * (width - len(left)),
        right + (0,) * (width - len(right)),
    )


def _clause_satisfied(operator: str, wanted: str, actual: str) -> bool:
    """One PEP 440 comparison, on numeric release segments only."""
    if wanted.endswith(".*"):
        prefix = _release(wanted[:-2])
        got = _release(actual)[: len(prefix)]
        matches = got == prefix
        if operator in {"==", "==="}:
            return matches
        if operator == "!=":
            return not matches
        raise PluginManifestError(f"operator {operator!r} does not accept a wildcard version")
    if operator == "~=":
        floor = _release(wanted)
        if len(floor) < 2:
            raise PluginManifestError(f"'~=' needs at least two release segments, got {wanted!r}")
        ceiling_prefix = floor[:-1]
        got = _release(actual)
        left, right = _padded(got, floor)
        return left >= right and got[: len(ceiling_prefix)] == ceiling_prefix
    left, right = _padded(_release(actual), _release(wanted))
    match operator:
        case "==" | "===":
            return left == right
        case "!=":
            return left != right
        case ">=":
            return left >= right
        case "<=":
            return left <= right
        case ">":
            return left > right
        case "<":
            return left < right
    raise PluginManifestError(f"unsupported version operator {operator!r}")


def core_version_satisfies(specifier: str, core_version: str) -> bool:
    """True when `core_version` satisfies every comma-separated clause of `specifier`.

    A deliberately small PEP 440 subset (`==`, `!=`, `>=`, `<=`, `>`, `<`, `~=`, and a
    trailing `.*` wildcard) compared on numeric release segments. Pre-release and local
    suffixes are ignored rather than guessed at: a plugin pinning `>=0.1` should load
    against `0.1.0`, `0.1.0+dirty`, and `0.2.0rc1` alike.
    """
    clauses = [clause.strip() for clause in specifier.split(",") if clause.strip()]
    if not clauses:
        raise PluginManifestError("requires_core must contain at least one version clause")
    for clause in clauses:
        matched = _SPECIFIER_RE.match(clause)
        if matched is None:
            raise PluginManifestError(f"{clause!r} is not a supported version specifier")
        if not _clause_satisfied(matched.group(1), matched.group(2), core_version):
            return False
    return True


# --------------------------------------------------------------------------- manifest


class PluginEgress(BaseModel):
    """What leaves the workstation when one of this plugin's providers is called.

    Same shape as the model-provider declaration (Product 34): a plugin does not get a
    quieter disclosure surface than the core does.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint_host: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    sends_source_text: bool
    sends_identifiers: bool
    description: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class PluginPermissions(BaseModel):
    """The named capabilities and core roles this plugin is allowed to use.

    Validated against `PLUGIN_ALLOWED_CAPABILITIES` here so an over-broad manifest fails
    at load; the gateway checks again at every call, because a manifest that was never
    validated (or was constructed in code) must not become authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capabilities: frozenset[str] = frozenset()
    roles_used: frozenset[str] = frozenset()

    @field_validator("capabilities")
    @classmethod
    def _within_the_plugin_surface(cls, value: frozenset[str]) -> frozenset[str]:
        denied = sorted(name for name in value if is_denied_capability(name))
        if denied:
            raise ValueError(
                "a plugin may never call accepted-state capabilities: " + ", ".join(denied)
            )
        outside = sorted(value - PLUGIN_ALLOWED_CAPABILITIES)
        if outside:
            allowed = ", ".join(sorted(PLUGIN_ALLOWED_CAPABILITIES))
            raise ValueError(
                f"capabilities outside the plugin surface: {', '.join(outside)}; "
                f"a plugin may call: {allowed}"
            )
        return value


class Contributions(BaseModel):
    """The eight extension points of Product 32.1, each a list of files in the plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schemas: tuple[RelativePath, ...] = ()
    interrogation: tuple[RelativePath, ...] = ()
    validators: tuple[RelativePath, ...] = ()
    workflows: tuple[RelativePath, ...] = ()
    roles: tuple[RelativePath, ...] = ()
    search_providers: tuple[RelativePath, ...] = ()
    writing_policies: tuple[RelativePath, ...] = ()
    ui_extensions: tuple[RelativePath, ...] = ()

    def all_paths(self) -> tuple[str, ...]:
        """Every declared file, in declaration order, for existence and scan checks."""
        return (
            *self.schemas,
            *self.interrogation,
            *self.validators,
            *self.workflows,
            *self.roles,
            *self.search_providers,
            *self.writing_policies,
            *self.ui_extensions,
        )

    def python_paths(self) -> tuple[str, ...]:
        """Declared files that are executed as code and therefore statically scanned."""
        return (*self.validators, *self.search_providers)


class PluginManifest(BaseModel):
    """A complete `plugin.yaml` (Product 32.3), closed to fields the loader cannot honour."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: PluginName
    version: PluginVersion
    requires_core: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    description: Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
    contributes: Contributions = Contributions()
    egress: tuple[PluginEgress, ...] = ()
    permissions: PluginPermissions = PluginPermissions()

    @field_validator("requires_core")
    @classmethod
    def _specifier_parses(cls, value: str) -> str:
        core_version_satisfies(value, "0.0.0")
        return value

    @model_validator(mode="after")
    def _providers_declare_their_egress(self) -> PluginManifest:
        """A search provider without a declared endpoint is undisclosed egress (Product 34)."""
        if self.contributes.search_providers and not self.egress:
            raise ValueError(
                f"plugin {self.name!r} contributes search providers but declares no egress"
            )
        return self

    @property
    def namespaces(self) -> frozenset[str]:
        """Vocabulary prefixes this plugin may claim."""
        return namespaces_for(self.name)

    @property
    def egress_hosts(self) -> frozenset[str]:
        """Hosts this plugin has disclosed it may contact."""
        return frozenset(item.endpoint_host for item in self.egress)

    def satisfied_by(self, core_version: str) -> bool:
        """True when this core version is inside the plugin's `requires_core` range."""
        return core_version_satisfies(self.requires_core, core_version)


def load_manifest(path: Path) -> PluginManifest:
    """Read and validate one `plugin.yaml`; `path` may be the file or its directory."""
    manifest_path = path / MANIFEST_FILENAME if path.is_dir() else path
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PluginManifestError(f"cannot read plugin manifest {manifest_path}: {exc}") from exc
    return _validated(_parsed_mapping(raw, manifest_path), manifest_path)


def _parsed_mapping(raw: str, source: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PluginManifestError(f"{source} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginManifestError(
            f"{source} must contain a YAML mapping, not {type(data).__name__}"
        )
    return data


def _validated(data: dict[str, Any], source: Path) -> PluginManifest:
    try:
        return PluginManifest.model_validate(data)
    except ValueError as exc:
        raise PluginManifestError(f"{source} is not a valid plugin manifest: {exc}") from exc


def manifest_paths(roots: Iterable[Path]) -> tuple[Path, ...]:
    """Directories under `roots` that hold a `plugin.yaml`, sorted and de-duplicated."""
    found: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        if (root / MANIFEST_FILENAME).is_file():
            found.add(root)
        found.update(child.parent for child in sorted(root.glob(f"*/{MANIFEST_FILENAME}")))
    return tuple(sorted(found))
