"""Which LaTeX engine this machine has, which one the project configured, and what to do.

The harness never ships a TeX distribution and never installs one. It looks for engines
already on `PATH`, checks them against the `manuscript:` section of `research.yaml`, and —
when nothing usable exists — produces setup guidance instead of a failure that leaves the
researcher guessing (LaTeX spec 9). Discovery touches only the filesystem: no engine is
executed to find out that it exists, so opening the manuscript workspace costs nothing and
can never change a source file.

The configured `extra_args` are an allowlist, not a passthrough. A compiler flag is an
execution capability — `-shell-escape` turns a document into arbitrary code — so a flag
that is not on the list is refused when `research.yaml` is read, long before any process
starts.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from research_harness.domain.errors import ResearchHarnessError
from research_harness.manuscript.files import ManuscriptPathError, normalize_relative_path

__all__ = [
    "ALLOWED_EXTRA_ARGS",
    "DEFAULT_ENTRY_FILE",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENGINE_PREFERENCE",
    "MANUSCRIPT_CONFIG_KEY",
    "DiscoveredEngine",
    "LatexEngine",
    "ManuscriptSettings",
    "ToolchainConfigError",
    "ToolchainReport",
    "ToolchainUnavailableError",
    "discover_engines",
    "discover_toolchain",
]

MANUSCRIPT_CONFIG_KEY = "manuscript"
"""Key of the optional `research.yaml` section this module validates."""

DEFAULT_ENTRY_FILE = "main.tex"
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_TIMEOUT_SECONDS = 3600.0


class LatexEngine(StrEnum):
    """A compiler the harness knows how to drive safely."""

    LATEXMK = "latexmk"
    TECTONIC = "tectonic"
    PDFLATEX = "pdflatex"
    XELATEX = "xelatex"
    LUALATEX = "lualatex"


ENGINE_PREFERENCE: tuple[LatexEngine, ...] = (
    LatexEngine.LATEXMK,
    LatexEngine.TECTONIC,
    LatexEngine.PDFLATEX,
    LatexEngine.XELATEX,
    LatexEngine.LUALATEX,
)
"""Order the harness picks an engine in when the project configures none.

`latexmk` first because it reruns TeX and BibTeX until the references settle, which is
what a manuscript with citations needs; `tectonic` next because it does the same on its
own and needs no system TeX tree; the single-pass engines last, in the order a document
class is most likely to expect.
"""

ALLOWED_EXTRA_ARGS: frozenset[str] = frozenset(
    {
        "-bibtex",
        "-bibtex-cond",
        "-file-line-error",
        "-halt-on-error",
        "-interaction=batchmode",
        "-interaction=nonstopmode",
        "-pdf",
        "-pdflua",
        "-pdfxe",
        "--keep-intermediates",
        "--keep-logs",
    }
)
"""Extra flags a project may add. Everything else — anything that names a file, a program,
an output directory, or an unstable option — is refused, because the harness owns those and
because a flag that can run a program is a shell escape by another name.
"""


class ToolchainConfigError(ResearchHarnessError):
    """The `manuscript:` section of `research.yaml` is not usable as written."""


class ToolchainUnavailableError(ResearchHarnessError):
    """No configured, installed engine exists; the report carries the setup guidance.

    Raised instead of attempting a compile, so a missing toolchain never touches a source
    file (LaTeX spec 9).
    """

    def __init__(self, report: ToolchainReport) -> None:
        self.report = report
        super().__init__(" ".join(report.guidance))


class ManuscriptSettings(BaseModel):
    """The `manuscript:` section of `research.yaml`, validated.

    Absent keys take their defaults, so a project that never writes the section still
    compiles `main.tex` with the best engine on `PATH`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: LatexEngine | None = None
    """Pin one engine; `None` means "the first of `ENGINE_PREFERENCE` that is installed"."""

    entry_file: str = DEFAULT_ENTRY_FILE
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0, le=MAX_TIMEOUT_SECONDS)
    extra_args: tuple[str, ...] = ()
    synctex: bool = True

    @field_validator("entry_file")
    @classmethod
    def _confined_entry_file(cls, value: str) -> str:
        relative = normalize_relative_path(value)
        if relative.suffix.lower() not in {".tex", ".ltx"}:
            raise ManuscriptPathError(f"entry_file {value!r} must be a .tex file")
        return relative.as_posix()

    @field_validator("extra_args")
    @classmethod
    def _allowlisted_extra_args(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if argument not in ALLOWED_EXTRA_ARGS:
                allowed = ", ".join(sorted(ALLOWED_EXTRA_ARGS))
                raise ValueError(
                    f"compiler flag {argument!r} is not allowed; "
                    f"manuscript.extra_args accepts only: {allowed}"
                )
        return value

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> ManuscriptSettings:
        """Validate the raw `manuscript:` mapping, naming `research.yaml` on failure."""
        if not config:
            return cls()
        try:
            return cls.model_validate(dict(config))
        except ValidationError as error:
            raise ToolchainConfigError(
                f"the manuscript: section of research.yaml is invalid: {error}"
            ) from error


class DiscoveredEngine(BaseModel):
    """An engine found on `PATH`, with the exact binary a compile would run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: LatexEngine
    executable: str


class ToolchainReport(BaseModel):
    """What is installed, what the project configured, and what a researcher should do."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    settings: ManuscriptSettings
    installed: tuple[DiscoveredEngine, ...] = ()
    configured: LatexEngine | None = None
    selected: DiscoveredEngine | None = None
    guidance: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        """True when a compile can run right now."""
        return self.selected is not None

    def require(self) -> DiscoveredEngine:
        """The engine to run, or :class:`ToolchainUnavailableError` carrying the guidance."""
        if self.selected is None:
            raise ToolchainUnavailableError(self)
        return self.selected


def discover_engines(*, path: str | None = None) -> tuple[DiscoveredEngine, ...]:
    """Engines present on `PATH`, in :data:`ENGINE_PREFERENCE` order.

    ``path`` overrides the search path, which is what lets a test point discovery at a
    directory of fake engines instead of the machine's real TeX installation.
    """
    found: list[DiscoveredEngine] = []
    for engine in ENGINE_PREFERENCE:
        executable = shutil.which(engine.value, path=path)
        if executable is not None:
            found.append(DiscoveredEngine(engine=engine, executable=executable))
    return tuple(found)


def discover_toolchain(
    settings: ManuscriptSettings | None = None, *, path: str | None = None
) -> ToolchainReport:
    """Resolve settings against what is installed and explain the outcome either way."""
    resolved = settings or ManuscriptSettings()
    installed = discover_engines(path=path)
    by_engine = {item.engine: item for item in installed}
    configured = resolved.engine
    selected = (
        by_engine.get(configured)
        if configured is not None
        else next((by_engine[engine] for engine in ENGINE_PREFERENCE if engine in by_engine), None)
    )
    return ToolchainReport(
        settings=resolved,
        installed=installed,
        configured=configured,
        selected=selected,
        guidance=_guidance(configured, selected, installed),
    )


def _guidance(
    configured: LatexEngine | None,
    selected: DiscoveredEngine | None,
    installed: tuple[DiscoveredEngine, ...],
) -> tuple[str, ...]:
    """Say what happened and, when a compile cannot run, exactly how to make it run."""
    if selected is not None:
        return (
            f"Compiling with {selected.engine.value} at {selected.executable}"
            + ("" if configured is None else " (pinned by manuscript.engine in research.yaml)")
            + ".",
        )
    names = ", ".join(item.engine.value for item in installed)
    lines = [
        f"research.yaml pins manuscript.engine: {configured.value}, which is not on PATH."
        if configured is not None
        else "No LaTeX engine was found on PATH."
    ]
    if installed:
        lines.append(
            f"Installed engines: {names}. Change manuscript.engine in research.yaml to one "
            f"of them, or install {configured.value if configured else 'an engine'}."
        )
    else:
        lines.append(
            "Install one of: tectonic (a single binary that fetches what a document needs, "
            "https://tectonic-typesetting.github.io), or a TeX distribution providing "
            "latexmk/pdflatex/xelatex/lualatex (TeX Live, MacTeX, MiKTeX)."
        )
        lines.append(
            "Then reopen the manuscript workspace; the harness only ever reads engines "
            "from PATH and installs nothing itself."
        )
    lines.append("No manuscript source was read or modified.")
    return tuple(lines)
