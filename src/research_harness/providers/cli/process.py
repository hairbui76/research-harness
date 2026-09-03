"""One bounded subprocess: spawn, drain, limit, cancel, clean up (CLI providers spec §14).

Both pipes are drained by threads so a chatty stderr cannot deadlock stdout. Output is
capped, every read has a deadline, and cancellation closes stdin, terminates the whole
process group (POSIX) or tree (Windows), and kills after a short grace. Nothing here
persists a byte: stdout lines go to the caller, stderr keeps only a bounded tail.
"""

from __future__ import annotations

import contextlib
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Self

from research_harness.providers.cli.types import ProbeOutcome

__all__ = [
    "CANCEL_GRACE_SECONDS",
    "DEFAULT_OUTPUT_LIMIT_BYTES",
    "MAX_LINE_BYTES",
    "STDERR_TAIL_BYTES",
    "BoundedProcess",
    "OutputLimitExceeded",
    "ProcessTimeout",
    "run_probe",
]

DEFAULT_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
STDERR_TAIL_BYTES = 16 * 1024
CANCEL_GRACE_SECONDS = 2.0
_WINDOWS = sys.platform == "win32"


class ProcessTimeout(Exception):  # noqa: N818 - the spec names this interface; callers import it
    """The deadline passed before the stream ended."""


class OutputLimitExceeded(Exception):  # noqa: N818 - spec-mandated name, imported by callers
    """The process wrote more than the cap allows."""


def _os_error_text(exc: OSError) -> str:
    name = getattr(exc, "strerror", None) or type(exc).__name__
    code = os.strerror(exc.errno) if exc.errno else ""
    tag = {2: "ENOENT", 13: "EACCES", 20: "ENOTDIR", 8: "ENOEXEC"}.get(exc.errno or 0, "OSError")
    return f"{tag}: {name or code}"


def _popen_kwargs() -> dict[str, Any]:
    """The one `Popen` keyword that detaches the child so its whole tree can be signalled.

    `Any` values because the two platform branches spread into different `Popen` overloads.
    """
    if _WINDOWS:  # pragma: no cover - exercised on Windows only
        # Only defined in the Windows build, so typeshed hides it from a POSIX check.
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


def _group_id(process: subprocess.Popen[bytes]) -> int | None:
    """Capture the child's process-group id now, while it is certainly still alive.

    `start_new_session=True` makes the child its own group leader, so this equals its pid.
    Capturing it once is what makes group signalling safe: `poll()` reaps the child, and a
    reaped pid is free for reuse, so signalling `process.pid` afterwards could reach an
    unrelated group. Linux keeps a `struct pid` alive while any process still references it
    as a pgid, so the id captured here stays reserved for as long as anything in the tree
    lives -- the stale-pid window is closed by construction. Windows kills by pid instead.
    """
    if _WINDOWS:  # pragma: no cover - exercised on Windows only
        return None
    try:
        return os.getpgid(process.pid)
    except ProcessLookupError:  # pragma: no cover - unreachable before the first reap
        return process.pid


def _kill_tree(process: subprocess.Popen[bytes], pgid: int | None, *, force: bool) -> None:
    if process.poll() is not None and not force:
        return
    if _WINDOWS:  # pragma: no cover - exercised on Windows only
        flag = ["/F"] if force else []
        subprocess.run(
            ["taskkill", "/T", *flag, "/PID", str(process.pid)], capture_output=True, check=False
        )
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(pgid if pgid is not None else process.pid, sig)
    except ProcessLookupError:
        return  # every member of the group is already gone
    except PermissionError:  # pragma: no cover - a foreign group; fall back to the child
        process.send_signal(sig)


def run_probe(
    argv: tuple[str, ...], *, env: Mapping[str, str], timeout: float, cwd: Path | None = None
) -> ProbeOutcome:
    """Run a short side-effect-free probe to completion, killing its tree on timeout."""
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd) if cwd else None,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_popen_kwargs(),
        )
    except OSError as exc:
        return ProbeOutcome(
            argv=argv, exit_code=None, stdout="", stderr="", os_error=_os_error_text(exc)
        )
    pgid = _group_id(process)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process, pgid, force=True)
        out, err = process.communicate()
        return ProbeOutcome(
            argv=argv,
            exit_code=process.returncode,
            stdout=_text(out),
            stderr=_text(err),
            timed_out=True,
        )
    return ProbeOutcome(
        argv=argv, exit_code=process.returncode, stdout=_text(out), stderr=_text(err)
    )


def _text(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


class BoundedProcess:
    """A running CLI with a deadline, an output cap, and process-tree cancellation."""

    def __init__(
        self, process: subprocess.Popen[bytes], *, timeout: float, output_limit: int
    ) -> None:
        self._process = process
        self._pgid = _group_id(process)
        self._deadline = time.monotonic() + timeout
        self._limit = output_limit
        self._lines: queue.Queue[str | Exception | None] = queue.Queue()
        self._stderr: deque[bytes] = deque()
        self._stderr_bytes = 0
        self._bytes_read = 0
        self._stdin_closed = False
        assert process.stdout is not None and process.stderr is not None
        self._readers = (
            threading.Thread(target=self._drain_stdout, args=(process.stdout,), daemon=True),
            threading.Thread(target=self._drain_stderr, args=(process.stderr,), daemon=True),
        )
        for reader in self._readers:
            reader.start()

    @classmethod
    def spawn(
        cls,
        argv: tuple[str, ...],
        *,
        env: Mapping[str, str],
        cwd: Path,
        timeout: float,
        output_limit: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    ) -> BoundedProcess:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_popen_kwargs(),
        )
        return cls(process, timeout=timeout, output_limit=output_limit)

    # -- stdin ---------------------------------------------------------------

    def write(self, text: str) -> None:
        stdin = self._process.stdin
        if stdin is None or self._stdin_closed:
            return
        try:
            stdin.write(text.encode("utf-8"))
            stdin.flush()
        except (BrokenPipeError, OSError):
            self._stdin_closed = True

    def close_stdin(self) -> None:
        stdin = self._process.stdin
        if stdin is not None and not self._stdin_closed:
            self._stdin_closed = True
            with contextlib.suppress(OSError):
                stdin.close()

    # -- stdout --------------------------------------------------------------

    def _drain_stdout(self, stream: IO[bytes]) -> None:
        # The size argument is the bound: a line longer than the cap is never materialised
        # whole, it comes back truncated and trips the check below.
        try:
            with contextlib.suppress(ValueError, OSError):
                for raw in iter(lambda: stream.readline(MAX_LINE_BYTES + 1), b""):
                    self._bytes_read += len(raw)
                    if len(raw) > MAX_LINE_BYTES or self._bytes_read > self._limit:
                        self._lines.put(OutputLimitExceeded())
                        return
                    self._lines.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _drain_stderr(self, stream: IO[bytes]) -> None:
        # Suppressed because a stream closed underneath a reader raises into the thread,
        # where it would surface only as an unhandled-thread-exception warning.
        with contextlib.suppress(ValueError, OSError):
            for chunk in iter(lambda: stream.read(4096), b""):
                self._stderr.append(chunk)
                self._stderr_bytes += len(chunk)
                while self._stderr_bytes > STDERR_TAIL_BYTES and len(self._stderr) > 1:
                    self._stderr_bytes -= len(self._stderr.popleft())

    def lines(self) -> Iterator[str]:
        """Yield stdout lines until EOF; raise on the deadline or the output cap."""
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout()
            try:
                item = self._lines.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                self.cancel()
                raise item
            yield item

    def stderr_tail(self) -> str:
        return b"".join(self._stderr).decode("utf-8", errors="replace")[-STDERR_TAIL_BYTES:]

    # -- lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def cancel(self, *, grace: float = CANCEL_GRACE_SECONDS) -> None:
        """Close stdin, terminate the tree, kill it after ``grace`` seconds.

        Idempotent and bounded, so it is safe to call twice and safe to call on a child that
        has already exited: a grandchild that inherited the pipes can still be holding them
        open, and only signalling the group lets the reader threads reach EOF.
        """
        self.close_stdin()
        if self.running:
            _kill_tree(self._process, self._pgid, force=False)
            if self.wait(grace) is None:
                _kill_tree(self._process, self._pgid, force=True)
                self.wait(grace)
        # Unconditional: reaps grandchildren that outlived the direct child.
        _kill_tree(self._process, self._pgid, force=True)
        for reader in self._readers:
            reader.join(timeout=1.0)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        # Always, never `if self.running`: an exited child can leave a grandchild holding the
        # pipes, and closing a stream while its reader thread is blocked on it deadlocks on
        # the buffered-reader lock. `cancel` joins the readers, so the closes below are safe.
        self.cancel()
        for stream in (self._process.stdout, self._process.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
