# ADR-013: Stale marks are projection state recomputed from canonical facts

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §19.2, §37, §42 (C, I); ROADMAP.md Task 3.2, Task 3.4, §5 (property tests), Task 17.1; implemented in `projection/dependencies.py`, `projection/rebuild.py`, `capabilities/invalidation.py`, `domain/enums.py` (`StaleState`)

## Context

ADR-008 decided that a changed upstream object marks its dependents stale rather than
rewriting them, leaving a storage question it did not answer. Writing the mark onto every
downstream canonical file makes a taxonomy revision a multi-thousand-file mutation, and
rewriting a derived object to say "you are stale" is the silent rewriting ADR-008 forbids,
one field short. Keeping marks only in SQLite makes `rm -rf .research/` an amnesty, and
§42 C says a rebuild must reproduce the same state.

## Decision

Stale marks are projection state, held in the `stale_marks` and `dependencies` tables and
never written back onto canonical objects. After a mutation,
`CapabilityContext.invalidate` builds a `DependencyGraph` from the canonical objects, walks
downstream with `mark_changed_many`, and persists the resulting `StaleSet`. Persisting is
best-effort: a missing or outdated database is not a mutation failure, because canonical
files are authoritative and `research rebuild` reconstructs the marks.

A rebuild derives the same set from two canonical sources and nothing else. First, an
object whose own `stale` field says `STALE` — the flag `domain/transitions.py` writes on
`Evidence`, `Claim`, `SynthesisMatrix`, `ManuscriptAnchor`, and their peers. Second,
`updated_at` ordering along the graph: a downstream object is stale when it is older than
something it depends on, and only when both timestamps justify it, so an object reviewed
*after* its upstream changed does not come back stale on every rebuild. `since` is the
upstream `updated_at`, not the wall clock, so two rebuilds produce identical tables. Edges
come from canonical fields — `Claim.derived_from` yields `matrix -> claim` — and marks are
ordered by impact: manuscript anchor, claim, synthesis, classification.

## Consequences

### Positive

- A hub taxonomy change marks thousands of objects without writing one canonical byte:
  2,903 marks in 6.7 ms, with the matrix file byte-identical (§42 I).
- Deleting `.research/` and rebuilding reproduces the same marks with the same `since`, so
  staleness is not an artifact of when the projection was built.

### Negative / costs

- The graph is rebuilt from all canonical objects on every mutation, so invalidation cost
  scales with the corpus rather than with the change.
- Nothing recomputes marks between mutations, and timestamp-derived staleness inherits
  clock granularity: objects written in one transaction are ordered by `updated_at` alone.

## Invariants this ADR protects

- Stale propagation never rewrites a derived object (Task 3.4, §19.2): nothing in
  `dependencies.py` takes a repository or returns a rewritten canonical object.
- Revising an accepted taxonomy marks matrix, Claim, and manuscript anchor stale, ordered
  manuscript → claim → synthesis (§42 I), and a rebuild reaches the same set (§42 C).
- Propagation terminates on cycles and is order-independent (ROADMAP.md §5), and
  `state.stale` reads recorded marks without recomputing or rewriting anything.
- A failed persist leaves canonical state correct and the projection behind, not the reverse.

## Rejected alternatives

- **Write `stale: true` onto every downstream canonical file.** Turns one revision into a
  mass canonical mutation and rewrites derived objects, which ADR-008 forbids.
- **Keep marks only in SQLite with no canonical derivation.** A rebuild would silently
  clear them, and §42 C would fail on the invariant that matters most.
- **Recompute staleness lazily at read time.** Every surface pays for the graph.
- **Emit an event per invalidation.** Invalidation reports canonical facts rather than
  adding one; an event with no canonical mutation is refused at commit (ADR-014).

## Where it is enforced

- `src/research_harness/projection/dependencies.py`: `DependencyGraph.from_objects`,
  `mark_changed`, `mark_changed_many`, `StaleSet`, `StalePriority`, `persist_stale_marks`,
  `load_stale_marks`; `projection/schema.py` (`DEPENDENCIES`, `STALE_MARKS`).
- `projection/rebuild.py`: `_recompute_stale`, `_persist_stale`, and its two reasons.
- `capabilities/invalidation.py`; `domain/transitions.py` is the only writer of the flag.
- Tests: `tests/unit/projection/test_staleness.py`,
  `tests/integration/projection/test_rebuild.py`, `tests/e2e/test_taxonomy_staleness.py`,
  `tests/e2e/invariants/test_i_stale_propagation.py` and `test_c_rebuildability.py`.
