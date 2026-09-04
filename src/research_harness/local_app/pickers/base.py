"""Shared folder-picker contract: result type, error, and the subprocess plumbing.

Adapters differ only in which executable they resolve and which argument array they
build; classification of the child process' exit code lives here so that Windows and
Linux agree on what counts as a selection, a cancellation, and a failure.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from research_harness.domain.errors import ResearchHarnessError

__all__ = [
    "DIALOG_TIMEOUT_SECONDS",
    "MAX_DIAGNOSTIC_CHARS",
    "FolderPicker",
    "FolderPickerError",
    "FolderSelection",
    "ManualFolderPicker",
    "PickerMethod",
    "SubprocessRunner",
    "WhichFunction",
    "current_system",
    "default_runner",
    "default_which",
    "manual_fallback",
    "run_folder_dialog",
]

PickerMethod = Literal["native", "zenity", "kdialog", "manual"]
"""How a folder was chosen, or `manual` when the UI must ask for a typed path."""

WhichFunction = Callable[[str], str | None]


@runtime_checkable
class SubprocessRunner(Protocol):
    """Runs one picker helper. `env` names variables to add to the child's own."""

    def __call__(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]: ...


DIALOG_TIMEOUT_SECONDS = 600.0
"""A dialog waits for a human, so the bound is generous; it only stops a wedged helper."""

MAX_DIAGNOSTIC_CHARS = 500
"""Upper bound on a picker error message, so child-process output cannot flood a log."""


class FolderPickerError(ResearchHarnessError):
    """The platform folder dialog failed; cancellation is not one of these."""


class FolderSelection(BaseModel):
    """Outcome of one folder dialog: a path, a cancellation, or a request to fall back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: Path | None
    method: PickerMethod
    cancelled: bool
    fallback_required: bool


@runtime_checkable
class FolderPicker(Protocol):
    """Selects one existing directory without changing any state."""

    def select_folder(self, title: str) -> FolderSelection: ...


def manual_fallback() -> FolderSelection:
    """No platform dialog is available: the UI must offer an authenticated path field."""
    return FolderSelection(path=None, method="manual", cancelled=False, fallback_required=True)


def default_which(name: str) -> str | None:
    """Resolve an executable at call time so tests can patch `shutil.which`."""
    return shutil.which(name)


def default_runner(
    argv: Sequence[str], *, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a picker helper as an argument array: never a shell, never inheriting stdin.

    A helper that reads a variable still needs the rest of the environment -- a
    PowerShell host without `SystemRoot` does not start -- so `env` is added to this
    process' own rather than replacing it.
    """
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=DIALOG_TIMEOUT_SECONDS,
        env=None if env is None else {**os.environ, **env},
    )


def current_system() -> str:
    """The running platform's name, indirected so the factory stays testable."""
    return platform.system()


def run_folder_dialog(
    argv: Sequence[str],
    method: PickerMethod,
    run: SubprocessRunner,
    *,
    env: Mapping[str, str] | None = None,
) -> FolderSelection:
    """Execute a picker helper and classify its exit code."""
    try:
        completed = run(argv, env=env)
    except subprocess.TimeoutExpired as error:
        raise FolderPickerError(
            _bounded(f"the {method} folder dialog timed out after {DIALOG_TIMEOUT_SECONDS:.0f}s")
        ) from error
    return classify(completed, method)


def classify(
    completed: subprocess.CompletedProcess[str],
    method: PickerMethod,
) -> FolderSelection:
    """Exit 0 with a path is a selection, exit 0 without one or exit 1 is a cancellation."""
    if completed.returncode == 0:
        selected = (completed.stdout or "").rstrip("\r\n")
        if selected:
            return FolderSelection(
                path=Path(selected), method=method, cancelled=False, fallback_required=False
            )
        return _cancelled(method)
    if completed.returncode == 1:
        return _cancelled(method)
    raise FolderPickerError(_failure_message(completed, method))


def _cancelled(method: PickerMethod) -> FolderSelection:
    return FolderSelection(path=None, method=method, cancelled=True, fallback_required=False)


def _failure_message(completed: subprocess.CompletedProcess[str], method: PickerMethod) -> str:
    detail = ((completed.stderr or "") or (completed.stdout or "")).strip()
    message = f"the {method} folder dialog failed with exit code {completed.returncode}"
    if detail:
        message = f"{message}: {detail}"
    return _bounded(message)


def _bounded(message: str) -> str:
    if len(message) <= MAX_DIAGNOSTIC_CHARS:
        return message
    return message[: MAX_DIAGNOSTIC_CHARS - 1] + "…"


@dataclass(frozen=True, slots=True)
class ManualFolderPicker:
    """Used where no supported native dialog exists; always asks for the typed-path field."""

    def select_folder(self, title: str) -> FolderSelection:
        """Report unavailability without spawning anything."""
        del title
        return manual_fallback()
