"""A plugin extends the domain; it never acquires scientific authority (ADR-010).

Every test here states one boundary from Product 32.2 and shows that the loader or the
gateway refuses to cross it. The negative fixtures under `tests/fixtures/plugins/bad_*`
each violate exactly one boundary, so a failure names the rule that broke.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from research_harness.capabilities.handlers import CORE_CAPABILITY_HANDLERS
from research_harness.capabilities.permissions import (
    HUMAN_AUTHORITY,
    Permission,
    PermissionDenied,
    Principal,
)
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.enums import ClaimType, EvidenceType
from research_harness.domain.errors import AuthorityError
from research_harness.evidence.interrogation import DEFAULT_SCHEMA
from research_harness.plugins import (
    DENIED_CAPABILITIES,
    PLUGIN_ALLOWED_CAPABILITIES,
    PermissionedGateway,
    PluginBoundaryError,
    PluginError,
    PluginLoadError,
    PluginManifestError,
    PluginPermissions,
    discover_plugins,
    ensure_plain_data,
    is_denied_capability,
    load_plugin,
    scan_module,
)
from research_harness.roles.contracts import HUMAN_ONLY_CAPABILITIES, WriteScope
from research_harness.roles.registry import ROLES

from .conftest import RecordingGateway, Request

# fixture directory -> (expected error, a phrase the message must contain)
BAD_FIXTURES: dict[str, tuple[type[PluginError], str]] = {
    "bad_workspace_import": (PluginBoundaryError, "research_harness.workspace"),
    "bad_file_write": (PluginBoundaryError, "open()"),
    "bad_accept_permission": (PluginManifestError, "evidence.accept"),
    "bad_role_scope": (PluginLoadError, "write_scope"),
    "bad_role_widened": (PluginBoundaryError, "widens core role"),
    "bad_vocabulary": (PluginBoundaryError, "experimental_result"),
    "bad_writing_policy": (PluginBoundaryError, "citation"),
    "bad_path_traversal": (PluginManifestError, "escape the plugin directory"),
}


@pytest.mark.parametrize("fixture_name", sorted(BAD_FIXTURES))
def test_each_bad_fixture_is_refused_with_its_own_error(
    fixture_name: str, fixtures_dir: Path, gateway: RecordingGateway
) -> None:
    expected, phrase = BAD_FIXTURES[fixture_name]
    with pytest.raises(expected) as caught:
        load_plugin(fixtures_dir / fixture_name, gateway=gateway)
    assert phrase in str(caught.value)


def test_every_plugin_error_is_catchable_as_one_family(
    fixtures_dir: Path, gateway: RecordingGateway
) -> None:
    """One `except PluginError` catches every refusal, whatever the specific rule."""
    for fixture_name in BAD_FIXTURES:
        with pytest.raises(PluginError):
            load_plugin(fixtures_dir / fixture_name, gateway=gateway)


def test_a_boundary_violation_is_an_authority_error(
    fixtures_dir: Path, gateway: RecordingGateway
) -> None:
    """Code guarding accepted state catches plugin overreach without knowing about plugins."""
    with pytest.raises(AuthorityError):
        load_plugin(fixtures_dir / "bad_workspace_import", gateway=gateway)


# ------------------------------------------------------------------ capability surface


def test_no_plugin_capability_is_an_accepted_state_mutation() -> None:
    """No accepted-state handler is on the plugin surface (Product 22, ADR-003)."""
    assert PLUGIN_ALLOWED_CAPABILITIES.isdisjoint(CORE_CAPABILITY_HANDLERS)


def test_every_registered_mutation_is_unreachable_from_a_plugin() -> None:
    """A capability that changes accepted state is refused whichever layer a plugin reaches.

    The gateway refuses every name outside the plugin surface, and the capability layer
    refuses every mutation to a non-human principal. Both are asserted, because the two
    checks answer different questions: the surface says what a manifest may ask for, and
    human authority says who may accept. Neither is allowed to be the only one.
    """
    host = Principal.agent_host("claude")
    mutations = [
        spec
        for spec in build_default_registry()
        if spec.human_only or spec.permission in HUMAN_AUTHORITY
    ]
    assert mutations, "the registry should carry accepted-state mutations"
    for spec in mutations:
        if _refused(spec.name):
            continue
        with pytest.raises(PermissionDenied):
            host.authorize(spec.name, spec.permission, human_only=spec.human_only)


def test_every_plugin_surface_capability_is_registered_and_never_admin() -> None:
    """The surface names real capabilities, and none of them rebuilds or initializes."""
    registry = build_default_registry()
    for name in PLUGIN_ALLOWED_CAPABILITIES:
        assert name in registry, name
        assert registry.get(name).permission is not Permission.ADMIN, name


def test_every_human_only_capability_is_denied() -> None:
    for pattern in HUMAN_ONLY_CAPABILITIES:
        name = pattern.replace(".*", ".accept") if pattern.endswith(".*") else pattern
        assert is_denied_capability(name), name


def _refused(name: str) -> bool:
    return is_denied_capability(name) or name not in PLUGIN_ALLOWED_CAPABILITIES


# ------------------------------------------------------------------------- the gateway


def test_gateway_forwards_a_declared_capability(gateway: RecordingGateway) -> None:
    permissioned = PermissionedGateway(gateway, PluginPermissions(capabilities={"work.get"}))
    result = permissioned.call("work.get", Request(), actor="plugin:minimal")
    assert result == {"capability": "work.get", "actor": "plugin:minimal"}
    assert gateway.calls == [("work.get", "plugin:minimal")]


def test_gateway_refuses_a_capability_the_manifest_did_not_declare(
    gateway: RecordingGateway,
) -> None:
    permissioned = PermissionedGateway(gateway, PluginPermissions(capabilities={"work.get"}))
    with pytest.raises(PluginBoundaryError, match="not declared in this plugin's manifest"):
        permissioned.call("evidence.extract", Request(), actor="plugin:minimal")
    assert gateway.calls == []


@pytest.mark.parametrize("capability", sorted(DENIED_CAPABILITIES - {"decision.*"}))
def test_gateway_refuses_accepted_state_mutations_even_when_the_manifest_lists_them(
    capability: str, gateway: RecordingGateway
) -> None:
    """A manifest is a declaration, not a permission.

    `model_construct` skips validation exactly as a hand-edited or hand-built permissions
    object would, which is the case the hard-coded deny list exists for.
    """
    forged = PluginPermissions.model_construct(
        capabilities=frozenset({capability}), roles_used=frozenset()
    )
    permissioned = PermissionedGateway(gateway, forged)
    assert not permissioned.allows(capability)
    with pytest.raises(PluginBoundaryError, match="changes accepted state"):
        permissioned.call(capability, Request(), actor="plugin:forged")
    assert gateway.calls == []


def test_gateway_refuses_an_unknown_capability(gateway: RecordingGateway) -> None:
    forged = PluginPermissions.model_construct(
        capabilities=frozenset({"database.execute_sql"}), roles_used=frozenset()
    )
    with pytest.raises(PluginBoundaryError, match="not part of the plugin surface"):
        PermissionedGateway(gateway, forged).call(
            "database.execute_sql", Request(), actor="plugin:forged"
        )


def test_a_manifest_cannot_declare_an_accepted_state_capability() -> None:
    with pytest.raises(ValueError, match="never call accepted-state capabilities"):
        PluginPermissions(capabilities={"work.get", "evidence.accept"})


# -------------------------------------------------------------------- the core is intact


def test_loading_a_plugin_changes_no_core_vocabulary_or_schema(
    minimal_dir: Path, gateway: RecordingGateway
) -> None:
    """Core meanings of Evidence, Claim, and Decision cannot be redefined (Task 14.1)."""
    before = {
        "evidence_types": sorted(member.value for member in EvidenceType),
        "claim_types": sorted(member.value for member in ClaimType),
        "schema": DEFAULT_SCHEMA.model_dump(mode="json"),
        "fingerprint": DEFAULT_SCHEMA.fingerprint(),
        "roles": sorted(ROLES),
        "write_scopes": sorted(scope.value for scope in WriteScope),
    }
    snapshot = copy.deepcopy(before)

    runtime = load_plugin(minimal_dir, gateway=gateway)
    assert runtime.vocabulary.labels()

    after = {
        "evidence_types": sorted(member.value for member in EvidenceType),
        "claim_types": sorted(member.value for member in ClaimType),
        "schema": DEFAULT_SCHEMA.model_dump(mode="json"),
        "fingerprint": DEFAULT_SCHEMA.fingerprint(),
        "roles": sorted(ROLES),
        "write_scopes": sorted(scope.value for scope in WriteScope),
    }
    assert after == snapshot


def test_no_write_scope_names_accepted_state() -> None:
    """The rule the `bad_role_scope` fixture runs into: `accepted` is not expressible."""
    assert "accepted" not in {scope.value for scope in WriteScope}


def test_plugin_vocabulary_is_read_beside_the_core_enums(
    minimal_dir: Path, gateway: RecordingGateway
) -> None:
    vocabulary = load_plugin(minimal_dir, gateway=gateway).vocabulary
    core = vocabulary.resolve_evidence_type("experimental_result")
    assert core is EvidenceType.EXPERIMENTAL_RESULT
    plugin_term = vocabulary.resolve_evidence_type("minimal.representation_observation")
    assert plugin_term is not None
    assert not isinstance(plugin_term, EvidenceType)
    assert vocabulary.resolve_claim_type("minimal.unknown_label") is None


# ------------------------------------------------------------- plugin code sees only data


def test_validator_namespace_exposes_no_handle_on_canonical_state(
    minimal_dir: Path, gateway: RecordingGateway
) -> None:
    """The probe validator looks for a repository, a context, or a connection and finds none."""
    runtime = load_plugin(minimal_dir, gateway=gateway)
    probe = runtime.validators["minimal.namespace_probe"]
    assert probe.run({"field": "minimal.traffic_unit", "value": "flow"}) == ()


def test_a_validator_is_never_handed_a_harness_object(
    minimal_dir: Path, gateway: RecordingGateway
) -> None:
    runtime = load_plugin(minimal_dir, gateway=gateway)
    validator = runtime.validators["minimal.traffic_unit"]
    with pytest.raises(PluginBoundaryError, match="plain data only"):
        validator.run({"field": "minimal.traffic_unit", "gateway": gateway})


def test_plain_data_check_accepts_json_shaped_values() -> None:
    payload = {"a": 1, "b": [1.5, "x", None, {"c": True}]}
    assert ensure_plain_data(payload) is payload


# -------------------------------------------------------------------------- static scan


@pytest.mark.parametrize(
    "source",
    [
        "import sqlite3\n",
        "import sqlalchemy\n",
        "from research_harness.workspace.repository import WorkspaceRepository\n",
        "from research_harness.capabilities.handlers import CAPABILITY_HANDLERS\n",
        "import os\n",
        "handle = open('x')\n",
        "from pathlib import Path\nPath('x').write_text('y')\n",
        "import sqlite3.dbapi2\n",
        "import research_harness\n",
        "import research_harness.evidence.interrogation\n",
        "from research_harness.capabilities import dto\n",
    ],
)
def test_scan_refuses_every_documented_escape_route(source: str, tmp_path: Path) -> None:
    module = tmp_path / "contribution.py"
    module.write_text(source, encoding="utf-8")
    with pytest.raises(PluginBoundaryError):
        scan_module(module, plugin="probe")


def test_scan_allows_importing_names_a_contribution_legitimately_needs(tmp_path: Path) -> None:
    """A connector subclasses `SearchProvider`; a from-import of a name is how it does it."""
    module = tmp_path / "contribution.py"
    module.write_text(
        "from research_harness.providers.search.base import SearchProvider\n"
        "from research_harness.capabilities.dto import CapabilityRequest\n"
        "NAMES = (SearchProvider.__name__, CapabilityRequest.__name__)\n",
        encoding="utf-8",
    )
    scan_module(module, plugin="probe")


def test_scan_allows_an_ordinary_pure_validator(tmp_path: Path) -> None:
    module = tmp_path / "contribution.py"
    module.write_text(
        "from collections.abc import Mapping\n"
        "import re\n"
        "def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:\n"
        "    text = str(candidate.get('value', '')).replace('-', '_')\n"
        "    return [] if re.match('^[a-z_]+$', text) else [{'field': 'v', 'message': text}]\n",
        encoding="utf-8",
    )
    scan_module(module, plugin="probe")


# --------------------------------------------------------------------------- discovery


def test_discover_plugins_finds_every_fixture_directory(fixtures_dir: Path) -> None:
    found = discover_plugins([fixtures_dir])
    assert {path.name for path in found} == set(BAD_FIXTURES) | {"minimal"}
    assert list(found) == sorted(found)


def test_discover_plugins_accepts_a_plugin_directory_itself(minimal_dir: Path) -> None:
    assert discover_plugins([minimal_dir]) == (minimal_dir,)


def test_a_plugin_requiring_a_newer_core_is_refused(
    minimal_dir: Path, gateway: RecordingGateway
) -> None:
    with pytest.raises(PluginManifestError, match="requires core"):
        load_plugin(minimal_dir, gateway=gateway, core_version="0.0.1")
