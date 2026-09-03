"""Privacy enforcement end to end: router, discovery, workspace, and CLI.

ROADMAP Task 17.4 / Product SS34. The load-bearing assertion in the enforcement tests is the
transport: every adapter is built on an `httpx.MockTransport` whose handler fails the test
if it is ever called, so "refused before any request is sent" is checked rather than
asserted in a docstring.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from typer.testing import CliRunner, Result

from research_harness.cli.app import app
from research_harness.cli.commands import evidence as evidence_commands
from research_harness.cli.commands import privacy as privacy_commands
from research_harness.privacy.egress import EgressReport, check_embedding_egress, egress_report
from research_harness.privacy.policy import EgressDeniedError, EgressPolicy, load_policy
from research_harness.privacy.traces import TraceWriter
from research_harness.providers.models.base import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
)
from research_harness.providers.models.embeddings import (
    HashingEmbeddingProvider,
    LocalOpenAICompatibleEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from research_harness.providers.models.router import (
    NoCapableProviderError,
    RouterConfig,
    build_router,
)
from research_harness.providers.models.scripted import ScriptedProvider
from research_harness.providers.search import (
    CROSSREF,
    SEARCH_SOURCES,
    build_search_registry,
)
from research_harness.workspace.repository import WorkspaceConfig, WorkspaceRepository
from research_harness.workspace.serialization import WorkspaceSerializationError, dump_yaml

API_KEY_SENTINEL = "sk-privacy-sentinel-must-never-be-written"

PROVIDERS: list[dict[str, Any]] = [
    {"name": "fast", "kind": "openai", "model": "gpt-x", "api_key_env": "OPENAI_API_KEY"},
    {"name": "careful", "kind": "anthropic", "model": "claude-x", "priority": 50},
    {"name": "on-box", "kind": "local_openai_compatible", "model": "qwen", "priority": 200},
]

runner = CliRunner()

if not any(command.name == "egress" for command in app.registered_commands):
    # The PM wires `privacy` into `cli/commands/__init__.py`; until then the test mounts it
    # itself, so it exercises the same app object either way.
    privacy_commands.register(app)


class Verdict(BaseModel):
    """Schema fixture; the answer a scripted role returns."""

    model_config = ConfigDict(extra="forbid")

    supported: bool


def forbidden_transport() -> httpx.MockTransport:
    """A transport that fails the test if any adapter tries to use it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a refused provider was contacted: {request.method} {request.url}")

    return httpx.MockTransport(handler)


def router_for(
    policy: EgressPolicy | None,
    *,
    providers: list[dict[str, Any]] | None = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    config = RouterConfig.model_validate({"providers": providers or PROVIDERS})
    return build_router(config, env or {}, transport=forbidden_transport(), policy=policy)


def request_for(role: str = "evidence_verifier") -> ModelRequest[Verdict]:
    return ModelRequest(
        role=role,
        requirements=ModelRequirements(context_tokens=8_000, reasoning="low"),
        instructions="Decide whether the source supports the candidate.",
        inputs=[InputEnvelope(object_id="W0001", kind="source_text", content="Table 3 reports…")],
        response_schema=Verdict,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[WorkspaceRepository]:
    workspace = WorkspaceRepository.init(tmp_path / "project", "privacy-project")
    _write_providers(workspace.root, PROVIDERS)
    yield WorkspaceRepository.open(workspace.root)


def _write_providers(root: Path, providers: list[dict[str, Any]]) -> None:
    path = root / "research.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["providers"] = providers
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def run(*args: str) -> Result:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"`research {' '.join(args)}` failed:\n{result.output}"
    return result


# -- model routing -----------------------------------------------------------


def test_disabled_external_models_refuse_hosted_providers_before_any_http_call() -> None:
    router = router_for(EgressPolicy(external_models="disabled"), providers=PROVIDERS[:2])
    with pytest.raises(EgressDeniedError) as caught:
        router.select(ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier")
    message = str(caught.value)
    assert "api.anthropic.com" in message
    assert "api.openai.com" in message
    assert "external_models" in message


def test_a_local_provider_still_answers_when_external_models_are_disabled() -> None:
    router = router_for(EgressPolicy(external_models="disabled"))
    entry = router.select(
        ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier"
    )
    assert entry.provider.name == "local"
    assert entry.model == "qwen"


def test_completing_through_a_refusing_router_sends_nothing() -> None:
    router = router_for(EgressPolicy(external_models="disabled"), providers=PROVIDERS[:1])
    with pytest.raises(EgressDeniedError):
        router.complete(request_for())


def test_allowed_hosts_pick_the_permitted_endpoint_and_refuse_the_rest() -> None:
    router = router_for(EgressPolicy(allowed_hosts=("api.openai.com",)), providers=PROVIDERS[:2])
    entry = router.select(
        ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier"
    )
    assert entry.provider.name == "openai"

    with pytest.raises(EgressDeniedError, match="allowed_hosts"):
        router_for(
            EgressPolicy(allowed_hosts=("api.anthropic.com",)), providers=PROVIDERS[:1]
        ).select(ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier")


def test_refusing_source_text_refuses_the_providers_that_send_it() -> None:
    router = router_for(EgressPolicy(allow_source_text=False), providers=PROVIDERS[:2])
    with pytest.raises(EgressDeniedError, match="allow_source_text"):
        router.select(ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier")


def test_a_router_without_a_policy_keeps_its_previous_behaviour() -> None:
    router = router_for(None, providers=PROVIDERS[:2])
    assert router.policy is None
    entry = router.select(
        ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier"
    )
    assert entry.provider.name == "anthropic"


def test_an_incapable_provider_still_fails_as_a_capability_problem() -> None:
    router = router_for(EgressPolicy(), providers=PROVIDERS)
    with pytest.raises(NoCapableProviderError):
        router.select(ModelRequirements(context_tokens=10_000_000, reasoning="low"), "extractor")


def test_narrowing_a_router_to_one_provider_keeps_the_policy() -> None:
    router = router_for(EgressPolicy(external_models="disabled"))
    narrowed = router.with_policy(router.policy)
    assert narrowed.policy == router.policy


# -- embeddings --------------------------------------------------------------


def test_an_in_process_embedder_is_allowed_under_the_strictest_policy() -> None:
    policy = EgressPolicy(external_models="disabled", allow_source_text=False)
    check_embedding_egress(policy, HashingEmbeddingProvider(dimension=16))


def test_a_hosted_embedder_is_refused_before_a_single_unit_is_embedded() -> None:
    policy = EgressPolicy(external_models="disabled")
    provider = OpenAIEmbeddingProvider(transport=forbidden_transport(), env={})
    with pytest.raises(EgressDeniedError) as caught:
        check_embedding_egress(policy, provider)
    assert "api.openai.com" in str(caught.value)
    assert "external_models" in str(caught.value)


def test_a_loopback_embedding_server_is_allowed_when_external_models_are_disabled() -> None:
    provider = LocalOpenAICompatibleEmbeddingProvider(
        model="nomic", dimension=8, transport=forbidden_transport(), env={}
    )
    check_embedding_egress(EgressPolicy(external_models="disabled"), provider)


# -- discovery ---------------------------------------------------------------


def test_disabled_search_providers_block_the_registry_build() -> None:
    with pytest.raises(EgressDeniedError) as caught:
        build_search_registry(
            {},
            transport=forbidden_transport(),
            policy=EgressPolicy(search_providers="disabled"),
        )
    assert "search_providers" in str(caught.value)


def test_asking_for_a_refused_source_by_name_is_refused_loudly() -> None:
    with pytest.raises(EgressDeniedError, match=CROSSREF):
        build_search_registry(
            {},
            transport=forbidden_transport(),
            sources=[CROSSREF],
            policy=EgressPolicy(allowed_hosts=("api.openalex.org",)),
        )


def test_allowed_hosts_narrow_the_default_source_set_instead_of_emptying_it() -> None:
    registry = build_search_registry(
        {},
        transport=forbidden_transport(),
        policy=EgressPolicy(allowed_hosts=("api.openalex.org",)),
    )
    assert registry.names == ("openalex",)


def test_an_unrestricted_policy_keeps_every_discovery_source() -> None:
    registry = build_search_registry({}, transport=forbidden_transport(), policy=EgressPolicy())
    assert registry.names == SEARCH_SOURCES


# -- the workspace policy ----------------------------------------------------


def test_a_workspace_written_before_the_privacy_section_opens_with_defaults(
    tmp_path: Path,
) -> None:
    repo = WorkspaceRepository.init(tmp_path / "old", "legacy")
    path = repo.layout.research_file
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    del config["privacy"]
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.config.privacy == EgressPolicy()
    assert load_policy(reopened) == EgressPolicy()
    assert reopened.verify().consistent


def test_update_config_round_trips_the_policy_and_keeps_the_workspace_consistent(
    repo: WorkspaceRepository,
) -> None:
    policy = EgressPolicy(
        external_models="disabled", allowed_hosts=("localhost",), redact_traces=True
    )
    repo.update_config(policy)

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.config.privacy == policy
    assert reopened.config.name == "privacy-project"
    assert reopened.config.providers == PROVIDERS
    assert reopened.verify().consistent


def test_a_credential_in_research_yaml_is_refused_when_the_workspace_opens(
    tmp_path: Path,
) -> None:
    repo = WorkspaceRepository.init(tmp_path / "leaky", "leaky")
    _write_providers(
        repo.root,
        [{"name": "fast", "kind": "openai", "model": "gpt-x", "api_key": API_KEY_SENTINEL}],
    )
    with pytest.raises(WorkspaceSerializationError) as caught:
        WorkspaceRepository.open(repo.root)
    message = str(caught.value)
    assert "api_key" in message
    assert "api_key_env" in message
    assert API_KEY_SENTINEL not in message


def test_a_credential_in_a_router_entry_is_refused_with_the_fix_in_the_message() -> None:
    with pytest.raises(ValidationError) as caught:
        RouterConfig.model_validate(
            {"providers": [{"name": "fast", "kind": "openai", "api_key": API_KEY_SENTINEL}]}
        )
    assert "api_key_env" in str(caught.value)


# -- the egress report -------------------------------------------------------


def test_the_egress_report_names_every_provider_and_what_it_sends(
    repo: WorkspaceRepository,
) -> None:
    report = egress_report(repo, {"OPENAI_API_KEY": API_KEY_SENTINEL})
    assert {entry.kind for entry in report.entries} == {"model", "embedding", "search"}

    models = {entry.provider: entry for entry in report.of_kind("model")}
    assert set(models) == {"fast", "careful", "on-box"}
    assert models["fast"].endpoint_host == "api.openai.com"
    assert models["fast"].sends_source_text is True
    assert models["fast"].key_env == "OPENAI_API_KEY"
    assert models["fast"].key_present is True
    assert models["careful"].key_present is False
    assert models["on-box"].endpoint_host == "localhost"
    assert models["on-box"].sends_source_text is False
    assert all(entry.allowed_by_policy for entry in report.entries)

    sources = {entry.provider for entry in report.of_kind("search")}
    assert sources == set(SEARCH_SOURCES)


def test_the_egress_report_marks_what_the_policy_refuses_and_why(
    repo: WorkspaceRepository,
) -> None:
    repo.update_config(EgressPolicy(external_models="disabled"))
    report = egress_report(WorkspaceRepository.open(repo.root), {})

    denied = {entry.provider for entry in report.denied}
    assert denied == {"fast", "careful", "openai"}  # the two hosted models and the hosted embedder
    assert all("external_models" in entry.policy_fields for entry in report.denied)
    assert all(entry.reason for entry in report.denied)
    on_box = next(entry for entry in report.of_kind("model") if entry.provider == "on-box")
    assert on_box.allowed_by_policy


def test_a_disabled_provider_entry_is_not_part_of_the_disclosure(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "disabled", "disabled")
    _write_providers(
        repo.root,
        [{"name": "fast", "kind": "openai", "model": "gpt-x", "enabled": False}],
    )
    report = egress_report(WorkspaceRepository.open(repo.root), {})
    assert report.of_kind("model") == ()


# -- secrets never reach a file, a dump, or the terminal ---------------------


def test_no_api_key_reaches_a_dump_a_canonical_file_a_trace_or_the_cli(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", API_KEY_SENTINEL)
    monkeypatch.setenv("ANTHROPIC_API_KEY", API_KEY_SENTINEL)
    env = {"OPENAI_API_KEY": API_KEY_SENTINEL, "ANTHROPIC_API_KEY": API_KEY_SENTINEL}

    router = build_router(
        RouterConfig.model_validate({"providers": PROVIDERS}),
        env,
        transport=forbidden_transport(),
        policy=load_policy(repo),
    )
    settings = router.entries[0].provider.settings  # type: ignore[attr-defined]
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == API_KEY_SENTINEL

    surfaces: dict[str, str] = {
        "provider settings dump": json.dumps(settings.model_dump(mode="json")),
        "provider settings repr": repr(router.entries[0].provider),
        "capabilities": router.entries[0].provider.capabilities().model_dump_json(),
        "router config": RouterConfig.model_validate({"providers": PROVIDERS}).model_dump_json(),
        "workspace config yaml": dump_yaml(repo.config),
        "research.yaml": repo.layout.research_file.read_text(encoding="utf-8"),
        "event log": repo.layout.events_file.read_text(encoding="utf-8"),
        "egress report": egress_report(repo, env).model_dump_json(),
        "egress cli": run("egress", "-w", str(repo.root), "--json").stdout,
        "privacy cli": run("privacy", "show", "-w", str(repo.root), "--json").stdout,
    }

    writer = TraceWriter(repo.layout.research_dir, EgressPolicy())
    provider = ScriptedProvider([{"supported": True}])
    response = provider.complete(request_for(), trace=writer)
    assert response.parsed.supported is True
    traces = writer.list_traces()
    assert len(traces) == 1
    surfaces["trace"] = traces[0].path.read_text(encoding="utf-8")

    for name, text in surfaces.items():
        assert API_KEY_SENTINEL not in text, f"the API key leaked into the {name}"

    report = EgressReport.model_validate_json(surfaces["egress report"])
    assert any(entry.key_present for entry in report.entries)


def test_the_egress_command_reports_a_key_by_name_and_presence_only(
    repo: WorkspaceRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", API_KEY_SENTINEL)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    output = run("egress", "-w", str(repo.root)).stdout
    assert "OPENAI_API_KEY (set)" in output
    assert "ANTHROPIC_API_KEY (unset)" in output
    assert API_KEY_SENTINEL not in output


# -- the CLI -----------------------------------------------------------------


def test_privacy_set_writes_research_yaml_and_show_reads_it_back(
    repo: WorkspaceRepository,
) -> None:
    run(
        "privacy",
        "set",
        "-w",
        str(repo.root),
        "--external-models",
        "disabled",
        "--no-allow-source-text",
        "--allowed-host",
        "localhost",
        "--search-providers",
        "disabled",
        "--redact-traces",
        "--trace-retention-days",
        "7",
    )

    on_disk = yaml.safe_load(repo.layout.research_file.read_text(encoding="utf-8"))["privacy"]
    assert on_disk == {
        "external_models": "disabled",
        "allowed_hosts": ["localhost"],
        "allow_source_text": False,
        "allow_identifiers": True,
        "search_providers": "disabled",
        "trace_retention_days": 7,
        "redact_traces": True,
    }

    reopened = WorkspaceRepository.open(repo.root)
    assert reopened.verify().consistent
    shown = json.loads(run("privacy", "show", "-w", str(repo.root), "--json").stdout)
    assert shown == on_disk


def test_privacy_set_changes_only_the_options_it_was_given(repo: WorkspaceRepository) -> None:
    run("privacy", "set", "-w", str(repo.root), "--redact-traces")
    policy = WorkspaceRepository.open(repo.root).config.privacy
    assert policy.redact_traces is True
    assert policy.external_models == "allowed"
    assert policy.trace_retention_days == 30


def test_privacy_set_without_options_says_so_rather_than_rewriting_the_file(
    repo: WorkspaceRepository,
) -> None:
    before = repo.layout.research_file.read_bytes()
    result = runner.invoke(app, ["privacy", "set", "-w", str(repo.root)])
    assert result.exit_code == 1
    assert "nothing to set" in result.output
    assert repo.layout.research_file.read_bytes() == before


def test_an_unknown_switch_value_is_refused(repo: WorkspaceRepository) -> None:
    result = runner.invoke(
        app, ["privacy", "set", "-w", str(repo.root), "--external-models", "maybe"]
    )
    assert result.exit_code == 1
    assert "allowed|disabled" in result.output


def test_traces_list_and_purge_manage_only_the_disposable_tree(
    repo: WorkspaceRepository,
) -> None:
    writer = TraceWriter(repo.layout.research_dir, EgressPolicy())
    provider = ScriptedProvider([{"supported": True}, {"supported": False}])
    provider.complete(request_for("extractor"), trace=writer)
    provider.complete(request_for("skeptic"), trace=writer)

    listed = json.loads(run("traces", "list", "-w", str(repo.root), "--json").stdout)
    assert listed["count"] == 2
    assert listed["bytes"] > 0

    canonical_before = _canonical_files(repo.root)
    purged = json.loads(run("traces", "purge", "-w", str(repo.root), "--all", "--json").stdout)
    assert purged["removed_files"] == 2
    assert writer.list_traces() == []
    assert _canonical_files(repo.root) == canonical_before


def test_purging_traces_needs_one_scope_not_two(repo: WorkspaceRepository) -> None:
    result = runner.invoke(
        app, ["traces", "purge", "-w", str(repo.root), "--all", "--older-than", "3"]
    )
    assert result.exit_code == 1
    assert "different things" in result.output


def _canonical_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".research" not in path.relative_to(root).parts
    }


# -- the workspace router ----------------------------------------------------


def test_the_workspace_router_carries_the_projects_policy(repo: WorkspaceRepository) -> None:
    repo.update_config(EgressPolicy(external_models="disabled"))
    reopened = WorkspaceRepository.open(repo.root)
    router = evidence_commands.load_router(reopened, env={})
    assert router.policy == reopened.config.privacy
    entry = router.select(
        ModelRequirements(context_tokens=8_000, reasoning="low"), "evidence_verifier"
    )
    assert entry.provider.name == "local"


def test_a_config_holding_no_privacy_section_still_builds_an_unrestricted_router(
    tmp_path: Path,
) -> None:
    config = WorkspaceConfig(name="defaults")
    assert config.privacy == EgressPolicy()
