"""Shared task completion checks and a bounded, provider-neutral repair loop."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# Also supports direct execution by Git hooks, outside Python's package importer.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.pre_push import ALL_TEST_CHECKS

PNPM = "pnpm.cmd" if os.name == "nt" else "pnpm"


@dataclass(frozen=True)
class Check:
    """One required check, executed without a command shell."""

    label: str
    command: tuple[str, ...]


CHECKS = (
    Check("Python lint", ("uv", "run", "ruff", "check", ".")),
    Check("Python formatting", ("uv", "run", "ruff", "format", "--check", ".")),
    Check("Python types", ("uv", "run", "mypy", "src")),
    Check("Frontend types", (PNPM, "-r", "typecheck")),
    Check(
        "Browser test types",
        (
            PNPM,
            "--filter",
            "research-harness-web",
            "exec",
            "tsc",
            "-p",
            "../browser-tests/tsconfig.json",
        ),
    ),
    Check("Frontend lint and design tokens", (PNPM, "-r", "lint")),
    *(Check(item.label, item.command) for item in ALL_TEST_CHECKS),
    Check("Production builds", (PNPM, "run", "build")),
    Check("Browser and real backend", (PNPM, "run", "test:browser")),
)

# Repository-local variables listed by `git rev-parse --local-env-vars`. Hooks export
# these; inheriting them would redirect tests that create their own temporary repos.
LOCAL_GIT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)


def clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in LOCAL_GIT_ENV:
        environment.pop(name, None)
    return environment


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", *args], cwd=root, stderr=subprocess.DEVNULL, env=clean_environment()
    )


def fingerprint(root: Path) -> str:
    """Hash tracked and nonignored new files, index, and commit, including deletions."""
    digest = hashlib.sha256()
    digest.update(git(root, "ls-files", "--stage", "-z"))
    try:
        digest.update(git(root, "rev-parse", "HEAD"))
    except subprocess.CalledProcessError:
        digest.update(b"unborn")
    for name in sorted(
        set(git(root, "ls-files", "-c", "-o", "--exclude-standard", "-z").split(b"\0"))
    ):
        if not name:
            continue
        path = root / os.fsdecode(name)
        digest.update(name + b"\0")
        if path.is_symlink():
            digest.update(b"symlink:" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        elif path.is_dir():
            # A submodule's checked out commit and changes are also inputs.
            digest.update(git(path, "rev-parse", "HEAD"))
            digest.update(git(path, "diff", "HEAD"))
        else:
            digest.update(b"deleted")
    return digest.hexdigest()


def write_report(root: Path, report: dict) -> None:
    destination = root / ".task-gate/latest.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def execute(
    argv: Sequence[str], root: Path, log: Path, timeout: float, prompt: str | None = None
) -> int:
    """Keep logs on disk; terminate the child tree on a timeout or interruption."""
    environment = dict(clean_environment(), TASK_GATE_ACTIVE="1", PYTHONUTF8="1")
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    with log.open("w", encoding="utf-8") as output:
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                **options,
            )
        except OSError as exc:
            output.write(f"Cannot start check: {exc}\n")
            return 127
        try:
            process.communicate(input=prompt, timeout=timeout)
            return process.returncode
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            output.write("\nStopped: timeout or interruption.\n")
            if isinstance(exc, KeyboardInterrupt):
                raise
            return 124


def check_repository(root: Path, *, checks: Sequence[Check] = CHECKS, timeout: float = 3600) -> int:
    """Run the full gate; only publish success for a tree unchanged during the run."""
    directory = root / ".task-gate"
    directory.mkdir(exist_ok=True)
    lock = directory / "check.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        print("Another gate is running (or left .task-gate/check.lock). Do not run concurrently.")
        return 2
    try:
        with handle:
            handle.write(str(os.getpid()))
        before = fingerprint(root)
        report = {"status": "running", "fingerprint": before, "started": time.time(), "checks": []}
        write_report(root, report)
        result = 0
        for index, check in enumerate(checks):
            log = directory / f"{index:02d}.log"
            print(
                f"[{index + 1}/{len(checks)}] {check.label}: {' '.join(check.command)}", flush=True
            )
            code = execute(check.command, root, log, timeout)
            report["checks"].append(
                {
                    "label": check.label,
                    "command": list(check.command),
                    "exit_code": code,
                    "log": log.relative_to(root).as_posix(),
                }
            )
            write_report(root, report)
            if code:
                result = code
                print(log.read_text(encoding="utf-8", errors="replace")[-12000:], flush=True)
                break
        if fingerprint(root) != before:
            result = result or 3
            report["reason"] = "Source changed during verification. Run the gate again."
        report["status"] = "passed" if result == 0 else "failed"
        report["finished"] = time.time()
        write_report(root, report)
        print(f"Task gate {report['status']}. Report: {directory / 'latest.json'}", flush=True)
        return result
    except KeyboardInterrupt:
        write_report(
            root, {"status": "cancelled", "checks": [], "reason": "User interrupted verification."}
        )
        raise
    finally:
        lock.unlink(missing_ok=True)


def status(root: Path) -> int:
    """Reject absent, failed, running, or stale completion evidence."""
    try:
        report = json.loads((root / ".task-gate/latest.json").read_text(encoding="utf-8"))
        valid = report["status"] == "passed" and report["fingerprint"] == fingerprint(root)
        valid = valid and not (root / ".task-gate/check.lock").exists()
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        valid = False
    return 0 if valid else 1


def loop(
    root: Path,
    task: str,
    agent: Sequence[str],
    *,
    rounds: int = 3,
    timeout: float = 3600,
    checks: Sequence[Check] = CHECKS,
) -> int:
    """Run an explicitly selected adapter, verify, and feed failures back within a budget."""
    directory = root / ".task-gate"
    directory.mkdir(exist_ok=True)
    prompt = task
    for attempt in range(rounds):
        before = fingerprint(root)
        print(f"Agent round {attempt + 1}/{rounds}", flush=True)
        code = execute(
            agent,
            root,
            directory / f"agent-{attempt + 1}.log",
            timeout,
            prompt + "\nDo not push, merge, bypass checks, or weaken tests. "
            "The controller runs verification.\n",
        )
        if code:
            write_report(root, {"status": "failed", "reason": f"Agent exited {code}", "checks": []})
            return code
        code = check_repository(root, checks=checks, timeout=timeout)
        if code == 0:
            return 0
        if attempt > 0 and fingerprint(root) == before:
            print("Stopped: repair made no source changes. See .task-gate/latest.json.")
            return code
        prompt = (
            task + "\nVerification failed. Read .task-gate/latest.json and its check logs, "
            "fix the cause, and finish."
        )
    print("Stopped: repair round limit reached; task remains failed.")
    return 1


def session_file(root: Path, event: dict) -> Path:
    session = hashlib.sha256(str(event.get("session_id", "unknown")).encode()).hexdigest()[:20]
    directory = root / ".task-gate"
    directory.mkdir(exist_ok=True)
    return directory / f"stop-{session}.json"


def start_hook(root: Path) -> int:
    """Reset the repair budget at each user task; remember read-only discussions."""
    if os.environ.get("TASK_GATE_ACTIVE") == "1":
        return 0
    path = session_file(root, json.load(sys.stdin))
    path.write_text(json.dumps({"count": 0, "baseline": fingerprint(root)}), encoding="utf-8")
    return 0


def stop_hook(root: Path) -> int:
    """Claude Stop hook: ask for verifiable evidence, with bounded continuations."""
    if os.environ.get("TASK_GATE_ACTIVE") == "1":
        return 0
    event = json.load(sys.stdin)
    counter = session_file(root, event)
    state = json.loads(counter.read_text(encoding="utf-8")) if counter.exists() else {}
    if state.get("baseline") == fingerprint(root):
        return 0
    if status(root) == 0:
        counter.unlink(missing_ok=True)
        return 0
    count = state.get("count", 0)
    state["count"] = count + 1
    counter.write_text(json.dumps(state), encoding="utf-8")
    if count >= 3:
        print(
            json.dumps(
                {
                    "continue": False,
                    "stopReason": (
                        "Task verification is still missing or failing after 3 continuations. "
                        "Task is NOT verified; inspect .task-gate/latest.json."
                    ),
                }
            )
        )
    else:
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        "Before completing this code task, run pnpm run task:check from the "
                        "repository root. Read .task-gate/latest.json and fix failures. Rerun. "
                        "Do not weaken tests or claim completion with a failed/stale report."
                    ),
                }
            )
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "status", "loop", "start", "stop", "push-hook"])
    parser.add_argument("--task-file", type=Path)
    parser.add_argument(
        "--agent-file", type=Path, help="JSON array of argv; task/feedback arrives on stdin"
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=3600)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.timeout <= 0 or not 1 <= args.rounds <= 5:
        parser.error("timeout must be positive and rounds must be 1..5")
    if args.action == "status":
        code = status(root)
        print(
            "Current tree verified."
            if code == 0
            else "Missing, failed, or stale verification. Run pnpm run task:check."
        )
        return code
    if args.action == "stop":
        return stop_hook(root)
    if args.action == "start":
        return start_hook(root)
    if args.action == "push-hook":
        head = git(root, "rev-parse", "HEAD").decode().strip()
        updates = [line.split() for line in sys.stdin if line.strip()]
        pushes = [item for item in updates if set(item[1]) != {"0"}]
        if not pushes:
            return 0
        if any(item[1] != head for item in pushes) or git(root, "status", "--porcelain").strip():
            print(
                "Push blocked: commit all changes and push only the checked-out HEAD. "
                "Test each branch in its own worktree."
            )
            return 1
        return subprocess.call([PNPM, "run", "test:pre-push"], cwd=root, env=clean_environment())
    if args.action == "loop":
        if not args.task_file or not args.agent_file:
            parser.error("loop requires --task-file and --agent-file")
        agent = json.loads(args.agent_file.read_text(encoding="utf-8"))
        if (
            not isinstance(agent, list)
            or not agent
            or not all(isinstance(arg, str) and arg for arg in agent)
        ):
            parser.error("agent-file must contain a nonempty JSON argv array")
        return loop(
            root,
            args.task_file.read_text(encoding="utf-8"),
            agent,
            rounds=args.rounds,
            timeout=args.timeout,
        )
    return check_repository(root, timeout=args.timeout)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Task cancelled; no further repair round will start.", file=sys.stderr)
        raise SystemExit(130) from None
