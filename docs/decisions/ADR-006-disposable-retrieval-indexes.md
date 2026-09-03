# ADR-006: Embedded retrieval indexes are disposable

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §2, §5 (P2, P7), §8.2, §15.1–§15.4, §42 C, §43, §44.11, §44.14; ROADMAP.md Global Constraints, Task 3.3, Phase 5 Tasks 5.1–5.4, Gate P5, §6 item 3, Task 17.3

## Context

A vector index accumulates project knowledge by accident: once answers come out of it,
changing the embedding model or chunk boundaries changes what the project appears to know
(PRODUCT.md §2, §43). Retrieval-first architectures worsen this by putting similarity
search where accepted research objects belong. The product needs fast local search over a
personal-scale corpus without letting an index acquire authority.

## Decision

Retrieval uses four complementary projections, all under `.research/` and all disposable:
a SQLite structured projection, an FTS5 lexical index, an embedded local vector index, and
citation-graph adjacency tables (§15.1). No accepted scientific state lives only in one.

Queries are classified and planned before retrieval (§15.2), and the planner applies the
authority ladder of §15.3: accepted Evidence and Claims, then accepted structured paper
state, then the parsed local corpus, then the citation neighborhood, then external
discovery. A retrieval chunk is an implementation artifact, not a research object (§15.4).
The embedding provider and model are recorded in index metadata, never in canonical
objects, and no external distributed search or graph infrastructure is introduced before a
demonstrated need (§15.1; ROADMAP.md Global Constraints).

## Consequences

### Positive

- Swapping embedding models or re-chunking is operational, not a scientific migration.
- Exact-terminology search keeps working with no embeddings at all (FTS5), and retrieval
  is testable offline against synthetic corpora with no service dependency.
- Ranking can prefer accepted evidence over similar-sounding prose — the behavior a
  researcher wants when auditing a claim.

### Negative / costs

- Four indexes must stay rebuildable, rebuild time grows with the corpus (a Task 17.3
  budget), and the query planner is a real component rather than "embed and search".
- Preferring accepted state can miss something a naive semantic sweep would surface; this
  is an accepted trade, not an oversight.

## Invariants this ADR protects

- Deleting `.research/` and rebuilding reproduces the same accepted state — §42 C.
- Changing the embedding model does not change Works, Evidence, Claims, Decisions, or
  manuscript provenance (§5 P7).
- Deleting the vector index changes retrieval performance only, and the embedding
  provider/model lives in index metadata, not canonical objects (Task 5.2).
- No canonical state exists only in SQLite, cache, vector index, or traces (§6, item 3).
- Accepted research objects are queried before raw-vector retrieval (§15.3, §43), and
  exact terminology search works without embeddings or services (Task 3.3).
- Retrieval responses expose source, structural location, authority, and score components
  (Task 5.4).

## Rejected alternatives

- **Vector RAG as the primary architecture.** §15 opens by rejecting it; it makes the
  index the de facto knowledge model, which §43 names as a risk.
- **Elasticsearch, a graph database, or Redis.** Excluded for a personal workstation by
  §15.1 and the Global Constraints until a need is demonstrated.
- **Persisting chunk IDs as citable research objects.** Contradicts §15.4; re-chunking
  would become a scientific event.
- **Recording the embedding model on canonical Evidence.** §42 C would fail the first time
  the embedding model changed.

## Where it is enforced

- `src/research_harness/projection/`: `fts.py`, `schema.py`, `rebuild.py`; index
  artifacts live under `.research/index/`.
- `src/research_harness/retrieval/`: `structured.py`, `lexical.py`, `semantic.py`
  (index abstraction), `planner.py` (ladder), `rerank.py`, `service.py`.
- Per `docs/architecture/conventions.md`, `projection/` is deletable and `workspace/`
  must not import it.
- Tests: `tests/integration/projection/test_fts.py`, `tests/integration/retrieval/`
  (`test_structured_lexical.py`, `test_semantic.py`), `tests/unit/retrieval/`
  (`test_planner.py`, `test_rerank.py`), `tests/e2e/test_rebuild.py`, Gate P5.
