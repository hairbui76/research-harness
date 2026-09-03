"""The workspace lock that serializes accepted-state mutation (Product 8.2).

One advisory `flock` on `.research/lock` is what makes "validate the change, its event, and
its invalidation set, then commit" a single logical unit across processes: a CLI, an editor
extension, and a server can all hold the same workspace open, but only one of them mutates
accepted state at a time. The lock file also carries the holder's pid and timestamp so a
blocked process can say *who* it is waiting for.

The lock is advisory and process-scoped: it protects concurrent harness processes, not a
researcher editing YAML by hand (Product 36 accepts that and validates on next load).
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from research_harness.domain.errors import WorkspaceError
from research_harness.workspace.layout import WorkspaceLayout

__all__ = ["DEFAULT_LOCK_TIMEOUT", "WorkspaceLock", "WorkspaceLockedError", "lock_holder"]

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT = 30.0
_POLL_INTERVAL = 0.02


class WorkspaceLockedError(WorkspaceError):
    """Another process holds the workspace lock and did not release it in time."""


def lock_holder(layout: WorkspaceLayout) -> dict[str, Any] | None:
    """Diagnostics written by the current holder, or ``None`` when unreadable."""
    try:
        text = layout.lock_file.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


class WorkspaceLock:
    """Exclusive, non-reentrant advisory lock over one workspace.

    Used as a context manager::

        with WorkspaceLock(layout):
            ...          # accepted-state mutation

    Blocks until the lock is free or ``timeout`` seconds elapse, then raises
    :class:`WorkspaceLockedError` naming the process that holds it.
    """

    def __init__(self, layout: WorkspaceLayout, timeout: float = DEFAULT_LOCK_TIMEOUT) -> None:
        self._layout = layout
        self._timeout = float(timeout)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        """True while this instance owns the lock."""
        return self._fd is not None

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def path(self) -> Path:
        """The lock file this instance contends for."""
        return self._layout.lock_file

    def acquire(self) -> Self:
        """Take the lock, waiting up to ``timeout`` seconds."""
        if self._fd is not None:
            raise WorkspaceError("the workspace lock is not reentrant; it is already held here")
        self._layout.lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._layout.lock_file, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + self._timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):  # pragma: no cover
                        raise
                    if time.monotonic() >= deadline:
                        raise WorkspaceLockedError(self._timeout_message()) from exc
                    time.sleep(min(_POLL_INTERVAL, max(deadline - time.monotonic(), 0.0)))
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        self._write_holder(fd)
        return self

    def release(self) -> None:
        """Release the lock; safe to call when it is not held."""
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.release()

    # -- diagnostics ---------------------------------------------------------

    def _write_holder(self, fd: int) -> None:
        """Record pid/host/time in the lock file so a waiter can name the holder."""
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "host": _hostname(),
                "acquired_at": datetime.now(UTC).isoformat(),
            },
            sort_keys=True,
        )
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, payload.encode("utf-8") + b"\n")
            os.fsync(fd)
        except OSError:  # pragma: no cover - diagnostics must never fail a mutation
            logger.debug("could not record lock holder in %s", self._layout.lock_file)

    def _timeout_message(self) -> str:
        holder = lock_holder(self._layout)
        who = (
            f" held by pid {holder.get('pid')} on {holder.get('host')} "
            f"since {holder.get('acquired_at')}"
            if holder
            else ""
        )
        return (
            f"workspace {self._layout.root} is locked{who}; "
            f"gave up after {self._timeout:g}s waiting for accepted-state access"
        )


def _hostname() -> str:
    try:
        return os.uname().nodename
    except (AttributeError, OSError):  # pragma: no cover - non-POSIX platforms
        return "unknown"
