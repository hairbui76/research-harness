"""Fixtures for the LaTeX compile tests: a small real project and a fake engine.

`project/` is an ordinary little manuscript - a `main.tex` that `\\input`s a section, a
display equation, a `\\cite`, and a `references.bib` - small enough to compile in a second
with a real toolchain and complete enough to exercise includes, citations, and SyncTeX.

`fake-latex` is the engine the suite normally runs: it takes the argv the compile service
builds, writes the files a real engine writes, and does what markers in the source tell it
to. :func:`install_fake_engine` puts it on a throwaway PATH under whichever engine names a
test wants, so discovery, selection, and execution are all exercised for real.

`recorded/` holds output captured from a real `tectonic` 0.17 run of `project/`: the
SyncTeX map (with the compile's absolute paths rewritten to `/home/researcher/manuscript`
so the sample is machine-independent) and the transcript and stderr of the same project
with an undefined control sequence added.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

__all__ = [
    "FAKE_ENGINE",
    "FIXTURE_DIR",
    "PROJECT_DIR",
    "RECORDED_DIR",
    "RECORDED_SOURCE_ROOT",
    "copy_project",
    "install_fake_engine",
]

FIXTURE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = FIXTURE_DIR / "project"
RECORDED_DIR = FIXTURE_DIR / "recorded"
FAKE_ENGINE = FIXTURE_DIR / "fake-latex"

RECORDED_SOURCE_ROOT = Path("/home/researcher/manuscript")
"""Project root the recorded SyncTeX sample was rewritten to refer to."""


def copy_project(destination: Path) -> Path:
    """Copy the fixture manuscript into ``destination`` (created if needed)."""
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PROJECT_DIR, destination, dirs_exist_ok=True)
    return destination


def install_fake_engine(bin_dir: Path, *names: str) -> Path:
    """Put the fake engine on a throwaway PATH under each of ``names``.

    A launcher rather than a copy, so the fixture runs under the interpreter the suite is
    running in and the test never depends on the checked-out file mode.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in names or ("pdflatex",):
        launcher = bin_dir / name
        launcher.write_text(
            f"#!{sys.executable}\n"
            "import runpy, sys\n"
            f"sys.argv[0] = {str(FAKE_ENGINE)!r}\n"
            f"runpy.run_path({str(FAKE_ENGINE)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
    return bin_dir
