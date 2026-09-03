"""Cross-paper synthesis: taxonomies, matrices, comparisons, and model proposals.

A synthesis matrix is derived state (Product 7.1, 37): it is a function of an accepted
taxonomy Decision and the accepted Evidence behind each cell, so when either moves the
matrix becomes stale rather than being quietly rebuilt (ADR-008). Cells are multi-label,
and an empty cell means "not recorded", never "the work lacks the property".

    from research_harness.synthesis import ClassificationRule, SynthesisService

    service = SynthesisService(ctx)
    service.revise_taxonomy("representation", ["raw_sequential", "field_based"], "v1 scheme")
    matrix, _ = service.build("representation", "representation", rules)
    table = service.compare("representation")
"""

from __future__ import annotations

from research_harness.synthesis.matrix import (
    CellChange,
    ClassificationRule,
    ComparisonRow,
    ComparisonTable,
    MatrixDiff,
    MatrixProposal,
    ProposedCell,
    RejectedProposal,
    apply_proposals,
    build_matrix,
    classification_text,
    compare_field,
    matrix_diff,
    matrix_name_for,
)
from research_harness.synthesis.service import (
    STAGING_SYNTHESIS_DIRNAME,
    SynthesisService,
    TaxonomyRevision,
    next_decision_id,
    next_matrix_id,
)

__all__ = [
    "STAGING_SYNTHESIS_DIRNAME",
    "CellChange",
    "ClassificationRule",
    "ComparisonRow",
    "ComparisonTable",
    "MatrixDiff",
    "MatrixProposal",
    "ProposedCell",
    "RejectedProposal",
    "SynthesisService",
    "TaxonomyRevision",
    "apply_proposals",
    "build_matrix",
    "classification_text",
    "compare_field",
    "matrix_diff",
    "matrix_name_for",
    "next_decision_id",
    "next_matrix_id",
]
