"""Personal-scale corpus and warm-latency benchmark for the ResearchGraph index.

:mod:`benchmarks.graph.generate_graph_corpus` builds the agreed shape — a canonical corpus
plus a conversation history, so the graph has every namespace it projects — and
:mod:`benchmarks.graph.run_graph_benchmarks` times the query modes graph spec §9 budgets
against it.

Neither ships with the package. The measurement itself lives in
`research_harness.graph.bench`, because `tests/perf/test_graph_budgets.py` and the Phase 20
gate test run the same workload against much smaller corpora.

Shape and results: `docs/plans/performance-budgets.md`, "The ResearchGraph index".
"""

from __future__ import annotations
