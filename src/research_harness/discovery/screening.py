"""Moving a discovered candidate through screening, and acquiring its source (Product 14).

The discovery space and the research corpus are different things, and this module is the
only bridge between them::

    discovery result -> candidate work -> screening -> source acquisition
                     -> identity verification -> included corpus

Two rules do the work. **Including a candidate creates nothing.** `include` records a
decision on the run; a `Work` appears only when :func:`acquire` ingests an actual file,
because a corpus entry that no artifact backs cannot carry evidence (ADR-002, ADR-003).
**Excluding a candidate persists its reason**, so the funnel behind a coverage claim can
be read back rather than reconstructed from memory (Product 14, 18).

Every change is persisted by re-recording the run through `search_run.record`, which is an
update-or-create: it diffs against the stored run and writes the new one in one journalled
transaction. Screening therefore never edits canonical state behind the capability layer.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import MutationResult, RecordSearchRunRequest
from research_harness.capabilities.handlers import record_search_run
from research_harness.domain.enums import IdentityResolutionOutcome, ScreeningState
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import SearchRunId, WorkId
from research_harness.domain.research import (
    IDENTIFIED_WORK_OUTCOMES,
    SearchCandidate,
    SearchResultCounts,
    SearchRun,
)
from research_harness.ingest.service import IngestResult, IngestService

__all__ = ["acquire", "screen", "screening_summary"]

logger = logging.getLogger(__name__)


def screen(
    ctx: CapabilityContext,
    run_id: SearchRunId | str,
    key: str,
    state: ScreeningState,
    *,
    reason: str | None = None,
) -> tuple[SearchRun, MutationResult]:
    """Record a screening decision for one candidate of ``run_id``.

    Excluding requires a reason and persists it; every other decision *may* carry one, and
    an inclusion reason is the half PRISMA provenance was missing (dogfood F9). The reason
    is stored on `SearchCandidate.screening_reason` whatever the decision, and an exclusion
    writes it into `exclusion_reason` as well so older readers keep working.

    Including a candidate that identity resolution already matched to a corpus Work keeps
    that link; including a candidate that resolved to a *distinct* work records the decision
    and nothing else -- the work is `included` pending source acquisition, and
    :func:`acquire` is what turns it into corpus state. An unresolved candidate can be
    included too, but it stays counted as unresolved in coverage until its identity is
    settled.
    """
    run = ctx.repo.get_search_run(SearchRunId(str(run_id)))
    entry = run.candidate(key)
    if entry is None:
        raise CapabilityError(
            f"discovery.screen: {run.id} recorded no candidate {key!r}; "
            f"it has {len(run.candidates)} candidate(s)"
        )
    if state is ScreeningState.EXCLUDED and not (reason and reason.strip()):
        raise CapabilityError(
            "discovery.screen: excluding a candidate requires a reason, and the reason is "
            "persisted (Product 14)"
        )
    if state is ScreeningState.DISCOVERED and reason:
        raise CapabilityError(
            "discovery.screen: 'discovered' is the state before a decision, so it records "
            "no reason; screen the candidate to keep one"
        )
    recorded = reason.strip() if reason and reason.strip() else None
    screened = entry.touch(
        screening=state,
        screening_reason=recorded,
        exclusion_reason=recorded if state is ScreeningState.EXCLUDED else None,
        screened_by=ctx.actor,
        screened_at=ctx.now(),
    )
    if state is ScreeningState.INCLUDED and not _identified(screened):
        logger.info(
            "%s: candidate %s is included pending source acquisition; inclusion alone "
            "creates no Work",
            run.id,
            key,
        )
    logger.info("%s: candidate %s screened %s by %s", run.id, key, state.value, ctx.actor)
    return _persist(ctx, run, _replace(run.candidates, screened))


def acquire(
    ctx: CapabilityContext,
    run_id: SearchRunId | str,
    key: str,
    pdf_path: Path | str,
) -> tuple[SearchRun, IngestResult, MutationResult]:
    """Ingest a candidate's source file and link the resulting Work back to the run.

    This is the only step that turns a discovery result into corpus state, and it goes
    through `corpus.ingest`, so the file is hashed, its identity resolved, and its Work,
    Version, and Artifact registered exactly as any other ingest. A candidate that already
    matched an existing Work re-uses it; a genuinely new one becomes a new Work. Either way
    the candidate ends `included` with `matched_work` naming what it became.
    """
    run = ctx.repo.get_search_run(SearchRunId(str(run_id)))
    entry = run.candidate(key)
    if entry is None:
        raise CapabilityError(f"discovery.acquire: {run.id} recorded no candidate {key!r}")
    if entry.screening is ScreeningState.EXCLUDED:
        raise CapabilityError(
            f"discovery.acquire: candidate {key!r} was excluded ({entry.reason}); "
            "re-screen it before acquiring its source"
        )
    ingested = IngestService(ctx).ingest_local_pdf(Path(pdf_path))
    acquired = entry.touch(
        screening=ScreeningState.INCLUDED,
        exclusion_reason=None,
        screening_reason=entry.screening_reason,
        screened_by=ctx.actor,
        screened_at=ctx.now(),
        identity=ingested.resolution.outcome,
        matched_work=ingested.work,
        full_text_available=True,
    )
    logger.info("%s: candidate %s acquired as %s", run.id, key, ingested.work)
    run, mutation = _persist(ctx, run, _replace(run.candidates, acquired))
    return run, ingested, mutation


def screening_summary(run: SearchRun) -> dict[str, int]:
    """Candidate counts per screening state, including the states with none."""
    counts = dict.fromkeys((state.value for state in ScreeningState), 0)
    for entry in run.candidates:
        counts[entry.screening.value] += 1
    return counts


# -- internals ---------------------------------------------------------------


def _replace(
    candidates: Sequence[SearchCandidate], updated: SearchCandidate
) -> tuple[SearchCandidate, ...]:
    """The candidate list with ``updated`` in place, order untouched.

    Order is discovery order and stays that way: it is the order the sources ranked the
    work in, and re-sorting it on screening would lose that.
    """
    return tuple(updated if entry.key == updated.key else entry for entry in candidates)


def _persist(
    ctx: CapabilityContext, run: SearchRun, candidates: tuple[SearchCandidate, ...]
) -> tuple[SearchRun, MutationResult]:
    """Re-record the run with new candidates, keeping every derived field in step.

    Work-level deduplication never merges Version or Artifact records: two candidates that
    resolve to the same Work stay two entries here, each with its own sources and ranks, so
    the derived lists are rebuilt from the candidates rather than edited in place.
    """
    updated = run.touch(
        updated_at=ctx.now(),
        candidates=candidates,
        results=SearchResultCounts(
            discovered=len(candidates),
            screened=sum(1 for entry in candidates if entry.screened),
            included=sum(1 for entry in candidates if entry.included),
        ),
        unresolved_identities=_unresolved(candidates),
        unresolved_keys=_unresolved(candidates),
        full_text_unavailable_keys=_without_full_text(candidates),
        unavailable_full_text=_works_without_full_text(candidates),
    )
    mutation = record_search_run(ctx, RecordSearchRunRequest(search_run=updated))
    return updated, mutation


def _unresolved(candidates: Sequence[SearchCandidate]) -> tuple[str, ...]:
    return tuple(
        entry.key for entry in candidates if entry.identity is IdentityResolutionOutcome.UNRESOLVED
    )


def _without_full_text(candidates: Sequence[SearchCandidate]) -> tuple[str, ...]:
    return tuple(entry.key for entry in candidates if entry.full_text_available is False)


def _works_without_full_text(candidates: Sequence[SearchCandidate]) -> tuple[WorkId, ...]:
    return tuple(
        sorted(
            {
                entry.matched_work
                for entry in candidates
                if entry.full_text_available is False and entry.matched_work is not None
            }
        )
    )


def _identified(entry: SearchCandidate) -> bool:
    """True when identity resolution definitely named the corpus Work this candidate is."""
    return entry.identity in IDENTIFIED_WORK_OUTCOMES and entry.matched_work is not None
