# ADR-015: One transaction, one event, and ids allocated server-side under the lock

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §7.2, §8.2, §19.3, §36, §42 (B, K); ROADMAP.md Task 1.4, Task 1.5, Task 10.2, Task 10.4, Task 17.2; `docs/architecture/domain-changelog.md` entry 16; implemented in `workspace/repository.py`, `workspace/journal.py`, `workspace/locking.py`, `capabilities/handlers.py`

## Context

ADR-001 makes an accepted-state mutation one journalled unit, leaving two questions a
transaction abstraction can get wrong in opposite directions. If a transaction may carry
several events, "one mutation, one semantic record" stops being checkable and a partial
recovery can land some events without their siblings. And if a client may choose the id of
the object it creates — the natural shape for a host posting a whole object — two callers
racing produce `C0007` twice.

## Decision

**A transaction carries exactly one event.** `WorkspaceTransaction` holds a single `_event`
set at construction, there is no method to add a second, and `MutationResult.event` is one
event rather than a tuple. The event is appended as an intent inside the same journal
transaction as the canonical files it describes, so "mutation and event both persist or
both fail" holds by construction rather than by a runtime check. Committing a transaction
whose journal is empty is refused, as is committing twice.

**Ids are allocated by the server, under the workspace lock.** An event names its subjects
and must exist before the transaction opens, so allocation is two-phase: `_peek_id` reads
the next id under the lock, and `_confirm_id` allocates it inside the transaction and
refuses if the two disagree. `allocate_id` takes the counter in `research.yaml` but
cross-checks it against ids already on disk, so a hand-created object can never be handed
out twice. A client that must name an id first sends a provisional one — `E0000`, `C0000`,
`D0000` — which the handler replaces; real allocation starts at 1, so they never collide.

## Consequences

### Positive

- Recovery has one question per unit, which is what makes "all six files or none, with the
  event agreeing" expressible at all.
- Two hosts writing concurrently cannot mint the same id, and deleting `.research/` cannot
  renumber accepted evidence.

### Negative / costs

- A mutation recording two distinct facts must be two transactions, which is why accepting
  Evidence and creating a Claim are separate units.
- `allocate_id` scans the flat collection directory per allocation — O(n) per id, a known
  scaling cost (ADR-023) — and peek-then-confirm asks the caller to retry on a lost race.

## Invariants this ADR protects

- Interrupting a multi-file canonical mutation leaves either the complete prior state or
  the complete new state with its matching event — §42 K, at every journal phase.
- No id is duplicated or skipped across an interruption, and the journal directory is empty
  after recovery.
- An event never persists without its canonical mutation, and no mutation without its event.
- Ids are assigned server-side; a transport never chooses one (§36, Task 10.2), and a
  provisional id is number zero and is never allocated.
- Workspace mutations are serialized: the lock is held for staging as well as commit.

## Rejected alternatives

- **Let a transaction batch several events.** Recovery would have to reason about partial
  event sets, and "one mutation, one semantic record" would stop being checkable.
- **Client-supplied ids.** Two hosts racing produce the same id, and §42 B's "exactly one
  canonical Claim" becomes unenforceable.
- **A counter with no on-disk cross-check.** A hand-created object, or a counter lost to a
  partial restore, would hand out an id twice.
- **Hold the lock only across the commit.** Allocation and artifact-immutability checks
  read the corpus while staging; that window is exactly the race being removed.

## Where it is enforced

- `src/research_harness/workspace/repository.py`: `WorkspaceTransaction` (single `_event`,
  `commit`, `allocate_id`), `WorkspaceRepository.transaction`, `lock`.
- `workspace/journal.py` (phase ordering, double-commit refusal) and `workspace/locking.py`.
- `capabilities/handlers.py`: `_peek_id`, `_confirm_id`, `next_evidence_id`, `_flat_ids`,
  `PROVISIONAL_EVIDENCE_ID`; `capabilities/dto.py` holds the other provisional ids.
- Tests: `tests/contract/capabilities/test_server_side_ids.py`, `tests/e2e/crash/`,
  `tests/integration/workspace/test_transaction_recovery.py` and `test_locking.py`,
  `tests/e2e/invariants/test_k_atomic_mutation.py`.
