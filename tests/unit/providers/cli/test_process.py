"""Bounded spawn, drain, limits, cancellation, and cleanup (CLI providers spec §14)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from research_harness.providers.cli.process import (
    CANCEL_GRACE_SECONDS,
    BoundedProcess,
    OutputLimitExceeded,
    ProcessTimeout,
    run_probe,
)
from tests.fixtures.cli.fakes import FakeCli


@pytest.fixture
def fake(tmp_path: Path) -> FakeCli:
    return FakeCli.install(
        tmp_path, "fake", probes=[{"args": ["slow"], "stdout": "late", "sleep": 5}]
    )


def test_run_probe_captures_exit_code_and_both_streams(fake: FakeCli) -> None:
    outcome = run_probe((str(fake.executable), "--version"), env=fake.env(), timeout=5)
    assert outcome.started and outcome.exit_code == 0
    assert outcome.stdout.strip() == "fake 1.2.3" and not outcome.timed_out


def test_run_probe_reports_a_missing_executable_as_an_os_error(tmp_path: Path) -> None:
    outcome = run_probe((str(tmp_path / "missing"), "--version"), env={"PATH": ""}, timeout=5)
    assert not outcome.started and outcome.os_error and "ENOENT" in outcome.os_error


def test_run_probe_reports_a_non_executable_file(tmp_path: Path) -> None:
    path = tmp_path / "plain"
    path.write_text("not a program", encoding="utf-8")
    outcome = run_probe((str(path), "--version"), env={"PATH": ""}, timeout=5)
    assert not outcome.started and outcome.os_error and "EACCES" in outcome.os_error


def test_run_probe_times_out_and_kills(fake: FakeCli) -> None:
    started = time.monotonic()
    outcome = run_probe((str(fake.executable), "slow"), env=fake.env(), timeout=0.5)
    assert outcome.timed_out and time.monotonic() - started < 4


def test_lines_arrive_in_order_and_stdin_is_delivered(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["one", "two", "three"])
    with BoundedProcess.spawn(
        (str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10
    ) as process:
        process.write("the prompt\n")
        process.close_stdin()
        assert list(process.lines()) == ["one", "two", "three"]
        assert process.wait(5) == 0
    assert fake.runs()[0]["stdin"] == "the prompt\n"


def test_stderr_is_drained_concurrently_and_only_a_tail_is_kept(
    fake: FakeCli, tmp_path: Path
) -> None:
    fake.set_run(lines=["ok"], stderr="x" * 100_000)
    with BoundedProcess.spawn(
        (str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10
    ) as process:
        process.close_stdin()
        assert list(process.lines()) == ["ok"]
        process.wait(5)
        assert 0 < len(process.stderr_tail()) <= 16_384


def test_the_output_cap_stops_a_runaway_process(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["y" * 1000] * 200)
    with BoundedProcess.spawn(
        (str(fake.executable), "run"),
        env=fake.env(),
        cwd=tmp_path,
        timeout=10,
        output_limit=50_000,
    ) as process:
        process.close_stdin()
        with pytest.raises(OutputLimitExceeded):
            for _ in process.lines():
                pass
    assert not process.running


def test_a_deadline_raises_and_the_tree_is_gone(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["partial"], hang=True)
    with BoundedProcess.spawn(
        (str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=0.8
    ) as process:
        process.close_stdin()
        seen: list[str] = []
        with pytest.raises(ProcessTimeout):
            for line in process.lines():
                seen.append(line)
        assert seen == ["partial"]
        process.cancel(grace=0.2)
        assert not process.running and process.exit_code is not None


def test_cancel_terminates_grandchildren(tmp_path: Path) -> None:
    """The fake spawns a child that would outlive it; the process group takes both."""
    parent = tmp_path / "parent.py"
    marker = tmp_path / "grandchild.pid"
    parent.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "print('spawned', flush=True)\n"
        "time.sleep(3600)\n",
        encoding="utf-8",
    )

    with BoundedProcess.spawn(
        (sys.executable, str(parent)),
        env={"PATH": os.environ["PATH"]},
        cwd=tmp_path,
        timeout=10,
    ) as process:
        assert next(process.lines()) == "spawned"
        pid = int(marker.read_text())
        process.cancel(grace=0.2)
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_exiting_the_context_cancels_a_running_process(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(hang=True)
    with BoundedProcess.spawn(
        (str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10
    ) as process:
        process.close_stdin()
    assert not process.running


def test_the_default_grace_is_short() -> None:
    assert CANCEL_GRACE_SECONDS == 2.0
