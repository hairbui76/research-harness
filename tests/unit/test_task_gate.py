"""Completion evidence must describe the tested tree, not an agent's claim."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.task_gate import (
    Check,
    check_repository,
    execute,
    fingerprint,
    loop,
    start_hook,
    status,
    stop_hook,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".task-gate/\n__pycache__/\n", encoding="utf-8")
    (tmp_path / "app.txt").write_text("before", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def command(code: str) -> Check:
    return Check("fixture", (sys.executable, "-c", code))


def test_success_expires_when_a_tracked_or_new_source_changes(repo: Path) -> None:
    assert check_repository(repo, checks=[command("print('passed')")]) == 0
    assert status(repo) == 0
    (repo / "app.txt").write_text("after", encoding="utf-8")
    assert status(repo) != 0
    assert check_repository(repo, checks=[command("pass")]) == 0
    (repo / "new.txt").write_text("new source", encoding="utf-8")
    assert status(repo) != 0


def test_a_failed_check_replaces_previous_success_and_preserves_log(repo: Path) -> None:
    assert check_repository(repo, checks=[command("pass")]) == 0
    assert check_repository(repo, checks=[command("print('broken'); exit(7)")]) == 7
    assert status(repo) != 0
    report = json.loads((repo / ".task-gate/latest.json").read_text())
    assert report["status"] == "failed"
    assert "broken" in (repo / report["checks"][0]["log"]).read_text()


def test_an_edit_during_checks_cannot_receive_a_pass(repo: Path) -> None:
    check = command("from pathlib import Path; Path('app.txt').write_text('racing edit')")
    assert check_repository(repo, checks=[check]) != 0
    assert status(repo) != 0


def test_missing_runner_and_timeout_fail_closed(repo: Path) -> None:
    assert check_repository(repo, checks=[Check("missing", ("nonexistent-task-tool-xyz",))]) != 0
    assert check_repository(repo, checks=[command("import time; time.sleep(30)")], timeout=0.1) != 0
    assert status(repo) != 0


def test_a_concurrent_check_does_not_overwrite_evidence(repo: Path) -> None:
    directory = repo / ".task-gate"
    directory.mkdir()
    (directory / "check.lock").write_text("another process")
    assert check_repository(repo, checks=[command("pass")]) != 0
    assert not (directory / "latest.json").exists()


def test_reports_do_not_change_the_source_fingerprint(repo: Path) -> None:
    before = fingerprint(repo)
    assert check_repository(repo, checks=[command("pass")]) == 0
    assert fingerprint(repo) == before


def test_loop_feeds_failure_to_adapter_then_retests_repaired_code(repo: Path) -> None:
    adapter = repo / "adapter.py"
    adapter.write_text(
        "import sys\nfrom pathlib import Path\n"
        "prompt = sys.stdin.read()\n"
        "if 'failed' in prompt:\n"
        "    Path('app.txt').write_text('fixed')\n",
        encoding="utf-8",
    )
    check = command(
        "from pathlib import Path; exit(0 if Path('app.txt').read_text() == 'fixed' else 1)"
    )
    assert loop(repo, "Fix the app", [sys.executable, str(adapter)], checks=[check]) == 0
    assert (repo / "app.txt").read_text() == "fixed"
    assert status(repo) == 0


def test_loop_stops_when_agent_makes_no_progress(repo: Path) -> None:
    assert loop(repo, "Fix it", [sys.executable, "-c", "pass"], checks=[command("exit(1)")]) != 0
    assert status(repo) != 0


def test_loop_budget_exhaustion_never_becomes_success(repo: Path) -> None:
    agent = [
        sys.executable,
        "-c",
        "from pathlib import Path; p=Path('app.txt'); p.write_text(p.read_text()+'x')",
    ]
    assert loop(repo, "Fix it", agent, rounds=2, checks=[command("exit(1)")]) != 0
    assert (repo / "app.txt").read_text() == "beforexx"
    assert status(repo) != 0


def test_claude_continuations_are_bounded_and_reset_for_a_new_task(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("TASK_GATE_ACTIVE", raising=False)

    def event() -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id":"test"}'))

    event()
    start_hook(repo)
    # Discussion without a source change must not cause a test/repair loop.
    event()
    stop_hook(repo)
    assert capsys.readouterr().out == ""
    (repo / "app.txt").write_text("coding task")
    for _ in range(3):
        event()
        stop_hook(repo)
        assert json.loads(capsys.readouterr().out)["decision"] == "block"
    event()
    stop_hook(repo)
    assert json.loads(capsys.readouterr().out)["continue"] is False
    event()
    start_hook(repo)
    (repo / "app.txt").write_text("next coding task")
    event()
    stop_hook(repo)
    assert json.loads(capsys.readouterr().out)["decision"] == "block"
    assert check_repository(repo, checks=[command("pass")]) == 0
    capsys.readouterr()
    event()
    stop_hook(repo)
    assert capsys.readouterr().out == ""


def test_git_hook_rejects_dirty_tree_and_propagates_failing_gate(repo: Path) -> None:
    """Exercise the installed entry point against an isolated Git repository, without pushing."""
    source = Path(__file__).resolve().parents[2]
    scripts = repo / "scripts"
    scripts.mkdir()
    for name in ("task_gate.py", "pre_push.py"):
        shutil.copyfile(source / "scripts" / name, scripts / name)
    (repo / "package.json").write_text(
        json.dumps({"scripts": {"test:pre-push": 'node -e "process.exit(9)"'}}),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Gate Test",
            "-c",
            "user.email=gate@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=repo,
        check=True,
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    update = f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"

    def run_hook(refs: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(scripts / "task_gate.py"), "push-hook"],
            cwd=repo,
            input=refs,
            capture_output=True,
            text=True,
        )

    assert run_hook(update).returncode == 9
    (repo / "app.txt").write_text("uncommitted")
    refused = run_hook(update)
    assert refused.returncode == 1
    assert "commit all changes" in refused.stdout
    assert run_hook(f"(delete) {'0' * 40} refs/heads/old {head}\n").returncode == 0


def test_interrupt_terminates_the_child_and_propagates_cancellation(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = subprocess.Popen.communicate

    def interrupted(process: subprocess.Popen, *args: object, **kwargs: object) -> None:
        # Inject a user interruption at the OS wait boundary, with a real child to clean up.
        monkeypatch.setattr(subprocess.Popen, "communicate", original)
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute(
            [sys.executable, "-c", "import time; time.sleep(30)"], repo, repo / "cancel.log", 60
        )


def test_hook_installer_preserves_other_existing_hooks(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    scripts = repo / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[2]
    shutil.copyfile(source / "scripts/install-hooks.mjs", scripts / "install-hooks.mjs")
    (repo / ".githooks").mkdir()
    (repo / ".githooks/pre-push").write_text("#!/bin/sh\nexit 0\n")
    existing = repo / ".git/hooks/pre-commit"
    existing.write_text("#!/bin/sh\nexit 7\n")
    result = subprocess.run(
        ["node", str(scripts / "install-hooks.mjs")], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert existing.read_text() == "#!/bin/sh\nexit 7\n"
    setting = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert setting.returncode == 1


def test_git_hook_environment_cannot_redirect_checks_to_another_repository(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = fingerprint(repo)
    other = repo.parent / f"{repo.name}-other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert fingerprint(repo) == before
    log = repo / ".task-gate/location.log"
    log.parent.mkdir()
    assert execute(["git", "rev-parse", "--show-toplevel"], repo, log, 10) == 0
    assert Path(log.read_text().strip()).resolve() == repo.resolve()
