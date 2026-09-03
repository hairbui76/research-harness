"""Bounded spawn, drain, limits, cancellation, and cleanup (CLI providers spec §14)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from research_harness.providers.cli.process import (
    CANCEL_GRACE_SECONDS,
    MAX_LINE_BYTES,
    PROBE_OUTPUT_LIMIT_BYTES,
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


def test_exiting_is_bounded_when_a_grandchild_inherits_the_pipes(tmp_path: Path) -> None:
    """The child exits at once but a grandchild holds stdout/stderr open (spec §14).

    Without a group kill the reader threads never see EOF, and closing a stream under a
    blocked reader deadlocks on the buffered-reader lock -- so `with` would never return.
    """
    parent = tmp_path / "parent.py"
    marker = tmp_path / "grandchild.pid"
    parent.write_text(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "print('parent done', flush=True)\n",
        encoding="utf-8",
    )
    started = time.monotonic()
    with BoundedProcess.spawn(
        (sys.executable, str(parent)),
        env={"PATH": os.environ["PATH"]},
        cwd=tmp_path,
        timeout=10,
    ) as process:
        assert next(process.lines()) == "parent done"
        pid = int(marker.read_text())
        # Pin the exact state the bug needs: the direct child is definitively reaped while
        # the grandchild is still alive holding the inherited pipes open.
        assert process.wait(5) == 0
        assert os.kill(pid, 0) is None
    assert time.monotonic() - started < 5
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_one_enormous_line_is_capped_before_it_is_buffered(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["z" * (MAX_LINE_BYTES + 100)])
    with BoundedProcess.spawn(
        (str(fake.executable), "run"),
        env=fake.env(),
        cwd=tmp_path,
        timeout=10,
        output_limit=64 * 1024 * 1024,
    ) as process:
        process.close_stdin()
        with pytest.raises(OutputLimitExceeded):
            for _ in process.lines():
                pass
        # The bound, not just the detection: the reader must never have materialised the
        # whole line, only the capped read plus the one byte that proves it overflowed.
        assert process._bytes_read <= MAX_LINE_BYTES + 1
    assert not process.running


def test_a_stdin_write_the_child_never_drains_hits_the_same_deadline(
    fake: FakeCli, tmp_path: Path
) -> None:
    """A pipe write blocks once the OS buffer fills; the deadline has to cover it too.

    The fake never reads its stdin and then sleeps for an hour, so a prompt larger than the
    64 KiB pipe buffer would hold `write` forever -- past every timeout §14 promises.
    """
    fake.set_run(read_stdin=False, hang=True, lines=[])
    started = time.monotonic()
    with BoundedProcess.spawn(
        (str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=1
    ) as process:
        with pytest.raises(ProcessTimeout):
            process.write("x" * 200_000)
        assert time.monotonic() - started < 10
        assert not process.running, "the tree is killed exactly as a stalled read kills it"
    assert process.exit_code is not None, "no zombie is left behind"


def test_a_prompt_smaller_than_the_pipe_buffer_is_written_without_waiting(
    fake: FakeCli, tmp_path: Path
) -> None:
    fake.set_run(lines=["ok"])
    with BoundedProcess.spawn(
        (str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10
    ) as process:
        process.write("the prompt\n")
        process.close_stdin()
        assert list(process.lines()) == ["ok"]
    assert fake.runs()[0]["stdin"] == "the prompt\n"


def test_a_flooding_probe_is_capped_and_says_it_was_truncated(tmp_path: Path) -> None:
    """A probe is a `--version` or a help text; 3 MiB of it is never held in memory."""
    flood = FakeCli.install(
        tmp_path,
        "flood",
        probes=[{"args": ["models"], "stdout": "z" * (3 * 1024 * 1024)}],
    )
    started = time.monotonic()

    outcome = run_probe((str(flood.executable), "models"), env=flood.env(), timeout=20)

    assert outcome.truncated and not outcome.timed_out
    assert 0 < len(outcome.stdout) <= PROBE_OUTPUT_LIMIT_BYTES
    assert time.monotonic() - started < 20


def test_an_ordinary_probe_is_whole_and_not_marked_truncated(fake: FakeCli) -> None:
    outcome = run_probe((str(fake.executable), "--version"), env=fake.env(), timeout=5)
    assert outcome.stdout.strip() == "fake 1.2.3" and not outcome.truncated
