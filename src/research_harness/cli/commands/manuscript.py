"""`research manuscript ...` and `research draft`: the manuscript command family.

The CLI is a transport (ADR-004). Every mutation here goes through
:class:`~research_harness.manuscript.attach.ManuscriptService`, which goes through the
capability layer; every read goes through the repository's typed accessors. Nothing in
this module writes a canonical file, and `draft` writes only into `.research/staging/`.

Locations are written the way an editor reports them - ``main.tex:16`` - because the point
of Product 30.1 is that a researcher can go from a line they are looking at to the Claim,
the Evidence, and the page span behind it without leaving the terminal.
"""

from __future__ import annotations

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
