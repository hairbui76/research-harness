"""Running a real LaTeX toolchain over owned source, in a bounded, confined process.

An HTML approximation of a manuscript is not a manuscript (LaTeX spec 2), so this module
runs the installed engine and keeps what it produced. Everything about the run is
deliberate:

*The process is confined.* The entry file must resolve inside `manuscript/`, the working
directory is `manuscript/`, `shell=False`, and the environment is rebuilt from a small
allowlist with `TEXINPUTS`/`BIBINPUTS` pinned to the project directory and
`shell_escape=f`, `openout_any=p` set for TeX Live engines. `tectonic` is run
`--untrusted` and never with `-Z shell-escape`. A compiler flag from `research.yaml` has
to be on the allowlist in :mod:`~research_harness.manuscript.toolchain` before it is
passed. `latexmk` runs `-norc` because a project `latexmkrc` is unsandboxed Perl, while a
`.tex` file without shell escape is not.

*The process is bounded.* It runs in its own process group with a timeout; on expiry the
whole group is killed, and the log written up to that point is still parsed, because
"what had it complained about before it hung" is the question a researcher then asks.

*The outputs are disposable and the last good one survives.* Everything lands under
`.research/build/manuscript/<build_id>/`, which can be deleted without losing a
manuscript, an anchor, or a conclusion. A successful build moves the `last-good.json`
pointer; a failed one leaves it alone and reports it as stale with its own timestamp, so
the preview keeps showing the last PDF that really compiled while the diagnostics describe
the source as it is now (LaTeX spec 5, 9).

A failed compile is an outcome, not an exception: :meth:`CompileService.compile` returns a
:class:`CompileResult` for a failure and for a timeout, and only raises when there is no
result to give — no engine at all, or a path that escapes the manuscript directory. A
caller that prefers exceptions calls :meth:`CompileResult.raise_for_status`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_harness.domain.base import Sha256, UtcDatetime, utc_now
from research_harness.domain.errors import ResearchHarnessError
from research_harness.manuscript.files import ManuscriptFileNotFoundError, ManuscriptFiles
from research_harness.manuscript.synctex import SynctexIndex, SynctexUnavailableReason
from research_harness.manuscript.toolchain import (
    DiscoveredEngine,
    LatexEngine,
    ManuscriptSettings,
    ToolchainReport,
    discover_toolchain,
)
from research_harness.workspace.atomic import atomic_write_bytes
from research_harness.workspace.layout import WorkspaceLayout
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "BUILD_DIRNAME",
    "BUILD_RECORD_FILENAME",
    "LAST_GOOD_FILENAME",
    "MANUSCRIPT_BUILD_DIRNAME",
    "STREAM_TAIL_CHARS",
    "CompileDiagnostic",
    "CompileFailedError",
    "CompileResult",
    "CompileService",
    "CompileStatus",
    "CompileTimeoutError",
    "DiagnosticSeverity",
    "LastGoodBuild",
    "manuscript_build_root",
    "parse_diagnostics",
]

logger = logging.getLogger(__name__)

BUILD_DIRNAME = "build"
MANUSCRIPT_BUILD_DIRNAME = "manuscript"
BUILD_RECORD_FILENAME = "build.json"
LAST_GOOD_FILENAME = "last-good.json"

STREAM_TAIL_CHARS = 16_000
"""How much of stdout/stderr a build record keeps; the log file holds the full story."""

_DRAIN_TIMEOUT_SECONDS = 10.0
_SYNCTEX_SUFFIXES = (".synctex.gz", ".synctex")
_SYNCTEX_FLAGS = frozenset({"-synctex=1", "--synctex"})
_BUILD_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")


# --------------------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------------------


class CompileError(ResearchHarnessError):
    """A manuscript compile could not be run, or produced no usable document."""


class CompileFailedError(CompileError):
    """The engine ran and reported errors; the result carries the diagnostics."""

    def __init__(self, result: CompileResult) -> None:
        self.result = result
        first = next(iter(result.errors), None)
        detail = f": {first.where()} {first.message}" if first is not None else ""
        super().__init__(f"{result.entry_file} did not compile{detail}")


class CompileTimeoutError(CompileError):
    """The engine exceeded `manuscript.timeout_seconds` and its process group was killed."""

    def __init__(self, result: CompileResult) -> None:
        self.result = result
        super().__init__(
            f"{result.entry_file} did not finish within {result.timeout_seconds:g}s; "
            "the compiler process group was killed and its diagnostics kept"
        )


# --------------------------------------------------------------------------------------
# vocabularies and results
# --------------------------------------------------------------------------------------


class CompileStatus(StrEnum):
    """How a build ended. `failed` and `timed_out` are results, not harness failures."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class DiagnosticSeverity(StrEnum):
    """Severity of one compiler message, as the engine itself classified it."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CompileDiagnostic(_Record):
    """One compiler message, placed in the source when the engine said where it was.

    A compiler diagnostic is never a scientific audit finding: a document can compile and
    fail its citation audit, or fail to compile while every Claim is supported, and the
    two lists stay separate all the way to the interface (LaTeX spec 7).
    """

    severity: DiagnosticSeverity
    message: str
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    code: str | None = None

    def where(self) -> str:
        """`file:line` when both are known, else whichever is, else the empty string."""
        if self.file is None:
            return "" if self.line is None else f"line {self.line}"
        return self.file if self.line is None else f"{self.file}:{self.line}"


class LastGoodBuild(_Record):
    """Pointer to the newest build that really produced a PDF.

    A failed or timed-out build reports the same pointer with ``stale`` set: the preview
    keeps a document to show, labelled honestly as older than the source on disk.
    """

    build_id: str
    engine: LatexEngine
    pdf: str
    compiled_at: UtcDatetime
    inputs_fingerprint: Sha256
    stale: bool = False


class CompileResult(_Record):
    """Everything one build produced: provenance, outputs, diagnostics, and the last good PDF.

    Paths are workspace-relative POSIX strings so a transport can hand them to a client
    without leaking the machine's directory layout; :meth:`CompileService.absolute`
    resolves one back.
    """

    build_id: str
    status: CompileStatus
    engine: LatexEngine
    executable: str
    args: tuple[str, ...]
    entry_file: str
    inputs_fingerprint: Sha256
    started_at: UtcDatetime
    finished_at: UtcDatetime
    duration_seconds: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    exit_status: int | None = None
    timed_out: bool = False
    build_dir: str
    pdf: str | None = None
    log: str | None = None
    synctex: str | None = None
    diagnostics: tuple[CompileDiagnostic, ...] = ()
    stdout_tail: str = ""
    stderr_tail: str = ""
    last_good: LastGoodBuild | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is CompileStatus.SUCCEEDED

    @property
    def errors(self) -> tuple[CompileDiagnostic, ...]:
        return self._of(DiagnosticSeverity.ERROR)

    @property
    def warnings(self) -> tuple[CompileDiagnostic, ...]:
        return self._of(DiagnosticSeverity.WARNING)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def raise_for_status(self) -> CompileResult:
        """Return the result, or raise the typed error a failure or a timeout earned."""
        if self.status is CompileStatus.TIMED_OUT:
            raise CompileTimeoutError(self)
        if self.status is CompileStatus.FAILED:
            raise CompileFailedError(self)
        return self

    def _of(self, severity: DiagnosticSeverity) -> tuple[CompileDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity is severity)


# --------------------------------------------------------------------------------------
# build storage
# --------------------------------------------------------------------------------------


def manuscript_build_root(layout: WorkspaceLayout) -> Path:
    """`.research/build/manuscript/` — disposable; deleting it loses only build outputs."""
    return layout.research_dir / BUILD_DIRNAME / MANUSCRIPT_BUILD_DIRNAME


# --------------------------------------------------------------------------------------
# the service
# --------------------------------------------------------------------------------------


class CompileService:
    """Compiles `manuscript/` with the configured engine and keeps the build record."""

    def __init__(
        self,
        workspace: WorkspaceLayout | Path | str,
        settings: ManuscriptSettings | None = None,
        *,
        search_path: str | None = None,
        environ: Mapping[str, str] | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        layout = workspace if isinstance(workspace, WorkspaceLayout) else WorkspaceLayout(workspace)
        self._layout = layout
        self._files = ManuscriptFiles(layout)
        self._settings = settings or ManuscriptSettings()
        self._search_path = search_path
        self._environ = dict(os.environ if environ is None else environ)
        self._now = now

    @classmethod
    def for_repository(
        cls,
        repository: WorkspaceRepository,
        *,
        search_path: str | None = None,
        environ: Mapping[str, str] | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> CompileService:
        """Build a service for an open workspace, validating its `manuscript:` config."""
        settings = ManuscriptSettings.from_config(repository.config.manuscript)
        return cls(repository.layout, settings, search_path=search_path, environ=environ, now=now)

    # -- state ---------------------------------------------------------------

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    @property
    def files(self) -> ManuscriptFiles:
        return self._files

    @property
    def settings(self) -> ManuscriptSettings:
        return self._settings

    @property
    def build_root(self) -> Path:
        return manuscript_build_root(self._layout)

    def toolchain(self) -> ToolchainReport:
        """What is installed, what is configured, and the setup guidance if nothing works."""
        return discover_toolchain(self._settings, path=self._search_path)

    def absolute(self, relative: str) -> Path:
        """Resolve a workspace-relative path from a result back to a real file."""
        return self._layout.resolve(PurePosixPath(relative))

    # -- compiling -----------------------------------------------------------

    def compile(
        self, *, entry_file: str | None = None, timeout_seconds: float | None = None
    ) -> CompileResult:
        """Run one bounded compile and record it under `.research/build/manuscript/`.

        Raises :class:`~research_harness.manuscript.toolchain.ToolchainUnavailableError`
        when no usable engine exists and
        :class:`~research_harness.manuscript.files.ManuscriptPathError` when the entry file
        escapes the manuscript directory — in both cases before any process starts, so no
        source file is read or changed. Every other outcome is a returned result.
        """
        engine = self.toolchain().require()
        entry = entry_file or self._settings.entry_file
        source = self._files.path_for(entry)
        if not source.is_file():
            raise ManuscriptFileNotFoundError(
                f"no manuscript entry file at {entry}; set manuscript.entry_file in research.yaml"
            )
        relative_entry = source.relative_to(self._files.root).as_posix()
        timeout = float(timeout_seconds or self._settings.timeout_seconds)

        fingerprint = self._files.fingerprint()
        started_at = self._now()
        build_id = self._allocate_build_id(started_at, fingerprint)
        directory = self.build_root / build_id
        self._prepare_build_dir(directory)

        command = _command_for(engine, directory, relative_entry, self._settings)
        environment = _environment(self._environ, directory)
        started = time.monotonic()
        completed = _run(command, cwd=self._files.root, env=environment, timeout=timeout)
        duration = time.monotonic() - started
        finished_at = self._now()

        outputs = _collect_outputs(directory, relative_entry)
        log_text = _read_text(outputs.log)
        diagnostics = parse_diagnostics(
            log=log_text,
            stdout=completed.stdout,
            stderr=completed.stderr,
            entry_file=relative_entry,
        )
        status = _status_for(completed, outputs.pdf)
        result = CompileResult(
            build_id=build_id,
            status=status,
            engine=engine.engine,
            executable=engine.executable,
            args=tuple(command),
            entry_file=relative_entry,
            inputs_fingerprint=fingerprint,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            timeout_seconds=timeout,
            exit_status=completed.returncode,
            timed_out=completed.timed_out,
            build_dir=self._layout.relative(directory).as_posix(),
            pdf=self._relative(outputs.pdf),
            log=self._relative(outputs.log),
            synctex=self._relative(outputs.synctex),
            diagnostics=diagnostics,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
            last_good=None,
        )
        result = result.model_copy(update={"last_good": self._settle_last_good(result)})
        self._write_record(directory, result)
        logger.info(
            "manuscript build %s %s in %.2fs (%d errors, %d warnings)",
            build_id,
            status.value,
            duration,
            result.error_count,
            result.warning_count,
        )
        return result

    # -- reading builds back -------------------------------------------------

    def build_ids(self) -> tuple[str, ...]:
        """Build ids newest first; the id sorts by its own timestamp prefix."""
        root = self.build_root
        if not root.is_dir():
            return ()
        found = [
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and _BUILD_ID_RE.match(entry.name)
        ]
        return tuple(sorted(found, reverse=True))

    def build(self, build_id: str) -> CompileResult:
        """Load a recorded build, or raise when it is absent or unreadable."""
        path = self._record_path(build_id)
        if not path.is_file():
            raise CompileError(f"no manuscript build {build_id}")
        try:
            return CompileResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError) as error:
            raise CompileError(f"build record {build_id} is unreadable: {error}") from error

    def latest(self) -> CompileResult | None:
        """The most recent readable build record, or ``None`` when nothing was compiled."""
        for build_id in self.build_ids():
            try:
                return self.build(build_id)
            except CompileError:  # pragma: no cover - a half-written build directory
                continue
        return None

    def last_good(self) -> LastGoodBuild | None:
        """The newest build that produced a PDF, if its PDF is still on disk."""
        path = self.build_root / LAST_GOOD_FILENAME
        if not path.is_file():
            return None
        try:
            pointer = LastGoodBuild.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError):
            logger.warning("ignoring unreadable %s", path)
            return None
        return pointer if self.absolute(pointer.pdf).is_file() else None

    def synctex(self, build_id: str) -> SynctexIndex:
        """The SyncTeX map of one build, or an index that says why there is none.

        The reason comes from the recorded build, not from the settings as they are now:
        a build that never asked for SyncTeX is a different fact from an engine that was
        asked and could not produce it.
        """
        record = self.build(build_id)
        if record.synctex is not None:
            return SynctexIndex.load(self.absolute(record.synctex), source_root=self._files.root)
        if not any(item in _SYNCTEX_FLAGS for item in record.args):
            return SynctexIndex.unavailable(
                SynctexUnavailableReason.NOT_REQUESTED,
                f"build {build_id} was run without SyncTeX (manuscript.synctex is false)",
            )
        return SynctexIndex.unavailable(
            SynctexUnavailableReason.MISSING_FILE,
            f"{record.engine.value} was asked for SyncTeX data and produced none "
            f"for build {build_id}",
        )

    # -- internals -----------------------------------------------------------

    def _allocate_build_id(self, started_at: datetime, fingerprint: str) -> str:
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        short = fingerprint.removeprefix("sha256:")[:8]
        candidate = f"{stamp}-{short}"
        suffix = 2
        while (self.build_root / candidate).exists():
            candidate = f"{stamp}-{short}-{suffix}"
            suffix += 1
        return candidate

    def _prepare_build_dir(self, directory: Path) -> None:
        """Create the build directory and mirror the source tree's subdirectories in it.

        TeX writes an auxiliary file beside each `\\include`d source, relative to the
        output directory; without the directory it stops with an unhelpful I/O error.
        """
        directory.mkdir(parents=True, exist_ok=True)
        for entry in self._files.tree():
            parent = PurePosixPath(entry.path).parent
            if parent != PurePosixPath("."):
                (directory / Path(str(parent))).mkdir(parents=True, exist_ok=True)

    def _settle_last_good(self, result: CompileResult) -> LastGoodBuild | None:
        """Move the pointer on success; on failure return the old one, marked stale."""
        if result.status is CompileStatus.SUCCEEDED and result.pdf is not None:
            pointer = LastGoodBuild(
                build_id=result.build_id,
                engine=result.engine,
                pdf=result.pdf,
                compiled_at=result.finished_at,
                inputs_fingerprint=result.inputs_fingerprint,
                stale=False,
            )
            atomic_write_bytes(self.build_root / LAST_GOOD_FILENAME, _dump(pointer))
            return pointer
        previous = self.last_good()
        return None if previous is None else previous.model_copy(update={"stale": True})

    def _write_record(self, directory: Path, result: CompileResult) -> None:
        atomic_write_bytes(directory / BUILD_RECORD_FILENAME, _dump(result))

    def _record_path(self, build_id: str) -> Path:
        if not _BUILD_ID_RE.match(build_id):
            raise CompileError(f"unsafe build id {build_id!r}")
        return self.build_root / build_id / BUILD_RECORD_FILENAME

    def _relative(self, path: Path | None) -> str | None:
        return None if path is None else self._layout.relative(path).as_posix()


# --------------------------------------------------------------------------------------
# command and environment
# --------------------------------------------------------------------------------------

_TEX_LIVE_ENGINES = frozenset({LatexEngine.PDFLATEX, LatexEngine.XELATEX, LatexEngine.LUALATEX})

_ENV_PASSTHROUGH: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "TECTONIC_CACHE_DIR",
    "SOURCE_DATE_EPOCH",
)
"""The only variables inherited from the caller. `TEXINPUTS`, `TEXMFHOME`, `BIBINPUTS`,
`TEXMFCNF`, and everything else a caller might have set to redirect the search path or the
configuration are dropped rather than trusted.
"""


def _command_for(
    engine: DiscoveredEngine, build_dir: Path, entry_file: str, settings: ManuscriptSettings
) -> list[str]:
    """The exact argv for one engine: outputs into the build directory, no shell escape."""
    output = str(build_dir)
    extra = list(settings.extra_args)
    if engine.engine is LatexEngine.TECTONIC:
        command = [engine.executable, "-X", "compile", entry_file, "--outdir", output]
        command += ["--untrusted", "--keep-logs"]
        if settings.synctex:
            command.append("--synctex")
        return command + extra
    if engine.engine is LatexEngine.LATEXMK:
        command = [engine.executable, "-norc", "-pdf", "-interaction=nonstopmode"]
        command += ["-file-line-error", f"-outdir={output}"]
        if settings.synctex:
            command.append("-synctex=1")
        return command + extra + [entry_file]
    command = [engine.executable, "-no-shell-escape", "-interaction=nonstopmode"]
    command += ["-file-line-error", f"-output-directory={output}"]
    if settings.synctex:
        command.append("-synctex=1")
    return command + extra + [entry_file]


def _environment(source: Mapping[str, str], build_dir: Path) -> dict[str, str]:
    """A scrubbed environment: an allowlist, plus the search and safety settings we own."""
    env = {name: source[name] for name in _ENV_PASSTHROUGH if name in source}
    project_first = f".{os.pathsep}"
    env.update(
        {
            # A single leading "." plus the trailing separator means "this project, then
            # the distribution's own default path" - and nothing the caller injected.
            "TEXINPUTS": project_first,
            "BIBINPUTS": project_first,
            "BSTINPUTS": project_first,
            # kpathsea permits absolute output paths only under TEXMFOUTPUT, which is how
            # -output-directory keeps working while openout_any stays paranoid.
            "TEXMFOUTPUT": str(build_dir),
            "openout_any": "p",
            "openin_any": "r",
            "shell_escape": "f",
            # Stop TeX wrapping the log at 79 columns; a wrapped path breaks file/line
            # attribution for every diagnostic that follows it.
            "max_print_line": "10000",
            "error_line": "254",
            "half_error_line": "238",
        }
    )
    return env


@dataclass(frozen=True, slots=True)
class _Completed:
    """What the engine process left behind, including the timeout verdict."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


def _run(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str], timeout: float
) -> _Completed:
    """Run the engine in its own process group and kill the whole group on timeout."""
    creation: dict[str, Any] = {}
    if sys.platform == "win32":  # pragma: no cover - POSIX is the tested path
        creation["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creation["start_new_session"] = True
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        **creation,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return _Completed(
            returncode=process.returncode, stdout=stdout, stderr=stderr, timed_out=False
        )
    except subprocess.TimeoutExpired:
        _kill_group(process)
        try:
            stdout, stderr = process.communicate(timeout=_DRAIN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - a grandchild held the pipes
            process.kill()
            stdout, stderr = "", ""
        return _Completed(
            returncode=process.returncode, stdout=stdout, stderr=stderr, timed_out=True
        )


def _kill_group(process: subprocess.Popen[str]) -> None:
    """Kill the engine and everything it started; latexmk's children outlive latexmk."""
    if sys.platform != "win32":
        try:
            os.killpg(os.getpgid(process.pid), 9)
            return
        except (OSError, ProcessLookupError):  # pragma: no cover - already gone
            pass
    process.kill()  # pragma: no cover - Windows and the already-dead case


@dataclass(frozen=True, slots=True)
class _Outputs:
    """The files a build produced, as absolute paths that exist."""

    pdf: Path | None
    log: Path | None
    synctex: Path | None


def _collect_outputs(directory: Path, entry_file: str) -> _Outputs:
    """Find `<stem>.pdf`, `<stem>.log`, and `<stem>.synctex(.gz)` wherever the engine put them."""
    stem = PurePosixPath(entry_file).stem
    return _Outputs(
        pdf=_find(directory, stem, (".pdf",)),
        log=_find(directory, stem, (".log",)),
        synctex=_find(directory, stem, _SYNCTEX_SUFFIXES),
    )


def _find(directory: Path, stem: str, suffixes: Iterable[str]) -> Path | None:
    for suffix in suffixes:
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    for suffix in suffixes:
        found = sorted(directory.rglob(f"{stem}{suffix}"))
        if found:
            return found[0]
    return None


def _status_for(completed: _Completed, pdf: Path | None) -> CompileStatus:
    """The engine's own verdict, not the parser's.

    A build succeeded when the process exited zero and left a PDF. Diagnostics are
    reported either way and never override the engine: a log line this parser misreads as
    an error must not be able to stop the last-good PDF from ever advancing again.
    """
    if completed.timed_out:
        return CompileStatus.TIMED_OUT
    if completed.returncode != 0 or pdf is None:
        return CompileStatus.FAILED
    return CompileStatus.SUCCEEDED


def _read_text(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover - the log vanished
        return ""


def _tail(text: str) -> str:
    return text if len(text) <= STREAM_TAIL_CHARS else text[-STREAM_TAIL_CHARS:]


def _dump(model: BaseModel) -> bytes:
    payload = model.model_dump(mode="json")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return f"{text}\n".encode()


# --------------------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------------------

_TEX_EXTENSIONS = r"tex|ltx|sty|cls|clo|def|fd|bib|bbl|aux|cfg"

#: `-file-line-error` output: `./sections/intro.tex:9: Undefined control sequence.`
_FILE_LINE_RE = re.compile(
    rf"^(?P<file>[^\s:][^:]*\.(?:{_TEX_EXTENSIONS})):(?P<line>\d+):\s*(?P<message>\S.*)$",
    re.IGNORECASE,
)
#: The classic form: a `!` line, then the offending source line as `l.<n> <context>`.
_LINE_MARKER_RE = re.compile(r"^l\.(?P<line>\d+)(?:\s|$)")
_WARNING_RE = re.compile(
    r"^(?P<origin>LaTeX Font|LaTeX|Package\s+(?P<package>\S+)|Class\s+(?P<klass>\S+))"
    r"\s+(?P<severity>Warning|Error):\s*(?P<message>.*)$"
)
_BOX_RE = re.compile(
    r"^(?P<kind>Overfull|Underfull)\s+\\(?P<box>[hv])box\s+\((?P<amount>[^)]*)\)"
    r"(?P<rest>.*)$"
)
_AT_LINES_RE = re.compile(r"at lines? (?P<line>\d+)(?:--(?P<end>\d+))?")
_INPUT_LINE_RE = re.compile(r"on input line (?P<line>\d+)")
_NO_FILE_RE = re.compile(r"^No file (?P<file>.+?)\.$")
#: tectonic's own stream: `error: sections/intro.tex:9: Undefined control sequence`.
_ENGINE_RE = re.compile(r"^(?P<severity>error|warning):\s*(?P<message>.+)$")
_ENGINE_PLACE_RE = re.compile(
    rf"^(?P<file>[^\s:][^:]*\.(?:{_TEX_EXTENSIONS})):(?P<line>\d+):\s*(?P<message>\S.*)$",
    re.IGNORECASE,
)
_FILENAME_CHARS = re.compile(r"[^\s()\[\]{}]+")
_ERROR_CONTEXT_LINES = 40
_WARNING_CONTINUATION_LINES = 4

_ERROR_CODES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^LaTeX Error: File `[^']*' not found"), "file-not-found"),
    (re.compile(r"^I can't find file"), "file-not-found"),
    (re.compile(r"^Undefined control sequence"), "undefined-control-sequence"),
    (re.compile(r"^Missing \$ inserted"), "missing-math-shift"),
    (re.compile(r"^Emergency stop"), "emergency-stop"),
    (re.compile(r"^Package (\S+) Error"), "package-error"),
    (re.compile(r"^Class (\S+) Error"), "class-error"),
    (re.compile(r"^LaTeX Error"), "latex-error"),
)

_WARNING_CODES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^Citation `[^']*' .*undefined", re.IGNORECASE), "citation-undefined"),
    (re.compile(r"^Reference `[^']*' .*undefined", re.IGNORECASE), "reference-undefined"),
    (re.compile(r"^Label `[^']*' multiply defined", re.IGNORECASE), "label-multiply-defined"),
    (re.compile(r"^There were undefined (references|citations)", re.IGNORECASE), "undefined-refs"),
    (re.compile(r"Rerun to get", re.IGNORECASE), "rerun-required"),
    (re.compile(r"^Empty `thebibliography'", re.IGNORECASE), "empty-bibliography"),
)


def parse_diagnostics(
    *, log: str = "", stdout: str = "", stderr: str = "", entry_file: str = ""
) -> tuple[CompileDiagnostic, ...]:
    """Structured file/line diagnostics from a TeX log plus the engine's own stream.

    The log is the authority — it is the only place that says which file was open when TeX
    complained — and the engine stream adds what a wrapper such as `tectonic` reports on
    its own. The two overlap, so identical messages at the same place are emitted once.
    """
    found = list(_LogScanner(log, entry_file).run())
    found.extend(_parse_engine_stream(stderr))
    found.extend(_parse_engine_stream(stdout))
    seen: set[tuple[str, str | None, int | None, str]] = set()
    unique: list[CompileDiagnostic] = []
    for item in found:
        normalized = item.message.strip().rstrip(".").casefold()
        key = (item.severity.value, item.file, item.line, normalized)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return tuple(unique)


class _LogScanner:
    """Reads a TeX transcript, tracking which file is open so a `!` can be placed."""

    def __init__(self, text: str, entry_file: str) -> None:
        self._lines = text.splitlines()
        self._entry = _clean_path(entry_file) or None
        self._stack: list[str | None] = []

    def run(self) -> list[CompileDiagnostic]:
        found: list[CompileDiagnostic] = []
        for index, line in enumerate(self._lines):
            diagnostic = self._diagnostic(index, line)
            if diagnostic is not None:
                found.append(diagnostic)
            self._track_files(line)
        return found

    # -- one line ------------------------------------------------------------

    def _diagnostic(self, index: int, line: str) -> CompileDiagnostic | None:
        stripped = line.rstrip()
        if not stripped:
            return None
        if stripped.startswith("!"):
            return self._error(index, stripped[1:].strip())
        placed = _FILE_LINE_RE.match(stripped)
        if placed is not None and not stripped.startswith("Package:"):
            message = placed.group("message").strip()
            return CompileDiagnostic(
                severity=DiagnosticSeverity.ERROR,
                message=message,
                file=_clean_path(placed.group("file")),
                line=int(placed.group("line")),
                code=_code_for(message, _ERROR_CODES) or "tex-error",
            )
        box = _BOX_RE.match(stripped)
        if box is not None:
            return self._box(box)
        warning = _WARNING_RE.match(stripped)
        if warning is not None:
            return self._warning(index, warning)
        absent = _NO_FILE_RE.match(stripped)
        if absent is not None:
            return CompileDiagnostic(
                severity=DiagnosticSeverity.INFO,
                message=stripped,
                file=self._current(),
                code="no-file",
            )
        return None

    def _error(self, index: int, message: str) -> CompileDiagnostic:
        line_number: int | None = None
        for follow in self._lines[index + 1 : index + 1 + _ERROR_CONTEXT_LINES]:
            marker = _LINE_MARKER_RE.match(follow)
            if marker is not None:
                line_number = int(marker.group("line"))
                break
            if follow.startswith("!"):
                break
        return CompileDiagnostic(
            severity=DiagnosticSeverity.ERROR,
            message=message,
            file=self._current(),
            line=line_number,
            code=_code_for(message, _ERROR_CODES) or "tex-error",
        )

    def _warning(self, index: int, match: re.Match[str]) -> CompileDiagnostic:
        error = match.group("severity") == "Error"
        severity = DiagnosticSeverity.ERROR if error else DiagnosticSeverity.WARNING
        message = match.group("message").strip()
        joined = " ".join([message, *self._continuation(index)]).strip()
        origin = match.group("package") or match.group("klass")
        found = _INPUT_LINE_RE.search(joined)
        codes = _ERROR_CODES if error else _WARNING_CODES
        if error:
            default = "package-error" if origin else "latex-error"
        else:
            default = "package-warning" if origin else "latex-warning"
        return CompileDiagnostic(
            severity=severity,
            message=joined or message,
            file=self._current(),
            line=int(found.group("line")) if found else None,
            code=_code_for(joined, codes) or default,
        )

    def _continuation(self, index: int) -> list[str]:
        """Following lines of a multi-line LaTeX warning, which TeX indents or prefixes."""
        parts: list[str] = []
        for follow in self._lines[index + 1 : index + 1 + _WARNING_CONTINUATION_LINES]:
            text = follow.strip()
            if not text or follow[:1] not in {" ", "("}:
                break
            if text.startswith("("):
                text = text.partition(")")[2].strip() or text
            parts.append(text)
        return parts

    def _box(self, match: re.Match[str]) -> CompileDiagnostic:
        rest = match.group("rest")
        found = _AT_LINES_RE.search(rest)
        kind = match.group("kind").lower()
        box = match.group("box")
        return CompileDiagnostic(
            severity=DiagnosticSeverity.WARNING,
            message=f"{match.group('kind')} \\{box}box ({match.group('amount')}){rest}".strip(),
            file=self._current(),
            line=int(found.group("line")) if found else None,
            code=f"{kind}-{box}box",
        )

    # -- the open-file stack -------------------------------------------------

    def _current(self) -> str | None:
        for name in reversed(self._stack):
            if name is not None:
                return name
        return self._entry

    def _track_files(self, line: str) -> None:
        """Push on `(name`, pop on `)`, the way every TeX log reader has to guess."""
        index = 0
        while index < len(line):
            char = line[index]
            if char == "(":
                match = _FILENAME_CHARS.match(line, index + 1)
                name = _clean_path(match.group(0)) if match is not None else ""
                self._stack.append(name if _looks_like_source(name) else None)
                index = match.end() if match is not None else index + 1
                continue
            if char == ")" and self._stack:
                self._stack.pop()
            index += 1


def _parse_engine_stream(text: str) -> list[CompileDiagnostic]:
    """`error:`/`warning:` lines a wrapper such as tectonic writes about the whole run."""
    found: list[CompileDiagnostic] = []
    for raw in text.splitlines():
        match = _ENGINE_RE.match(raw.strip())
        if match is None:
            continue
        severity = (
            DiagnosticSeverity.ERROR
            if match.group("severity") == "error"
            else DiagnosticSeverity.WARNING
        )
        body = match.group("message").strip()
        placed = _ENGINE_PLACE_RE.match(body)
        codes = _ERROR_CODES if severity is DiagnosticSeverity.ERROR else _WARNING_CODES
        if placed is not None:
            message = placed.group("message").strip()
            found.append(
                CompileDiagnostic(
                    severity=severity,
                    message=message,
                    file=_clean_path(placed.group("file")),
                    line=int(placed.group("line")),
                    code=_code_for(message, codes) or "engine-error",
                )
            )
            continue
        found.append(
            CompileDiagnostic(
                severity=severity,
                message=body,
                code=_code_for(body, codes)
                or ("engine-error" if severity is DiagnosticSeverity.ERROR else "engine-warning"),
            )
        )
    return found


def _code_for(message: str, table: Iterable[tuple[re.Pattern[str], str]]) -> str | None:
    for pattern, code in table:
        if pattern.search(message):
            return code
    return None


def _clean_path(name: str) -> str:
    cleaned = name.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _looks_like_source(name: str) -> bool:
    """True for a token that is plausibly a file TeX just opened, not prose in parentheses."""
    if not name or name.startswith("-"):
        return False
    suffix = PurePosixPath(name).suffix.lower().lstrip(".")
    return bool(suffix) and re.fullmatch(_TEX_EXTENSIONS, suffix, re.IGNORECASE) is not None
