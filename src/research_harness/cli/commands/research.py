"""`research note`, `question`, `taxonomy`, `matrix`, and `compare`: the capture family.

The transport is thin by design (ADR-004): every command resolves a workspace, calls a
service in `research/` or `synthesis/` — which in turn calls a capability handler — and
prints. Nothing here writes a canonical file, decides a taxonomy, or accepts a label.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import MutationResult
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.domain.claim import Claim
from research_harness.domain.enums import DecisionStatus, DecisionType, NoteStatus, QuestionStatus
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import QuestionId, SynthesisId
from research_harness.domain.research import (
    Decision,
    MatrixCell,
    ResearchNote,
    ResearchQuestion,
    SynthesisMatrix,
)
from research_harness.research import (
    NotePromotion,
    NoteService,
    QuestionService,
    next_claim_id,
    next_question_id,
)
from research_harness.synthesis import ClassificationRule, ComparisonTable, SynthesisService
from research_harness.synthesis.matrix import MatrixDiff, matrix_diff
from research_harness.synthesis.service import TaxonomyRevision, next_decision_id

__all__ = ["PromoteTo", "register"]

CLI_SOURCE = "cli"
"""What `note add` records as the capture host; provenance only, never note content."""

note_app = typer.Typer(
    name="note", help="Capture and promote research notes.", no_args_is_help=True
)
question_app = typer.Typer(
    name="question", help="Track open research questions.", no_args_is_help=True
)
taxonomy_app = typer.Typer(
    name="taxonomy", help="Record project taxonomy decisions.", no_args_is_help=True
)
matrix_app = typer.Typer(
    name="matrix", help="Build cross-paper synthesis matrices.", no_args_is_help=True
)


class PromoteTo(StrEnum):
    """What a captured note may be promoted into (Product 31)."""

    CLAIM = "claim"
    QUESTION = "question"
    DECISION = "decision"


def register(app: typer.Typer) -> None:
    """Add `research note/question/taxonomy/matrix ...` and `research compare` to ``app``."""
    app.add_typer(note_app, name="note")
    app.add_typer(question_app, name="question")
    app.add_typer(taxonomy_app, name="taxonomy")
    app.add_typer(matrix_app, name="matrix")
    app.command("compare")(compare)


# -- notes -------------------------------------------------------------------


@note_app.command("add")
def note_add(
    text: Annotated[str, typer.Argument(help="What to capture, verbatim.")],
    workspace: WorkspaceOption = None,
    source: Annotated[
        str | None,
        typer.Option("--source", help="Where the note came from; recorded as provenance only."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Capture a low-authority note (`note.add`); it can never be cited as support."""
    with cli_errors():
        ctx = context_for(workspace)
        note, result = NoteService(ctx).capture(text, source=source or CLI_SOURCE)
        emit(
            {"note": _note_payload(note), "mutation": result.as_dict()},
            [f"{note.key}  {note.status.value}", f"  text               {note.text}"],
            as_json=as_json,
        )


@note_app.command("list")
def note_list(
    workspace: WorkspaceOption = None,
    status: Annotated[
        NoteStatus | None, typer.Option("--status", help="Only notes in this status.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List captured notes, newest last."""
    with cli_errors():
        ctx = context_for(workspace)
        notes = NoteService(ctx).list(status)
        emit(
            {"notes": [_note_payload(note) for note in notes]},
            _note_lines(notes),
            as_json=as_json,
        )


@note_app.command("promote")
def note_promote(
    key: Annotated[str, typer.Argument(help="Note key, as printed by `research note add`.")],
    to: Annotated[PromoteTo, typer.Option("--to", help="The research object the note becomes.")],
    workspace: WorkspaceOption = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="JSON fields for the object being created."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Promote a captured note into a Claim, Question, or Decision (researcher only)."""
    with cli_errors():
        ctx = context_for(workspace)
        service = NoteService(ctx)
        note = service.get(key)
        spec = _load_spec(file)
        promotion = _promote(ctx, service, note, to, spec)
        emit(
            {
                "note": _note_payload(promotion.note),
                "target": str(promotion.target),
                "created": promotion.created.as_dict(),
                "promoted": promotion.promoted.as_dict(),
            },
            [
                f"{promotion.note.key}  promoted into {promotion.target}",
                f"  capability         {promotion.created.capability}",
                f"  event              {promotion.promoted.event.event.value}",
                *_stale_lines(promotion.promoted),
            ],
            as_json=as_json,
        )


def _promote(
    ctx: CapabilityContext,
    service: NoteService,
    note: ResearchNote,
    to: PromoteTo,
    spec: dict[str, Any],
) -> NotePromotion:
    key = note.key or ""
    match to:
        case PromoteTo.CLAIM:
            return service.promote_to_claim(key, _claim_from(ctx, note, spec))
        case PromoteTo.QUESTION:
            return service.promote_to_question(key, _question_from(ctx, note, spec))
        case PromoteTo.DECISION:
            return service.promote_to_decision(key, _decision_from(ctx, note, spec))


def _claim_from(ctx: CapabilityContext, note: ResearchNote, spec: dict[str, Any]) -> Claim:
    if not spec:
        raise ResearchHarnessError(
            "promoting a note into a Claim needs --file with the claim's statement, type, "
            "semantics, scope, and assessment: a claim is not a sentence with citations"
        )
    fields = {
        "statement": note.text,
        **spec,
        "id": spec.get("id") or next_claim_id(ctx.repo),
        "provenance": spec.get("provenance") or ctx.provenance(workflow="note"),
    }
    return Claim.model_validate(fields)


def _question_from(
    ctx: CapabilityContext, note: ResearchNote, spec: dict[str, Any]
) -> ResearchQuestion:
    fields = {
        "question": note.text,
        **spec,
        "id": spec.get("id") or next_question_id(ctx.repo),
        "provenance": spec.get("provenance") or ctx.provenance(workflow="note"),
    }
    return ResearchQuestion.model_validate(fields)


def _decision_from(ctx: CapabilityContext, note: ResearchNote, spec: dict[str, Any]) -> Decision:
    fields = {
        "type": DecisionType.OTHER.value,
        "rationale": note.text,
        **spec,
        "id": spec.get("id") or next_decision_id(ctx.repo),
        "status": DecisionStatus.PROPOSED.value,
        "provenance": spec.get("provenance") or ctx.provenance(workflow="note"),
    }
    return Decision.model_validate(fields)


# -- questions ---------------------------------------------------------------


@question_app.command("create")
def question_create(
    text: Annotated[str, typer.Argument(help="The question, in the researcher's words.")],
    workspace: WorkspaceOption = None,
    uncertainty: Annotated[
        str | None,
        typer.Option("--uncertainty", help="What is still unresolved about it."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Register an open research question (`question.create`)."""
    with cli_errors():
        ctx = context_for(workspace)
        question, result = QuestionService(ctx).create(text, remaining_uncertainty=uncertainty)
        emit(
            {"question": _question_payload(question), "mutation": result.as_dict()},
            [f"{question.id}  {question.status.value}  {question.question}"],
            as_json=as_json,
        )


@question_app.command("list")
def question_list(
    workspace: WorkspaceOption = None,
    status: Annotated[
        QuestionStatus | None, typer.Option("--status", help="Only questions in this status.")
    ] = None,
    open_only: Annotated[
        bool, typer.Option("--open", help="Only questions that are not answered yet.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """List research questions and what currently bears on them."""
    with cli_errors():
        ctx = context_for(workspace)
        service = QuestionService(ctx)
        questions = service.open_questions() if open_only else service.list(status)
        emit(
            {"questions": [_question_payload(item) for item in questions]},
            _question_lines(questions),
            as_json=as_json,
        )


@question_app.command("resolve")
def question_resolve(
    question: Annotated[str, typer.Argument(help="Question to answer (RQ####).")],
    answer: Annotated[str, typer.Argument(help="The answer, captured as a research note.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Answer a question: status `answered`, no uncertainty left, answer captured as a note."""
    with cli_errors():
        ctx = context_for(workspace)
        answered, result = QuestionService(ctx).resolve(QuestionId(question), answer)
        emit(
            {"question": _question_payload(answered), "mutation": result.as_dict()},
            [
                f"{answered.id}  {answered.status.value}",
                f"  answer             {answer}",
                f"  event              {result.event.event.value}",
            ],
            as_json=as_json,
        )


# -- taxonomy ----------------------------------------------------------------


@taxonomy_app.command("set")
def taxonomy_set(
    name: Annotated[str, typer.Argument(help="Taxonomy name, e.g. representation.")],
    terms: Annotated[
        str, typer.Option("--terms", help="Comma-separated approved terms, in display order.")
    ],
    rationale: Annotated[
        str, typer.Option("--rationale", help="Why the project classifies this way.")
    ],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Accept a taxonomy Decision and write the taxonomy it approves (`taxonomy.put`).

    Revising an accepted taxonomy marks dependent matrices and Claims stale; nothing
    downstream is rewritten (Product 42.I, ADR-008).
    """
    with cli_errors():
        ctx = context_for(workspace)
        revision = SynthesisService(ctx).revise_taxonomy(name, _terms(terms), rationale)
        emit(_revision_payload(revision), _revision_lines(revision), as_json=as_json)


# -- matrices ----------------------------------------------------------------


@matrix_app.command("build")
def matrix_build(
    field: Annotated[str, typer.Argument(help="Field to classify, e.g. representation.")],
    taxonomy: Annotated[str, typer.Option("--taxonomy", help="Taxonomy to classify under.")],
    rules: Annotated[Path, typer.Option("--rules", help="JSON classification rules.")],
    workspace: WorkspaceOption = None,
    matrix: Annotated[
        str | None, typer.Option("--matrix", help="Write this matrix id (S####).")
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite a matrix a Claim was read off."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Classify the corpus for one field from accepted evidence (`synthesis.build_matrix`).

    A rebuild prints the cells that moved, because a rule fix that silently reclassifies a
    work is a change to the record nobody saw (dogfood F16), and it refuses to overwrite a
    matrix a Claim was read off without `--force`.
    """
    with cli_errors():
        ctx = context_for(workspace)
        service = SynthesisService(ctx)
        matrix_id = SynthesisId(matrix) if matrix else None
        previous = service.existing_matrix(field, taxonomy, matrix_id=matrix_id)
        built, result = service.build(
            field,
            taxonomy,
            _load_rules(rules, field),
            matrix_id=matrix_id,
            force=force,
        )
        table = service.compare(field, matrix_id=built.id)
        diff = None if previous is None else matrix_diff(previous, built)
        emit(
            {
                "matrix": _matrix_payload(built),
                "comparison": table.as_dict(),
                "diff": None if diff is None else diff.as_dict(),
                "mutation": result.as_dict(),
            },
            [
                f"{built.id}  {built.name}",
                f"  taxonomy           {built.taxonomy}",
                f"  works              {len(built.works)}",
                f"  classified         {len(built.works) - len(table.unclassified)}"
                f" of {len(built.works)}",
                *_diff_lines(diff),
                f"  event              {result.event.event.value}",
                *_stale_lines(result),
            ],
            as_json=as_json,
        )


@matrix_app.command("stale")
def matrix_stale(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """List synthesis matrices and cells an upstream change has made stale."""
    with cli_errors():
        ctx = context_for(workspace)
        marks = SynthesisService(ctx).stale_matrices()
        payload = {
            "stale": [
                {
                    "object_id": mark.object_id,
                    "reason": mark.reason,
                    "priority": int(mark.priority),
                    "source_change": mark.source_change,
                }
                for mark in marks
            ]
        }
        lines = [f"{mark.object_id}  {mark.reason}" for mark in marks] or [
            "no synthesis matrix is stale"
        ]
        emit(payload, lines, as_json=as_json)


def compare(
    field: Annotated[str, typer.Argument(help="Field to compare across the corpus.")],
    workspace: WorkspaceOption = None,
    matrix: Annotated[
        str | None, typer.Option("--matrix", help="Compare this matrix (S####).")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Show one field across every work: labels, the evidence behind them, and the gaps.

    A work with no labels is *unclassified*, which is a statement about the record and
    never about the work: absence needs its own coverage and evidence (Product 11).
    """
    with cli_errors():
        ctx = context_for(workspace)
        table = SynthesisService(ctx).compare(
            field, matrix_id=SynthesisId(matrix) if matrix else None
        )
        emit(table.as_dict(), _comparison_lines(table), as_json=as_json)


# -- payloads and lines ------------------------------------------------------


def _note_payload(note: ResearchNote) -> dict[str, Any]:
    return {
        "key": note.key,
        "status": note.status.value,
        "text": note.text,
        "promoted_to": None if note.promoted_to is None else str(note.promoted_to),
        "created_at": note.created_at.isoformat(),
        "source": note.provenance.note,
    }


def _note_lines(notes: list[ResearchNote]) -> list[str]:
    if not notes:
        return ['no notes captured yet; run `research note add "..."`']
    width = max(len(note.key or "") for note in notes)
    return [
        f"{(note.key or '').ljust(width)}  {note.status.value.ljust(9)}  {note.text}"
        for note in notes
    ]


def _question_payload(question: ResearchQuestion) -> dict[str, Any]:
    return {
        "id": str(question.id),
        "question": question.question,
        "status": question.status.value,
        "claims": [str(value) for value in question.claims],
        "search_runs": [str(value) for value in question.search_runs],
        "supporting_evidence": [str(value) for value in question.supporting_evidence],
        "counter_evidence": [str(value) for value in question.counter_evidence],
        "remaining_uncertainty": question.remaining_uncertainty or None,
        "stale": question.stale.value,
    }


def _question_lines(questions: list[ResearchQuestion]) -> list[str]:
    if not questions:
        return ['no research questions yet; run `research question create "..."`']
    lines: list[str] = []
    for question in questions:
        lines.append(f"{question.id}  {question.status.value.ljust(18)}  {question.question}")
        if question.remaining_uncertainty:
            lines.append(f"  uncertainty        {question.remaining_uncertainty}")
        linked = (
            f"claims {len(question.claims)}, searches {len(question.search_runs)}, "
            f"support {len(question.supporting_evidence)}, "
            f"counter {len(question.counter_evidence)}"
        )
        lines.append(f"  linked             {linked}")
    return lines


def _matrix_payload(matrix: SynthesisMatrix) -> dict[str, Any]:
    return {
        "id": str(matrix.id),
        "name": matrix.name,
        "taxonomy": matrix.taxonomy,
        "works": [str(work) for work in matrix.works],
        "fields": list(matrix.fields),
        "cells": [
            {
                "work": str(cell.work),
                "field": cell.field,
                "labels": list(cell.labels),
                "evidence": [str(value) for value in cell.evidence],
            }
            for cell in matrix.cells
        ],
        "stale": matrix.stale.value,
    }


def _revision_payload(revision: TaxonomyRevision) -> dict[str, Any]:
    return {
        "taxonomy": revision.taxonomy.name,
        "decision": str(revision.decision.id),
        "supersedes": (
            None if revision.decision.supersedes is None else str(revision.decision.supersedes)
        ),
        "terms": [term.term for term in revision.taxonomy.terms],
        "accepted": revision.accepted.as_dict(),
        "written": revision.written.as_dict(),
        "stale": [
            {
                "object_id": mark.object_id,
                "reason": mark.reason,
                "priority": int(mark.priority),
                "source_change": mark.source_change,
            }
            for mark in revision.stale
        ],
    }


def _revision_lines(revision: TaxonomyRevision) -> list[str]:
    terms = ", ".join(term.term for term in revision.taxonomy.terms)
    lines = [
        f"{revision.taxonomy.name}  {revision.decision.id} accepted"
        f"  ({len(revision.taxonomy.terms)} terms)",
        f"  terms              {terms}",
        f"  event              {revision.written.event.event.value}",
    ]
    if revision.decision.supersedes is not None:
        lines.append(f"  supersedes         {revision.decision.supersedes}")
    lines += [f"  stale              {mark.object_id}  {mark.reason}" for mark in revision.stale]
    return lines


def _comparison_lines(table: ComparisonTable) -> list[str]:
    lines = [f"{table.matrix}  {table.field}  (taxonomy: {table.taxonomy or '-'})"]
    if not table.rows:
        return [*lines, "  no works in this matrix"]
    width = max(len(str(row.work)) for row in table.rows)
    for row in table.rows:
        labels = ", ".join(row.labels) if row.labels else "-  (not recorded)"
        evidence = ", ".join(str(value) for value in row.evidence) or "-"
        lines.append(f"  {str(row.work).ljust(width)}  {labels}")
        lines.append(f"  {' ' * width}  evidence: {evidence}")
    counts = ", ".join(f"{label} {count}" for label, count in table.label_counts().items())
    lines.append(f"  labels             {counts or '-'}")
    lines.append(f"  unclassified       {len(table.unclassified)} of {len(table.rows)} works")
    return lines


def _cell_line(cell: MatrixCell) -> str:
    return f"{cell.work}  {', '.join(cell.labels) or '-'}"


def _diff_lines(diff: MatrixDiff | None) -> list[str]:
    """What a rebuild moved, cell by cell; nothing at all on a first build.

    `MatrixCellChange` existed and no transport read it, so a rule fix that moved RAPIER
    from `raw sequential, behavior-aware` to `behavior-aware` printed `classified 5 of 5`
    (dogfood F16).
    """
    if diff is None:
        return []
    if diff.is_empty:
        return ["  changes            none; this rebuild classifies the corpus identically"]
    lines = [f"  changes            {len(diff.changed)} cell(s) moved"]
    lines += [f"    added            {_cell_line(cell)}" for cell in diff.added]
    lines += [f"    removed          {_cell_line(cell)}" for cell in diff.removed]
    for change in diff.changed:
        moved = []
        if change.added_labels:
            moved.append(f"+{', '.join(change.added_labels)}")
        if change.removed_labels:
            moved.append(f"-{', '.join(change.removed_labels)}")
        if change.added_evidence:
            moved.append(f"+evidence {', '.join(str(item) for item in change.added_evidence)}")
        if change.removed_evidence:
            moved.append(f"-evidence {', '.join(str(item) for item in change.removed_evidence)}")
        lines.append(f"    {change.work}  {change.field}  {'  '.join(moved)}")
    return lines


def _stale_lines(result: MutationResult) -> list[str]:
    return [f"  stale              {mark.object_id}  {mark.reason}" for mark in result.stale]


# -- inputs ------------------------------------------------------------------


def _terms(value: str) -> tuple[str, ...]:
    return tuple(term.strip() for term in value.split(",") if term.strip())


def _load_spec(path: Path | None) -> dict[str, Any]:
    """Object fields for a promotion target, as a JSON object; empty when no file is given."""
    if path is None:
        return {}
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ResearchHarnessError(f"{path}: expected a JSON object of object fields")
    return data


def _load_rules(path: Path, field: str) -> tuple[ClassificationRule, ...]:
    """Classification rules from JSON: a list of rules, or ``{"rules": [...]}``.

    A rule without its own ``field`` inherits the field being built, so the common case is
    ``[{"term": "field_based", "any_of": ["field", "header"]}]``.
    """
    data = _read_json(path)
    entries = data.get("rules", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ResearchHarnessError(f"{path}: expected a JSON list of classification rules")
    rules: list[ClassificationRule] = []
    for entry in entries:
        if not isinstance(entry, dict) or "term" not in entry:
            raise ResearchHarnessError(f"{path}: every rule needs a 'term' and 'any_of'")
        rules.append(
            ClassificationRule(
                term=str(entry["term"]),
                field=str(entry.get("field", field)),
                any_of=tuple(str(value) for value in entry.get("any_of", ())),
            )
        )
    return tuple(rules)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResearchHarnessError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ResearchHarnessError(f"{path} is not valid JSON: {exc}") from exc
