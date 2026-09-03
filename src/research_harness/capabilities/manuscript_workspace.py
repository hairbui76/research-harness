"""The manuscript workspace as named capabilities: files, compile, build, SyncTeX, diffs.

Phase 21 gives the manuscript the same shape every other subsystem has: one set of named
capabilities that HTTP, MCP, and the CLI all reach, with the permission decided here rather
than by whichever transport happened to carry the call (Product 22, ADR-004, ADR-009).

The permission split is the whole argument of the phase in one table:

============================  ==========  =========================================
capability                    permission  why
============================  ==========  =========================================
``manuscript.files``          read        listing owned source changes nothing
``manuscript.read_file``      read        so does opening it
``manuscript.build``          read        a recorded build plus the current audit
``manuscript.synctex``        read        a lookup in a map the compiler wrote
``manuscript.suggest``        stage       a candidate under `.research/staging`
``manuscript.write_file``     mutate      the researcher's own source
``manuscript.compile``        mutate      runs a local process over that source
``manuscript.apply_suggestion`` mutate    a model's words entering the manuscript
============================  ==========  =========================================

An agent host may read the manuscript and propose a diff; it may not save a file, start a
compiler, or apply its own suggestion. That is the same refusal it gets for accepted
scientific state, on purpose: source ownership is the researcher's (LaTeX spec 4).

Every handler here is a translation. The rules live in
:mod:`~research_harness.manuscript.workspace` and
:mod:`~research_harness.manuscript.suggest`; nothing in this module decides what a finding
means or when a diff may be applied.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec
from research_harness.domain.errors import CapabilityError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from research_harness.manuscript.workspace import ManuscriptWorkspace

__all__ = [
    "MANUSCRIPT_WORKSPACE_CAPABILITIES",
    "MANUSCRIPT_WORKSPACE_HANDLERS",
    "ApplySuggestionRequest",
    "BuildRequest",
    "CompileRequest",
    "ManuscriptFilesRequest",
    "ReadFileRequest",
    "SuggestRequest",
    "SynctexRequest",
    "WriteFileRequest",
    "manuscript_workspace_specs",
]


# --------------------------------------------------------------------------------------
# requests
# --------------------------------------------------------------------------------------


class ManuscriptFilesRequest(CapabilityRequest):
    """`manuscript.files`: the source tree of this workspace's manuscript."""


class ReadFileRequest(CapabilityRequest):
    """`manuscript.read_file`: one file's text plus the hash a later save must present."""

    path: str


class WriteFileRequest(CapabilityRequest):
    """`manuscript.write_file`: save a file, proving which version was edited.

    ``expected_hash`` is the ``content_hash`` of the snapshot the caller edited. A save
    whose hash does not match the bytes on disk is refused with both hashes, because an
    external editor's change is not something to merge blind (LaTeX spec 4).
    """

    path: str
    content: str
    expected_hash: str


class CompileRequest(CapabilityRequest):
    """`manuscript.compile`: run the configured local engine once, bounded."""

    entry_file: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)


class BuildRequest(CapabilityRequest):
    """`manuscript.build`: one build's compiler diagnostics and the current audit."""

    build_id: str | None = None
    """The build to read: a recorded id, or one of the two role names the daemon's PDF
    route accepts -- `latest` (the newest build) and `last-good` (the newest one that
    produced a PDF). Omitted means `latest`, so a client that is looking at
    `/manuscript/builds/last-good/pdf` can ask about exactly that build."""

    audit: bool = True
    parse_sources: bool = False
    """Re-parse the source artifacts so evidence anchors and page spans are checked too."""


class SynctexRequest(CapabilityRequest):
    """`manuscript.synctex`: source to PDF, or PDF to source, for one build.

    Exactly one direction per call: ``file`` and ``line`` look forward, ``page``, ``x``,
    and ``y`` look back.
    """

    build_id: str | None = None
    """The build whose map to read; `latest` and `last-good` are accepted here too."""
    file: str | None = None
    line: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    x: float | None = None
    y: float | None = None

    def forward(self) -> tuple[str, int] | None:
        """The source location to look forward from, when this request names one."""
        return None if self.file is None or self.line is None else (self.file, self.line)

    def inverse(self) -> tuple[int, float, float] | None:
        """The PDF point to look back from, when this request names one."""
        if self.page is None or self.x is None or self.y is None:
            return None
        return (self.page, self.x, self.y)

    def checked(self) -> tuple[tuple[str, int] | None, tuple[int, float, float] | None]:
        """Both directions, with the pair refused when it names neither or both."""
        source, point = self.forward(), self.inverse()
        if source is not None and point is not None:
            raise CapabilityError("manuscript.synctex: name either file+line or page+x+y, not both")
        if source is None and point is None:
            raise CapabilityError(
                "manuscript.synctex: pass file and line to look forward, or page, x and y "
                "to look back"
            )
        return source, point


class SuggestRequest(CapabilityRequest):
    """`manuscript.suggest`: a model rewrite of one span, staged as a candidate diff."""

    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    provider: str
    instruction: str | None = None
    style: str | None = None
    session_id: str | None = None
    message_id: str | None = None
    context_pack_id: str | None = None


class ApplySuggestionRequest(CapabilityRequest):
    """`manuscript.apply_suggestion`: write an accepted candidate into the source."""

    candidate_id: str
    expected_hash: str | None = None
    """Defaults to the hash the candidate was produced against, which is what a reviewer
    read; passing an older one is refused as a conflict rather than merged."""


# --------------------------------------------------------------------------------------
# handlers
# --------------------------------------------------------------------------------------


def _workspace(ctx: CapabilityContext) -> ManuscriptWorkspace:
    """The manuscript workspace for this context; imported here so `capabilities` stays
    importable without the manuscript stack (Gate P1)."""
    from research_harness.manuscript.workspace import ManuscriptWorkspace

    return ManuscriptWorkspace(ctx)


def manuscript_files(ctx: CapabilityContext, request: ManuscriptFilesRequest) -> BaseModel:
    """`manuscript.files`: the source tree a researcher can open. Writes nothing."""
    del request
    return _workspace(ctx).tree()


def manuscript_read_file(ctx: CapabilityContext, request: ReadFileRequest) -> BaseModel:
    """`manuscript.read_file`: one file with the hash that makes a later save checkable."""
    return _workspace(ctx).read(request.path)


def manuscript_write_file(ctx: CapabilityContext, request: WriteFileRequest) -> BaseModel:
    """`manuscript.write_file`: the researcher's explicit save, conflict-checked."""
    return _workspace(ctx).write(request.path, request.content, request.expected_hash)


def manuscript_compile(ctx: CapabilityContext, request: CompileRequest) -> BaseModel:
    """`manuscript.compile`: one bounded local compile; the manuscript is never rewritten."""
    return _workspace(ctx).compile(
        entry_file=request.entry_file, timeout_seconds=request.timeout_seconds
    )


def manuscript_build(ctx: CapabilityContext, request: BuildRequest) -> BaseModel:
    """`manuscript.build`: compiler diagnostics and scientific findings, side by side."""
    return _workspace(ctx).build(
        request.build_id, audit=request.audit, parse_sources=request.parse_sources
    )


def manuscript_synctex(ctx: CapabilityContext, request: SynctexRequest) -> BaseModel:
    """`manuscript.synctex`: navigate source <-> PDF, or say why that is not possible."""
    workspace = _workspace(ctx)
    source, point = request.checked()
    if source is not None:
        return workspace.forward(source[0], source[1], build_id=request.build_id)
    page, x, y = point if point is not None else (1, 0.0, 0.0)
    return workspace.inverse(page, x, y, build_id=request.build_id)


def manuscript_suggest(ctx: CapabilityContext, request: SuggestRequest) -> BaseModel:
    """`manuscript.suggest`: stage a candidate diff; the manuscript file is not touched."""
    # `_model_provider` is the package's own provider-selection helper: it applies the
    # workspace egress policy and the trace sink, and duplicating it here would give this
    # capability a second answer to "which model may run" (Product 20.2, 34).
    from research_harness.capabilities.extra_handlers import _model_provider
    from research_harness.manuscript.suggest import suggest_edit
    from research_harness.manuscript.toolchain import ManuscriptSettings

    return suggest_edit(
        ctx,
        file=request.file,
        line_start=request.line_start,
        line_end=request.line_end,
        provider=_model_provider(ctx, request.provider),
        instruction=request.instruction,
        style=request.style,
        session_id=request.session_id,
        message_id=request.message_id,
        context_pack_id=request.context_pack_id,
        settings=ManuscriptSettings.from_config(ctx.repo.config.manuscript),
    )


def manuscript_apply_suggestion(
    ctx: CapabilityContext, request: ApplySuggestionRequest
) -> BaseModel:
    """`manuscript.apply_suggestion`: the one path from candidate to manuscript source."""
    from research_harness.manuscript.suggest import apply_suggestion

    return apply_suggestion(ctx, request.candidate_id, expected_hash=request.expected_hash)


# --------------------------------------------------------------------------------------
# specs
# --------------------------------------------------------------------------------------


def _spec(
    name: str,
    *,
    summary: str,
    semantics: str,
    permission: Permission,
    request_model: type[BaseModel],
    response_model: type[BaseModel],
    handler: Callable[[CapabilityContext, Any], BaseModel],
    human_only: bool = False,
    long_running: bool = False,
) -> CapabilitySpec:
    """One capability spec, spelled out so the table below reads as a table."""
    return CapabilitySpec(
        name=name,
        summary=summary,
        permission=permission,
        scientific_semantics=semantics,
        request_model=request_model,
        response_model=response_model,
        handler=handler,
        human_only=human_only,
        long_running=long_running,
    )


MANUSCRIPT_WORKSPACE_CAPABILITIES: tuple[str, ...] = (
    "manuscript.files",
    "manuscript.read_file",
    "manuscript.write_file",
    "manuscript.compile",
    "manuscript.build",
    "manuscript.synctex",
    "manuscript.suggest",
    "manuscript.apply_suggestion",
)
"""The Phase 21 names, in the order the implementation plan lists them (§0.4)."""

MANUSCRIPT_WORKSPACE_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], BaseModel]] = (
    MappingProxyType(
        {
            "manuscript.files": manuscript_files,
            "manuscript.read_file": manuscript_read_file,
            "manuscript.write_file": manuscript_write_file,
            "manuscript.compile": manuscript_compile,
            "manuscript.build": manuscript_build,
            "manuscript.synctex": manuscript_synctex,
            "manuscript.suggest": manuscript_suggest,
            "manuscript.apply_suggestion": manuscript_apply_suggestion,
        }
    )
)
"""The same eight, as the handler table `capabilities.handlers` merges (ADR-004: one
dispatch table, so a capability nobody can reach is a wiring bug rather than a surprise)."""


def manuscript_workspace_specs() -> list[CapabilitySpec]:
    """The manuscript workspace capabilities, with their response models."""
    from research_harness.manuscript.files import FileSnapshot
    from research_harness.manuscript.suggest import AppliedSuggestion, SuggestionCandidate
    from research_harness.manuscript.workspace import BuildView, ManuscriptTree, SynctexView

    return [
        _spec(
            "manuscript.files",
            summary="Every source file of the manuscript a researcher can open.",
            semantics="reads owned manuscript source; changes nothing",
            permission=Permission.READ,
            request_model=ManuscriptFilesRequest,
            response_model=ManuscriptTree,
            handler=manuscript_files,
        ),
        _spec(
            "manuscript.read_file",
            summary="One manuscript file with the hash a later save must present.",
            semantics="reads one owned source file; changes nothing",
            permission=Permission.READ,
            request_model=ReadFileRequest,
            response_model=FileSnapshot,
            handler=manuscript_read_file,
        ),
        _spec(
            "manuscript.write_file",
            summary="Save one manuscript file, refusing an outside change.",
            semantics=(
                "writes the researcher's own manuscript source under a hash check; refuses "
                "when the file changed outside the harness"
            ),
            permission=Permission.MUTATE,
            request_model=WriteFileRequest,
            response_model=FileSnapshot,
            handler=manuscript_write_file,
            human_only=True,
        ),
        _spec(
            "manuscript.compile",
            summary="Run the configured local LaTeX engine once, bounded and confined.",
            semantics=(
                "runs a local process over owned source and writes only disposable build "
                "outputs; no manuscript file is changed"
            ),
            permission=Permission.MUTATE,
            request_model=CompileRequest,
            response_model=BuildView,
            handler=manuscript_compile,
            human_only=True,
        ),
        _spec(
            "manuscript.build",
            summary="One build: compiler diagnostics and scientific audit findings.",
            semantics="reads a recorded build and audits the manuscript; changes nothing",
            permission=Permission.READ,
            request_model=BuildRequest,
            response_model=BuildView,
            handler=manuscript_build,
        ),
        _spec(
            "manuscript.synctex",
            summary="Source-to-PDF and PDF-to-source navigation for one build.",
            semantics="reads the compiler's SyncTeX map; changes nothing",
            permission=Permission.READ,
            request_model=SynctexRequest,
            response_model=SynctexView,
            handler=manuscript_synctex,
        ),
        _spec(
            "manuscript.suggest",
            summary="Stage a model rewrite of one span as a reviewable candidate diff.",
            semantics=(
                "writes a candidate under .research/staging with its protected-span, "
                "semantic, and Claim-wording verdicts; the manuscript is untouched"
            ),
            permission=Permission.STAGE,
            request_model=SuggestRequest,
            response_model=SuggestionCandidate,
            handler=manuscript_suggest,
        ),
        _spec(
            "manuscript.apply_suggestion",
            summary="Apply a reviewed candidate diff to the manuscript source.",
            semantics=(
                "writes owned manuscript source from an audited candidate and records the "
                "source mutation; refuses a changed protected span, a failed audit, and a "
                "stale hash"
            ),
            permission=Permission.MUTATE,
            request_model=ApplySuggestionRequest,
            response_model=AppliedSuggestion,
            handler=manuscript_apply_suggestion,
            human_only=True,
        ),
    ]


def pdf_path_for(root: Path | str, build_id: str | None, *, last_good_only: bool = False) -> Path:
    """The PDF file one build should show, for the daemon's byte route.

    Lives beside the capabilities rather than in `server/` so that the route and
    `manuscript.build` agree about which PDF a reader is looking at, including the
    last-good fallback after a failed compile. ``last_good_only`` asks for that fallback
    directly, which is the one question the build id cannot express.
    """
    from research_harness.capabilities.context import open_context

    workspace = _workspace(open_context(Path(root)))
    return workspace.last_good_pdf() if last_good_only else workspace.pdf_path(build_id)
