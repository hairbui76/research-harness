"""The boundary checks a plugin must pass before any of its code or data is used.

Product 32.2 is a list of things a plugin must not do. This module turns each of them into
a check that runs at load time, because a boundary discovered at runtime has already been
crossed:

1. contribution modules are statically scanned before they are executed, so a validator
   that imports the workspace, opens a database, or writes a file never runs at all;
2. a contributed role may not exceed the plugin's permissions, may not widen the core role
   of the same name, and may not name a write scope outside the candidate scopes;
3. a vocabulary may only *add* labels — a plugin label equal to a core enum value is
   refused, because core meanings cannot be redefined (ADR-010);
4. a writing policy must preserve every core protected span and stays candidate-only;
5. an interrogation field may not be named like a core field unless it is namespaced.

The static scan is a gate, not a sandbox. It refuses the obvious routes out of the SPI
(`import research_harness.workspace`, `sqlite3.connect`, `open(...)`, `os.*`) and it makes
a plugin that wants those routes declare them by failing to load. Real isolation would
need a separate process; what this buys is that the boundary is checked by machine, on
every load, rather than by a reviewer reading a diff.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from research_harness.domain.enums import ClaimType, EvidenceType
from research_harness.evidence.interrogation import DEFAULT_SCHEMA, InterrogationField
from research_harness.plugins.manifest import (
    PLUGIN_ALLOWED_CAPABILITIES,
    PluginBoundaryError,
    PluginManifest,
    is_denied_capability,
)
from research_harness.plugins.spi import (
    InterrogationContribution,
    RoleContribution,
    SchemaContribution,
    SearchProviderContribution,
    WorkflowFragmentContribution,
    WritingPolicyContribution,
)
from research_harness.roles.contracts import RoleContract, WriteScope
from research_harness.roles.registry import ROLES

__all__ = [
    "CORE_PACKAGE",
    "FORBIDDEN_CALL_NAMES",
    "FORBIDDEN_FROM_MODULES",
    "FORBIDDEN_IMPORTS",
    "FORBIDDEN_METHOD_NAMES",
    "build_role_contract",
    "check_interrogation",
    "check_role",
    "check_search_provider",
    "check_vocabulary",
    "check_workflow",
    "check_writing_policy",
    "resolve_inside",
    "scan_module",
]

FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "ctypes",
        "importlib",
        "os",
        "pickle",
        "research_harness.capabilities.context",
        "research_harness.capabilities.handlers",
        "research_harness.projection",
        "research_harness.workspace",
        "runpy",
        "shutil",
        "socket",
        "sqlalchemy",
        "sqlite3",
        "subprocess",
        "sys",
    }
)
"""Modules a contribution may not import: persistence, process control, and the two core
packages that own canonical state. `research_harness.capabilities.dto` is deliberately
absent — a plugin builds capability *requests*; it just never gets a context to run them
against."""

FORBIDDEN_CALL_NAMES: frozenset[str] = frozenset(
    {"__import__", "breakpoint", "compile", "eval", "exec", "input", "open"}
)
"""Builtins a contribution may not call. `globals` and `locals` are allowed on purpose:
introspection is harmless here, and a plugin that looks for a repository in its own
namespace should be able to look and find nothing."""

FORBIDDEN_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "chmod",
        "connect",
        "executemany",
        "executescript",
        "hardlink_to",
        "makedirs",
        "mkdir",
        "rename",
        "rmdir",
        "rmtree",
        "symlink_to",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
)
"""Method names that create, move, or destroy files, or open a database connection.

Chosen to avoid false positives on ordinary Python: `replace` and `remove` are left out
because `str.replace` and `list.remove` are everywhere, and neither is reachable as a
filesystem call without a `Path` or `os` that this list already refuses."""


def resolve_inside(directory: Path, relative: str) -> Path:
    """Resolve `relative` under `directory`, refusing anything that escapes it.

    The manifest already rejects `..` textually; this repeats the check after symlink
    resolution, because a symlink inside the plugin can point anywhere.
    """
    root = directory.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise PluginBoundaryError(
            f"contribution {relative!r} resolves to {candidate}, outside the plugin directory"
        )
    return candidate


# ---------------------------------------------------------------------- static scan


def scan_module(path: Path, *, plugin: str) -> None:
    """Refuse to load a contribution module that reaches past the SPI.

    Raises `PluginBoundaryError` naming the file, the line, and what was found.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - the loader checks existence first
        raise PluginBoundaryError(f"cannot read plugin module {path}: {exc}") from exc
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise PluginBoundaryError(f"plugin module {path} does not parse: {exc}") from exc
    for node in ast.walk(tree):
        _check_import(node, path, plugin)
        _check_call(node, path, plugin)


def _refuse(path: Path, plugin: str, line: int, what: str) -> PluginBoundaryError:
    return PluginBoundaryError(
        f"plugin {plugin!r}: {path.name}:{line} {what}; a plugin reaches the harness only "
        "through its capability gateway (Product 32.2)"
    )


CORE_PACKAGE = "research_harness"

FORBIDDEN_FROM_MODULES: frozenset[str] = frozenset({CORE_PACKAGE, f"{CORE_PACKAGE}.capabilities"})
"""Harness packages a contribution may not import *from*, matched exactly.

`from research_harness.capabilities.dto import ...` is allowed: a plugin builds capability
requests. `from research_harness.capabilities import dto` is not, because binding the
package binds `handlers` and `context` beside it."""


def _forbidden_module(name: str | None) -> str | None:
    """The forbidden prefix `name` falls under, if any."""
    if not name:
        return None
    for forbidden in FORBIDDEN_IMPORTS:
        if name == forbidden or name.startswith(f"{forbidden}."):
            return forbidden
    return None


def _check_import(node: ast.AST, path: Path, plugin: str) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            forbidden = _forbidden_module(alias.name)
            if forbidden is not None:
                raise _refuse(path, plugin, node.lineno, f"imports {forbidden!r}")
            if alias.name == CORE_PACKAGE or alias.name.startswith(f"{CORE_PACKAGE}."):
                # `import research_harness.x.y` binds the root package, and with it every
                # submodule already loaded in this process. Names only.
                raise _refuse(
                    path,
                    plugin,
                    node.lineno,
                    f"imports the {alias.name!r} module; a contribution may only write "
                    "`from research_harness.… import <name>`",
                )
    elif isinstance(node, ast.ImportFrom):
        forbidden = _forbidden_module(node.module)
        if forbidden is not None:
            raise _refuse(path, plugin, node.lineno, f"imports from {forbidden!r}")
        if node.module in FORBIDDEN_FROM_MODULES:
            raise _refuse(path, plugin, node.lineno, f"imports from the {node.module!r} package")


def _check_call(node: ast.AST, path: Path, plugin: str) -> None:
    if not isinstance(node, ast.Call):
        return
    func = node.func
    if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
        raise _refuse(path, plugin, node.lineno, f"calls {func.id}()")
    if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_METHOD_NAMES:
        raise _refuse(path, plugin, node.lineno, f"calls .{func.attr}(), which writes state")


# ---------------------------------------------------------------------- vocabulary

_CORE_EVIDENCE_LABELS: frozenset[str] = frozenset(member.value for member in EvidenceType)
_CORE_CLAIM_LABELS: frozenset[str] = frozenset(member.value for member in ClaimType)


def check_vocabulary(contribution: SchemaContribution, manifest: PluginManifest) -> None:
    """A vocabulary may add labels; it may never reuse or redefine a core one."""
    if contribution.namespace not in manifest.namespaces:
        allowed = ", ".join(sorted(manifest.namespaces))
        raise PluginBoundaryError(
            f"plugin {manifest.name!r} may not use vocabulary namespace "
            f"{contribution.namespace!r}; it may use: {allowed}"
        )
    for term in contribution.evidence_types:
        _check_label(term.label, _CORE_EVIDENCE_LABELS, "evidence type", manifest)
    for term in contribution.claim_types:
        _check_label(term.label, _CORE_CLAIM_LABELS, "claim type", manifest)
    for field in contribution.fields:
        _check_label(field.name, frozenset(DEFAULT_SCHEMA.names), "interrogation field", manifest)


def _check_label(
    label: str, core_labels: frozenset[str], kind: str, manifest: PluginManifest
) -> None:
    if label in core_labels:
        raise PluginBoundaryError(
            f"plugin {manifest.name!r} redefines the core {kind} {label!r}; core meanings of "
            "Evidence, Claim, and Decision cannot be redefined (ADR-010)"
        )
    _require_namespace(label, kind, manifest)


def _require_namespace(label: str, kind: str, manifest: PluginManifest) -> None:
    namespace, separator, remainder = label.partition(".")
    if not separator or not remainder:
        allowed = ", ".join(sorted(f"{item}." for item in manifest.namespaces))
        raise PluginBoundaryError(
            f"plugin {manifest.name!r} declares unnamespaced {kind} {label!r}; prefix it with "
            f"one of: {allowed}"
        )
    if namespace not in manifest.namespaces:
        allowed = ", ".join(sorted(manifest.namespaces))
        raise PluginBoundaryError(
            f"plugin {manifest.name!r} may not claim namespace {namespace!r} for {kind} "
            f"{label!r}; it may use: {allowed}"
        )


# -------------------------------------------------------------------- interrogation


def check_interrogation(contribution: InterrogationContribution, manifest: PluginManifest) -> None:
    """Plugin questions are added beside the core ones, never on top of them."""
    core_names = frozenset(DEFAULT_SCHEMA.names)
    for field in contribution.fields:
        if field.name in core_names:
            raise PluginBoundaryError(
                f"plugin {manifest.name!r} redefines core interrogation field {field.name!r}; "
                f"namespace it instead, as {sorted(manifest.namespaces)[0]}.{field.name}"
            )
        _require_namespace(field.name, "interrogation field", manifest)
        _check_categorical(field, manifest)


def _check_categorical(field: InterrogationField, manifest: PluginManifest) -> None:
    """A categorical question must say what its answers may be, or review cannot check it."""
    if field.categories and len(set(field.categories)) != len(field.categories):
        raise PluginBoundaryError(
            f"plugin {manifest.name!r} field {field.name!r} repeats a category"
        )


# --------------------------------------------------------------------------- roles


def check_role(contribution: RoleContribution, manifest: PluginManifest) -> None:
    """A plugin role stays inside the plugin's permissions and inside its core namesake."""
    _require_namespace(contribution.name, "role", manifest)
    _check_role_capabilities(contribution, manifest)
    _check_role_does_not_widen_core(contribution, manifest)


def _check_role_capabilities(contribution: RoleContribution, manifest: PluginManifest) -> None:
    denied = sorted(
        name for name in contribution.allowed_capabilities if is_denied_capability(name)
    )
    if denied:
        raise PluginBoundaryError(
            f"role {contribution.name!r} of plugin {manifest.name!r} asks for human-only "
            f"capabilities: {', '.join(denied)}"
        )
    outside_surface = sorted(contribution.allowed_capabilities - PLUGIN_ALLOWED_CAPABILITIES)
    if outside_surface:
        raise PluginBoundaryError(
            f"role {contribution.name!r} of plugin {manifest.name!r} asks for capabilities "
            f"outside the plugin surface: {', '.join(outside_surface)}"
        )
    undeclared = sorted(contribution.allowed_capabilities - manifest.permissions.capabilities)
    if undeclared:
        raise PluginBoundaryError(
            f"role {contribution.name!r} exceeds the permissions plugin {manifest.name!r} "
            f"declares: {', '.join(undeclared)}; a role cannot widen its plugin silently"
        )


def _check_role_does_not_widen_core(
    contribution: RoleContribution, manifest: PluginManifest
) -> None:
    """A plugin may narrow a core role of the same name; it may never widen one."""
    bare = contribution.name.rpartition(".")[2]
    core = ROLES.get(bare)
    if core is None:
        return
    extra_capabilities = sorted(contribution.allowed_capabilities - core.allowed_capabilities)
    if extra_capabilities:
        raise PluginBoundaryError(
            f"role {contribution.name!r} widens core role {bare!r} with capabilities "
            f"{', '.join(extra_capabilities)}; a plugin may narrow a core role, never widen it"
        )
    extra_inputs = sorted(kind.value for kind in contribution.allowed_inputs - core.allowed_inputs)
    if extra_inputs:
        raise PluginBoundaryError(
            f"role {contribution.name!r} lets core role {bare!r} read {', '.join(extra_inputs)}, "
            "which its contract does not allow"
        )
    if contribution.write_scope is not core.write_scope:
        raise PluginBoundaryError(
            f"role {contribution.name!r} changes the write scope of core role {bare!r} from "
            f"{core.write_scope.value!r} to {contribution.write_scope.value!r}"
        )


def build_role_contract(contribution: RoleContribution) -> RoleContract:
    """Turn a checked contribution into the same `RoleContract` the core roles use.

    The contract carries `HUMAN_ONLY_CAPABILITIES` in `forbidden`, so a plugin role that
    somehow reaches `assert_capability_allowed` for an acceptance capability is refused by
    the core's own check and not only by ours.
    """
    return RoleContract(
        name=contribution.name,
        objective=contribution.objective,
        allowed_inputs=contribution.allowed_inputs,
        allowed_capabilities=contribution.allowed_capabilities,
        forbidden=contribution.forbidden,
        output_schema=contribution.schema_type,
        write_scope=contribution.write_scope,
        requirements=contribution.requirements,
        template_version=contribution.template_version,
        system_prompt=contribution.system_prompt,
    )


# ------------------------------------------------------------------------ workflows


def check_workflow(contribution: WorkflowFragmentContribution, manifest: PluginManifest) -> None:
    """Every capability a fragment's stages call must be one the manifest declared."""
    declared = manifest.permissions.capabilities
    for stage in contribution.stages:
        denied = sorted(name for name in stage.capabilities if is_denied_capability(name))
        if denied:
            raise PluginBoundaryError(
                f"workflow {contribution.name!r} stage {stage.name!r} calls accepted-state "
                f"capabilities: {', '.join(denied)}"
            )
        undeclared = sorted(set(stage.capabilities) - declared)
        if undeclared:
            raise PluginBoundaryError(
                f"workflow {contribution.name!r} stage {stage.name!r} calls undeclared "
                f"capabilities: {', '.join(undeclared)}"
            )
    unknown_roles = sorted(contribution.role_names() - set(ROLES) - manifest.permissions.roles_used)
    if unknown_roles:
        raise PluginBoundaryError(
            f"workflow {contribution.name!r} names unknown roles: {', '.join(unknown_roles)}"
        )


# ------------------------------------------------------------------ search providers


def check_search_provider(
    contribution: SearchProviderContribution, manifest: PluginManifest
) -> None:
    """A connector may only contact a host the manifest disclosed (Product 34)."""
    if contribution.endpoint_host not in manifest.egress_hosts:
        declared = ", ".join(sorted(manifest.egress_hosts)) or "nothing"
        raise PluginBoundaryError(
            f"search provider {contribution.name!r} contacts {contribution.endpoint_host!r}, "
            f"which plugin {manifest.name!r} does not declare; it declares: {declared}"
        )


# ------------------------------------------------------------------- writing policies


def check_writing_policy(contribution: WritingPolicyContribution, manifest: PluginManifest) -> None:
    """A writing policy constrains wording only, and never drops a protected span."""
    _require_namespace(contribution.name, "writing policy", manifest)
    dropped = contribution.dropped_protections()
    if dropped:
        names = ", ".join(sorted(kind.value for kind in dropped))
        raise PluginBoundaryError(
            f"writing policy {contribution.name!r} of plugin {manifest.name!r} drops core "
            f"protected spans: {names}; a style pass may change wording, never a protected "
            "span (Product 30.4)"
        )
    if contribution.authority != "candidate_only":  # pragma: no cover - the model pins it
        raise PluginBoundaryError(
            f"writing policy {contribution.name!r} claims authority "
            f"{contribution.authority!r}; a policy produces manuscript candidates only"
        )


# ------------------------------------------------------------------------ whole plugin


def check_declared_files(manifest: PluginManifest, directory: Path) -> Mapping[str, Path]:
    """Resolve every declared contribution path, refusing missing files and escapes."""
    resolved: dict[str, Path] = {}
    for relative in manifest.contributes.all_paths():
        path = resolve_inside(directory, relative)
        if not path.is_file():
            raise PluginBoundaryError(
                f"plugin {manifest.name!r} declares {relative!r}, which is not a file"
            )
        resolved[relative] = path
    return resolved


def scan_declared_modules(manifest: PluginManifest, resolved: Mapping[str, Path]) -> None:
    """Statically scan every declared module before any of it is executed."""
    for relative in manifest.contributes.python_paths():
        scan_module(resolved[relative], plugin=manifest.name)


def unreachable_capabilities(names: Iterable[str]) -> Sequence[str]:
    """The subset of `names` a plugin can never call, for reporting in an error."""
    return sorted(
        name
        for name in names
        if is_denied_capability(name) or name not in PLUGIN_ALLOWED_CAPABILITIES
    )


def write_scope_is_candidate(scope: WriteScope) -> bool:
    """True when `scope` stages a candidate rather than writing nothing."""
    return scope is not WriteScope.NONE
