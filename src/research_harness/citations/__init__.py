"""Citation graph, snowballing, and independent-support accounting (Product 15.1, 17).

The graph is adjacency plus provenance: `cites` edges read deterministically off
reference metadata, the fetched lists behind them, and the same-work merges that keep one
paper from appearing as several. Snowballing walks it outwards from seeds and returns
discovery candidates, never corpus state. Independence accounting reads it in the other
direction, asking how many of the sources behind a claim are actually independent.

Nothing in this package writes canonical state, and nothing here promotes a discovery
result past screening state `discovered` (Product 14, ADR-003, ADR-006).
"""

from __future__ import annotations

from research_harness.citations.graph import (
    ARTIFACT_REFERENCES,
    SAME_WORK_OUTCOMES,
    CitationEdge,
    CitationGraph,
    EdgeKey,
    FetchDirection,
    NodeKey,
    NodeResolution,
    ReferenceList,
    SemanticRelation,
    SemanticRelationKind,
    candidate_key,
    node_key_for,
    resolve_nodes,
    resolve_same_work,
)
from research_harness.citations.independence import (
    AUTHOR_OVERLAP_THRESHOLD,
    DependentGroup,
    DependentGroupKind,
    IndependenceReport,
    double_counting_risks,
    independent_support,
)
from research_harness.citations.snowball import (
    DEFAULT_MAX_PER_LEVEL,
    MAX_SNOWBALL_DEPTH,
    SnowballDirection,
    SnowballPlan,
    SnowballResult,
    run_snowball,
)

__all__ = [
    "ARTIFACT_REFERENCES",
    "AUTHOR_OVERLAP_THRESHOLD",
    "DEFAULT_MAX_PER_LEVEL",
    "MAX_SNOWBALL_DEPTH",
    "SAME_WORK_OUTCOMES",
    "CitationEdge",
    "CitationGraph",
    "DependentGroup",
    "DependentGroupKind",
    "EdgeKey",
    "FetchDirection",
    "IndependenceReport",
    "NodeKey",
    "NodeResolution",
    "ReferenceList",
    "SemanticRelation",
    "SemanticRelationKind",
    "SnowballDirection",
    "SnowballPlan",
    "SnowballResult",
    "candidate_key",
    "double_counting_risks",
    "independent_support",
    "node_key_for",
    "resolve_nodes",
    "resolve_same_work",
    "run_snowball",
]
