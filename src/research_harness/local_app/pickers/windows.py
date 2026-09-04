"""Windows folder dialog through a fixed PowerShell script run in a short-lived process."""

from __future__ import annotations

from dataclasses import dataclass, field

from research_harness.local_app.pickers.base import (
    FolderSelection,
    SubprocessRunner,
    WhichFunction,
    default_runner,
    default_which,
    manual_fallback,
    run_folder_dialog,
)

__all__ = ["POWERSHELL_CANDIDATES", "WINDOWS_PICKER_SCRIPT", "WindowsFolderPicker"]

WINDOWS_PICKER_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $args[0]
$dialog.UseDescriptionForTitle = $true
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.Write($dialog.SelectedPath)
    exit 0
}
exit 1
""".strip()
"""Constant script; the window title arrives as `$args[0]`, never as interpolated source."""

POWERSHELL_CANDIDATES = ("pwsh", "powershell.exe", "powershell")
"""PowerShell 7 first, then Windows PowerShell."""


@dataclass(frozen=True, slots=True)
class WindowsFolderPicker:
    """Shows the native `FolderBrowserDialog` from a non-interactive PowerShell host."""

    run: SubprocessRunner = field(default=default_runner)
    which: WhichFunction = field(default=default_which)

    def select_folder(self, title: str) -> FolderSelection:
        """Ask Windows for one existing directory."""
        for candidate in POWERSHELL_CANDIDATES:
            if executable := self.which(candidate):
                argv = [
                    executable,
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    WINDOWS_PICKER_SCRIPT,
                    title,
                ]
                return run_folder_dialog(argv, "native", self.run)
        return manual_fallback()
