"""Run the repository's required pre-push test suites."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TestCheck:
    """One test suite required before a push."""

    label: str
    command: tuple[str, ...]


PYTHON_TEST_GROUPS: tuple[tuple[str, str], ...] = (
    ("contract", "contract"),
    ("end-to-end", "e2e"),
    ("integration", "integration"),
    ("performance", "perf"),
    ("unit", "unit"),
)


ALL_TEST_CHECKS: tuple[TestCheck, ...] = (
    *(
        TestCheck(
            f"Python {label} tests",
            ("uv", "run", "pytest", f"tests/{directory}", "-q"),
        )
        for label, directory in PYTHON_TEST_GROUPS
    ),
    TestCheck(
        "pnpm workspace test suites",
        ("pnpm.cmd" if os.name == "nt" else "pnpm", "-r", "test"),
    ),
)


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def run_checks(*, runner: Runner = subprocess.run) -> int:
    """Run every required test suite and return the first failure code."""
    for check in ALL_TEST_CHECKS:
        print(f"Running {check.label}: {' '.join(check.command)}", flush=True)
        try:
            result = runner(check.command)
        except FileNotFoundError as exc:
            missing = exc.filename or str(exc)
            print(f"Cannot run {check.label}: missing executable {missing}", file=sys.stderr)
            return 127
        if result.returncode != 0:
            print(
                f"{check.label} failed with exit code {result.returncode}; push blocked.",
                file=sys.stderr,
            )
            return result.returncode
    print("All required test suites passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the repository command
    raise SystemExit(run_checks())
