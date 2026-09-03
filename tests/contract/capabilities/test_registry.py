"""Task 10.1: the registry exposes Product 22 names, and enforces permissions server-side.

The registry is the one place a permission check cannot be skipped, so these tests are about
refusals as much as about discovery: an agent host reading is fine, an agent host accepting
evidence is not, and a name with no implementation is absent rather than faked.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.permissions import (
    AGENT_HOST_PERMISSIONS,
    CapabilityNotFound,
    InvalidRequest,
    Permission,
    PermissionDenied,
    Principal,
    PrincipalKind,
)
from research_harness.capabilities.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    MutationResponse,
    build_default_registry,
)

#: The Product 22 capability list, verbatim. Every one of these is either registered with a
#: real handler or listed as planned with a reason; none of them may quietly disappear.
PRODUCT_22_NAMES: tuple[str, ...] = (
    "corpus.search",
    "corpus.ingest",
    "corpus.screen",
    "work.get",
    "work.parse",
    "work.interrogate",
    "retrieval.search",
    "retrieval.resolve_source",
    "evidence.extract",
    "evidence.verify",
    "evidence.accept",
    "evidence.reject",
    "claim.create",
    "claim.find_support",
    "claim.find_counterevidence",
    "claim.audit",
    "question.create",
    "question.resolve",
    "synthesis.compare",
    "synthesis.build_matrix",
    "synthesis.find_pattern",
    "manuscript.draft",
    "manuscript.attach_claim",
    "manuscript.audit",
    "citation.verify",
    "review.inbox",
    "review.accept_batch",
    "review.resolve_conflict",
    "state.rebuild",
    "state.stale",
)


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    """The registry the daemon and the MCP server both serve."""
    return build_default_registry()


def test_every_product_22_name_is_registered_or_planned(registry: CapabilityRegistry) -> None:
    known = set(registry.names()) | {item.name for item in registry.planned()}
    assert set(PRODUCT_22_NAMES) <= known


def test_planned_names_have_no_handler_and_say_why(registry: CapabilityRegistry) -> None:
    planned = registry.planned()
    assert planned, "a build with nothing planned should say so explicitly"
    for item in planned:
        assert item.name not in registry
        assert item.reason.strip(), f"{item.name} is planned without a reason"
        with pytest.raises(CapabilityNotFound) as refused:
            registry.get(item.name)
        assert item.reason in str(refused.value)


def test_internal_phase_one_handlers_are_registered(registry: CapabilityRegistry) -> None:
    """Phase 10 adds discovery over the Phase 1 handlers; it does not drop any of them."""
    for name in ("decision.accept", "note.add", "note.promote", "taxonomy.put", "work.register"):
        assert name in registry


def test_describe_is_json_able_and_carries_both_schemas(registry: CapabilityRegistry) -> None:
    descriptors = registry.describe()
    assert [item.name for item in descriptors] == list(registry.names())
    for descriptor in descriptors:
        json.dumps(descriptor.model_dump(mode="json"))
        assert descriptor.request_schema.get("type") == "object"
        assert descriptor.response_schema
        assert descriptor.scientific_semantics.strip()


def test_every_spec_declares_its_scientific_semantics(registry: CapabilityRegistry) -> None:
    """Product 22: a capability declares what it may change, in scientific terms."""
    for spec in registry:
        assert issubclass(spec.request_model, BaseModel)
        assert issubclass(spec.response_model, BaseModel)
        assert spec.permission in set(Permission)
        assert len(spec.scientific_semantics.split()) >= 3


def test_mutating_capabilities_are_marked_human_only(registry: CapabilityRegistry) -> None:
    """Accepted-state mutation is a researcher act, so the descriptor says so up front."""
    for descriptor in registry.describe():
        if descriptor.permission in {Permission.MUTATE, Permission.ADMIN}:
            assert descriptor.human_only


def test_every_plugin_allowed_capability_is_a_read_or_a_stage(
    registry: CapabilityRegistry,
) -> None:
    """ADR-010: a plugin reads and proposes. It never reaches a capability that accepts.

    `plugins.PLUGIN_ALLOWED_CAPABILITIES` is what a manifest may ask for, and this is the
    property that makes the list safe to grant: every name on it must be `read` or `stage`
    in the registry, because a `mutate` name granted to a plugin passes the gateway and is
    then refused for want of human authority - a refusal the manifest author cannot see
    coming.

    There is no exemption. `corpus.search` used to be one: it is `mutate`, because it
    records a canonical `SearchRun`, and it was on the plugin surface all the same. It came
    off the surface instead (dogfood F-plugin allowlist); a plugin that needs discovery runs
    it through a workflow fragment the host approves.
    """
    from research_harness.plugins.manifest import PLUGIN_ALLOWED_CAPABILITIES

    offenders = {
        name
        for name in PLUGIN_ALLOWED_CAPABILITIES
        if name in registry
        and registry.get(name).permission not in {Permission.READ, Permission.STAGE}
    }
    assert offenders == set(), (
        f"{sorted(offenders)} are plugin-allowed but change accepted state; either give "
        "them `read`/`stage` semantics or take them off "
        "`plugins.PLUGIN_ALLOWED_CAPABILITIES`"
    )


def test_corpus_search_is_off_the_plugin_surface(registry: CapabilityRegistry) -> None:
    """A `mutate` capability is not something a manifest may ask for (ADR-010, ADR-020)."""
    from research_harness.plugins.manifest import PLUGIN_ALLOWED_CAPABILITIES

    assert registry.get("corpus.search").permission is Permission.MUTATE
    assert "corpus.search" not in PLUGIN_ALLOWED_CAPABILITIES


def test_no_capability_exposes_raw_sql_or_a_write_path(registry: CapabilityRegistry) -> None:
    """ADR-004: there is no `execute_sql` and no `patch_object`, by name or by field."""
    forbidden = {"sql", "statement_sql", "query_sql", "patch", "write_path", "destination"}
    for spec in registry:
        assert "sql" not in spec.name
        properties = spec.request_model.model_json_schema().get("properties", {})
        assert not forbidden & set(properties), f"{spec.name} exposes {forbidden & set(properties)}"


# -- invocation --------------------------------------------------------------


def test_invoke_validates_the_request_dto(project: CapabilityContext) -> None:
    registry = build_default_registry()
    with pytest.raises(InvalidRequest) as refused:
        registry.invoke("note.add", project, {"not_a_field": 1}, principal=Principal.human())
    assert "note.add" in str(refused.value)


def test_invoke_refuses_an_unknown_capability(project: CapabilityContext) -> None:
    registry = build_default_registry()
    with pytest.raises(CapabilityNotFound):
        registry.invoke("nonsense.capability", project, {}, principal=Principal.human())


def test_invoke_returns_the_declared_response_model(project: CapabilityContext) -> None:
    registry = build_default_registry()
    response = registry.invoke(
        "note.add", project, {"text": "a captured thought"}, principal=Principal.human()
    )
    assert isinstance(response, MutationResponse)
    assert response.capability == "note.add"
    assert response.event.event.value == "note.captured"


def test_an_agent_host_may_read_but_may_not_mutate(project: CapabilityContext) -> None:
    """Product 29: hosts read and propose; the researcher accepts."""
    registry = build_default_registry()
    host = Principal.agent_host("some-host")
    assert host.granted == AGENT_HOST_PERMISSIONS

    with pytest.raises(PermissionDenied) as refused:
        registry.invoke("note.add", project, {"text": "host wrote this"}, principal=host)
    assert "may not" in str(refused.value) or "does not hold" in str(refused.value)

    stale = registry.invoke("state.stale", project, {}, principal=host)
    assert stale.model_dump()["count"] == 0


def test_a_model_principal_may_not_accept_evidence(project: CapabilityContext) -> None:
    registry = build_default_registry()
    model = Principal.model("vendor-a/model-x")
    assert model.kind is PrincipalKind.MODEL
    with pytest.raises(PermissionDenied):
        registry.invoke("evidence.accept", project, {}, principal=model)


def test_permission_is_checked_before_the_request_is_validated(
    project: CapabilityContext,
) -> None:
    """A refused caller learns it is refused, not which fields it got wrong."""
    registry = build_default_registry()
    with pytest.raises(PermissionDenied):
        registry.invoke(
            "evidence.accept", project, {"garbage": True}, principal=Principal.agent_host("h")
        )


def test_a_human_principal_cannot_mutate_through_a_model_context(
    project: CapabilityContext,
) -> None:
    """The principal says who asked; the context says whose authority is recorded."""
    registry = build_default_registry()
    as_model = CapabilityContext(repo=project.repo, actor="vendor-a/model-x")
    with pytest.raises(PermissionDenied) as refused:
        registry.invoke("note.add", as_model, {"text": "x"}, principal=Principal.human())
    assert "not the researcher" in str(refused.value)


# -- registration ------------------------------------------------------------


def _spec(name: str) -> CapabilitySpec:
    class _Empty(BaseModel):
        pass

    def handler(ctx: CapabilityContext, request: Any) -> BaseModel:
        del ctx, request
        return _Empty()

    return CapabilitySpec(
        name=name,
        summary="a test capability",
        permission=Permission.READ,
        scientific_semantics="reads nothing at all",
        request_model=_Empty,
        response_model=_Empty,
        handler=handler,
    )


def test_registering_a_name_twice_is_a_wiring_error() -> None:
    registry = CapabilityRegistry()
    registry.register(_spec("x.y"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_spec("x.y"))


def test_a_registered_name_cannot_also_be_planned() -> None:
    registry = CapabilityRegistry()
    registry.register(_spec("x.y"))
    with pytest.raises(ValueError, match="cannot also be planned"):
        registry.plan("x.y", "because")
