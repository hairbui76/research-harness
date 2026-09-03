"""What is installed, what `research.yaml` asked for, and what to tell a researcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.manuscript.toolchain import (
    ALLOWED_EXTRA_ARGS,
    ENGINE_PREFERENCE,
    LatexEngine,
    ManuscriptSettings,
    ToolchainConfigError,
    ToolchainUnavailableError,
    discover_engines,
    discover_toolchain,
)


def bin_dir(root: Path, *names: str) -> str:
    """A throwaway PATH entry holding executables with the given engine names."""
    directory = root / "bin"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        executable = directory / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    return str(directory)


# -- discovery --------------------------------------------------------------------------


def test_discovery_returns_installed_engines_in_preference_order(tmp_path: Path) -> None:
    path = bin_dir(tmp_path, "xelatex", "tectonic", "latexmk")

    found = discover_engines(path=path)

    assert [item.engine for item in found] == [
        LatexEngine.LATEXMK,
        LatexEngine.TECTONIC,
        LatexEngine.XELATEX,
    ]


def test_discovery_finds_nothing_in_an_empty_search_path(tmp_path: Path) -> None:
    assert discover_engines(path=bin_dir(tmp_path)) == ()


def test_discovery_never_runs_an_engine_to_learn_that_it_exists(tmp_path: Path) -> None:
    """The executable is not even readable as a program; discovery is filesystem-only."""
    directory = tmp_path / "bin"
    directory.mkdir()
    (directory / "pdflatex").write_bytes(b"\x00\x01\x02")
    (directory / "pdflatex").chmod(0o755)

    found = discover_engines(path=str(directory))

    assert [item.engine for item in found] == [LatexEngine.PDFLATEX]


def test_the_preference_order_puts_the_engines_that_rerun_themselves_first() -> None:
    assert ENGINE_PREFERENCE[:2] == (LatexEngine.LATEXMK, LatexEngine.TECTONIC)


# -- selection --------------------------------------------------------------------------


def test_without_configuration_the_first_preferred_installed_engine_is_selected(
    tmp_path: Path,
) -> None:
    report = discover_toolchain(path=bin_dir(tmp_path, "lualatex", "tectonic"))

    assert report.available
    assert report.configured is None
    assert report.selected is not None
    assert report.selected.engine is LatexEngine.TECTONIC


def test_a_configured_engine_wins_over_the_preference_order(tmp_path: Path) -> None:
    settings = ManuscriptSettings(engine=LatexEngine.LUALATEX)

    report = discover_toolchain(settings, path=bin_dir(tmp_path, "lualatex", "tectonic"))

    assert report.selected is not None
    assert report.selected.engine is LatexEngine.LUALATEX
    assert "pinned by manuscript.engine" in " ".join(report.guidance)


def test_a_configured_engine_that_is_not_installed_reports_what_is(tmp_path: Path) -> None:
    settings = ManuscriptSettings(engine=LatexEngine.XELATEX)

    report = discover_toolchain(settings, path=bin_dir(tmp_path, "tectonic"))

    assert not report.available
    guidance = " ".join(report.guidance)
    assert "xelatex" in guidance
    assert "Installed engines: tectonic" in guidance
    assert "No manuscript source was read or modified." in report.guidance


def test_no_engine_at_all_yields_installation_guidance(tmp_path: Path) -> None:
    report = discover_toolchain(path=bin_dir(tmp_path))

    assert not report.available
    guidance = " ".join(report.guidance)
    assert "No LaTeX engine was found on PATH." in guidance
    assert "tectonic" in guidance and "TeX Live" in guidance
    assert "installs nothing itself" in guidance


def test_requiring_an_unavailable_toolchain_raises_with_the_guidance(tmp_path: Path) -> None:
    report = discover_toolchain(path=bin_dir(tmp_path))

    with pytest.raises(ToolchainUnavailableError) as error:
        report.require()

    assert error.value.report is report
    assert "No LaTeX engine was found on PATH." in str(error.value)


# -- settings from research.yaml --------------------------------------------------------


def test_an_absent_manuscript_section_gives_the_documented_defaults() -> None:
    settings = ManuscriptSettings.from_config(None)

    assert settings.engine is None
    assert settings.entry_file == "main.tex"
    assert settings.timeout_seconds == 120
    assert settings.extra_args == ()
    assert settings.synctex is True


def test_settings_are_read_from_the_manuscript_section() -> None:
    settings = ManuscriptSettings.from_config(
        {
            "engine": "tectonic",
            "entry_file": "paper/main.tex",
            "timeout_seconds": 45,
            "extra_args": ["-halt-on-error"],
            "synctex": False,
        }
    )

    assert settings.engine is LatexEngine.TECTONIC
    assert settings.entry_file == "paper/main.tex"
    assert settings.timeout_seconds == 45
    assert settings.extra_args == ("-halt-on-error",)
    assert settings.synctex is False


@pytest.mark.parametrize(
    "entry_file",
    ["../secrets.tex", "/etc/passwd.tex", "sections/../../out.tex", "notes.txt", ""],
)
def test_an_entry_file_that_escapes_or_is_not_tex_is_refused(entry_file: str) -> None:
    with pytest.raises(ToolchainConfigError):
        ManuscriptSettings.from_config({"entry_file": entry_file})


@pytest.mark.parametrize(
    "argument",
    ["-shell-escape", "--shell-escape", "-Z shell-escape", "-output-directory=/tmp", "-e"],
)
def test_a_compiler_flag_outside_the_allowlist_is_refused(argument: str) -> None:
    with pytest.raises(ToolchainConfigError) as error:
        ManuscriptSettings.from_config({"extra_args": [argument]})

    assert "not allowed" in str(error.value)


def test_the_allowlist_holds_no_flag_that_can_run_a_program_or_redirect_output() -> None:
    substrings = ("shell-escape", "output-directory", "outdir", "exec", "write18")
    exact = {"-e", "-r", "-o", "-jobname", "--outdir", "-latexoption"}
    assert not [
        argument
        for argument in ALLOWED_EXTRA_ARGS
        if argument in exact or any(token in argument for token in substrings)
    ]


def test_an_unknown_key_in_the_manuscript_section_is_refused_by_name() -> None:
    with pytest.raises(ToolchainConfigError) as error:
        ManuscriptSettings.from_config({"engien": "tectonic"})

    assert "research.yaml" in str(error.value)


@pytest.mark.parametrize("timeout", [0, -1, 100_000])
def test_an_impossible_timeout_is_refused(timeout: int) -> None:
    with pytest.raises(ToolchainConfigError):
        ManuscriptSettings.from_config({"timeout_seconds": timeout})
