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

__all__ = [
    "POWERSHELL_CANDIDATES",
    "WINDOWS_PICKER_SCRIPT",
    "WINDOWS_TITLE_ENV",
    "WindowsFolderPicker",
]

WINDOWS_TITLE_ENV = "RESEARCH_HARNESS_PICKER_TITLE"
"""The window title reaches the script as an environment variable.

`-Command` does not bind trailing arguments to `$args` -- it joins them into the command
text -- so a title passed positionally is parsed as source and the dialog never opens. An
environment variable keeps the script a constant that no caller's text can extend.
"""

WINDOWS_PICKER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$title = $env:RESEARCH_HARNESS_PICKER_TITLE
if (-not $title) { $title = 'Choose a folder' }
$selected = $null
$failure = $null
try {
    $shell = New-Object -ComObject Shell.Application
    # 0x01 return only file-system directories, 0x10 offer a path box, 0x40 resizable.
    $folder = $shell.BrowseForFolder(0, $title, 0x51)
    if ($null -ne $folder) { $selected = $folder.Self.Path }
} catch {
    $failure = $_.Exception.Message
}
if ($failure) { [Console]::Error.Write($failure); exit 3 }
if ($selected) { [Console]::Out.Write($selected); exit 0 }
exit 1
""".strip()
"""Constant script: the title arrives in the environment, never as interpolated source.

The dialog is the shell's `BrowseForFolder` rather than `System.Windows.Forms`, because a
WinForms dialog needs a single-threaded apartment and PowerShell 7 runs multi-threaded by
default -- there `ShowDialog` throws, the host exits 1, and a caller cannot tell that from
someone pressing Cancel. The exit codes are explicit for the same reason: 0 chose a folder,
1 cancelled, 3 failed with the reason on stderr.
"""

POWERSHELL_CANDIDATES = ("pwsh", "powershell.exe", "powershell")
"""PowerShell 7 first, then Windows PowerShell."""


@dataclass(frozen=True, slots=True)
class WindowsFolderPicker:
    """Shows the shell's folder dialog from a non-interactive PowerShell host."""

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
                ]
                return run_folder_dialog(argv, "native", self.run, env={WINDOWS_TITLE_ENV: title})
        return manual_fallback()
