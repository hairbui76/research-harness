"""`research discover`, `snowball`, `screen`, `acquire`, and `coverage`: the discovery family.

A transport and nothing more (ADR-004): it resolves a workspace, builds a provider registry
from the environment, calls `discovery/`, and prints. It never writes a canonical file, and
it never decides what a search permits a claim to say.

`discover` and `screen` each carry both a positional form and a sub-verb (`discover rerun
SR0001`, `screen list SR0001`). Click cannot give one command group both its own positional
arguments and subcommands, so the sub-verb is dispatched from the leading word here; a
`SearchRunId` never collides with `rerun` or `list`, which is what makes that unambiguous.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.context import CapabilityContext
from research_harness.citations.snowball import MAX_SNOWBALL_DEPTH, SnowballDirection, SnowballPlan
from research_harness.claims.coverage import CoverageUniverse
from research_harness.claims.service import ClaimService
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.discovery.absence import AbsenceAuditReport, audit_absence_claim
from research_harness.discovery.screening import acquire as acquire_candidate
from research_harness.discovery.screening import screen as screen_candidate
from research_harness.discovery.screening import screening_summary
from research_harness.discovery.search_runs import DEFAULT_MAX_PAGES, DiscoveryService
from research_harness.domain.claim import Claim
from research_harness.domain.enums import ScreeningState
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ClaimId, EvidenceId, SearchRunId, WorkId
from research_harness.domain.research import SearchRun
from research_harness.domain.work import Work
from research_harness.ingest.service import IngestResult
from research_harness.privacy.policy import EgressPolicy, load_policy
from research_harness.providers.search import SearchProviderRegistry, build_search_registry
from research_harness.providers.search.base import SearchQuery

__all__ = ["build_registry", "register"]

RERUN_VERB = "rerun"
LIST_VERB = "list"

_DIRECTIONS: tuple[SnowballDirection, ...] = ("backward", "forward", "both")


def register(app: typer.Typer) -> None:
    """Add `research discover`, `snowball`, `screen`, `acquire`, and `coverage` to ``app``."""
    app.command("discover")(discover)
    app.command("snowball")(snowball)
    app.command("screen")(screen)
    app.command("acquire")(acquire)
    app.command("coverage")(coverage)


def build_registry(
    sources: Sequence[str] | None = None, *, policy: EgressPolicy | None = None
) -> SearchProviderRegistry:
    """The configured discovery sources.

    Credentials and the polite-pool contact address come from the process environment and
    never from a workspace file (Product 34). Tests replace this function to run the whole
    command family against in-memory sources.
    """
    return build_search_registry(
        os.environ, sources=list(sources) if sources else None, policy=policy
    )


# -- discover ----------------------------------------------------------------


def discover(
    query: Annotated[
        list[str] | None,
        typer.Argument(metavar="QUERY", help="Search text, or `rerun <SR####>`."),
    ] = None,
    workspace: WorkspaceOption = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Search only this source; repeatable."),
    ] = None,
    max_pages: Annotated[
        int, typer.Option("--max-pages", help="Pages to walk per source.")
    ] = DEFAULT_MAX_PAGES,
    year_from: Annotated[
        int | None, typer.Option("--year-from", help="Earliest publication year to search.")
    ] = None,
    cutoff: Annotated[
        str | None, typer.Option("--cutoff", help="Coverage cutoff, YYYY-MM or YYYY-MM-DD.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Run a reproducible search and persist it as a SearchRun (`search_run.record`)."""
    with cli_errors():
        words = list(query or ())
        ctx = context_for(workspace)
        if _is_verb(words, RERUN_VERB):
            run, mutation = _service(ctx, source).rerun(SearchRunId(words[1]))
        else:
            if not words:
                raise ResearchHarnessError(
                    'discover needs a query: `research discover "<query>"`, or '
                    "`research discover rerun <SR####>` to re-execute a recorded run"
                )
            text = " ".join(words)
            run, mutation = _service(ctx, source).run_search(
                text,
                SearchQuery(text=text, year_from=year_from),
                sources=source or None,
                max_pages=max_pages,
                cutoff=cutoff,
            )
        emit(_run_payload(run, mutation), _run_lines(run), as_json=as_json)


def snowball(
    seed: Annotated[str, typer.Argument(help="Seed: a Work id (W####), `doi:...`, `arxiv:...`.")],
    workspace: WorkspaceOption = None,
    depth: Annotated[
        int, typer.Option("--depth", help=f"Levels to walk (1-{MAX_SNOWBALL_DEPTH}).")
    ] = 1,
    direction: Annotated[
        str, typer.Option("--direction", help="backward, forward, or both.")
    ] = "both",
    source: Annotated[
        list[str] | None, typer.Option("--source", help="Walk only this source; repeatable.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Snowball from one seed and persist the walk as a SearchRun."""
    with cli_errors():
        if direction not in _DIRECTIONS:
            raise ResearchHarnessError(
                f"unknown snowball direction {direction!r}; use {', '.join(_DIRECTIONS)}"
            )
        ctx = context_for(workspace)
        plan = SnowballPlan(
            seeds=(seed,),
            direction=direction,
            depth=depth,
            sources=tuple(source or ()),
        )
        run, mutation = _service(ctx, source).snowball(seed, plan)
        emit(_run_payload(run, mutation), _run_lines(run), as_json=as_json)


# -- screening ---------------------------------------------------------------


def screen(
    run: Annotated[
        list[str] | None,
        typer.Argument(metavar="SR KEY", help="Run and candidate key, or `list <SR####>`."),
    ] = None,
    workspace: WorkspaceOption = None,
    include: Annotated[bool, typer.Option("--include", help="Include the candidate.")] = False,
    exclude: Annotated[
        str | None, typer.Option("--exclude", help="Exclude it, persisting this reason.")
    ] = None,
    screened: Annotated[
        bool, typer.Option("--screened", help="Mark it screened, decision still open.")
    ] = False,
    reason: Annotated[
        str | None,
        typer.Option(
            "--reason",
            help="Why: recorded for an inclusion or a screened decision too, not only "
            "for --exclude.",
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Record a screening decision, or list a run's candidates (`research screen list <SR>`).

    Every decision may carry `--reason`, not just an exclusion: PRISMA provenance needs the
    inclusion half too, and it is the decision a reviewer is most often asked to defend.
    """
    with cli_errors():
        words = list(run or ())
        ctx = context_for(workspace)
        if _is_verb(words, LIST_VERB):
            record = ctx.repo.get_search_run(SearchRunId(words[1]))
            emit(_screen_list_payload(record), _screen_list_lines(record), as_json=as_json)
            return
        if len(words) != 2:
            raise ResearchHarnessError(
                "screen needs a run and a candidate key: `research screen <SR####> <key> "
                '--include|--exclude "reason"|--screened`, or `research screen list <SR####>`'
            )
        state, decision_reason = _screening_choice(
            include=include, exclude=exclude, screened=screened, reason=reason
        )
        record, mutation = screen_candidate(ctx, words[0], words[1], state, reason=decision_reason)
        entry = record.candidate(words[1])
        payload = {
            "run": str(record.id),
            "key": words[1],
            "screening": state.value,
            "reason": decision_reason,
            "matched_work": None if entry is None else _text(entry.matched_work),
            "counts": screening_summary(record),
            "mutation": mutation.as_dict(),
        }
        emit(payload, _screen_lines(record, words[1]), as_json=as_json)


def acquire(
    run: Annotated[str, typer.Argument(help="Run holding the candidate (SR####).")],
    key: Annotated[str, typer.Argument(help="Candidate key to acquire.")],
    pdf: Annotated[Path, typer.Argument(help="Local source file to ingest.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Ingest an included candidate's source file and link the Work it became."""
    with cli_errors():
        ctx = context_for(workspace)
        record, ingested, mutation = acquire_candidate(ctx, run, key, pdf)
        payload = {
            "run": str(record.id),
            "key": key,
            "work": str(ingested.work),
            "version": str(ingested.version),
            "artifact": str(ingested.artifact),
            "created": ingested.created,
            "resolution": ingested.resolution.outcome.value,
            "counts": screening_summary(record),
            "mutation": mutation.as_dict(),
        }
        emit(payload, _acquire_lines(record, key, ingested), as_json=as_json)


# -- coverage ----------------------------------------------------------------


def coverage(
    claim: Annotated[str, typer.Argument(help="Claim to audit (C####).")],
    universe: Annotated[
        str, typer.Option("--universe", help="What the coverage is measured against.")
    ],
    cutoff: Annotated[str, typer.Option("--cutoff", help="Publication cutoff, YYYY-MM.")],
    workspace: WorkspaceOption = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", help="Source the universe declares; repeatable."),
    ] = None,
    matrix_cell_empty: Annotated[
        bool,
        typer.Option("--matrix-cell-empty", help="An empty synthesis cell prompted this claim."),
    ] = False,
    models_agree: Annotated[
        bool, typer.Option("--models-agree", help="Models agreed the property is absent.")
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the funnel without recording it on the Claim."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Audit a claim's search coverage, record it, and say what wording it permits.

    The funnel this computes is written onto the Claim through `claim.update_coverage`,
    which is where `research claim audit` reads it: two commands computing the same
    quantity and disagreeing is what capped every literature-wide claim at L1 (dogfood F2).
    `--dry-run` prints the funnel and records nothing.
    """
    with cli_errors():
        ctx = context_for(workspace)
        claim_id = ClaimId(claim)
        record = ctx.repo.get_claim(claim_id)
        works = {work.id: work for work in ctx.repo.list_works()}
        report = audit_absence_claim(
            record,
            _runs_for(ctx, record),
            CoverageUniverse(definition=universe, cutoff=cutoff, sources=tuple(source or ())),
            works,
            _evidence_for(ctx, works),
            matrix_cell_empty=matrix_cell_empty,
            models_agree=models_agree,
        )
        payload = _audit_payload(report)
        lines = _audit_lines(report)
        if dry_run:
            payload["recorded"] = False
            lines.append("  recorded           no (--dry-run)")
        else:
            _, mutation = ClaimService(ctx).record_coverage(claim_id, report.coverage.coverage)
            payload["recorded"] = True
            payload["mutation"] = mutation.as_dict()
            lines.append(f"  recorded           on {claim_id} ({mutation.event.event.value})")
        emit(payload, lines, as_json=as_json)


# -- shared ------------------------------------------------------------------


def _service(ctx: CapabilityContext, sources: Sequence[str] | None) -> DiscoveryService:
    return DiscoveryService(ctx, build_registry(sources, policy=load_policy(ctx.repo)))


def _is_verb(words: Sequence[str], verb: str) -> bool:
    """True when the positional words are exactly ``<verb> <argument>``."""
    return len(words) == 2 and words[0] == verb


def _screening_choice(
    *, include: bool, exclude: str | None, screened: bool, reason: str | None = None
) -> tuple[ScreeningState, str | None]:
    """Exactly one screening decision per invocation, with the reason it may carry.

    An exclusion still states its reason inline (`--exclude "..."`); `--reason` records one
    for any decision, so an inclusion can be defended from the record too (dogfood F9).
    """
    chosen = [flag for flag in (include, exclude is not None, screened) if flag]
    if len(chosen) != 1:
        raise ResearchHarnessError(
            'screen needs exactly one of --include, --exclude "reason", or --screened'
        )
    if exclude is not None and reason is not None:
        raise ResearchHarnessError(
            "--exclude already carries the reason; do not also pass --reason"
        )
    if include:
        return ScreeningState.INCLUDED, reason
    if screened:
        return ScreeningState.SCREENED, reason
    return ScreeningState.EXCLUDED, exclude


def _runs_for(ctx: CapabilityContext, claim: Claim) -> tuple[SearchRun, ...]:
    """The runs behind a claim: the ones its coverage names, else every recorded run.

    A rerun of a named run counts as named too. Coverage is recorded on the claim now, and
    a recorded set that excluded later reruns would freeze the funnel at the moment it was
    first written: the rerun that finishes a source that failed is the same search finished,
    not a different one, which is exactly what `discovery.effective_runs` already knows.
    """
    runs = ctx.repo.list_search_runs()
    linked = set(claim.coverage.search_runs)
    if not linked:
        return tuple(runs)
    return tuple(run for run in runs if run.id in _with_reruns(runs, linked))


def _with_reruns(runs: Sequence[SearchRun], linked: set[SearchRunId]) -> set[SearchRunId]:
    """``linked`` plus every run that reproduces one of them, transitively."""
    selected = set(linked)
    changed = True
    while changed:
        changed = False
        for run in runs:
            if run.reproduces in selected and run.id not in selected:
                selected.add(run.id)
                changed = True
    return selected


def _evidence_for(
    ctx: CapabilityContext, works: Mapping[WorkId, Work]
) -> dict[EvidenceId, Evidence]:
    return {item.id: item for work in works for item in ctx.repo.iter_evidence(work)}


def _text(value: object) -> str | None:
    return None if value is None else str(value)


# -- payloads ----------------------------------------------------------------


def _run_payload(run: SearchRun, mutation: Any) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "question": run.question,
        "sources": list(run.sources),
        "queries": list(run.queries),
        "filters": dict(run.filters),
        "cutoff": None if run.cutoff is None else run.cutoff.isoformat(),
        "reproduces": _text(run.reproduces),
        "results": run.results.model_dump(mode="json"),
        "cursors": [cursor.model_dump(mode="json") for cursor in run.cursors],
        "failures": [failure.model_dump(mode="json") for failure in run.failures],
        "unresolved_keys": list(run.unresolved_keys),
        "full_text_unavailable_keys": list(run.full_text_unavailable_keys),
        "candidates": [_candidate_payload(run, entry.key) for entry in run.candidates],
        "mutation": mutation.as_dict(),
    }


def _candidate_payload(run: SearchRun, key: str) -> dict[str, Any]:
    entry = run.candidate(key)
    if entry is None:  # pragma: no cover - the key comes from the run itself
        raise ResearchHarnessError(f"{run.id} has no candidate {key!r}")
    title = entry.candidate.metadata.title
    return {
        "key": entry.key,
        "title": None if title is None else title.value,
        "sources": list(entry.sources),
        "ranks": dict(entry.ranks),
        "screening": entry.screening.value,
        "exclusion_reason": entry.exclusion_reason,
        "screening_reason": entry.screening_reason,
        "identity": None if entry.identity is None else entry.identity.value,
        "matched_work": _text(entry.matched_work),
        "full_text_available": entry.full_text_available,
    }


def _run_lines(run: SearchRun) -> list[str]:
    counts = run.results
    lines = [
        f"{run.id}  {counts.discovered} candidate(s) from {len(run.sources)} source(s): "
        f"discovered {counts.discovered}, screened {counts.screened}, included {counts.included}",
        f"  question           {run.question}",
        f"  queries            {', '.join(run.queries)}",
    ]
    if run.cutoff is not None:
        lines.append(f"  cutoff             {run.cutoff.isoformat()}")
    if run.reproduces is not None:
        lines.append(f"  reproduces         {run.reproduces}")
    lines += [
        f"  cursor {cursor.source:<16} {cursor.pages_fetched} page(s), "
        f"{'exhausted' if cursor.exhausted else 'stopped early'}"
        for cursor in run.cursors
    ]
    lines += [
        f"  failure {failure.source:<15} {failure.reason}"
        f"{' (partial)' if failure.incomplete else ''}"
        for failure in run.failures
    ]
    lines.append(f"  unresolved         {len(run.unresolved_keys)}")
    lines.append(f"  no full text       {len(run.full_text_unavailable_keys)}")
    lines += [_candidate_line(run, entry.key) for entry in run.candidates]
    return lines


def _candidate_line(run: SearchRun, key: str) -> str:
    payload = _candidate_payload(run, key)
    reported = ", ".join(
        f"{source}#{payload['ranks'].get(source, '-')}" for source in payload["sources"]
    )
    return (
        f"    {payload['key']}  [{reported}]  {payload['screening']}  "
        f"{payload['identity'] or 'unresolved'}  {payload['title'] or '-'}"
    )


def _screen_list_payload(run: SearchRun) -> dict[str, Any]:
    return {
        "run": str(run.id),
        "counts": screening_summary(run),
        "candidates": [_candidate_payload(run, entry.key) for entry in run.candidates],
    }


def _screen_list_lines(run: SearchRun) -> list[str]:
    counts = screening_summary(run)
    summary = ", ".join(f"{state} {count}" for state, count in counts.items())
    lines = [f"{run.id}  {len(run.candidates)} candidate(s): {summary}"]
    for entry in run.candidates:
        lines.append(_candidate_line(run, entry.key))
        if entry.reason:
            verb = "excluded" if entry.exclusion_reason else entry.screening.value
            lines.append(f"      {verb} because: {entry.reason}")
    return lines


def _screen_lines(run: SearchRun, key: str) -> list[str]:
    entry = run.candidate(key)
    if entry is None:  # pragma: no cover - just written
        raise ResearchHarnessError(f"{run.id} has no candidate {key!r}")
    lines = [f"{run.id}  {key}: {entry.screening.value}"]
    if entry.reason:
        lines.append(f"  reason             {entry.reason}")
    if entry.matched_work is not None:
        lines.append(f"  work               {entry.matched_work}")
    elif entry.included:
        lines.append("  work               none yet; included pending source acquisition")
    lines.append(
        f"  counts             discovered {run.results.discovered}, "
        f"screened {run.results.screened}, included {run.results.included}"
    )
    return lines


def _acquire_lines(run: SearchRun, key: str, ingested: IngestResult) -> list[str]:
    return [
        f"{run.id}  {key}: acquired as {ingested.work}",
        f"  version/artifact   {ingested.version} / {ingested.artifact}",
        f"  identity           {ingested.resolution.outcome.value}",
        f"  created            {ingested.created}",
    ]


def _audit_payload(report: AbsenceAuditReport) -> dict[str, Any]:
    ledger = report.coverage.ledger
    return {
        "claim": str(report.claim),
        "permitted": report.permitted,
        "wording": report.wording,
        "overturn_risk": report.overturn_risk.value,
        "allowed_scope": report.allowed_scope.value,
        "unresolved": list(report.unresolved),
        "incomplete_runs": [str(run_id) for run_id in report.incomplete_runs],
        "reasons": list(report.reasons),
        "notes": list(report.coverage.notes),
        "universe": report.coverage.universe.model_dump(mode="json"),
        "coverage": report.coverage.coverage.model_dump(mode="json"),
        "funnel": {
            "discovered": len(ledger.discovered),
            "screened": len(ledger.screened),
            "relevant": len(ledger.relevant),
            "full_text_available": len(ledger.full_text_available),
            "examined": len(ledger.examined),
            "unresolved": len(ledger.unresolved),
        },
    }


def _audit_lines(report: AbsenceAuditReport) -> list[str]:
    payload = _audit_payload(report)
    funnel = payload["funnel"]
    lines = [
        f"{report.claim}  absence audit: {'permitted' if report.permitted else 'NOT permitted'}",
        f"  universe           {report.coverage.universe.definition}",
        f"  cutoff             {report.coverage.universe.cutoff}",
        f"  overturn risk      {report.overturn_risk.value}",
        f"  allowed scope      {report.allowed_scope.label}",
        "  funnel             "
        + " -> ".join(
            f"{name} {funnel[name]}"
            for name in ("discovered", "screened", "relevant", "full_text_available", "examined")
        ),
        f"  unresolved         {len(report.unresolved)}",
    ]
    lines += [f"    unresolved       {key}" for key in report.unresolved]
    lines += [f"  incomplete run     {run_id}" for run_id in report.incomplete_runs]
    lines.append(f"  wording            {report.wording or '(refused)'}")
    lines += [f"  reason             {reason}" for reason in report.reasons]
    lines += [f"  note               {note}" for note in report.coverage.notes]
    return lines
