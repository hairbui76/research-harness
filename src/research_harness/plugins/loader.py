"""Turn a plugin directory into a bounded `PluginRuntime`, or refuse to load it.

Load order is the boundary: manifest, then declared files, then a static scan of every
module, then the boundary checks, and only then is any plugin code executed. A plugin that
fails any step contributes nothing — there is no partial load, because a half-loaded
plugin would have already run the code the scan was meant to stop.

Modules are executed with `runpy.run_path`, which gives each one a fresh namespace and
keeps it out of `sys.modules`: two plugins may each ship `validators/traffic_unit.py`
without colliding, and neither becomes importable by anything else in the process.
"""

from __future__ import annotations

import logging
import runpy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from research_harness import __version__
from research_harness.evidence.interrogation import InterrogationSchema
from research_harness.plugins.manifest import (
    MANIFEST_FILENAME,
    PluginBoundaryError,
    PluginError,
    PluginLoadError,
    PluginManifest,
    PluginManifestError,
    load_manifest,
    manifest_paths,
)
from research_harness.plugins.spi import (
    CapabilityGateway,
    InterrogationContribution,
    LoadedValidator,
    PermissionedGateway,
    PluginRuntime,
    PluginVocabulary,
    RoleContribution,
    SchemaContribution,
    SearchProviderContribution,
    SearchProviderFactory,
    UiExtensionDescriptor,
    WorkflowFragmentContribution,
    WritingPolicyContribution,
    merge_interrogation,
)
from research_harness.plugins.validation import (
    build_role_contract,
    check_declared_files,
    check_interrogation,
    check_role,
    check_search_provider,
    check_vocabulary,
    check_workflow,
    check_writing_policy,
    scan_declared_modules,
)
from research_harness.roles.contracts import RoleContract

logger = logging.getLogger(__name__)

__all__ = [
    "PluginBoundaryError",
    "PluginError",
    "PluginLoadError",
    "PluginManifestError",
    "discover_plugins",
    "load_plugin",
]


def discover_plugins(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Plugin directories under `roots`, sorted; a root holding a manifest counts itself."""
    return manifest_paths(roots)


def load_plugin(
    plugin_dir: Path,
    *,
    gateway: CapabilityGateway,
    core_version: str = __version__,
) -> PluginRuntime:
    """Load one plugin, refusing it outright if any boundary check fails."""
    directory = plugin_dir.resolve()
    manifest = load_manifest(directory / MANIFEST_FILENAME)
    if not manifest.satisfied_by(core_version):
        raise PluginManifestError(
            f"plugin {manifest.name!r} requires core {manifest.requires_core}, "
            f"but this core is {core_version}"
        )

    resolved = check_declared_files(manifest, directory)
    scan_declared_modules(manifest, resolved)

    vocabulary = _load_vocabulary(manifest, resolved)
    schemas = _load_interrogation(manifest, resolved)
    validators = _load_validators(manifest, resolved)
    fragments = _load_workflows(manifest, resolved)
    roles = _load_roles(manifest, resolved)
    providers = _load_search_providers(manifest, resolved)
    policies = _load_writing_policies(manifest, resolved)
    ui_extensions = _load_ui_extensions(manifest, resolved)

    logger.info(
        "loaded plugin %s %s: %d interrogation schema(s), %d validator(s), %d role(s)",
        manifest.name,
        manifest.version,
        len(schemas),
        len(validators),
        len(roles),
    )
    return PluginRuntime(
        manifest=manifest,
        directory=directory,
        vocabulary=vocabulary,
        interrogation_schemas=schemas,
        validators=validators,
        workflow_fragments=fragments,
        roles=roles,
        search_providers=providers,
        writing_policies=policies,
        ui_extensions=ui_extensions,
        gateway=PermissionedGateway(gateway, manifest.permissions),
    )


# --------------------------------------------------------------------------- helpers


def _yaml_mapping(path: Path, relative: str) -> dict[str, Any]:
    """Read one contribution file as a YAML mapping."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PluginLoadError(f"cannot read contribution {relative!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginLoadError(
            f"contribution {relative!r} must contain a YAML mapping, not {type(data).__name__}"
        )
    return data


def _model[T: BaseModel](model: type[T], data: Mapping[str, Any], relative: str) -> T:
    try:
        return model.model_validate(dict(data))
    except ValueError as exc:
        raise PluginLoadError(
            f"contribution {relative!r} is not a valid {model.__name__}: {exc}"
        ) from exc


def _load_vocabulary(manifest: PluginManifest, resolved: Mapping[str, Path]) -> PluginVocabulary:
    contributions: list[SchemaContribution] = []
    for relative in manifest.contributes.schemas:
        contribution = _model(
            SchemaContribution, _yaml_mapping(resolved[relative], relative), relative
        )
        check_vocabulary(contribution, manifest)
        contributions.append(contribution)
    return PluginVocabulary.of(contributions)


def _load_interrogation(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, InterrogationSchema]:
    schemas: dict[str, InterrogationSchema] = {}
    for relative in manifest.contributes.interrogation:
        contribution = _model(
            InterrogationContribution, _yaml_mapping(resolved[relative], relative), relative
        )
        check_interrogation(contribution, manifest)
        schema = merge_interrogation(manifest.name, contribution)
        schemas[schema.name] = schema
    return schemas


def _load_validators(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, LoadedValidator]:
    validators: dict[str, LoadedValidator] = {}
    for relative in manifest.contributes.validators:
        path = resolved[relative]
        namespace = _execute(path, relative, manifest.name)
        function = namespace.get("validate")
        if not callable(function):
            raise PluginLoadError(
                f"validator {relative!r} of plugin {manifest.name!r} must define "
                "validate(candidate) -> list of findings"
            )
        name = f"{manifest.name}.{path.stem}"
        validators[name] = LoadedValidator(
            name=name, plugin=manifest.name, source=path, function=function
        )
    return validators


def _execute(path: Path, relative: str, plugin: str) -> dict[str, Any]:
    """Run a scanned module in a throwaway namespace and return what it defined."""
    try:
        return runpy.run_path(str(path), run_name=f"research_harness.plugin.{plugin}")
    except Exception as exc:
        # Any failure inside plugin code is a load failure: nothing partial is kept.
        raise PluginLoadError(
            f"contribution {relative!r} of plugin {plugin!r} failed: {exc}"
        ) from exc


def _load_workflows(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, WorkflowFragmentContribution]:
    fragments: dict[str, WorkflowFragmentContribution] = {}
    for relative in manifest.contributes.workflows:
        contribution = _model(
            WorkflowFragmentContribution, _yaml_mapping(resolved[relative], relative), relative
        )
        check_workflow(contribution, manifest)
        fragments[contribution.name] = contribution
    return fragments


def _load_roles(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, RoleContract]:
    roles: dict[str, RoleContract] = {}
    for relative in manifest.contributes.roles:
        contribution = _model(
            RoleContribution, _yaml_mapping(resolved[relative], relative), relative
        )
        check_role(contribution, manifest)
        contract = build_role_contract(contribution)
        roles[contract.name] = contract
    return roles


def _load_search_providers(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, SearchProviderFactory]:
    factories: dict[str, SearchProviderFactory] = {}
    for relative in manifest.contributes.search_providers:
        path = resolved[relative]
        namespace = _execute(path, relative, manifest.name)
        descriptor_data = namespace.get("PROVIDER")
        if not isinstance(descriptor_data, Mapping):
            raise PluginLoadError(
                f"search provider {relative!r} of plugin {manifest.name!r} must define a "
                "PROVIDER mapping with 'name' and 'endpoint_host'"
            )
        contribution = _model(
            SearchProviderContribution,
            {**descriptor_data, "module": relative},
            relative,
        )
        check_search_provider(contribution, manifest)
        build = namespace.get("build")
        if not callable(build):
            raise PluginLoadError(
                f"search provider {relative!r} of plugin {manifest.name!r} must define "
                "build(env) -> SearchProvider"
            )
        factories[contribution.name] = SearchProviderFactory(
            name=contribution.name,
            plugin=manifest.name,
            source=path,
            endpoint_host=contribution.endpoint_host,
            declared_hosts=manifest.egress_hosts,
            build_fn=build,
        )
    return factories


def _load_writing_policies(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, WritingPolicyContribution]:
    policies: dict[str, WritingPolicyContribution] = {}
    for relative in manifest.contributes.writing_policies:
        contribution = _model(
            WritingPolicyContribution, _yaml_mapping(resolved[relative], relative), relative
        )
        check_writing_policy(contribution, manifest)
        policies[contribution.name] = contribution
    return policies


def _load_ui_extensions(
    manifest: PluginManifest, resolved: Mapping[str, Path]
) -> Mapping[str, UiExtensionDescriptor]:
    descriptors: dict[str, UiExtensionDescriptor] = {}
    for relative in manifest.contributes.ui_extensions:
        contribution = _model(
            UiExtensionDescriptor, _yaml_mapping(resolved[relative], relative), relative
        )
        descriptors[contribution.name] = contribution
    return descriptors
