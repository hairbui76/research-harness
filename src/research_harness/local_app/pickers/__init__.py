"""Folder-picker adapters and the factory that chooses one for the running platform."""

from __future__ import annotations

from research_harness.local_app.pickers.base import (
    DIALOG_TIMEOUT_SECONDS,
    FolderPicker,
    FolderPickerError,
    FolderSelection,
    ManualFolderPicker,
    PickerMethod,
    SubprocessRunner,
    WhichFunction,
    current_system,
    manual_fallback,
)
from research_harness.local_app.pickers.linux import LinuxFolderPicker
from research_harness.local_app.pickers.windows import WINDOWS_PICKER_SCRIPT, WindowsFolderPicker

__all__ = [
    "DIALOG_TIMEOUT_SECONDS",
    "WINDOWS_PICKER_SCRIPT",
    "FolderPicker",
    "FolderPickerError",
    "FolderSelection",
    "LinuxFolderPicker",
    "ManualFolderPicker",
    "PickerMethod",
    "SubprocessRunner",
    "WhichFunction",
    "WindowsFolderPicker",
    "folder_picker",
    "manual_fallback",
]


def folder_picker(system: str | None = None) -> FolderPicker:
    """The adapter for `system` (default: this host); unsupported platforms get manual entry."""
    name = (system if system is not None else current_system()).strip().lower()
    if name == "windows":
        return WindowsFolderPicker()
    if name == "linux":
        return LinuxFolderPicker()
    return ManualFolderPicker()
