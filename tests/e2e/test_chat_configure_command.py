"""`research chat configure` binds, shows, and clears with the daemon's words (spec §11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    """A fake `codex` that probes clean; nothing here ever spawns the real one."""
    DEFAULT_CACHE.clear()
    fake = FakeCli.install(
        tmp_path / "tools",
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[
            {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
            {"args": ["exec", "--help"], "stdout": HELP},
            # An empty catalog, so the scan falls back to the runtime's declared models
            # rather than the fake answering the model probe on its `run` branch.
            {"args": ["debug", "models"], "stdout": "{}"},
        ],
        run={"lines": lines("codex-success.jsonl")},
    )
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return fake


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return WorkspaceRepository.init(tmp_path / "project", "cli").root


def test_configure_prints_egress_then_the_binding_and_list_and_show_repeat_it(
    workspace: Path, codex: FakeCli
) -> None:
    # A project session, because a runtime binding is external egress and a private
    # session is refused one at bind time (binding spec §8; `conversation/service.py`).
    created = json.loads(
        runner.invoke(
            app,
            ["chat", "new", "Latency", "--visibility", "project", "-w", str(workspace), "--json"],
        ).stdout
    )
    session = created["session"]["id"]

    result = runner.invoke(
        app,
        [
            "chat",
            "configure",
            session,
            "--runtime",
            "codex",
            "--model",
            "gpt-5.5",
            "--reasoning",
            "high",
            "-w",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines[0].startswith("egress: ") and "chatgpt.com" in lines[0]
    assert lines[1] == "bound to: session:codex/gpt-5.5 (reasoning high)"
    assert codex.runs() == []

    listed = runner.invoke(app, ["chat", "list", "-w", str(workspace)]).stdout
    assert "[session:codex/gpt-5.5 (reasoning high)]" in listed
    shown = runner.invoke(app, ["chat", "show", session, "-w", str(workspace)]).stdout
    assert shown.splitlines()[1] == "bound to: session:codex/gpt-5.5 (reasoning high)"

    cleared = runner.invoke(app, ["chat", "configure", session, "--clear", "-w", str(workspace)])
    assert cleared.exit_code == 0 and "bound to: project default" in cleared.stdout


def test_configure_refuses_with_the_entry_sentence_and_exits_non_zero(
    workspace: Path, codex: FakeCli
) -> None:
    created = json.loads(
        runner.invoke(
            app, ["chat", "new", "x", "--visibility", "project", "-w", str(workspace), "--json"]
        ).stdout
    )
    session = created["session"]["id"]
    result = runner.invoke(
        app,
        [
            "chat",
            "configure",
            session,
            "--runtime",
            "pi",
            "--model",
            "default",
            "-w",
            str(workspace),
        ],
    )
    assert result.exit_code == 1
    assert "has no proven bounded" in result.output
    as_json = runner.invoke(
        app, ["chat", "configure", session, "--entry", "nope", "-w", str(workspace), "--json"]
    )
    assert as_json.exit_code == 1 and "no provider named 'nope'" in as_json.output
