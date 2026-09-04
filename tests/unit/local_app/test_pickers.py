"""Folder-picker adapters: argument arrays, cancellation, and manual fallback.

Every test injects a fake runner; none of them may launch a real dialog.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from research_harness.domain.errors import ResearchHarnessError
from research_harness.local_app.pickers import (
    FolderPicker,
    FolderPickerError,
    FolderSelection,
    LinuxFolderPicker,
    ManualFolderPicker,
    WindowsFolderPicker,
    folder_picker,
)
from research_harness.local_app.pickers import base as picker_base
from research_harness.local_app.pickers.windows import (
    WINDOWS_PICKER_SCRIPT,
    WINDOWS_TITLE_ENV,
)

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def completed(
    argv: Sequence[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=list(argv), returncode=returncode, stdout=stdout, stderr=stderr
    )


def recorder(
    calls: list[list[str]],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    envs: list[Mapping[str, str] | None] | None = None,
) -> Runner:
    def run(
        argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if envs is not None:
            envs.append(env)
        return completed(argv, returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def only(name: str, executable: str) -> Callable[[str], str | None]:
    def which(candidate: str) -> str | None:
        return executable if candidate == name else None

    return which


def refuse(  # pragma: no cover
    _argv: Sequence[str], *, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    raise AssertionError("the picker must not spawn a process in this case")


# --- Linux -----------------------------------------------------------------


def test_linux_prefers_zenity() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("zenity", "/usr/bin/zenity"),
        run=recorder(calls, stdout="/tmp/project\n"),
    )

    result = picker.select_folder("Open project")

    assert calls == [
        ["/usr/bin/zenity", "--file-selection", "--directory", "--title", "Open project"]
    ]
    assert result.path == Path("/tmp/project")
    assert result.method == "zenity"
    assert result.cancelled is False
    assert result.fallback_required is False


def test_linux_falls_back_to_kdialog_when_zenity_is_missing() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("kdialog", "/usr/bin/kdialog"),
        run=recorder(calls, stdout="/home/researcher/project\n"),
    )

    result = picker.select_folder("Open project")

    assert calls == [
        [
            "/usr/bin/kdialog",
            "--getexistingdirectory",
            str(Path.home()),
            "--title",
            "Open project",
        ]
    ]
    assert result.method == "kdialog"
    assert result.path == Path("/home/researcher/project")


def test_linux_without_a_picker_requests_manual_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name, *_a, **_k: None)

    result = LinuxFolderPicker(run=refuse).select_folder("Open project")

    assert result.fallback_required is True
    assert result.path is None
    assert result.method == "manual"
    assert result.cancelled is False


def test_linux_default_which_resolves_through_shutil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name, *_a, **_k: "/usr/bin/zenity" if name == "zenity" else None
    )
    calls: list[list[str]] = []

    result = LinuxFolderPicker(run=recorder(calls, stdout="/tmp/p")).select_folder("Open")

    assert calls[0][0] == "/usr/bin/zenity"
    assert result.path == Path("/tmp/p")


def test_cancel_is_not_an_error() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("zenity", "/usr/bin/zenity"), run=recorder(calls, returncode=1)
    )

    result = picker.select_folder("Open")

    assert result.cancelled is True
    assert result.path is None
    assert result.method == "zenity"
    assert result.fallback_required is False


def test_success_exit_with_empty_stdout_is_cancelled() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("zenity", "/usr/bin/zenity"), run=recorder(calls, returncode=0, stdout="\n")
    )

    assert picker.select_folder("Open").cancelled is True


def test_trailing_newlines_are_stripped_from_the_selected_path() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("zenity", "/usr/bin/zenity"),
        run=recorder(calls, stdout="/tmp/a b\r\n"),
    )

    assert picker.select_folder("Open").path == Path("/tmp/a b")


def test_unexpected_exit_code_raises_a_picker_error() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("zenity", "/usr/bin/zenity"),
        run=recorder(calls, returncode=127, stderr="zenity: cannot open display"),
    )

    with pytest.raises(FolderPickerError) as raised:
        picker.select_folder("Open")

    assert "127" in str(raised.value)
    assert "cannot open display" in str(raised.value)
    assert isinstance(raised.value, ResearchHarnessError)


def test_picker_error_diagnostic_is_bounded() -> None:
    calls: list[list[str]] = []
    picker = LinuxFolderPicker(
        which=only("zenity", "/usr/bin/zenity"),
        run=recorder(calls, returncode=5, stderr="x" * 10_000),
    )

    with pytest.raises(FolderPickerError) as raised:
        picker.select_folder("Open")

    assert len(str(raised.value)) <= 500


def test_timeout_becomes_a_picker_error() -> None:
    def time_out(
        argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=list(argv), timeout=600.0)

    picker = LinuxFolderPicker(which=only("zenity", "/usr/bin/zenity"), run=time_out)

    with pytest.raises(FolderPickerError, match="timed out"):
        picker.select_folder("Open")


# --- Windows ---------------------------------------------------------------


def test_windows_passes_the_title_in_the_environment_not_in_the_command() -> None:
    """`-Command` joins trailing arguments into the command text.

    PowerShell binds `$args` for `-File`, not for `-Command`: a title passed positionally
    is appended to the script, which then fails to parse, and the host exits 1 -- which
    the caller reads as a cancellation, so nothing opens and nothing is reported.
    """
    calls: list[list[str]] = []
    envs: list[Mapping[str, str] | None] = []
    picker = WindowsFolderPicker(
        which=only("pwsh", r"C:\pwsh.exe"),
        run=recorder(calls, stdout="C:\\research\\project", envs=envs),
    )

    result = picker.select_folder("Choose a project")

    assert calls == [
        [
            r"C:\pwsh.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            WINDOWS_PICKER_SCRIPT,
        ]
    ]
    assert envs == [{WINDOWS_TITLE_ENV: "Choose a project"}]
    assert result.method == "native"
    assert result.path == Path("C:\\research\\project")


def test_windows_never_lets_a_title_extend_the_script() -> None:
    """The script is a constant: no caller's text becomes source."""
    calls: list[list[str]] = []
    envs: list[Mapping[str, str] | None] = []
    picker = WindowsFolderPicker(
        which=only("pwsh", r"C:\pwsh.exe"),
        run=recorder(calls, stdout="C:\\x", envs=envs),
    )

    picker.select_folder("'; Remove-Item C:\\ -Recurse; '")

    assert calls[0][-1] == WINDOWS_PICKER_SCRIPT
    assert "Remove-Item" not in " ".join(calls[0])
    assert envs == [{WINDOWS_TITLE_ENV: "'; Remove-Item C:\\ -Recurse; '"}]


def test_the_windows_script_reads_the_title_and_reports_a_failure_apart_from_a_cancel() -> None:
    """A dialog that never opened must not look like someone pressing Cancel."""
    assert f"$env:{WINDOWS_TITLE_ENV}" in WINDOWS_PICKER_SCRIPT
    assert "BrowseForFolder" in WINDOWS_PICKER_SCRIPT, (
        "a WinForms dialog needs a single-threaded apartment, which PowerShell 7 is not"
    )
    assert "exit 3" in WINDOWS_PICKER_SCRIPT and "exit 1" in WINDOWS_PICKER_SCRIPT


def test_windows_prefers_pwsh_over_powershell() -> None:
    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        return {"pwsh": r"C:\pwsh.exe", "powershell.exe": r"C:\powershell.exe"}.get(name)

    WindowsFolderPicker(which=which, run=recorder(calls, stdout="C:\\x")).select_folder("t")

    assert calls[0][0] == r"C:\pwsh.exe"


def test_windows_falls_back_to_powershell_when_pwsh_is_missing() -> None:
    calls: list[list[str]] = []
    picker = WindowsFolderPicker(
        which=only("powershell.exe", r"C:\powershell.exe"),
        run=recorder(calls, stdout="C:\\x"),
    )

    picker.select_folder("t")

    assert calls[0][0] == r"C:\powershell.exe"


def test_windows_without_powershell_requests_manual_fallback() -> None:
    result = WindowsFolderPicker(which=lambda _name: None, run=refuse).select_folder("t")

    assert result.fallback_required is True
    assert result.method == "manual"
    assert result.path is None


def test_windows_cancel_is_not_an_error() -> None:
    calls: list[list[str]] = []
    picker = WindowsFolderPicker(
        which=only("pwsh", r"C:\pwsh.exe"), run=recorder(calls, returncode=1)
    )

    result = picker.select_folder("t")

    assert result.cancelled is True
    assert result.method == "native"


def test_windows_script_is_a_fixed_single_command_without_interpolation() -> None:
    assert WINDOWS_PICKER_SCRIPT.strip() == WINDOWS_PICKER_SCRIPT
    for placeholder in ("{}", "{0}", "{title}", "%s", "$args"):
        assert placeholder not in WINDOWS_PICKER_SCRIPT, (
            "the script takes no substitution: the title arrives in the environment"
        )


# --- Manual picker and factory ---------------------------------------------


def test_manual_picker_always_requests_fallback() -> None:
    result = ManualFolderPicker().select_folder("anything")

    assert result == FolderSelection(
        path=None, method="manual", cancelled=False, fallback_required=True
    )


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Linux", LinuxFolderPicker),
        ("Windows", WindowsFolderPicker),
        ("Darwin", ManualFolderPicker),
        ("FreeBSD", ManualFolderPicker),
    ],
)
def test_factory_picks_the_adapter_for_the_system(system: str, expected: type[object]) -> None:
    assert isinstance(folder_picker(system), expected)


def test_factory_defaults_to_the_running_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker_base.platform, "system", lambda: "Windows")

    assert isinstance(folder_picker(), WindowsFolderPicker)


def test_every_adapter_satisfies_the_folder_picker_protocol() -> None:
    for picker in (LinuxFolderPicker(), WindowsFolderPicker(), ManualFolderPicker()):
        assert isinstance(picker, FolderPicker)


# --- Result model and default runner ---------------------------------------


def test_folder_selection_is_frozen_and_rejects_unknown_fields() -> None:
    selection = FolderSelection(
        path=Path("/tmp/p"), method="zenity", cancelled=False, fallback_required=False
    )

    with pytest.raises(ValueError):
        selection.cancelled = True  # type: ignore[misc]
    with pytest.raises(ValueError):
        FolderSelection(
            path=None,
            method="manual",
            cancelled=False,
            fallback_required=True,
            extra="no",  # type: ignore[call-arg]
        )


def test_default_runner_never_uses_a_shell_and_bounds_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"] = list(argv)
        seen.update(kwargs)
        return completed(argv)

    monkeypatch.setattr(subprocess, "run", fake_run)

    picker_base.default_runner(["/usr/bin/zenity", "--directory"])

    assert seen["argv"] == ["/usr/bin/zenity", "--directory"]
    assert seen.get("shell", False) is False
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["check"] is False
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["timeout"] == picker_base.DIALOG_TIMEOUT_SECONDS
    assert picker_base.DIALOG_TIMEOUT_SECONDS >= 300
