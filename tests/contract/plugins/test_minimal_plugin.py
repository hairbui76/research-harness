"""ROADMAP Task 14.3: an example plugin adds a field and a validator, and changes nothing else.

The `minimal` fixture contributes to all eight extension points of Product 32.1. These
tests show what it gained (its own interrogation schema, validator, role, policy, and
connector) and what it did not gain (any authority the core did not already grant).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.domain.errors import AuthorityError
from research_harness.evidence.interrogation import DEFAULT_SCHEMA, ValueKind
from research_harness.manuscript.protected import ProtectedSpanKind
from research_harness.plugins import (
    PLUGIN_ALLOWED_CAPABILITIES,
    IssueSeverity,
    PluginBoundaryError,
    PluginRuntime,
    load_plugin,
)
from research_harness.roles.contracts import (
    HUMAN_ONLY_CAPABILITIES,
    InputKind,
    WriteScope,
    assert_can_read,
    assert_can_write,
    assert_capability_allowed,
)
from research_harness.roles.registry import ROLES
from research_harness.roles.schemas import ClaimAuditOutput

from .conftest import RecordingGateway, Request

SCHEMA_NAME = "minimal:paper"
FIELD = "minimal.traffic_unit"
ROLE = "minimal.domain_reviewer"


@pytest.fixture
def runtime(minimal_dir: Path, gateway: RecordingGateway) -> PluginRuntime:
    """The loaded example plugin."""
    return load_plugin(minimal_dir, gateway=gateway)


def test_manifest_identifies_the_plugin(runtime: PluginRuntime) -> None:
    assert runtime.name == "minimal"
    assert runtime.version == "0.1.0"
    assert runtime.manifest.namespaces == frozenset({"minimal"})


# ------------------------------------------------------------------ interrogation field


def test_the_merged_schema_carries_the_plugin_field(runtime: PluginRuntime) -> None:
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    assert FIELD in schema.names
    field = schema.field(FIELD)
    assert field.value_kind is ValueKind.CATEGORICAL
    assert field.categories == ("packet", "flow", "session")


def test_the_merged_schema_keeps_every_core_question(runtime: PluginRuntime) -> None:
    schema = runtime.interrogation_schemas[SCHEMA_NAME]
    assert set(DEFAULT_SCHEMA.names).issubset(schema.names)
    assert schema.fingerprint() != DEFAULT_SCHEMA.fingerprint()


def test_the_core_schema_is_untouched_by_the_merge(runtime: PluginRuntime) -> None:
    assert FIELD not in DEFAULT_SCHEMA.names
    assert DEFAULT_SCHEMA.name == "generic-empirical"


# --------------------------------------------------------------------------- validator


def test_the_validator_flags_a_value_outside_the_project_taxonomy(runtime: PluginRuntime) -> None:
    validator = runtime.validators["minimal.traffic_unit"]
    issues = validator.run({"field": FIELD, "value": "datagram"})
    assert len(issues) == 1
    assert issues[0].field == FIELD
    assert issues[0].severity is IssueSeverity.ERROR
    assert "datagram" in issues[0].message


def test_the_validator_accepts_a_taxonomy_value_and_a_hybrid(runtime: PluginRuntime) -> None:
    validator = runtime.validators["minimal.traffic_unit"]
    assert validator.run({"field": FIELD, "value": "flow"}) == ()
    assert validator.run({"field": FIELD, "value": ["packet", "flow"]}) == ()


def test_the_validator_ignores_candidates_for_other_fields(runtime: PluginRuntime) -> None:
    validator = runtime.validators["minimal.traffic_unit"]
    assert validator.run({"field": "dataset", "value": "anything"}) == ()


def test_a_missing_value_is_a_warning_not_an_absence_claim(runtime: PluginRuntime) -> None:
    """`not recorded` is a warning; `absent` stays an audited researcher conclusion."""
    issues = runtime.validators["minimal.traffic_unit"].run({"field": FIELD, "value": None})
    assert [issue.severity for issue in issues] == [IssueSeverity.WARNING]


# -------------------------------------------------------------------------------- role


def test_the_plugin_role_is_not_in_the_core_registry(runtime: PluginRuntime) -> None:
    """Core roles are exactly what they were; a plugin role lives on its own runtime."""
    assert ROLE not in ROLES
    assert sorted(runtime.roles) == [ROLE]


def test_the_plugin_role_writes_only_its_own_candidate_scope(runtime: PluginRuntime) -> None:
    contract = runtime.roles[ROLE]
    assert contract.write_scope is WriteScope.AUDIT_RESULT
    assert_can_write(contract, WriteScope.AUDIT_RESULT)
    for scope in (WriteScope.STAGING_EVIDENCE, WriteScope.MANUSCRIPT_CANDIDATE, WriteScope.NONE):
        with pytest.raises(AuthorityError):
            assert_can_write(contract, scope)


def test_the_plugin_role_reads_only_what_it_declared(runtime: PluginRuntime) -> None:
    contract = runtime.roles[ROLE]
    assert_can_read(contract, InputKind.ACCEPTED_EVIDENCE)
    with pytest.raises(AuthorityError):
        assert_can_read(contract, InputKind.MANUSCRIPT_TEXT)


def test_the_plugin_role_cannot_call_an_acceptance_capability(runtime: PluginRuntime) -> None:
    contract = runtime.roles[ROLE]
    assert contract.allowed_capabilities <= PLUGIN_ALLOWED_CAPABILITIES
    assert contract.forbidden >= HUMAN_ONLY_CAPABILITIES
    assert_capability_allowed(contract, "work.get")
    for capability in ("evidence.accept", "review.accept_batch", "decision.accept"):
        with pytest.raises(AuthorityError):
            assert_capability_allowed(contract, capability)


def test_the_plugin_role_answers_with_a_core_schema(runtime: PluginRuntime) -> None:
    """A plugin configures a role; it does not invent the shape of a scientific answer."""
    assert runtime.roles[ROLE].output_schema is ClaimAuditOutput


# --------------------------------------------------------------------- workflow fragment


def test_the_workflow_fragment_calls_only_declared_capabilities(runtime: PluginRuntime) -> None:
    fragment = runtime.workflow_fragments["minimal.traffic_audit"]
    assert fragment.capability_names() <= runtime.manifest.permissions.capabilities
    assert fragment.capability_names() <= PLUGIN_ALLOWED_CAPABILITIES
    assert [stage.name for stage in fragment.stages] == [
        "read_work",
        "extract_traffic_unit",
        "queue_for_review",
    ]


# ------------------------------------------------------------------------ writing policy


def test_the_writing_policy_is_candidate_only_and_protects_every_core_span(
    runtime: PluginRuntime,
) -> None:
    policy = runtime.writing_policies["minimal.house_style"]
    assert policy.authority == "candidate_only"
    assert policy.dropped_protections() == frozenset()
    assert policy.protected_spans >= frozenset(ProtectedSpanKind)
    assert {constraint.name for constraint in policy.wording_constraints} == {
        "no_unbounded_novelty",
        "hedge_stacking",
    }


# ------------------------------------------------------------------------ search provider


def test_the_search_provider_is_built_lazily_and_declares_its_egress(
    runtime: PluginRuntime,
) -> None:
    factory = runtime.search_providers["minimal-example-index"]
    assert factory.endpoint_host in runtime.manifest.egress_hosts
    provider = factory.build({})
    egress = provider.capabilities().egress
    assert egress.endpoint_host == "index.example.org"
    assert egress.sends_source_text is False


def test_a_provider_contacting_an_undeclared_host_is_refused(runtime: PluginRuntime) -> None:
    factory = runtime.search_providers["minimal-example-index"]
    narrowed = type(factory)(
        name=factory.name,
        plugin=factory.plugin,
        source=factory.source,
        endpoint_host=factory.endpoint_host,
        declared_hosts=frozenset({"declared.example.org"}),
        build_fn=factory.build_fn,
    )
    with pytest.raises(PluginBoundaryError, match="does not declare"):
        narrowed.build({})


# ------------------------------------------------------------------------- ui extension


def test_the_ui_descriptor_is_data_only(runtime: PluginRuntime) -> None:
    descriptor = runtime.ui_extensions["minimal.traffic_matrix"]
    assert descriptor.view == "matrix"
    assert FIELD in descriptor.fields


# ----------------------------------------------------------------------------- gateway


def test_the_runtime_gateway_enforces_the_manifest(
    runtime: PluginRuntime,
    gateway: RecordingGateway,
) -> None:
    assert runtime.gateway.call("work.get", Request(), actor="plugin:minimal") is not None
    with pytest.raises(PluginBoundaryError):
        runtime.gateway.call("claim.find_support", Request(), actor="plugin:minimal")
    assert gateway.calls == [("work.get", "plugin:minimal")]
