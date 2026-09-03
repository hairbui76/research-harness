"""External discovery: reproducible search runs, screening, and the absence audit.

Discovery space and the research corpus are different things (Product 14), and this package
owns the boundary between them:

* :mod:`~research_harness.discovery.search_runs` executes a query across sources, pages
  each one, deduplicates work-level while keeping every source and rank, resolves identity
  against the corpus, and persists the whole operation as a `SearchRun`.
* :mod:`~research_harness.discovery.screening` moves a candidate through
  `discovered -> screened -> included/excluded`, persists exclusion reasons, and acquires a
  source file when an included candidate is finally read into the corpus.
* :mod:`~research_harness.discovery.absence` reads coverage off those runs and refuses the
  absence wordings the record cannot support.
* `DiscoveryService.enrichments` and :func:`apply_enrichments` read back the metadata a
  hit carried for a `Work` the corpus already holds, so a source's better title, authors,
  year or venue is neither applied silently nor lost silently (dogfood F5).

Nothing here writes canonical state directly: every mutation goes through
`capabilities.record_search_run` or `corpus.ingest` (ADR-004).

    service = DiscoveryService(ctx, build_search_registry())
    run, mutation = service.run_search("adversarial traffic", SearchQuery(text="..."))
    run, mutation = screen(ctx, run.id, run.candidates[0].key, ScreeningState.INCLUDED)
"""

from __future__ import annotations

from research_harness.discovery.absence import (
    BASELINE_AXES,
    NO_EVIDENCE,
    NO_WORK_EXISTS_REFUSAL,
    AbsenceAuditReport,
    BaselineAxis,
    BaselineRecommendation,
    audit_absence_claim,
    baseline_comparison,
    coverage_for,
    effective_runs,
    examined_works,
    latest_candidates,
    ledger_for,
    superseded_runs,
)
from research_harness.discovery.screening import acquire, screen, screening_summary
from research_harness.discovery.search_runs import (
    DEFAULT_MAX_PAGES,
    ENRICHABLE_FIELDS,
    METADATA_UPDATE_CAPABILITY,
    SNOWBALL_QUERY_PREFIX,
    DiscoveryService,
    EnrichmentPlan,
    MetadataConflict,
    MetadataEnrichment,
    apply_enrichments,
    enrichment_for,
    enrichments_for,
    next_search_run_id,
)

__all__ = [
    "BASELINE_AXES",
    "DEFAULT_MAX_PAGES",
    "ENRICHABLE_FIELDS",
    "METADATA_UPDATE_CAPABILITY",
    "NO_EVIDENCE",
    "NO_WORK_EXISTS_REFUSAL",
    "SNOWBALL_QUERY_PREFIX",
    "AbsenceAuditReport",
    "BaselineAxis",
    "BaselineRecommendation",
    "DiscoveryService",
    "EnrichmentPlan",
    "MetadataConflict",
    "MetadataEnrichment",
    "acquire",
    "apply_enrichments",
    "audit_absence_claim",
    "baseline_comparison",
    "coverage_for",
    "effective_runs",
    "enrichment_for",
    "enrichments_for",
    "examined_works",
    "latest_candidates",
    "ledger_for",
    "next_search_run_id",
    "screen",
    "screening_summary",
    "superseded_runs",
]
