"""One manuscript workspace: files, compiles, SyncTeX, and the audit, composed for a client.

The parts already exist and each one answers a narrow question - what is on disk
(:mod:`~research_harness.manuscript.files`), what the engine did
(:mod:`~research_harness.manuscript.compile`), where a line landed on a page
(:mod:`~research_harness.manuscript.synctex`), and whether the prose is defensible
(:mod:`~research_harness.manuscript.audit`). A manuscript workspace asks all four at once,
and this module is where they are assembled so that every transport assembles them the
same way.

Two boundaries are kept visible rather than smoothed over.

*A compile is not an audit.* :class:`BuildView` carries compiler ``diagnostics`` and
scientific ``audit_findings`` as two lists that are never merged and never summed. A
document may compile while failing its audit and pass its audit while failing to compile
(LaTeX spec 7, Product 42 P), so a view that reported "3 errors" would be answering a
question nobody asked.

*A missing answer is an answer.* No PDF, no SyncTeX map, and no installed engine are all
reported as themselves - with the reason and, for a missing toolchain, the setup guidance -
rather than as an empty result that a client would render as "fine" (LaTeX spec 6, 9).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.manuscript import ManuscriptAuditFinding
from research_harness.manuscript.audit import AuditScope, ManuscriptAuditReport
from research_harness.manuscript.compile import (
    CompileDiagnostic,
    CompileError,
    CompileResult,
    CompileService,
    CompileStatus,
    LastGoodBuild,
)
from research_harness.manuscript.files import (
    FileSnapshot,
    ManuscriptFile,
    ManuscriptFiles,
)
from research_harness.manuscript.synctex import (
    PdfLocation,
    SourceLocation,
    SynctexIndex,
    SynctexUnavailable,
    SynctexUnavailableReason,
)
from research_harness.manuscript.toolchain import ManuscriptSettings, ToolchainReport

__all__ = [
    "BUILD_ALIASES",
    "LAST_GOOD_BUILD",
    "LATEST_BUILD",
    "BuildView",
    "ManuscriptTree",
    "ManuscriptWorkspace",
    "SynctexView",
]

logger = logging.getLogger(__name__)

LATEST_BUILD = "latest"
"""The newest recorded build. Accepted anywhere a build id is: the daemon's PDF route has
always taken it, and a client that shows "the current build" should not have to look one
up first (LaTeX spec SS6)."""

LAST_GOOD_BUILD = "last-good"
"""The newest build that really produced a PDF, whatever has happened since."""

BUILD_ALIASES: frozenset[str] = frozenset({LATEST_BUILD, LAST_GOOD_BUILD})
"""Build ids that name a build by its role rather than by its timestamp."""


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ManuscriptTree(_View):
    """Every source file a researcher can open, plus where the entry point is."""

    root: str
    """The manuscript directory, workspace-relative, so a client can render a header."""

    entry_file: str
    files: tuple[ManuscriptFile, ...] = ()

    @property
    def count(self) -> int:
        return len(self.files)


class SynctexView(_View):
    """A SyncTeX lookup, or the honest reason there is no mapping for this build."""

    build_id: str | None = None
    available: bool = False
    reason: SynctexUnavailableReason | None = None
    detail: str | None = None
    pdf_locations: tuple[PdfLocation, ...] = ()
    source_location: SourceLocation | None = None

    @classmethod
    def unavailable(cls, build_id: str | None, state: SynctexUnavailable) -> SynctexView:
        return cls(build_id=build_id, available=False, reason=state.reason, detail=state.detail)


class BuildView(_View):
    """One build as a manuscript workspace shows it: the engine's answer and the science's.

    ``diagnostics`` is what the compiler said about the source, grouped by file and line by
    the compile service. ``audit_findings`` is what the manuscript audit says about the same
    manuscript as it is *now*. They are computed independently and reported separately on
    purpose: `error_count` counts compiler errors and nothing else, and
    `audit_error_count` counts scientific errors and nothing else.
    """

    build_id: str | None = None
    status: CompileStatus | None = None
    result: CompileResult | None = None
    diagnostics: tuple[CompileDiagnostic, ...] = ()
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)

    audit_findings: tuple[ManuscriptAuditFinding, ...] = ()
    audit_error_count: int = Field(default=0, ge=0)
    audit_ran: bool = False
    audit_unavailable_reason: str | None = None

    pdf_available: bool = False
    pdf: str | None = None
    """Workspace-relative path of this build's PDF, when it produced one."""

    pdf_stale: bool = False
    """True when the PDF a reader should look at came from an earlier, better build."""

    last_good: LastGoodBuild | None = None
    synctex_available: bool = False
    synctex_reason: SynctexUnavailableReason | None = None
    synctex_detail: str | None = None

    toolchain: ToolchainReport
    guidance: tuple[str, ...] = ()
    """What a researcher should do; the setup instructions when no engine is installed."""

    @property
    def compiled(self) -> bool:
        """True when this workspace has a build to show at all."""
        return self.build_id is not None


class ManuscriptWorkspace:
    """The manuscript of one workspace: read it, write it, compile it, and audit it.

    Constructed from a :class:`~research_harness.capabilities.context.CapabilityContext`,
    so the settings come from the project's `manuscript:` section and every mutation runs
    on the context's actor and clock.
    """

    def __init__(
        self,
        ctx: CapabilityContext,
        *,
        search_path: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._ctx = ctx
        self._settings = ManuscriptSettings.from_config(ctx.repo.config.manuscript)
        self._files = ManuscriptFiles(ctx.repo.layout)
        self._compile = CompileService(
            ctx.repo.layout,
            self._settings,
            search_path=search_path,
            environ=environ,
            now=ctx.clock,
        )

    # -- state ---------------------------------------------------------------

    @property
    def ctx(self) -> CapabilityContext:
        return self._ctx

    @property
    def settings(self) -> ManuscriptSettings:
        return self._settings

    @property
    def files(self) -> ManuscriptFiles:
        return self._files

    @property
    def compiler(self) -> CompileService:
        return self._compile

    def toolchain(self) -> ToolchainReport:
        """What is installed, what is configured, and the guidance when nothing works."""
        return self._compile.toolchain()

    # -- files ---------------------------------------------------------------

    def tree(self) -> ManuscriptTree:
        """Every source file under `manuscript/`, and the entry file a compile would run."""
        return ManuscriptTree(
            root=self._ctx.repo.layout.relative(self._files.root).as_posix(),
            entry_file=self._settings.entry_file,
            files=self._files.tree(),
        )

    def read(self, path: str) -> FileSnapshot:
        """One file's text with the hash a later save must present."""
        return self._files.read(path)

    def write(self, path: str, content: str, expected_hash: str) -> FileSnapshot:
        """Save a file, refusing when the bytes on disk are not ``expected_hash``.

        A researcher's own save is their own edit: it is conflict-checked and atomic, and
        it appends no event, because the semantic log records changes to accepted
        scientific state, not keystrokes in an editor (Product 19.3). Applying a *model's*
        candidate does record one - see
        :func:`~research_harness.manuscript.suggest.apply_suggestion`.
        """
        with self._ctx.repo.lock():
            return self._files.write(path, content, expected_hash)

    def pdf_path(self, build_id: str | None = None) -> Path:
        """The PDF a client should show: this build's, else the last good one.

        Raises :class:`~research_harness.manuscript.compile.CompileError` when there is no
        PDF to show, because "here is an empty file" is the one answer a preview must never
        be given.
        """
        record = self._resolve(build_id)
        if record is not None and record.pdf is not None:
            path = self._compile.absolute(record.pdf)
            if path.is_file():
                return path
        pointer = self._compile.last_good()
        if pointer is not None:
            path = self._compile.absolute(pointer.pdf)
            if path.is_file():
                return path
        raise CompileError(
            "no compiled PDF for this manuscript yet; run `research manuscript compile`"
        )

    def last_good_pdf(self) -> Path:
        """The newest PDF that really compiled, whatever has happened since."""
        pointer = self._compile.last_good()
        if pointer is not None:
            path = self._compile.absolute(pointer.pdf)
            if path.is_file():
                return path
        raise CompileError("this manuscript has never compiled to a PDF")

    # -- compiling -----------------------------------------------------------

    def compile(
        self, *, entry_file: str | None = None, timeout_seconds: float | None = None
    ) -> BuildView:
        """Run one bounded compile and return the build as a client sees it.

        The workspace lock is held for the whole run, so two compiles of one workspace can
        never interleave their outputs or race for the `last-good.json` pointer - whichever
        process asked second waits and then compiles the source as it is then.
        """
        with self._ctx.repo.lock():
            result = self._compile.compile(entry_file=entry_file, timeout_seconds=timeout_seconds)
        return self.build(result.build_id)

    def build(
        self,
        build_id: str | None = None,
        *,
        audit: bool = True,
        parse_sources: bool = False,
        scope: AuditScope | None = None,
    ) -> BuildView:
        """The build named by ``build_id``, or the latest one, with the scientific audit.

        ``parse_sources`` re-parses the artifacts behind the evidence so that source spans
        and evidence anchors are checked too; it is off by default because an editor asks
        for this view on every compile and a whole-corpus re-parse is not free.
        """
        record = self._resolve(build_id)
        report, unavailable = self._audit(audit, parse_sources, scope)
        return self._view(record, report, unavailable)

    def builds(self) -> tuple[str, ...]:
        """Recorded build ids, newest first."""
        return self._compile.build_ids()

    def last_good(self) -> LastGoodBuild | None:
        return self._compile.last_good()

    # -- source and PDF navigation -------------------------------------------

    def forward(self, file: str, line: int, *, build_id: str | None = None) -> SynctexView:
        """Where ``file``:``line`` landed in the PDF, or why that cannot be answered."""
        resolved, index = self._synctex(build_id)
        state = index.state
        if state is not None:
            return SynctexView.unavailable(resolved, state)
        return SynctexView(
            build_id=resolved, available=True, pdf_locations=index.forward(file, line)
        )

    def inverse(self, page: int, x: float, y: float, *, build_id: str | None = None) -> SynctexView:
        """The source line behind a point on a page, or why that cannot be answered."""
        resolved, index = self._synctex(build_id)
        state = index.state
        if state is not None:
            return SynctexView.unavailable(resolved, state)
        return SynctexView(
            build_id=resolved, available=True, source_location=index.inverse(page, x, y)
        )

    # -- audit ---------------------------------------------------------------

    def audit(
        self, *, parse_sources: bool = False, scope: AuditScope | None = None
    ) -> ManuscriptAuditReport:
        """The scientific audit of the manuscript as it is now (Product 30.3)."""
        from research_harness.manuscript.attach import ManuscriptService

        service = ManuscriptService(self._ctx, main_tex=self._settings.entry_file)
        return service.audit(parsed=parse_sources, scope=scope)

    # -- internals -----------------------------------------------------------

    def _resolve(self, build_id: str | None) -> CompileResult | None:
        """One build, by id or by role. `latest` and `last-good` are ids like any other.

        The daemon's PDF route has always accepted the two aliases, so a client that asks
        `manuscript.build` about the PDF it is looking at has to be able to name it the
        same way; anything else makes "which build is this?" a question with two answers.
        """
        if build_id is None or build_id == LATEST_BUILD:
            return self._compile.latest()
        if build_id == LAST_GOOD_BUILD:
            pointer = self._compile.last_good()
            return None if pointer is None else self._compile.build(pointer.build_id)
        return self._compile.build(build_id)

    def _audit(
        self, wanted: bool, parse_sources: bool, scope: AuditScope | None
    ) -> tuple[ManuscriptAuditReport | None, str | None]:
        """The audit, or the reason it could not run; never an exception into the view.

        A manuscript that cannot be parsed is a fact about the workspace, not a failure of
        the build view: the compiler diagnostics still have to reach the researcher, and
        the audit says honestly that it did not run.
        """
        if not wanted:
            return None, None
        try:
            return self.audit(parse_sources=parse_sources, scope=scope), None
        except ResearchHarnessError as error:
            logger.info("manuscript audit unavailable for the build view: %s", error)
            return None, str(error)

    def _synctex(self, build_id: str | None) -> tuple[str | None, SynctexIndex]:
        record = self._resolve(build_id)
        if record is None:
            return None, SynctexIndex.unavailable(
                SynctexUnavailableReason.MISSING_FILE,
                "this manuscript has not been compiled yet, so there is no SyncTeX map",
            )
        return record.build_id, self._compile.synctex(record.build_id)

    def _view(
        self,
        record: CompileResult | None,
        report: ManuscriptAuditReport | None,
        audit_unavailable: str | None,
    ) -> BuildView:
        toolchain = self.toolchain()
        pointer = self._compile.last_good()
        findings = () if report is None else report.findings
        audit_errors = 0 if report is None else len(report.errors)
        synctex_available = False
        synctex_reason: SynctexUnavailableReason | None = None
        synctex_detail: str | None = None
        if record is not None:
            index = self._compile.synctex(record.build_id)
            state = index.state
            synctex_available = state is None
            synctex_reason = None if state is None else state.reason
            synctex_detail = None if state is None else state.detail

        own_pdf = record is not None and record.pdf is not None
        return BuildView(
            build_id=None if record is None else record.build_id,
            status=None if record is None else record.status,
            result=record,
            diagnostics=() if record is None else record.diagnostics,
            error_count=0 if record is None else record.error_count,
            warning_count=0 if record is None else record.warning_count,
            audit_findings=findings,
            audit_error_count=audit_errors,
            audit_ran=report is not None,
            audit_unavailable_reason=audit_unavailable,
            pdf_available=own_pdf or pointer is not None,
            pdf=(record.pdf if own_pdf and record is not None else None),
            pdf_stale=not own_pdf and pointer is not None,
            last_good=pointer,
            synctex_available=synctex_available,
            synctex_reason=synctex_reason,
            synctex_detail=synctex_detail,
            toolchain=toolchain,
            guidance=_guidance(toolchain, record, pointer),
        )


def _guidance(
    toolchain: ToolchainReport, record: CompileResult | None, pointer: LastGoodBuild | None
) -> tuple[str, ...]:
    """What to do next, in the order a researcher needs it."""
    if not toolchain.available:
        return toolchain.guidance
    lines: list[str] = []
    if record is None:
        lines.append("This manuscript has not been compiled yet; run `manuscript.compile`.")
        return tuple(lines)
    if record.status is not CompileStatus.SUCCEEDED:
        lines.append(
            f"Build {record.build_id} {record.status.value}: "
            f"{record.error_count} compiler error(s) against the source as it is now."
        )
        if pointer is not None:
            lines.append(
                f"The preview is the last PDF that compiled ({pointer.build_id}, "
                f"{pointer.compiled_at.isoformat()}); it is stale."
            )
        else:
            lines.append("There is no earlier PDF to fall back to.")
    return tuple(lines)
