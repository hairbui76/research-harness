"""`research ingest`, `research parse`, and `research work`: the corpus command family.

Every mutation here goes through a capability handler; reads go through the repository's
typed accessors. Nothing in this module writes a canonical file (ADR-004).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import IngestLocalPdfRequest, ParseWorkRequest
from research_harness.capabilities.handlers import ingest_local_pdf, parse_work
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.domain.document import ParsedDocument
from research_harness.domain.ids import ArtifactId, WorkId
from research_harness.domain.work import Work
from research_harness.ingest.service import IngestResult, ParseResult
from research_harness.parsing.base import diagnostics_summary, document_diagnostics

__all__ = ["register"]

work_app = typer.Typer(name="work", help="Inspect the corpus.", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    """Add `research ingest`, `research parse`, and `research work ...` to ``app``."""
    app.command("ingest")(ingest)
    app.command("parse")(parse)
    app.add_typer(work_app, name="work")


def ingest(
    pdf: Annotated[Path, typer.Argument(help="Local file to ingest.")],
    workspace: WorkspaceOption = None,
    as_new: Annotated[
        bool,
        typer.Option("--as-new", help="Register a new Work even if the identity looks familiar."),
    ] = False,
    attach_to: Annotated[
        str | None,
        typer.Option("--attach-to", help="Attach the file to this Work (W####)."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Register a local file as an immutable Artifact of a Work (`corpus.ingest`)."""
    with cli_errors():
        ctx = context_for(workspace)
        result = ingest_local_pdf(
            ctx,
            IngestLocalPdfRequest(
                path=pdf,
                as_new=as_new,
                attach_to=WorkId(attach_to) if attach_to else None,
            ),
        )
        emit(_ingest_payload(result), _ingest_lines(result), as_json=as_json)


def parse(
    work: Annotated[str, typer.Argument(help="Work to parse (W####).")],
    workspace: WorkspaceOption = None,
    artifact: Annotated[
        str | None,
        typer.Option("--artifact", help="Parse this artifact (A####) instead of the newest PDF."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Parse a Work's artifact into structural blocks and store them (`work.parse`)."""
    with cli_errors():
        ctx = context_for(workspace)
        result = parse_work(
            ctx,
            ParseWorkRequest(
                work=WorkId(work),
                artifact=ArtifactId(artifact) if artifact else None,
            ),
        )
        emit(_parse_payload(result), _parse_lines(result), as_json=as_json)


@work_app.command("list")
def work_list(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """List every Work in the corpus."""
    with cli_errors():
        ctx = context_for(workspace)
        works = ctx.repo.list_works()
        payload = {"works": [_work_summary(ctx, work) for work in works]}
        emit(payload, _work_list_lines(works), as_json=as_json)


@work_app.command("show")
def work_show(
    work: Annotated[str, typer.Argument(help="Work to show (W####).")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show one Work: its versions, artifacts, parsed blocks, and accepted evidence."""
    with cli_errors():
        ctx = context_for(workspace)
        record = ctx.repo.get_work(WorkId(work))
        payload = _work_detail(ctx, record)
        emit(payload, _work_show_lines(payload), as_json=as_json)


# -- payloads ----------------------------------------------------------------


def _ingest_payload(result: IngestResult) -> dict[str, Any]:
    return {
        "work": str(result.work),
        "version": str(result.version),
        "artifact": str(result.artifact),
        "created": result.created,
        "resolution": result.resolution.outcome.value,
        "reasons": list(result.resolution.reasons),
        "conflicts": [
            {
                "field": conflict.field,
                "existing": conflict.existing.value,
                "incoming": conflict.incoming.value,
            }
            for conflict in result.resolution.conflicts
        ],
        "metadata_notes": {note.field: note.note for note in result.metadata_notes},
        "undecodable_fields": list(result.undecodable_fields),
        "mutation": None if result.mutation is None else result.mutation.as_dict(),
    }


UNDECODABLE_HINT = (
    "the PDF's font does not decode, so this field was left empty rather than "
    "written as mojibake; `research discover` can propose it from a catalogue record"
)


def _ingest_lines(result: IngestResult) -> list[str]:
    created = {
        "nothing": "already registered; nothing was written",
        "artifact": "added an artifact to an existing version",
        "version": "added a version and an artifact",
        "work": "registered a new work",
    }[result.created]
    lines = [
        f"{result.work} / {result.version} / {result.artifact}: {created}",
        f"  identity           {result.resolution.outcome.value}",
    ]
    lines += [f"  reason             {reason}" for reason in result.resolution.reasons]
    lines += [
        f"  conflict           {conflict.field}: existing {conflict.existing.value!r}, "
        f"incoming {conflict.incoming.value!r}"
        for conflict in result.resolution.conflicts
    ]
    unreadable = result.undecodable_fields
    if unreadable:
        lines.append(f"  text quality       {', '.join(unreadable)} unreadable")
        lines.append(f"  warning            {UNDECODABLE_HINT}")
    if result.mutation is not None:
        lines += [f"  warning            {text}" for text in result.mutation.validation.warnings]
        lines.append(f"  event              {result.mutation.event.event.value}")
    return lines


def _parse_payload(result: ParseResult) -> dict[str, Any]:
    return {
        "work": str(result.work),
        "artifact": str(result.artifact),
        "parser": f"{result.document.parser_name}@{result.document.parser_version}",
        "pages": result.page_count,
        "blocks": len(result.blocks),
        "diagnostics": document_diagnostics(result.document),
        "diagnostics_summary": diagnostics_summary(result.document),
        "mutation": result.mutation.as_dict(),
    }


def _parse_lines(result: ParseResult) -> list[str]:
    """Blocks, parser, and what the parser could not read.

    The diagnostics were always recorded and never shown, so a publication-quality PDF
    with 29 Caesar-shifted spans reported itself as a clean 304-block parse (dogfood F6).
    A researcher must be told before quoting a span from an affected page.
    """
    return [
        f"{result.work} / {result.artifact}: parsed {len(result.blocks)} blocks "
        f"across {result.page_count} pages",
        f"  parser             {result.document.parser_name}@{result.document.parser_version}",
        f"  text quality       {diagnostics_summary(result.document)}",
        f"  event              {result.mutation.event.event.value}",
    ]


def _work_summary(ctx: CapabilityContext, work: Work) -> dict[str, Any]:
    del ctx
    return {
        "id": str(work.id),
        "title": work.title,
        "year": work.year,
        "screening": work.screening.value,
        "versions": [str(version) for version in work.versions],
        "artifacts": [str(artifact) for artifact in work.artifacts],
    }


def _work_list_lines(works: list[Work]) -> list[str]:
    if not works:
        return ["no works in this corpus yet; run `research ingest <pdf>`"]
    width = max(len(str(work.id)) for work in works)
    return [f"{str(work.id).ljust(width)}  {work.year or '????'}  {work.title}" for work in works]


def _work_detail(ctx: CapabilityContext, work: Work) -> dict[str, Any]:
    repo = ctx.repo
    artifacts = repo.list_artifacts(work.id)
    parses = [
        document
        for artifact in artifacts
        for document in [repo.get_parsed_document(artifact.id, work=work.id)]
        if document is not None
    ]
    # One read: a stored document is exactly the artifact's blocks, and it also carries the
    # parse provenance the text-quality line is read from.
    blocks = [block for document in parses for block in document.blocks]
    return {
        "id": str(work.id),
        "title": work.title,
        "authors": list(work.authors),
        "year": work.year,
        "venue": work.venue,
        "screening": work.screening.value,
        "identifiers": work.identifiers.model_dump(mode="json", exclude_none=True),
        "versions": [
            {"id": str(version.id), "kind": version.kind.value, "label": version.label}
            for version in repo.list_versions(work.id)
        ],
        "artifacts": [
            {
                "id": str(artifact.id),
                "version": str(artifact.version),
                "kind": artifact.kind.value,
                "file_hash": artifact.file_hash,
                "size_bytes": artifact.size_bytes,
                "original_filename": artifact.original_filename,
            }
            for artifact in artifacts
        ],
        "blocks": len(blocks),
        "pages": max((block.page for block in blocks), default=0),
        "evidence": sum(1 for _ in repo.iter_evidence(work.id)),
        "parse_quality": [_parse_quality(document) for document in parses],
    }


def _parse_quality(document: ParsedDocument) -> dict[str, Any]:
    """What the parser could not read in one artifact, read back off its stored blocks."""
    return {
        "artifact": str(document.artifact),
        "diagnostics": document_diagnostics(document),
        "summary": diagnostics_summary(document),
    }


def _work_show_lines(payload: dict[str, Any]) -> list[str]:
    lines = [
        f"{payload['id']}  {payload['title']}",
        f"  authors            {', '.join(payload['authors']) or '-'}",
        f"  year               {payload['year'] or '-'}",
        f"  screening          {payload['screening']}",
        f"  versions           {len(payload['versions'])}",
        f"  artifacts          {len(payload['artifacts'])}",
        f"  blocks             {payload['blocks']}",
        f"  pages              {payload['pages']}",
        f"  evidence           {payload['evidence']}",
    ]
    lines += [
        f"    {artifact['id']}  {artifact['kind']}  {artifact['size_bytes']} bytes  "
        f"{artifact['original_filename']}"
        for artifact in payload["artifacts"]
    ]
    lines += [
        f"  text quality       {quality['artifact']}: {quality['summary']}"
        for quality in payload["parse_quality"]
    ]
    return lines
