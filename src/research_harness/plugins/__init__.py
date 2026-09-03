"""Domain plugins: extension over an invariant core (Product 32, ADR-010).

A plugin adds vocabulary, questions, checks, workflow shape, bounded roles, connectors,
writing policies, and UI descriptors. It does not add authority. Everything a plugin
produces is a candidate, everything it calls goes through one permissioned gateway, and
every core meaning — Evidence, Claim, Decision, accepted state — is unchanged by loading
one.

    from research_harness.plugins import load_plugin

    runtime = load_plugin(Path("plugins/structured-traffic"), gateway=gateway)
    schema = runtime.interrogation_schemas["structured-traffic:paper"]
    issues = runtime.validators["structured-traffic.traffic_unit"].run(candidate)

The three refusals worth knowing before writing a plugin: a contribution module that
imports the workspace or opens a database is refused before it runs; a manifest asking for
an accepted-state capability is refused, and the gateway refuses it a second time whatever
the manifest says; and a vocabulary term equal to a core enum value is refused, because
core meanings cannot be redefined.
"""

from __future__ import annotations

from research_harness.plugins.loader import discover_plugins, load_plugin
from research_harness.plugins.manifest import (
    DENIED_CAPABILITIES,
    MANIFEST_FILENAME,
    PLUGIN_ALLOWED_CAPABILITIES,
    Contributions,
    PluginBoundaryError,
    PluginEgress,
    PluginError,
    PluginLoadError,
    PluginManifest,
    PluginManifestError,
    PluginPermissions,
    core_version_satisfies,
    is_denied_capability,
    load_manifest,
    namespaces_for,
)
from research_harness.plugins.spi import (
    CORE_PROTECTED_SPAN_KINDS,
    PLUGIN_ROLE_OUTPUT_SCHEMAS,
    PLUGIN_ROLE_WRITE_SCOPES,
    CapabilityGateway,
    InterrogationContribution,
    IssueSeverity,
    LoadedValidator,
    PermissionedGateway,
    PluginRuntime,
    PluginVocabulary,
    RoleContribution,
    SchemaContribution,
    SearchProviderContribution,
    SearchProviderFactory,
    UiExtensionDescriptor,
    ValidationIssue,
    ValidatorContribution,
    VocabularyField,
    VocabularyTerm,
    WordingConstraint,
    WorkflowFragmentContribution,
    WorkflowStageDescriptor,
    WritingPolicyContribution,
    ensure_plain_data,
    merge_interrogation,
)
from research_harness.plugins.validation import (
    FORBIDDEN_CALL_NAMES,
    FORBIDDEN_IMPORTS,
    FORBIDDEN_METHOD_NAMES,
    build_role_contract,
    scan_module,
)

__all__ = [
    "CORE_PROTECTED_SPAN_KINDS",
    "DENIED_CAPABILITIES",
    "FORBIDDEN_CALL_NAMES",
    "FORBIDDEN_IMPORTS",
    "FORBIDDEN_METHOD_NAMES",
    "MANIFEST_FILENAME",
    "PLUGIN_ALLOWED_CAPABILITIES",
    "PLUGIN_ROLE_OUTPUT_SCHEMAS",
    "PLUGIN_ROLE_WRITE_SCOPES",
    "CapabilityGateway",
    "Contributions",
    "InterrogationContribution",
    "IssueSeverity",
    "LoadedValidator",
    "PermissionedGateway",
    "PluginBoundaryError",
    "PluginEgress",
    "PluginError",
    "PluginLoadError",
    "PluginManifest",
    "PluginManifestError",
    "PluginPermissions",
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
    "build_role_contract",
    "core_version_satisfies",
    "discover_plugins",
    "ensure_plain_data",
    "is_denied_capability",
    "load_manifest",
    "load_plugin",
    "merge_interrogation",
    "namespaces_for",
    "scan_module",
]
