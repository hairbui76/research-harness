"""`provider.cli.*`: one server-side truth for scan, configure, remove, and test (spec §16).

Everything is driven through fake executables; the workstation's real CLIs are never run.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.testclient import TestClient

from research_harness.capabilities.cli_providers import (
    EXTERNAL_EGRESS_NOTICE,
    ConfigureCliProviderRequest,
    RemoveCliProviderRequest,
    ScanCliRuntimesRequest,
    TestCliProviderRequest,
    configure_cli_provider,
    remove_cli_provider,
    scan_cli_runtimes,
    test_cli_provider,
)
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Permission, PermissionDenied, Principal
from research_harness.capabilities.providers import ListProvidersRequest, list_providers
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.server.app import create_app, ensure_token
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.cli.fakes import FakeCli

# `test_cli_provider` is the handler behind the capability *named* `provider.cli.test`, not a
# test: without this pytest would collect the imported function and fail on its parameters.
test_cli_provider.__test__ = False  # type: ignore[attr-defined]

STREAMS = Path(__file__).resolve().parents[2] / "fixtures" / "cli" / "streams"
HELP = (
    "--sandbox --output-schema --json --ephemeral --skip-git-repo-check "
    "--ignore-user-config --ignore-rules"
)


def lines(name: str) -> list[str]:
    return [
        line
        for line in (STREAMS / name).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def probe_reply() -> list[str]:
    body = {"ok": True, "echo": "will be replaced"}
    return [
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i", "type": "agent_message", "text": json.dumps(body)},
            }
        ),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}}),
    ]


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    DEFAULT_CACHE.clear()
    yield
    DEFAULT_CACHE.clear()


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    fake = FakeCli.install(
        tmp_path / "tools",
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[
            {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
            {"args": ["exec", "--help"], "stdout": HELP},
            {
                "args": ["debug", "models"],
                "stdout": json.dumps(
                    {
                        "models": [
                            {
                                "slug": "gpt-5.5",
                                "display_name": "GPT-5.5",
                                "visibility": "list",
                                "supported_reasoning_levels": [
                                    {"effort": "low"},
                                    {"effort": "high"},
                                ],
                                "context_window": 272000,
                            }
                        ]
                    }
                ),
            },
        ],
        run={"lines": lines("codex-success.jsonl")},
    )
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak")
    return fake


@pytest.fixture
def project(tmp_path: Path) -> CapabilityContext:
    repo = WorkspaceRepository.init(tmp_path / "project", "cli-providers")
    return open_context(repo.root, HUMAN_ACTOR)


def configured(ctx: CapabilityContext) -> list[dict[str, Any]]:
    return list(
        yaml.safe_load(ctx.repo.layout.research_file.read_text(encoding="utf-8")).get(
            "providers", []
        )
    )


# -- scan ----------------------------------------------------------------------


def test_scan_lists_all_seven_runtimes_in_registry_order_and_edits_nothing(
    project: CapabilityContext, codex: FakeCli
) -> None:
    before = project.repo.layout.research_file.read_bytes()
    report = scan_cli_runtimes(project, ScanCliRuntimesRequest())

    assert [item.runtime for item in report.runtimes] == [
        "codex",
        "claude",
        "cursor-agent",
        "amp",
        "deepseek-harness",
        "opencode",
        "pi",
    ]
    assert report.count == 7 and report.notice == EXTERNAL_EGRESS_NOTICE
    found = report.runtimes[0]
    assert (
        found.available
        and found.version == "0.150.1"
        and found.auth_status == "ok"
        and found.bounded_mode == "safe"
    )
    assert (
        found.compatibility == "verified"
        and [m.id for m in found.models] == ["default", "gpt-5.5"]
        and found.model_source == "live"
    )
    assert not report.runtimes[1].available, "claude is not on the fake PATH"
    assert project.repo.layout.research_file.read_bytes() == before
    assert codex.runs() == []
    assert "sk-must-not-leak" not in report.model_dump_json()


def test_scan_reports_configured_entries_beside_the_runtimes(
    project: CapabilityContext, codex: FakeCli
) -> None:
    configure_cli_provider(
        project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5")
    )
    report = scan_cli_runtimes(project, ScanCliRuntimesRequest(rescan=True))
    assert [item.name for item in report.configured] == ["codex-sub"]
    assert report.configured[0].available and report.configured[0].unavailable_reason is None


def test_scan_is_a_read_a_host_may_make(project: CapabilityContext, codex: FakeCli) -> None:
    registry = build_default_registry()
    spec = registry.get("provider.cli.scan")
    assert spec.permission is Permission.READ and not spec.descriptor().human_only
    result = registry.invoke(
        "provider.cli.scan", project, {}, principal=Principal.agent_host("claude")
    )
    assert result.count == 7


# -- configure -----------------------------------------------------------------


def test_configure_writes_one_validated_entry(project: CapabilityContext, codex: FakeCli) -> None:
    result = configure_cli_provider(
        project,
        ConfigureCliProviderRequest(
            name="codex-sub",
            runtime="codex",
            model="gpt-5.5",
            priority=10,
            reasoning="high",
            timeout_seconds=120,
        ),
    )

    assert result.created and result.file == "research.yaml"
    assert configured(project) == [
        {
            "name": "codex-sub",
            "kind": "local_cli",
            "runtime": "codex",
            "model": "gpt-5.5",
            "priority": 10,
            "reasoning": "high",
            "timeout_seconds": 120.0,
            "enabled": True,
        }
    ]
    again = configure_cli_provider(
        project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="default")
    )
    assert not again.created and configured(project)[0]["model"] == "default"


def test_configure_refuses_an_unavailable_or_unsafe_runtime(
    project: CapabilityContext, codex: FakeCli
) -> None:
    with pytest.raises(CapabilityError, match="claude is not installed"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="c", runtime="claude"))
    codex.write_script(
        {
            **codex.script(),
            "probes": [
                {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
                {"args": ["exec", "--help"], "stdout": "--json"},
            ],
        }
    )
    with pytest.raises(CapabilityError, match="no tested bounded"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="c", runtime="codex"))
    with pytest.raises(CapabilityError, match="unknown runtime 'nope'"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="c", runtime="nope"))
    assert configured(project) == []


def test_configure_will_not_take_over_an_http_entry_of_the_same_name(
    project: CapabilityContext, codex: FakeCli
) -> None:
    project.repo.update_providers([{"name": "fast", "kind": "openai", "model": "gpt-x"}])
    with pytest.raises(CapabilityError, match="'fast' is an openai entry"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="fast", runtime="codex"))


def test_configure_and_remove_are_admin_and_human_only(
    project: CapabilityContext, codex: FakeCli
) -> None:
    registry = build_default_registry()
    for name in ("provider.cli.configure", "provider.cli.remove"):
        spec = registry.get(name)
        assert spec.permission is Permission.ADMIN and spec.descriptor().human_only
    with pytest.raises(PermissionDenied):
        registry.invoke(
            "provider.cli.configure",
            project,
            {"name": "c", "runtime": "codex"},
            principal=Principal.agent_host("claude"),
        )
    as_model = open_context(project.root, "vendor/model")
    with pytest.raises(AuthorityError):
        configure_cli_provider(as_model, ConfigureCliProviderRequest(name="c", runtime="codex"))


def test_remove_takes_only_the_named_cli_entry(project: CapabilityContext, codex: FakeCli) -> None:
    project.repo.update_providers([{"name": "fast", "kind": "openai", "model": "gpt-x"}])
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    result = remove_cli_provider(project, RemoveCliProviderRequest(name="codex-sub"))
    assert result.name == "codex-sub" and [e["name"] for e in configured(project)] == ["fast"]
    with pytest.raises(CapabilityError, match="'fast' is an openai entry"):
        remove_cli_provider(project, RemoveCliProviderRequest(name="fast"))
    with pytest.raises(CapabilityError, match="no provider named 'gone'"):
        remove_cli_provider(project, RemoveCliProviderRequest(name="gone"))


# -- provider.list -------------------------------------------------------------


def test_a_configured_cli_entry_appears_in_the_catalog_as_external(
    project: CapabilityContext, codex: FakeCli
) -> None:
    configure_cli_provider(
        project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5")
    )
    listed = list_providers(project, ListProvidersRequest())
    row = listed.models[0]
    assert row.id == "codex-sub" and row.label == "codex-sub/gpt-5.5"
    assert row.provider == "local_cli"
    assert row.egress_class.value == "external" and row.available and row.default


def test_a_logged_out_runtime_is_listed_but_unavailable(
    project: CapabilityContext, codex: FakeCli
) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    codex.write_script(
        {
            **codex.script(),
            "probes": [
                {"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1},
                {"args": ["exec", "--help"], "stdout": HELP},
            ],
        }
    )
    DEFAULT_CACHE.clear()
    row = list_providers(project, ListProvidersRequest()).models[0]
    assert not row.available
    assert row.unavailable_reason == "codex is not logged in: run `codex login`"


def test_the_policy_is_asked_before_the_runtime(project: CapabilityContext, codex: FakeCli) -> None:
    from research_harness.privacy.policy import EgressPolicy

    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    project.repo.update_config(EgressPolicy(external_models="disabled"))
    row = list_providers(open_context(project.root, HUMAN_ACTOR), ListProvidersRequest()).models[0]
    assert not row.available and "privacy policy" in (row.unavailable_reason or "")


def test_the_scan_view_and_the_catalog_agree_about_a_refused_entry(
    project: CapabilityContext, codex: FakeCli
) -> None:
    """The settings screen and the model selector read one verdict, not two (spec §11)."""
    from research_harness.privacy.policy import EgressPolicy

    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    project.repo.update_config(EgressPolicy(external_models="disabled"))
    fresh = open_context(project.root, HUMAN_ACTOR)

    view = scan_cli_runtimes(fresh, ScanCliRuntimesRequest()).configured[0]
    row = list_providers(fresh, ListProvidersRequest()).models[0]

    assert not view.available and "privacy policy" in (view.unavailable_reason or "")
    assert view.unavailable_reason == row.unavailable_reason


# -- test ----------------------------------------------------------------------


def test_the_test_call_runs_one_validated_request_and_reports_the_destination(
    project: CapabilityContext, codex: FakeCli
) -> None:
    configure_cli_provider(
        project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5")
    )
    codex.set_run(lines=probe_reply())

    report = test_cli_provider(project, TestCliProviderRequest(name="codex-sub"))

    assert report.runtime == "codex" and report.model == "gpt-5.5" and report.version == "0.150.1"
    assert report.egress_host == "chatgpt.com" and report.egress_kind == "external"
    run = codex.runs()[0]
    assert "provider.cli.test" in run["stdin"]
    if report.ok:
        assert report.latency_ms is not None and report.diagnostic is None
    else:
        assert report.diagnostic == "structured_output" and "echo" in report.message
    assert list(project.repo.layout.traces_dir.glob("*/*.json")), (
        "a test call is traced like any call"
    )


def test_the_test_call_is_refused_by_the_policy_before_any_spawn(
    project: CapabilityContext, codex: FakeCli
) -> None:
    from research_harness.privacy.policy import EgressPolicy

    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    project.repo.update_config(EgressPolicy(external_models="disabled"))
    report = test_cli_provider(
        open_context(project.root, HUMAN_ACTOR), TestCliProviderRequest(name="codex-sub")
    )
    assert not report.ok and report.diagnostic == "privacy_refused"
    assert "privacy policy" in report.message
    assert codex.runs() == []


def test_the_test_call_reports_a_failure_without_a_secret(
    project: CapabilityContext, codex: FakeCli
) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    codex.set_run(
        lines=lines("codex-failed.jsonl"),
        stderr="token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd",
    )
    report = test_cli_provider(project, TestCliProviderRequest(name="codex-sub"))
    assert not report.ok and report.diagnostic == "unsupported_model"
    assert "sk-proj" not in report.model_dump_json()


def test_the_test_call_says_so_when_the_entry_is_switched_off(
    project: CapabilityContext, codex: FakeCli
) -> None:
    """A disabled entry is not routed, so testing it is answered rather than crashed."""
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    configure_cli_provider(
        project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", enabled=False)
    )

    report = test_cli_provider(project, TestCliProviderRequest(name="codex-sub"))

    assert not report.ok and report.diagnostic == "unavailable"
    assert "disabled" in report.message
    assert codex.runs() == []


def test_the_test_call_is_human_only_even_though_it_is_a_read(
    project: CapabilityContext, codex: FakeCli
) -> None:
    registry = build_default_registry()
    spec = registry.get("provider.cli.test")
    assert spec.permission is Permission.READ and spec.human_only
    with pytest.raises(PermissionDenied):
        registry.invoke(
            "provider.cli.test",
            project,
            {"name": "codex-sub"},
            principal=Principal.agent_host("claude"),
        )


# -- over HTTP -----------------------------------------------------------------


def test_configure_and_scan_answer_identically_over_the_daemon(
    project: CapabilityContext, codex: FakeCli
) -> None:
    app = create_app(project.root, registry=build_default_registry())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {ensure_token(project.root)}"
        served = client.post(
            "/capabilities/provider.cli.configure",
            json={"name": "codex-sub", "runtime": "codex", "model": "gpt-5.5"},
        ).json()
        assert served["ok"] is True and served["result"]["created"] is True
        scanned = client.post("/capabilities/provider.cli.scan", json={}).json()
        assert scanned["ok"] is True
    direct = scan_cli_runtimes(
        open_context(project.root, HUMAN_ACTOR), ScanCliRuntimesRequest()
    ).model_dump(mode="json")
    assert scanned["result"]["configured"] == direct["configured"]
    assert [r["runtime"] for r in scanned["result"]["runtimes"]] == [
        r["runtime"] for r in direct["runtimes"]
    ]
