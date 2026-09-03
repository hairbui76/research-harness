"""`provider.list`: the model catalog, and the four facts it has to get right.

A model selector is the place a researcher decides where a message goes, so the catalog is
a privacy surface as much as a convenience. Four properties are pinned here:

* it names what a caller passes back (`id`), and the same label the rest of the harness
  prints (`label`);
* `egress_class` is the same vocabulary a `ContextPack` records, so a client can compare
  "where would this go" with "where did that go";
* `available` follows the *policy* first and a credential second, and is never determined
  by contacting anything — the fake environment here holds one key and no server;
* `default` is the router's own answer: the first entry the policy allows, in priority
  order, whether or not it happens to have a key.

Nothing here touches a network. Every entry is configuration, and `_availability` reads the
name of an environment variable, never a value out of `research.yaml`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.capabilities.providers import (
    ListProvidersRequest,
    ProviderCatalog,
    list_providers,
)
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.domain.conversation import EgressClass
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.models.media import DOCUMENT_MEDIA_TYPES, IMAGE_MEDIA_TYPES
from research_harness.workspace.repository import WorkspaceRepository

PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "on-box",
        "kind": "local_openai_compatible",
        "model": "llava-test",
        "base_url": "http://127.0.0.1:11434/v1",
        "priority": 10,
        "capabilities": {"input_media": ["image/png"], "max_context_tokens": 32000},
    },
    {
        "name": "hosted",
        "kind": "anthropic",
        "model": "claude-test-1",
        "priority": 20,
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    {
        "name": "keyless",
        "kind": "openai",
        "model": "gpt-test-1",
        "priority": 30,
        "api_key_env": "OPENAI_API_KEY",
    },
    {
        "name": "retired",
        "kind": "openai",
        "model": "gpt-old",
        "priority": 1,
        "enabled": False,
    },
]


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return build_default_registry()


def configure(root: Path, providers: list[dict[str, Any]], **privacy: Any) -> Path:
    config_path = root / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["providers"] = providers
    if privacy:
        config["privacy"] = {**config.get("privacy", {}), **privacy}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    repo = WorkspaceRepository.init(tmp_path / "project", "provider-catalog")
    return configure(repo.root, PROVIDERS)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """One key present, one absent: the two states `available` has to tell apart."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-test-key-never-printed")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_MODEL_API_KEY", raising=False)
    yield


def catalog(workspace: Path) -> ProviderCatalog:
    return list_providers(open_context(workspace, HUMAN_ACTOR), ListProvidersRequest())


# -- the shape ---------------------------------------------------------------


def test_the_catalog_lists_every_enabled_entry_in_priority_order(
    workspace: Path, env: None
) -> None:
    listed = catalog(workspace)

    assert listed.count == 3
    assert [item.id for item in listed.models] == ["on-box", "hosted", "keyless"]
    assert [item.label for item in listed.models] == [
        "on-box/llava-test",
        "hosted/claude-test-1",
        "keyless/gpt-test-1",
    ]
    assert "retired" not in {item.id for item in listed.models}, "a disabled entry is not routed"


def test_each_row_names_its_adapter_window_and_media(workspace: Path, env: None) -> None:
    served, hosted, _ = catalog(workspace).models

    assert served.provider == "local_openai_compatible"
    assert served.context_tokens == 32000
    assert served.input_media == ("image/png",)
    assert served.vision is True, "declaring an image type means the model can see"

    assert hosted.provider == "anthropic"
    assert set(hosted.input_media) == IMAGE_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES


def test_egress_class_is_the_vocabulary_a_receipt_records(workspace: Path, env: None) -> None:
    """A client compares "where would this go" with `ContextPack.egress` directly."""
    served, hosted, _ = catalog(workspace).models

    assert served.egress_class is EgressClass.LOCAL
    assert hosted.egress_class is EgressClass.EXTERNAL


# -- availability ------------------------------------------------------------


def test_a_local_entry_is_available_without_a_credential(workspace: Path, env: None) -> None:
    served = catalog(workspace).models[0]

    assert served.available and served.unavailable_reason is None


def test_a_hosted_entry_is_available_only_when_its_key_is_in_the_environment(
    workspace: Path, env: None
) -> None:
    _, hosted, keyless = catalog(workspace).models

    assert hosted.available
    assert not keyless.available
    assert keyless.unavailable_reason is not None
    assert "OPENAI_API_KEY" in keyless.unavailable_reason


def test_no_field_of_the_catalog_can_carry_a_key(workspace: Path, env: None) -> None:
    """Product 34: the catalog names the variable, never the value."""
    printed = catalog(workspace).model_dump_json()

    assert "a-test-key-never-printed" not in printed


def test_the_policy_is_asked_before_the_credential(tmp_path: Path, env: None) -> None:
    """A refused provider is not "missing a key"; it is one this project will not talk to."""
    repo = WorkspaceRepository.init(tmp_path / "refused", "provider-catalog")
    configure(repo.root, PROVIDERS, external_models="disabled")

    listed = catalog(repo.root)
    served, hosted, _ = listed.models

    assert served.available, "a loopback endpoint has no egress to have a policy about"
    assert not hosted.available
    assert hosted.unavailable_reason is not None
    assert "privacy policy" in hosted.unavailable_reason


def test_the_default_is_the_entry_the_router_would_select(workspace: Path, env: None) -> None:
    listed = catalog(workspace)

    assert [item.default for item in listed.models] == [True, False, False]


def test_the_default_moves_when_the_policy_refuses_the_first_entry(
    tmp_path: Path, env: None
) -> None:
    """The catalog answers what routing would answer, not what a client would prefer."""
    repo = WorkspaceRepository.init(tmp_path / "narrowed", "provider-catalog")
    configure(
        repo.root,
        [{**PROVIDERS[1], "priority": 5}, PROVIDERS[0]],
        external_models="disabled",
    )

    defaults = {item.id: item.default for item in catalog(repo.root).models}

    assert defaults == {"hosted": False, "on-box": True}


def test_a_workspace_with_no_providers_answers_with_an_empty_catalog(tmp_path: Path) -> None:
    """ "Nothing configured" is an answer a selector can render, not an error."""
    repo = WorkspaceRepository.init(tmp_path / "bare", "provider-catalog")

    listed = catalog(repo.root)

    assert listed.count == 0 and listed.models == ()


# -- the capability surface --------------------------------------------------


def test_provider_list_is_a_host_readable_read(registry: CapabilityRegistry) -> None:
    spec = registry.get("provider.list")

    assert spec.permission is Permission.READ
    assert not spec.descriptor().human_only
    assert spec.handler is list_providers


def test_an_agent_host_may_read_the_catalog(
    registry: CapabilityRegistry, workspace: Path, env: None
) -> None:
    ctx: CapabilityContext = open_context(workspace, HUMAN_ACTOR)

    result = registry.invoke("provider.list", ctx, {}, principal=Principal.agent_host("claude"))

    assert [item.id for item in result.models] == ["on-box", "hosted", "keyless"]


def test_the_catalog_matches_the_egress_report_it_is_derived_from(
    workspace: Path, env: None
) -> None:
    """One disclosure, two views: the selector's and `research egress`'s."""
    import os

    from research_harness.privacy.egress import egress_report

    ctx = open_context(workspace, HUMAN_ACTOR)
    report = egress_report(ctx.repo, os.environ)
    disclosed = {row.provider: row for row in report.of_kind("model")}

    for item in catalog(workspace).models:
        row = disclosed[item.id]
        local = item.egress_class is EgressClass.LOCAL
        assert item.available == (row.allowed_by_policy and (local or row.key_present))
        assert item.label == f"{row.provider}/{row.model}"
        assert item.available or item.unavailable_reason
