# ADR-023: Budgets are measured and published; only behavior-preserving hotspots are fixed

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P8), §26, §41; ROADMAP.md Task 17.3, Gate P17; recorded in `docs/plans/performance-budgets.md` and `benchmarks/README.md`; implemented in `workspace/events.py` (`_CanonicalIndex`), `projection/rows.py` (`upsert_rows`), `projection/rebuild.py`, `tests/perf/`

## Context

Task 17.3 says to measure rather than prematurely optimize, and names a target corpus:
1,000 Works, 100,000 DocumentBlocks, 50,000 Evidence records, 5,000 Claims. Without numbers,
"is this fast enough for a personal workstation?" is answered by whoever last touched the
code, and every optimization becomes a plausible change to a system whose correctness rests
on digests, determinism, and rebuildability. Some obvious speedups here would change a
recorded digest, making them scientific-state decisions in a performance costume.

## Decision

Performance is measured against a generated full-scale corpus, and the numbers, the proposed
budgets, and a ranked hotspot list are published in `docs/plans/performance-budgets.md`. A
budget is what a researcher should get at that corpus size; a failing row says so with its
factor. Optimization is scheduled from that list, and **only where the fix is
behavior-preserving**. Two were taken: `_CanonicalIndex` builds the maps `verify_consistency`
needs once per verification and lazily, replacing a full corpus walk per id that made opening
a project quadratic in evidence records; and `upsert_rows` groups consecutive rows of one
`(table, columns)` shape into an `executemany` with one compiled statement per shape, while
SQLite still applies rows in order, so tables and determinism are unchanged.

Two were deliberately left. Digesting the JSON form, or caching a digest with its object,
would change every recorded digest and needs an event-log version bump (ADR-014) — a
decision, not a local optimization. Compiling `ResearchId`'s pattern once per subclass,
bucketing the Review Inbox, and narrowing the FTS index set are behavior-preserving and not
yet scheduled. `tests/perf/` re-runs the benchmark at 5 % scale with looser ceilings, skipped
unless `RESEARCH_HARNESS_PERF=1`, so slow hardware does not fail an unrelated build.

## Consequences

### Positive

- The two worst paths — project open and rebuild — were fixed against a profile rather than
  a guess, and both fixes are provably output-identical.
- A hotspot that would change a digest is visibly a PM decision with a version bump attached
  rather than a tempting one-line change.

### Negative / costs

- Several budgets are still failing — Review Inbox 18 s against 1 s, FTS p95 71 ms against
  50 ms — and the document records them as failing rather than relaxing them to match.
- Per-key YAML reads during verification are still uncached, so `open` is faster but not
  inside its budget, and the `tests/perf` ceiling still describes the old behavior.

## Invariants this ADR protects

- No optimization changes a recorded digest, an allocated id, or a rebuild's output without
  an explicit version bump (ADR-001, ADR-014).
- Batched writes produce the same tables in the same order, with the same attribution of a
  refusal to the file that caused it; the consistency index changes what is read, not what
  is checked, and `verify_consistency` still fails closed.
- Corpus generation is deterministic given a seed, so benchmarks are comparable across runs.
- A transaction never exceeds the event log's object-digest cap.

## Rejected alternatives

- **Optimize top-down without a budget.** Produces faster code and no answer to whether the
  product is usable; a budget relaxed to match the implementation measures nothing.
- **Digest the JSON form now for the easy win.** Changes every stored digest; it belongs
  behind an event-log version bump, not inside a performance pass.
- **Cache the projection across rebuilds, or run tight CI ceilings at full scale.** A
  rebuild that reuses the old database is not a rebuild (§42 C), and a 335-second rebuild
  per CI run fails on shared hardware for reasons unrelated to the change under test.

## Where it is enforced

- `docs/plans/performance-budgets.md` (budgets, measurements, ranked hotspots),
  `benchmarks/generate_corpus.py` and `benchmarks/run_benchmarks.py`.
- `src/research_harness/workspace/events.py`: `_CanonicalIndex`, `verify_consistency`, and
  `MAX_EVENT_OBJECTS`, the ceiling that bounds transaction size.
- `projection/rows.py` (`upsert_rows`, `_batched`, the statement cache) and
  `projection/rebuild.py` (`_write_records(batched=...)` and its attribution fallback).
- Tests: `tests/perf/test_budgets.py` (opt-in via `RESEARCH_HARNESS_PERF=1`),
  `tests/unit/projection/test_rows.py`, `tests/integration/projection/test_rebuild.py`.
