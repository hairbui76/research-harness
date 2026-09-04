"""Linux folder dialog through `zenity`, then `kdialog`, then a manual-path fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from research_harness.local_app.pickers.base import (
    FolderSelection,
    SubprocessRunner,
    WhichFunction,
    default_runner,
    default_which,
    manual_fallback,
    run_folder_dialog,
)

__all__ = ["LinuxFolderPicker"]


@dataclass(frozen=True, slots=True)
class LinuxFolderPicker:
    """Runs whichever of `zenity`/`kdialog` exists, always as an argument array."""

    run: SubprocessRunner = field(default=default_runner)
    which: WhichFunction = field(default=default_which)

    def select_folder(self, title: str) -> FolderSelection:
        """Ask the desktop for one existing directory."""
        if executable := self.which("zenity"):
            argv = [executable, "--file-selection", "--directory", "--title", title]
            return run_folder_dialog(argv, "zenity", self.run)
        if executable := self.which("kdialog"):
            argv = [executable, "--getexistingdirectory", str(Path.home()), "--title", title]
            return run_folder_dialog(argv, "kdialog", self.run)
        return manual_fallback()
