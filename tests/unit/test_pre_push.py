"""The repository-wide pre-push test gate."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts.pre_push import ALL_TEST_CHECKS, PYTHON_TEST_GROUPS, run_checks


def completed(argv: Sequence[str], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), returncode)


def test_the_gate_runs_the_complete_python_and_workspace_test_suites() -> None:
    calls: list[list[str]] = []

    def succeed(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(argv)

    result = run_checks(runner=succeed)

    assert result == 0
    assert calls == [
        ["uv", "run", "pytest", "tests/contract", "-q"],
        ["uv", "run", "pytest", "tests/e2e", "-q"],
        ["uv", "run", "pytest", "tests/integration", "-q"],
        ["uv", "run", "pytest", "tests/perf", "-q"],
        ["uv", "run", "pytest", "tests/unit", "-q"],
        ["pnpm.cmd" if os.name == "nt" else "pnpm", "-r", "test"],
    ]


def test_the_gate_stops_at_the_first_failed_suite() -> None:
    calls: list[list[str]] = []

    def fail_python(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return completed(argv, returncode=7)

    result = run_checks(runner=fail_python)

    assert result == 7
    assert calls == [["uv", "run", "pytest", "tests/contract", "-q"]]


def test_the_gate_reports_a_missing_test_runner_as_a_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def missing(_argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("uv")

    result = run_checks(runner=missing)

    assert result == 127
    captured = capsys.readouterr()
    assert "uv" in captured.err


def test_the_declared_gate_contains_only_full_test_commands() -> None:
    assert [check.label for check in ALL_TEST_CHECKS] == [
        "Python contract tests",
        "Python end-to-end tests",
        "Python integration tests",
        "Python performance tests",
        "Python unit tests",
        "pnpm workspace test suites",
    ]
    assert all("test" in " ".join(check.command) for check in ALL_TEST_CHECKS)


def test_every_python_test_group_is_part_of_the_gate() -> None:
    tests_root = Path("tests")
    discovered_groups = {
        path.name for path in tests_root.iterdir() if path.is_dir() and any(path.rglob("test_*.py"))
    }
    configured_groups = {directory for _label, directory in PYTHON_TEST_GROUPS}

    assert configured_groups == discovered_groups
    assert list(tests_root.glob("test_*.py")) == []
