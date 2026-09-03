"""`research providers …` is the terminal's view of `provider.cli.*` (spec §17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from research_harness.cli.app import app
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.cli.fakes import FakeCli

STREAMS = Path(__file__).resolve().parents[1] / "fixtures" / "cli" / "streams"
HELP = (
    "--sandbox --output-schema --json --ephemeral --skip-git-repo-check "
    "--ignore-user-config --ignore-rules"
)
runner = CliRunner()


def lines(name: str) -> list[str]:
    return [
        line
        for line in (STREAMS / name).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def probe_reply() -> list[str]:
    """The two Codex lines of one passing probe; the fake fills `{{NONCE}}` in from stdin."""
    body = {"ok": True, "echo": "{{NONCE}}"}
    return [
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i", "type": "agent_message", "text": json.dumps(body)},
            }
        ),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}}),
    ]


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    DEFAULT_CACHE.clear()
    fake = FakeCli.install(
        tmp_path / "tools",
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[
            {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
            {"args": ["exec", "--help"], "stdout": HELP},
        ],
        run={"lines": lines("codex-success.jsonl")},
    )
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return fake


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return WorkspaceRepository.init(tmp_path / "project", "cli").root


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_scan_prints_every_runtime_with_its_state(workspace: Path, codex: FakeCli) -> None:
    code, out = run("providers", "scan", "--workspace", str(workspace))
    assert code == 0
    assert "codex" in out and "0.150.1" in out and "logged in" in out and "bounded" in out
    assert "claude" in out and "not installed" in out
    assert "leave the machine" in out
    code, out = run("providers", "scan", "--workspace", str(workspace), "--json")
    assert json.loads(out)["count"] == 7


def test_add_refuses_an_unavailable_runtime_and_writes_an_available_one(
    workspace: Path, codex: FakeCli
) -> None:
    code, out = run(
        "providers", "add", "claude", "--name", "claude-sub", "--workspace", str(workspace)
    )
    assert code == 1 and "not installed" in out
    code, out = run(
        "providers",
        "add",
        "codex",
        "--name",
        "codex-sub",
        "--model",
        "gpt-5.5",
        "--priority",
        "10",
        "--workspace",
        str(workspace),
    )
    assert code == 0 and "codex-sub" in out and "research.yaml" in out
    entries = yaml.safe_load((workspace / "research.yaml").read_text(encoding="utf-8"))["providers"]
    assert entries == [
        {
            "name": "codex-sub",
            "kind": "local_cli",
            "runtime": "codex",
            "model": "gpt-5.5",
            "priority": 10,
            "enabled": True,
        }
    ]


def test_test_states_the_destination_before_it_calls(workspace: Path, codex: FakeCli) -> None:
    """The destination is named first, and the verdict is the runtime's, not the command's.

    `codex-success.jsonl` answers with a claim-shaped object, so this probe deterministically
    fails `CliProbeReply` and the command must exit 1 -- and must still not print the answer.
    """
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    code, out = run("providers", "test", "codex-sub", "--workspace", str(workspace))
    lines_out = out.splitlines()
    assert lines_out[0].startswith("egress: codex-sub sends research content to chatgpt.com")
    assert code == 1, "a probe the runtime failed exits non-zero"
    assert lines_out[1] == "codex-sub (codex/default, 0.150.1): failed"
    assert "the runtime answered, but not with the requested object" in out
    assert "diagnostic: structured_output" in out
    assert "supported" not in out, "no raw model response is printed"


def test_test_exits_zero_when_the_runtime_echoes_the_nonce(workspace: Path, codex: FakeCli) -> None:
    """The success path: the destination is named first, then the verdict, and the exit is 0."""
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    codex.set_run(lines=probe_reply())

    code, out = run("providers", "test", "codex-sub", "--workspace", str(workspace))

    lines_out = out.splitlines()
    assert code == 0, out
    assert lines_out[0].startswith("egress: codex-sub sends research content to chatgpt.com")
    assert lines_out[1].endswith(": ok"), "the egress sentence precedes the verdict line"
    assert "diagnostic" not in out

    code, out = run("providers", "test", "codex-sub", "--workspace", str(workspace), "--json")
    assert code == 0, out
    body = json.loads(out)
    assert body["ok"] is True and body["egress_host"] == "chatgpt.com"


def test_remove_takes_the_entry_out(workspace: Path, codex: FakeCli) -> None:
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    code, _ = run("providers", "remove", "codex-sub", "--workspace", str(workspace))
    assert (
        code == 0
        and yaml.safe_load((workspace / "research.yaml").read_text(encoding="utf-8")).get(
            "providers", []
        )
        == []
    )


def test_list_and_doctor_show_the_cli_entry(workspace: Path, codex: FakeCli) -> None:
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    code, out = run("providers", "list", "--workspace", str(workspace))
    assert code == 0 and "codex-sub" in out and "external" in out
    code, out = run("doctor", "--workspace", str(workspace))
    assert "codex-sub" in out and "local_cli:codex" in out and "0.150.1" in out


def test_existing_workflow_commands_select_the_cli_entry_with_provider(
    workspace: Path, codex: FakeCli
) -> None:
    """`--provider <name>` reaches a CLI entry through the same narrowing as an HTTP one."""
    from research_harness.cli.providers import resolve_model_client

    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    client = resolve_model_client(WorkspaceRepository.open(workspace), "codex-sub", None)
    assert client.entries[0].provider.name == "local_cli:codex"
