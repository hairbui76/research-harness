"""`research manuscript ...` and `research draft`: the manuscript command family.

The CLI is a transport (ADR-004). Every mutation here goes through
:class:`~research_harness.manuscript.attach.ManuscriptService` or
:class:`~research_harness.manuscript.workspace.ManuscriptWorkspace`, which go through the
capability layer; every read goes through the repository's typed accessors. Nothing in
this module writes a canonical file, and `draft` and `suggest` write only into
`.research/staging/`.

Locations are written the way an editor reports them - ``main.tex:16`` - because the point
of Product 30.1 is that a researcher can go from a line they are looking at to the Claim,
the Evidence, and the page span behind it without leaving the terminal.

The workspace half of the family - `files`, `read`, `write`, `compile`, `build`, `synctex`,
`suggest`, `apply` - mirrors the `manuscript.*` capabilities one for one, and prints the
compiler's diagnostics and the scientific audit as two separate lists, because a terminal
that summed them would be the first place the distinction was lost (LaTeX spec 7).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.dto import MutationResult
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.cli.providers import resolve_model_client
from research_harness.domain.enums import FindingSeverity, ManuscriptFindingKind
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId
from research_harness.domain.manuscript import ManuscriptAnchor
from research_harness.manuscript.attach import (
    ManuscriptError,
    ManuscriptService,
    RevalidationReport,
)
from research_harness.manuscript.audit import ManuscriptAuditReport, TraceLink
from research_harness.manuscript.draft import DraftCandidate, draft_section
from research_harness.manuscript.files import FileSnapshot
from research_harness.manuscript.suggest import (
    AppliedSuggestion,
    DiffLineKind,
    SuggestionCandidate,
    apply_suggestion,
    suggest_edit,
)
from research_harness.manuscript.workspace import (
    BuildView,
    ManuscriptTree,
    ManuscriptWorkspace,
    SynctexView,
)

__all__ = ["register"]

manuscript_app = typer.Typer(
    name="manuscript",
    help="Attach Claims to manuscript text, revalidate anchors, audit, and trace.",
    no_args_is_help=True,
)

LocationArgument = Annotated[
    str, typer.Argument(metavar="FILE:LINE", help="Manuscript location, e.g. main.tex:16.")
]
ClaimArgument = Annotated[str, typer.Argument(metavar="CLAIM", help="Claim to attach (C####).")]

MainTexOption = Annotated[
    str,
    typer.Option("--main", help="Main LaTeX file inside the manuscript directory."),
]
ProjectOption = Annotated[
    Path | None,
    typer.Option(
        "--project",
        help="Manuscript project root; defaults to the workspace's manuscript/ directory.",
        show_default=False,
    ),
]

PathArgument = Annotated[
    str, typer.Argument(metavar="PATH", help="Manuscript-relative file, e.g. sections/intro.tex.")
]


def register(app: typer.Typer) -> None:
    """Add `research manuscript ...` and `research draft` to ``app``."""
    app.add_typer(manuscript_app, name="manuscript")
    app.command("draft")(draft)


# -- attachment --------------------------------------------------------------


@manuscript_app.command("attach")
def attach(
    location: LocationArgument,
    claim: ClaimArgument,
    workspace: WorkspaceOption = None,
    project: ProjectOption = None,
    main: MainTexOption = "main.tex",
    as_json: JsonOption = False,
) -> None:
    """Bind the sentence at FILE:LINE to an existing Claim (`manuscript.attach_claim`)."""
    with cli_errors():
        service = _service(workspace, project, main)
        file, line = _split_location(location)
        anchor, mutation = service.attach((file, line), ClaimId(claim))
        emit(_attach_payload(anchor, mutation), _attach_lines(anchor, mutation), as_json=as_json)


@manuscript_app.command("attach-text")
def attach_text(
    sentence: Annotated[str, typer.Argument(help="The sentence to attach, quoted.")],
    claim: ClaimArgument,
    workspace: WorkspaceOption = None,
    project: ProjectOption = None,
    main: MainTexOption = "main.tex",
    as_json: JsonOption = False,
) -> None:
    """Bind a sentence found by its text to an existing Claim."""
    with cli_errors():
        service = _service(workspace, project, main)
        found = service.find_sentence_by_text(sentence)
        anchor, mutation = service.attach(found, ClaimId(claim))
        emit(_attach_payload(anchor, mutation), _attach_lines(anchor, mutation), as_json=as_json)


@manuscript_app.command("anchors")
def anchors(
    workspace: WorkspaceOption = None,
    project: ProjectOption = None,
    main: MainTexOption = "main.tex",
    as_json: JsonOption = False,
) -> None:
    """List every stored manuscript anchor and the Claim it carries."""
    with cli_errors():
        service = _service(workspace, project, main)
        stored = service.anchors()
        payload = {"anchors": [_anchor_summary(anchor) for anchor in stored]}
        emit(payload, _anchor_lines(stored), as_json=as_json)


@manuscript_app.command("revalidate")
def revalidate(
    workspace: WorkspaceOption = None,
    project: ProjectOption = None,
    main: MainTexOption = "main.tex",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report the verdicts without recording any of them."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Re-find every anchored sentence; a reword goes stale rather than moving (ADR-008)."""
    with cli_errors():
        service = _service(workspace, project, main)
        report = service.revalidate(apply=not dry_run)
        payload = {**report.as_dict(), "dry_run": dry_run}
        emit(payload, _revalidate_lines(report, dry_run=dry_run), as_json=as_json)


# -- audit and trace ---------------------------------------------------------


@manuscript_app.command("audit")
def audit(
    workspace: WorkspaceOption = None,
    project: ProjectOption = None,
    main: MainTexOption = "main.tex",
    no_parse: Annotated[
        bool,
        typer.Option(
            "--no-parse",
            help="Skip re-parsing source PDFs; source spans are then not checked.",
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Audit the manuscript against the accepted research graph (Product 30.3)."""
    with cli_errors():
        service = _service(workspace, project, main)
        report = service.audit(parsed=not no_parse)
        emit(_audit_payload(report), _audit_lines(report), as_json=as_json)


@manuscript_app.command("trace")
def trace(
    location: LocationArgument,
    workspace: WorkspaceOption = None,
    project: ProjectOption = None,
    main: MainTexOption = "main.tex",
    as_json: JsonOption = False,
) -> None:
    """Resolve FILE:LINE to its Claim, its Evidence, and the exact source span."""
    with cli_errors():
        service = _service(workspace, project, main)
        file, line = _split_location(location)
        link = service.trace(file, line)
        if link is None:
            sentence = service.find_sentence(file, line)
            payload: dict[str, Any] = {
                "location": f"{sentence.file}:{sentence.line_start}",
                "sentence": sentence.normalized_text,
                "claim": None,
                "evidence": [],
                "spans": [],
            }
            emit(
                payload,
                [
                    f"{sentence.file}:{sentence.line_start}  {sentence.normalized_text}",
                    "  no Claim is attached to this sentence; "
                    "run `research manuscript attach` first",
                ],
                as_json=as_json,
            )
            return
        emit(_trace_payload(link), _trace_lines(link), as_json=as_json)


# -- the manuscript workspace ------------------------------------------------


@manuscript_app.command("files")
def files(
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """List the source files of the manuscript (`manuscript.files`)."""
    with cli_errors():
        tree = _workspace(workspace).tree()
        emit(tree.model_dump(mode="json"), _tree_lines(tree), as_json=as_json)


@manuscript_app.command("read")
def read(
    path: PathArgument,
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Print one manuscript file with the hash a later `write` must present."""
    with cli_errors():
        snapshot = _workspace(workspace).read(path)
        emit(snapshot.model_dump(mode="json"), _snapshot_lines(snapshot), as_json=as_json)


@manuscript_app.command("write")
def write(
    path: PathArgument,
    expected_hash: Annotated[
        str,
        typer.Option(
            "--expected-hash",
            help="content_hash of the version you edited; a mismatch is refused.",
        ),
    ],
    content: Annotated[
        Path | None,
        typer.Option("--from", help="File to read the new content from; '-' reads stdin."),
    ] = None,
    text: Annotated[str | None, typer.Option("--text", help="The new content, inline.")] = None,
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Save one manuscript file, refusing an outside change (`manuscript.write_file`)."""
    with cli_errors():
        snapshot = _workspace(workspace).write(path, _content(content, text), expected_hash)
        emit(
            snapshot.model_dump(mode="json"),
            [f"wrote {snapshot.path}", *_snapshot_lines(snapshot)[1:]],
            as_json=as_json,
        )


@manuscript_app.command("compile")
def compile_(
    workspace: WorkspaceOption = None,
    entry: Annotated[
        str | None,
        typer.Option("--entry", help="Entry .tex file; defaults to manuscript.entry_file."),
    ] = None,
    timeout: Annotated[
        float | None, typer.Option("--timeout", help="Seconds before the process is killed.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Compile with the configured local engine (`manuscript.compile`)."""
    with cli_errors():
        view = _workspace(workspace).compile(entry_file=entry, timeout_seconds=timeout)
        emit(view.model_dump(mode="json"), _build_lines(view), as_json=as_json)


@manuscript_app.command("build")
def build(
    build_id: Annotated[
        str | None,
        typer.Argument(
            metavar="BUILD_ID",
            help=(
                "Build to read; `latest` or `last-good` name one by its role, and "
                "omitting it means the latest."
            ),
        ),
    ] = None,
    workspace: WorkspaceOption = None,
    no_audit: Annotated[
        bool, typer.Option("--no-audit", help="Report compiler diagnostics only.")
    ] = False,
    parse_sources: Annotated[
        bool,
        typer.Option("--parse-sources", help="Re-parse source PDFs so anchors are checked."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Show one build: compiler diagnostics and scientific findings (`manuscript.build`)."""
    with cli_errors():
        view = _workspace(workspace).build(
            build_id, audit=not no_audit, parse_sources=parse_sources
        )
        emit(view.model_dump(mode="json"), _build_lines(view), as_json=as_json)


@manuscript_app.command("synctex")
def synctex(
    location: Annotated[
        str | None,
        typer.Argument(
            metavar="FILE:LINE",
            help="Source location to look forward from, e.g. main.tex:16.",
            show_default=False,
        ),
    ] = None,
    workspace: WorkspaceOption = None,
    page: Annotated[
        int | None, typer.Option("--page", help="PDF page to look back from (1-based).")
    ] = None,
    x: Annotated[float | None, typer.Option("--x", help="PDF x, points from the left.")] = None,
    y: Annotated[float | None, typer.Option("--y", help="PDF y, points from the top.")] = None,
    build_id: Annotated[
        str | None,
        typer.Option(
            "--build",
            help="Build to use; `latest` or `last-good` are accepted, as is omitting it.",
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Map source to PDF, or PDF to source (`manuscript.synctex`)."""
    with cli_errors():
        service = _workspace(workspace)
        if location is not None:
            file, line = _split_location(location)
            view = service.forward(file, line, build_id=build_id)
        elif page is not None and x is not None and y is not None:
            view = service.inverse(page, x, y, build_id=build_id)
        else:
            raise CapabilityError("pass FILE:LINE to look forward, or --page --x --y to look back")
        emit(view.model_dump(mode="json"), _synctex_lines(view), as_json=as_json)


# -- candidate diffs ---------------------------------------------------------


@manuscript_app.command("suggest")
def suggest(
    location: Annotated[
        str,
        typer.Argument(metavar="FILE:START-END", help="Span to rewrite, e.g. main.tex:14-18."),
    ],
    workspace: WorkspaceOption = None,
    style: Annotated[
        str | None, typer.Option("--style", help="humanize | venue | copyedit.")
    ] = None,
    instruction: Annotated[
        str | None, typer.Option("--instruction", help="What the rewrite should do.")
    ] = None,
    session: Annotated[
        str | None, typer.Option("--session", help="Conversation session that asked (CS####).")
    ] = None,
    message: Annotated[
        str | None, typer.Option("--message", help="Message that asked (M####).")
    ] = None,
    context_pack: Annotated[
        str | None, typer.Option("--context-pack", help="Context receipt id (CP####).")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Provider entry from `providers:` in research.yaml, or 'scripted'.",
            show_default=False,
        ),
    ] = None,
    script: Annotated[
        Path | None,
        typer.Option("--script", help="JSON file of scripted writer responses."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Stage a candidate diff for one span; the manuscript is not touched."""
    with cli_errors():
        ctx = context_for(workspace)
        file, start, end = _split_span(location)
        candidate = suggest_edit(
            ctx,
            file=file,
            line_start=start,
            line_end=end,
            provider=resolve_model_client(ctx, provider, script),
            instruction=instruction,
            style=style,
            session_id=session,
            message_id=message,
            context_pack_id=context_pack,
        )
        emit(candidate.as_dict(), _candidate_lines(candidate), as_json=as_json)


@manuscript_app.command("apply")
def apply(
    candidate_id: Annotated[
        str, typer.Argument(metavar="CANDIDATE", help="Staged candidate to apply.")
    ],
    workspace: WorkspaceOption = None,
    expected_hash: Annotated[
        str | None,
        typer.Option(
            "--expected-hash",
            help="Defaults to the hash the candidate was produced against.",
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Apply a reviewed candidate diff to the manuscript (`manuscript.apply_suggestion`)."""
    with cli_errors():
        applied = apply_suggestion(
            context_for(workspace), candidate_id, expected_hash=expected_hash
        )
        emit(_applied_payload(applied), _applied_lines(applied), as_json=as_json)


# -- drafting ----------------------------------------------------------------


def draft(
    purpose: Annotated[str, typer.Argument(help="What this section has to do.")],
    claims: Annotated[
        str,
        typer.Option("--claims", help="Claims to draft from, comma separated (C0001,C0002)."),
    ],
    workspace: WorkspaceOption = None,
    style: Annotated[
        str | None, typer.Option("--style", help="Style constraints for the draft.")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            help="Provider entry from `providers:` in research.yaml, or 'scripted' with --script.",
            show_default=False,
        ),
    ] = None,
    script: Annotated[
        Path | None,
        typer.Option(
            "--script",
            help="JSON file of scripted writer responses, for the `scripted` provider.",
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Draft a manuscript section candidate from accepted Claims (Product 30)."""
    with cli_errors():
        ctx = context_for(workspace)
        candidate = draft_section(
            ctx,
            purpose,
            claims=[ClaimId(value) for value in _split_claims(claims)],
            provider=resolve_model_client(ctx, provider, script),
            style=style,
        )
        emit(_draft_payload(candidate), _draft_lines(candidate), as_json=as_json)


# -- wiring ------------------------------------------------------------------


def _workspace(workspace: Path | None) -> ManuscriptWorkspace:
    return ManuscriptWorkspace(context_for(workspace))


def _content(source: Path | None, text: str | None) -> str:
    """The new file content: a file, stdin, or an inline string - exactly one of them."""
    if (source is None) == (text is None):
        raise CapabilityError("pass exactly one of --from <file>|- and --text <content>")
    if text is not None:
        return text
    if source is None or str(source) == "-":
        return sys.stdin.read()
    return source.read_text(encoding="utf-8")


def _split_span(location: str) -> tuple[str, int, int]:
    """Split ``file:start-end``; a single line means a one-line span."""
    file, separator, span = location.rpartition(":")
    if not separator:
        raise ManuscriptError(f"{location!r} is not a FILE:START-END span, e.g. main.tex:14-18")
    start_text, dash, end_text = span.partition("-")
    if not start_text.strip().isdigit() or (dash and not end_text.strip().isdigit()):
        raise ManuscriptError(f"{location!r} is not a FILE:START-END span, e.g. main.tex:14-18")
    start = int(start_text)
    return file, start, int(end_text) if dash else start


def _service(workspace: Path | None, project: Path | None, main: str) -> ManuscriptService:
    return ManuscriptService(context_for(workspace), project_root=project, main_tex=main)


def _split_location(location: str) -> tuple[str, int]:
    """Split ``file:line``; a Windows drive letter keeps its colon."""
    file, separator, line = location.rpartition(":")
    if not separator or not line.strip().isdigit():
        raise ManuscriptError(f"{location!r} is not a FILE:LINE location, e.g. main.tex:16")
    return file, int(line)


def _split_claims(values: str) -> list[str]:
    parsed = [item.strip() for item in values.split(",") if item.strip()]
    if not parsed:
        raise CapabilityError("--claims needs at least one claim id, e.g. --claims C0001")
    return parsed


# -- workspace payloads ------------------------------------------------------


def _tree_lines(tree: ManuscriptTree) -> list[str]:
    if not tree.files:
        return [f"no manuscript source under {tree.root}/"]
    width = max(len(item.path) for item in tree.files)
    lines = [f"{tree.root}/  ({tree.count} files, entry {tree.entry_file})"]
    lines += [
        f"  {item.path.ljust(width)}  {item.kind.value:<5}  {item.size_bytes:>9} bytes"
        for item in tree.files
    ]
    return lines


def _snapshot_lines(snapshot: FileSnapshot) -> list[str]:
    return [
        f"{snapshot.path}  {snapshot.kind.value}  {snapshot.size_bytes} bytes",
        f"  content_hash       {snapshot.content_hash}",
        f"  modified_at        {snapshot.modified_at.isoformat()}",
        "",
        snapshot.content.rstrip("\n"),
    ]


def _build_lines(view: BuildView) -> list[str]:
    if not view.compiled:
        return [
            "this manuscript has not been compiled yet",
            *(f"  {item}" for item in view.guidance),
        ]
    status = view.status.value if view.status is not None else "unknown"
    lines = [f"build {view.build_id}  {status}"]
    if view.result is not None:
        lines.append(
            f"  engine             {view.result.engine.value} "
            f"({view.result.duration_seconds:.2f}s, exit {view.result.exit_status})"
        )
    lines.append(f"  compiler           {view.error_count} errors, {view.warning_count} warnings")
    for item in view.diagnostics:
        lines.append(f"    [{item.severity.value}] {item.where()}: {item.message}")
    if view.audit_ran:
        lines.append(
            f"  audit              {len(view.audit_findings)} findings "
            f"({view.audit_error_count} errors)"
        )
        for finding in view.audit_findings:
            lines.append(f"    [{finding.severity.value}] {finding.kind.value}: {finding.message}")
    else:
        lines.append(f"  audit              not run: {view.audit_unavailable_reason or 'skipped'}")
    lines.append(
        f"  pdf                {view.pdf or (view.last_good.pdf if view.last_good else '-')}"
        + ("  (stale: the last good build)" if view.pdf_stale else "")
    )
    lines.append(
        "  synctex            available"
        if view.synctex_available
        else f"  synctex            unavailable ({view.synctex_reason}): {view.synctex_detail}"
    )
    lines += [f"  {item}" for item in view.guidance]
    return lines


def _synctex_lines(view: SynctexView) -> list[str]:
    if not view.available:
        return [
            f"source/PDF navigation is unavailable ({view.reason}): {view.detail}",
        ]
    if view.source_location is not None:
        found = view.source_location
        return [f"{found.file}:{found.line}" + ("" if found.column is None else f":{found.column}")]
    if not view.pdf_locations:
        return ["that line produced nothing in the PDF"]
    return [
        f"page {item.page}  x={item.x:.1f} y={item.y:.1f} w={item.width:.1f} h={item.height:.1f}"
        for item in view.pdf_locations
    ]


def _candidate_lines(candidate: SuggestionCandidate) -> list[str]:
    lines = [
        f"staged {candidate.candidate_id}  {candidate.file}:"
        f"{candidate.line_start}-{candidate.line_end}",
        f"  policy             {candidate.policy}",
        f"  audit              {candidate.audit_status.value}",
        f"  protected spans    {len(candidate.protected_spans)} "
        f"({len(candidate.protected_violations)} changed)",
        f"  semantic diff      {candidate.semantic_diff.summary()}",
    ]
    for finding in candidate.audit_findings:
        lines.append(f"    [{finding.severity.value}] {finding.kind.value}: {finding.message}")
    for hunk in candidate.hunks:
        lines.append(f"  {hunk.header}")
        lines += [f"  {_MARK[line.kind]}{line.text}" for line in hunk.lines]
    if candidate.blocked_reason:
        lines.append(f"  blocked            {candidate.blocked_reason}")
    elif candidate.applicable:
        lines.append(f"  apply with         research manuscript apply {candidate.candidate_id}")
    return lines


_MARK = {
    DiffLineKind.CONTEXT: " ",
    DiffLineKind.ADDED: "+",
    DiffLineKind.REMOVED: "-",
}


def _applied_payload(applied: AppliedSuggestion) -> dict[str, Any]:
    return {
        "candidate": applied.candidate.as_dict(),
        "snapshot": applied.snapshot.model_dump(mode="json"),
        "event": applied.event.model_dump(mode="json"),
        "anchors_to_revalidate": list(applied.anchors_to_revalidate),
    }


def _applied_lines(applied: AppliedSuggestion) -> list[str]:
    lines = [
        f"applied {applied.candidate.candidate_id} to {applied.snapshot.path}",
        f"  content_hash       {applied.snapshot.content_hash}",
        f"  event              {applied.event.event.value}",
    ]
    if applied.anchors_to_revalidate:
        lines.append(
            f"  revalidate         {len(applied.anchors_to_revalidate)} anchor(s): "
            "run `research manuscript revalidate`"
        )
    return lines


# -- payloads ----------------------------------------------------------------


def _attach_payload(anchor: ManuscriptAnchor, mutation: MutationResult) -> dict[str, Any]:
    return {"anchor": _anchor_summary(anchor), "mutation": mutation.as_dict()}


def _attach_lines(anchor: ManuscriptAnchor, mutation: MutationResult) -> list[str]:
    return [
        f"{anchor.file}:{anchor.line_start}-{anchor.line_end} -> {anchor.claim}",
        f"  sentence           {anchor.sentence}",
        f"  fingerprint        {anchor.sentence_fingerprint}",
        f"  citations          {', '.join(anchor.citation_keys) or '-'}",
        f"  event              {mutation.event.event.value}",
    ]


def _anchor_summary(anchor: ManuscriptAnchor) -> dict[str, Any]:
    return {
        "key": f"{anchor.file}#{anchor.sentence_fingerprint}",
        "file": anchor.file,
        "line_start": anchor.line_start,
        "line_end": anchor.line_end,
        "claim": str(anchor.claim),
        "sentence": anchor.sentence,
        "fingerprint": anchor.sentence_fingerprint,
        "citation_keys": list(anchor.citation_keys),
        "status": anchor.status.value,
        "stale": anchor.stale.value,
    }


def _anchor_lines(anchors_: tuple[ManuscriptAnchor, ...]) -> list[str]:
    if not anchors_:
        return ["no manuscript anchors yet; run `research manuscript attach <file>:<line> <C####>`"]
    width = max(len(f"{item.file}:{item.line_start}") for item in anchors_)
    return [
        f"{f'{item.file}:{item.line_start}'.ljust(width)}  {item.claim}  "
        f"{item.status.value:<7}  {item.sentence}"
        for item in anchors_
    ]


def _revalidate_lines(report: RevalidationReport, *, dry_run: bool) -> list[str]:
    if not report.results:
        return ["no manuscript anchors to revalidate"]
    lines = [
        f"{len(report.results)} anchors: {len(report.valid)} valid "
        f"({len(report.relocated)} relocated), {len(report.stale)} stale, "
        f"{len(report.missing)} missing"
    ]
    for result in report.results:
        anchor = result.anchor
        similarity = "" if result.similarity is None else f" [{result.similarity:.2f}]"
        lines.append(
            f"  {result.status.value:<7} {anchor.file}:{anchor.line_start} {anchor.claim}"
            f"{similarity}  {result.reason}"
        )
    lines.append(
        "  dry run: nothing was recorded"
        if dry_run
        else f"  recorded {len(report.applied)} anchor updates"
    )
    return lines


def _audit_payload(report: ManuscriptAuditReport) -> dict[str, Any]:
    payload = report.model_dump(mode="json")
    payload["counts"] = {kind.value: len(report.of_kind(kind)) for kind in ManuscriptFindingKind}
    payload["errors"] = len(report.errors)
    payload["is_clean"] = report.is_clean
    return payload


def _audit_lines(report: ManuscriptAuditReport) -> list[str]:
    lines = [
        f"{report.sentences_checked} substantive sentences: "
        f"{report.anchored_sentences} anchored, {report.unanchored_substantive} unregistered",
        f"{len(report.findings)} findings ({len(report.errors)} errors)",
    ]
    for finding in report.findings:
        mark = "ERROR" if finding.severity is FindingSeverity.ERROR else finding.severity.value
        lines.append(f"  [{mark}] {finding.kind.value}: {finding.message}")
    if report.is_clean:
        lines.append("  the manuscript raised nothing")
    return lines


def _trace_payload(link: TraceLink) -> dict[str, Any]:
    return {
        "location": f"{link.sentence.file}:{link.sentence.line_start}",
        "sentence": link.sentence.normalized_text,
        "anchor": link.anchor_key,
        "claim": str(link.claim),
        "evidence": [str(item) for item in link.evidence],
        "spans": [
            {
                "block": str(span.block),
                "page": span.page,
                "bbox": None if span.bbox is None else list(span.bbox.as_tuple()),
                "text": span.text,
            }
            for span in link.spans
        ],
    }


def _trace_lines(link: TraceLink) -> list[str]:
    lines = [
        f"{link.sentence.file}:{link.sentence.line_start}  {link.sentence.normalized_text}",
        f"  claim              {link.claim}",
        f"  evidence           {', '.join(str(item) for item in link.evidence) or '-'}",
    ]
    for span in link.spans:
        bbox = (
            "-"
            if span.bbox is None
            else ", ".join(f"{value:.1f}" for value in span.bbox.as_tuple())
        )
        lines.append(f"  span               page {span.page}  [{bbox}]  {span.text!r}")
    if not link.spans:
        lines.append("  span               no source parse resolved for this evidence")
    return lines


def _draft_payload(candidate: DraftCandidate) -> dict[str, Any]:
    return candidate.as_dict()


def _draft_lines(candidate: DraftCandidate) -> list[str]:
    lines = [
        f"staged {candidate.path}",
        f"  purpose            {candidate.purpose}",
        f"  claims             {', '.join(str(item) for item in candidate.claim_refs) or '-'}",
        f"  evidence           {', '.join(str(item) for item in candidate.evidence_refs) or '-'}",
        f"  protected spans    {len(candidate.protected_spans)}",
    ]
    lines += [f"  NEEDS SOURCE       {item}" for item in candidate.needs_source]
    if candidate.is_complete:
        lines.append("  every statement traces to an accepted claim")
    return lines
