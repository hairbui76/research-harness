"""Reaching a domain plugin from the command line, without widening what a plugin may do.

`research interrogate --schema plugin:<plugin-name>[:<schema>]` is the whole surface. It
loads one plugin directory through :func:`research_harness.plugins.load_plugin`, which
runs the manifest, declared-file, and static-scan checks *before* any plugin code, wraps
the harness in a :class:`~research_harness.plugins.PermissionedGateway` bounded by the
manifest's declared capabilities, and merges each interrogation contribution beside the
core schema with `merge_interrogation` (ADR-010, Product 32.2).

Nothing here hands a plugin a repository, a context, or a path into the workspace: the
gateway forwards named capability calls to the registry and refuses everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

import research_harness
from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.permissions import Principal
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.errors import ResearchHarnessError
from research_harness.evidence.interrogation import InterrogationSchema
from research_harness.plugins import PluginError, PluginRuntime, discover_plugins, load_plugin

__all__ = [
    "BUNDLED_PLUGINS_DIR",
    "PLUGIN_DIRNAME",
    "PLUGIN_SCHEMA_PREFIX",
    "RegistryGateway",
    "load_named_plugin",
    "plugin_interrogation_schema",
    "plugin_roots",
]

PLUGIN_SCHEMA_PREFIX = "plugin:"
"""What marks a `--schema` value as a plugin reference rather than a name or a file."""

PLUGIN_DIRNAME = "plugins"

BUNDLED_PLUGINS_DIR = Path(research_harness.__file__).resolve().parents[2] / PLUGIN_DIRNAME
"""The harness's own top-level `plugins/` directory, when running from a source tree."""


@dataclass(frozen=True, slots=True)
class RegistryGateway:
    """The inner gateway a plugin reaches the harness through: named capabilities only.

    `load_plugin` wraps this in a `PermissionedGateway` bounded by the plugin's manifest,
    so a call arrives here only after the core deny list, the plugin surface, and the
    manifest have all allowed it. The principal is an agent host, never the researcher:
    a plugin reads and proposes, and accepted state is reached only through human review
    (Product 24, 29; ADR-007).
    """

    ctx: CapabilityContext
    registry: CapabilityRegistry
    principal: Principal

    def call(self, name: str, request: BaseModel, *, actor: str) -> object:
        """Invoke the named capability on behalf of ``actor``."""
        return self.registry.invoke(name, self.ctx, request, principal=self.principal)


def plugin_roots(root: Path | None = None) -> tuple[Path, ...]:
    """Where the CLI looks for plugin directories, most specific first.

    A workspace may carry its own `plugins/`; the harness's top-level `plugins/` holds the
    ones shipped with it. Only directories that exist are returned, so an installed wheel
    with no bundled plugins simply searches one place less.
    """
    roots: list[Path] = []
    if root is not None:
        workspace_plugins = Path(root) / PLUGIN_DIRNAME
        if workspace_plugins.is_dir():
            roots.append(workspace_plugins)
    if BUNDLED_PLUGINS_DIR.is_dir():
        roots.append(BUNDLED_PLUGINS_DIR)
    return tuple(roots)


def load_named_plugin(ctx: CapabilityContext, name: str) -> PluginRuntime:
    """Load the plugin called ``name`` from the workspace's roots, or say where it looked."""
    roots = plugin_roots(ctx.root)
    for directory in discover_plugins(roots):
        if directory.name != name:
            continue
        registry = build_default_registry()
        gateway = RegistryGateway(
            ctx=ctx,
            registry=registry,
            principal=Principal.agent_host(f"plugin:{name}"),
        )
        return load_plugin(directory, gateway=gateway)
    available = ", ".join(sorted(item.name for item in discover_plugins(roots))) or "none"
    searched = ", ".join(str(item) for item in roots) or "no plugin directory"
    raise ResearchHarnessError(f"no plugin named {name!r} under {searched} (found: {available})")


def plugin_interrogation_schema(ctx: CapabilityContext, reference: str) -> InterrogationSchema:
    """Resolve ``plugin:<plugin-name>[:<schema>]`` to the merged interrogation schema.

    With no schema part the plugin must contribute exactly one, which is the common case;
    naming several without saying which is a question the CLI refuses to answer for the
    researcher. The returned schema is the plugin's fields merged *beside* the core ones by
    `merge_interrogation`, so a plugin adds questions and never removes one.
    """
    body = reference[len(PLUGIN_SCHEMA_PREFIX) :]
    plugin_name, _, schema_name = body.partition(":")
    if not plugin_name:
        raise ResearchHarnessError(
            f"{reference!r} names no plugin; use --schema plugin:<plugin-name>[:<schema>]"
        )
    try:
        runtime = load_named_plugin(ctx, plugin_name)
    except PluginError as exc:
        raise ResearchHarnessError(f"plugin {plugin_name!r} could not be loaded: {exc}") from exc
    schemas = runtime.interrogation_schemas
    if not schemas:
        raise ResearchHarnessError(f"plugin {plugin_name!r} contributes no interrogation schema")
    if not schema_name:
        if len(schemas) > 1:
            names = ", ".join(sorted(schemas))
            raise ResearchHarnessError(
                f"plugin {plugin_name!r} contributes several interrogation schemas; name "
                f"one: {names}"
            )
        return next(iter(schemas.values()))
    qualified = f"{plugin_name}:{schema_name}"
    schema = schemas.get(qualified) or schemas.get(schema_name)
    if schema is None:
        names = ", ".join(sorted(schemas))
        raise ResearchHarnessError(
            f"plugin {plugin_name!r} has no interrogation schema {schema_name!r} (has: {names})"
        )
    return schema
