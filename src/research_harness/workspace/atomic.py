"""Durable primitives shared by every canonical writer: atomic replace and fsync.

A canonical file must never be observed half-written, so every write lands in a temp file
in the same directory, is fsynced, and is then renamed over the target. Renaming within a
directory is atomic on POSIX, so a reader sees either the old bytes or the new bytes.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

__all__ = [
    "TEMP_PREFIX",
    "atomic_write_bytes",
    "atomic_write_text",
    "clean_partials",
    "fsync_directory",
    "write_bytes_durably",
]

TEMP_PREFIX = ".tmp-"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically, creating parent directories."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f"{TEMP_PREFIX}{path.name}.{uuid4().hex}"
    try:
        write_bytes_durably(temp, data)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    fsync_directory(directory)


def atomic_write_text(path: Path, text: str) -> None:
    """UTF-8 flavour of :func:`atomic_write_bytes`."""
    atomic_write_bytes(path, text.encode("utf-8"))


def write_bytes_durably(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` and fsync the file (not the directory entry)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def fsync_directory(directory: Path) -> None:
    """Persist a directory entry so a rename survives a crash; a no-op where unsupported."""
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platforms without directory descriptors
        return
    try:
        os.fsync(handle)
    except OSError:  # pragma: no cover - filesystems that cannot fsync a directory
        pass
    finally:
        os.close(handle)


def clean_partials(directory: Path) -> None:
    """Remove temp files a crashed writer left behind; they are never valid state."""
    if not directory.is_dir():
        return
    for leftover in directory.glob(f"{TEMP_PREFIX}*"):
        with suppress(OSError):
            leftover.unlink()
