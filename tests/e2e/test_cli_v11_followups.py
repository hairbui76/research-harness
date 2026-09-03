"""Two terminal papercuts from the v1.1 dogfood, and the behaviour that closes them.

Both are the same kind of defect: the daemon and the CLI knew something the researcher at
the terminal could not find out.

1. **`research manuscript build latest`** answered `no manuscript build latest`, while
   `GET /manuscript/builds/latest/pdf` had always accepted the name — so a client that
   showed a PDF could not ask about the build it was showing.
2. **`research chat send --script`** took a JSON file whose shape was never stated. A chat
   turn's reply schema is `ChatReply`, and the role-keyed shape the workflow commands take
   cannot work here (`conversation` is a routing role, not a workflow role), so a file in
   that shape reached the provider and failed as a schema error about a name the researcher
   never typed. The shape is now stated in the option help and in the refusal.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner, Result

from research_harness.cli.commands import init as init_commands
from research_harness.cli.commands import manuscript as manuscript_commands
from research_harness.cli.commands import session as session_commands
from research_harness.cli.commands.session import CHAT_SCRIPT_SHAPE
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.latex import copy_project, install_fake_engine

runner = CliRunner()

ANSWER = "Batching reduced tail latency by nine percent across the pilot corpus."


@pytest.fixture
def cli() -> typer.Typer:
    app = typer.Typer(name="research", no_args_is_help=True, add_completion=False)
    for module in (init_commands, manuscript_commands, session_commands):
        module.register(app)
    return app


def run(app: typer.Typer, *args: str) -> Result:
    result = runner.invoke(app, list(args))
    if result.exit_code != 0:  # pragma: no cover - surfaced only when the fix regresses
        raise AssertionError(f"`research {' '.join(args)}` failed: {result.output}")
    return result


def printed(result: Result) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(result.stdout)
    return body


# -- 1. `latest` and `last-good` on the terminal ------------------------------


@pytest.mark.skipif(os.name == "nt", reason="the fake engine is a POSIX executable script")
class TestBuildAliases:
    @pytest.fixture
    def workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        root = tmp_path / "project"
        repo = WorkspaceRepository.init(root, "cli-build-aliases")
        copy_project(repo.layout.manuscript_dir)
        monkeypatch.setenv("PATH", str(install_fake_engine(tmp_path / "bin", "pdflatex")))
        yield root

    def test_the_terminal_reads_a_build_by_the_name_the_pdf_route_uses(
        self, cli: typer.Typer, workspace: Path
    ) -> None:
        compiled = printed(run(cli, "manuscript", "compile", "-w", str(workspace), "--json"))

        latest = printed(run(cli, "manuscript", "build", "latest", "-w", str(workspace), "--json"))
        last_good = printed(
            run(cli, "manuscript", "build", "last-good", "-w", str(workspace), "--json")
        )

        assert latest["build_id"] == compiled["build_id"]
        assert last_good["build_id"] == compiled["build_id"]

    def test_synctex_takes_the_same_names_on_the_build_option(
        self, cli: typer.Typer, workspace: Path
    ) -> None:
        run(cli, "manuscript", "compile", "-w", str(workspace), "--json")

        forward = run(
            cli,
            "manuscript",
            "synctex",
            "sections/intro.tex:4",
            "-w",
            str(workspace),
            "--build",
            "latest",
        )

        assert forward.stdout.startswith("page ")

    def test_an_unknown_name_is_still_refused(self, cli: typer.Typer, workspace: Path) -> None:
        run(cli, "manuscript", "compile", "-w", str(workspace), "--json")

        refused = runner.invoke(cli, ["manuscript", "build", "newest", "-w", str(workspace)])

        assert refused.exit_code == 1
        assert "no manuscript build newest" in refused.stderr

    def test_the_help_names_both_aliases(self, cli: typer.Typer) -> None:
        """A name that only works if you already know it is not a feature."""
        help_text = " ".join(run(cli, "manuscript", "build", "--help").stdout.split())

        assert "latest" in help_text and "last-good" in help_text


# -- 2. the chat script shape ------------------------------------------------


@pytest.fixture
def chat_workspace(cli: typer.Typer, tmp_path: Path) -> Path:
    root = tmp_path / "chat"
    run(cli, "init", str(root), "--name", "cli-chat-script")
    run(cli, "chat", "new", "Latency study", "-w", str(root), "--json")
    return root


def script(tmp_path: Path, payload: Any, name: str = "reply.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_list_of_text_replies_is_the_shape_a_chat_script_takes(
    cli: typer.Typer, chat_workspace: Path, tmp_path: Path
) -> None:
    sent = printed(
        run(
            cli,
            "chat",
            "send",
            "CS0001",
            "what do we know?",
            "-w",
            str(chat_workspace),
            "--script",
            str(script(tmp_path, [{"text": ANSWER}])),
            "--json",
        )
    )

    assert sent["state"] == "succeeded"
    assert sent["text"] == ANSWER


def test_one_reply_object_is_accepted_as_a_single_answer(
    cli: typer.Typer, chat_workspace: Path, tmp_path: Path
) -> None:
    sent = printed(
        run(
            cli,
            "chat",
            "send",
            "CS0001",
            "what do we know?",
            "-w",
            str(chat_workspace),
            "--script",
            str(script(tmp_path, {"text": ANSWER})),
            "--json",
        )
    )

    assert sent["text"] == ANSWER


def test_the_role_keyed_shape_is_refused_by_name_before_anything_is_written(
    cli: typer.Typer, chat_workspace: Path, tmp_path: Path
) -> None:
    """The dogfood case: it used to reach the provider and fail as a schema error."""
    refused = runner.invoke(
        cli,
        [
            "chat",
            "send",
            "CS0001",
            "what do we know?",
            "-w",
            str(chat_workspace),
            "--script",
            str(script(tmp_path, {"writer": [{"draft": "a paragraph"}]})),
        ],
    )

    assert refused.exit_code == 1
    assert 'object with a "text" string' in refused.stderr
    assert "conversation" in refused.stderr
    # Nothing was appended: the refusal happens before the send begins.
    shown = printed(run(cli, "chat", "show", "CS0001", "-w", str(chat_workspace), "--json"))
    assert shown["messages"] == []


def test_a_reply_without_text_is_refused_the_same_way(
    cli: typer.Typer, chat_workspace: Path, tmp_path: Path
) -> None:
    refused = runner.invoke(
        cli,
        [
            "chat",
            "send",
            "CS0001",
            "hello",
            "-w",
            str(chat_workspace),
            "--script",
            str(script(tmp_path, [{"answer": ANSWER}])),
        ],
    )

    assert refused.exit_code == 1
    assert CHAT_SCRIPT_SHAPE.split("—")[0].strip() in " ".join(refused.stderr.split())


def test_an_unreadable_script_says_which_file(
    cli: typer.Typer, chat_workspace: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    refused = runner.invoke(
        cli,
        ["chat", "send", "CS0001", "hello", "-w", str(chat_workspace), "--script", str(broken)],
    )

    assert refused.exit_code == 1
    assert "cannot read script" in refused.stderr


def test_the_option_help_shows_the_shape(cli: typer.Typer) -> None:
    help_text = " ".join(run(cli, "chat", "send", "--help").stdout.split())

    assert '"text"' in help_text
