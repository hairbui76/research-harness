"""`cli/providers.py`: one answer to "which backend does this run talk to".

Three commands used to answer it three ways, and two of the three answers were wrong in a
way a reader could not see: `research claim audit` built its router without the project's
privacy policy, and `research draft` refused every configured provider outright. The rules
this file states are the ones all three now share.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.cli.providers import (
    SCRIPTED_PROVIDER,
    load_router,
    optional_model_client,
    resolve_model_client,
    scripted_model_provider,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.models.router import ModelRouter
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.roles.extractor import EXTRACTOR
from research_harness.roles.writer import WRITER
from research_harness.workspace.repository import WorkspaceRepository

PROVIDERS = [
    {
        "name": "house-openai",
        "kind": "openai",
        "model": "gpt-4o-mini",
        "api_key_env": "RESEARCH_TEST_OPENAI_KEY",
        "tags": ["fast"],
    },
    {
        "name": "house-local",
        "kind": "local_openai_compatible",
        "model": "qwen3",
        "priority": 10,
        "tags": ["local"],
    },
]

ENV = {"RESEARCH_TEST_OPENAI_KEY": "not-a-real-key"}


def workspace(tmp_path: Path, *, privacy: EgressPolicy | None = None) -> CapabilityContext:
    """A workspace whose `research.yaml` carries a `providers:` list."""
    repo = WorkspaceRepository.init(tmp_path / "project", "providers")
    path = repo.layout.research_file
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = PROVIDERS
    if privacy is not None:
        config["privacy"] = privacy.model_dump(mode="json")
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return open_context(repo.root)


# -- the scripted adapter ----------------------------------------------------


def test_a_script_is_the_scripted_provider_whether_or_not_it_is_named(tmp_path: Path) -> None:
    script = tmp_path / "replies.json"
    script.write_text(json.dumps([{"draft": "one"}]), encoding="utf-8")
    ctx = workspace(tmp_path)

    for provider in (None, SCRIPTED_PROVIDER):
        client = resolve_model_client(ctx, provider, script)
        assert isinstance(client, ModelRouter)
        assert client.entries[0].provider.name == SCRIPTED_PROVIDER


def test_a_script_and_a_configured_provider_are_a_contradiction(tmp_path: Path) -> None:
    script = tmp_path / "replies.json"
    script.write_text("[]", encoding="utf-8")
    with pytest.raises(ResearchHarnessError, match="asks for a configured one"):
        resolve_model_client(workspace(tmp_path), "house-local", script)


def test_the_scripted_provider_without_a_script_says_what_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ResearchHarnessError, match="needs --script"):
        resolve_model_client(workspace(tmp_path), SCRIPTED_PROVIDER, None)


def test_a_script_may_be_a_list_a_role_map_or_one_reply(tmp_path: Path) -> None:
    """A writer script is one response object; a multi-role script is keyed by role."""
    listed = tmp_path / "listed.json"
    listed.write_text(json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")
    assert isinstance(scripted_model_provider(listed), ScriptedProvider)

    single = tmp_path / "single.json"
    single.write_text(json.dumps({"draft": "text", "claim_refs": []}), encoding="utf-8")
    provider = scripted_model_provider(single)
    assert provider.remaining == 1

    by_role = tmp_path / "roles.json"
    by_role.write_text(
        json.dumps({EXTRACTOR.name: [{"candidates": []}], WRITER.name: {"draft": "x"}}),
        encoding="utf-8",
    )
    # A callable script has no queue to count; it answers per request instead.
    assert scripted_model_provider(by_role).remaining == 0


def test_an_unreadable_script_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ResearchHarnessError, match="cannot read script"):
        scripted_model_provider(tmp_path / "missing.json")


# -- configured providers ----------------------------------------------------


def test_no_provider_named_routes_over_the_whole_workspace_table(tmp_path: Path) -> None:
    router = resolve_model_client(workspace(tmp_path), None, None, env=ENV)
    assert isinstance(router, ModelRouter)
    assert {entry.provider.name for entry in router.entries} == {"openai", "local"}


def test_naming_a_provider_narrows_the_table_by_tag_or_by_name(tmp_path: Path) -> None:
    ctx = workspace(tmp_path)
    by_tag = resolve_model_client(ctx, "local", None, env=ENV)
    assert isinstance(by_tag, ModelRouter)
    assert [entry.model for entry in by_tag.entries] == ["qwen3"]

    by_name = resolve_model_client(ctx, "openai", None, env=ENV)
    assert isinstance(by_name, ModelRouter)
    assert [entry.model for entry in by_name.entries] == ["gpt-4o-mini"]


def test_narrowing_the_table_keeps_the_projects_privacy_policy(tmp_path: Path) -> None:
    """A `--provider` that dropped the policy would call a host the project forbids."""
    policy = EgressPolicy(allowed_hosts=("localhost",))
    ctx = workspace(tmp_path, privacy=policy)

    whole = resolve_model_client(ctx, None, None, env=ENV)
    narrowed = resolve_model_client(ctx, "local", None, env=ENV)

    assert isinstance(whole, ModelRouter) and isinstance(narrowed, ModelRouter)
    assert whole.policy == policy
    assert narrowed.policy == policy


def test_an_unknown_provider_lists_the_tags_that_exist(tmp_path: Path) -> None:
    with pytest.raises(ResearchHarnessError, match="no provider named 'gpt5'"):
        resolve_model_client(workspace(tmp_path), "gpt5", None, env=ENV)


def test_a_workspace_with_no_providers_says_how_to_run_offline(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "bare", "bare")
    with pytest.raises(ResearchHarnessError, match="--provider scripted --script"):
        resolve_model_client(open_context(repo.root), None, None)


def test_load_router_accepts_a_repository_directly(tmp_path: Path) -> None:
    ctx = workspace(tmp_path)
    assert len(load_router(ctx.repo, env=ENV).entries) == 2
    assert len(resolve_model_client(ctx.repo, None, None, env=ENV).entries) == 2


# -- the optional form -------------------------------------------------------


def test_naming_nothing_means_no_model_pass_at_all(tmp_path: Path) -> None:
    """`research claim audit` runs deterministically when no backend is named."""
    assert optional_model_client(workspace(tmp_path), None, None) is None


def test_the_optional_form_still_refuses_a_bad_combination(tmp_path: Path) -> None:
    script = tmp_path / "s.json"
    script.write_text("[]", encoding="utf-8")
    with pytest.raises(ResearchHarnessError):
        optional_model_client(workspace(tmp_path), "house-local", script)
