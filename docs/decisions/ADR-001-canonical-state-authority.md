# ADR-001: Git-readable canonical state vs SQLite projection authority

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P1, P2), §8.1, §8.2, §19.3, §42 (C, K), §44.5, §44.21; ROADMAP.md Global Constraints, Phase 1 Tasks 1.4–1.5, Phase 3 Tasks 3.1–3.2, Gate P3, Task 17.2

## Context

Scientific conclusions must stay inspectable months later, diffable, and independent of
any database schema (PRODUCT.md §5 P1). Daily operation needs joins, full-text search,
and graph queries over tens of thousands of objects (ROADMAP.md Task 17.3 budgets),
which files alone cannot serve at interactive latency. One store cannot do both: if
SQLite holds the record, scientific history is opaque to Git and a schema migration
becomes a scientific risk; if files are the only store, every query is a scan.

## Decision

Canonical scientific state is human-readable files under the workspace root — YAML for
single objects, JSON Lines for append-heavy collections, Markdown/LaTeX for manuscript
text (PRODUCT.md §8.1). These files carry scientific authority. Everything under
`.research/` — `research.db`, `index/`, `cache/`, `staging/`, `traces/` — is a regenerable
projection with no authority (§8.2).

The semantic event log (`events/research.jsonl`) is Git-visible but is an audit
companion, not a second authority and not the log from which accepted state must be
replayed (§19.3, §44.21). Accepted-state mutation is one logical unit: validate the
canonical change, its
semantic event, and its dependency invalidation set under the workspace lock, then
commit through a durable transaction journal (§8.2). Recovery either finishes the unit
or restores the prior canonical state.

## Consequences

### Positive

- Git supplies history, diff, blame, and branching for scientific state at no extra cost,
  and `research rebuild` is a supported path rather than a disaster procedure.
- Index format, embedding model, and SQLite schema can change without touching
  conclusions; a research change is reviewable as a text diff.

### Negative / costs

- Every accepted-state write pays for atomic replace, fsync, a workspace lock, and a
  journal record, and two representations must stay consistent.
- Serialization must be deterministic (`docs/architecture/conventions.md`) or diffs
  become noise, and event/canonical disagreement fails closed.

## Invariants this ADR protects

- Deleting `.research/` and rebuilding reproduces the same accepted Works, Evidence,
  Claims, Decisions, and manuscript links — §42 C.
- Interrupting a multi-file canonical mutation leaves either the complete prior state or
  the complete new state with its matching event and invalidation set — §42 K.
- SQLite rows never become the only copy of scientific state (Task 3.1).
- Projection object IDs equal canonical IDs; rebuild changes neither content nor IDs (Task 3.2).
- Rebuilding projections never requires replaying the full historical event log (§19.3).
- An event without its matching canonical mutation is not a valid workspace state.

## Rejected alternatives

- **SQLite as system of record, files exported on demand.** Fast, but the record becomes
  opaque to Git and to manual repair, and a migration bug becomes a scientific bug.
- **Event sourcing as the sole authority.** Rebuild would depend on replaying every
  historical event, which §19.3 forbids, and log corruption would be unrecoverable.
- **Document or vector database as canonical storage.** Excluded by §4 and §5 P7.
- **Best-effort writes without a journal.** A crash mid-mutation would leave a half-accepted
  state indistinguishable from an intended one; rejected by §42 K.

## Where it is enforced

- `src/research_harness/workspace/`: `layout.py`, `serialization.py`, `repository.py`,
  `locking.py`, `journal.py`, `events.py`, `migrations.py` — the only writers of canonical
  files, all through atomic replace.
- `src/research_harness/projection/`: `schema.py`, `rebuild.py` — deletable by
  definition. Per `docs/architecture/conventions.md`, `workspace/` must not import
  `projection/`, `providers/`, `cli/`, or `server/`.
- Tests: `tests/integration/workspace/test_repository.py` and
  `test_transaction_recovery.py`, `tests/unit/workspace/test_events.py`,
  `tests/integration/projection/test_schema.py`, `tests/e2e/test_rebuild.py`, and the
  crash/atomicity suite of Task 17.2.
