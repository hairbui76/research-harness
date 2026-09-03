# ADR-008: Staleness instead of silent derived-state rewriting

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §16, §19.2, §24.2, §25, §30.3, §37, §41.7, §42 (D, I, J), §43, §44.19; ROADMAP.md Global Constraints, Task 2.4, Task 3.4, Task 7.5, Tasks 9.2 and 9.4, §5 (property tests), Task 17.1

## Context

Research state is layered: a taxonomy Decision feeds classifications, which feed a matrix,
which feeds a Claim, which feeds a manuscript section (PRODUCT.md §37). Anchors have the
same shape — an Evidence object depends on a parse of a specific artifact (§16). When an
upstream object changes there are two tempting failures: leave the downstream object
unchanged and silently wrong, or recompute it so the researcher never learns it moved.

## Decision

When an upstream object changes, dependent derived objects are marked `stale`; they are
never silently rewritten (§19.2, §37). Stale items are prioritized by scientific impact:
manuscript claim affected, then accepted Claim, then synthesis, then classification, then
index-only (§37). The invalidation set is part of the atomic mutation unit, so a canonical
change, its semantic event, and its stale set commit together or not at all (§8.2,
ADR-001).

Broken provenance follows the same rule. If a later parser or a revised artifact makes an
anchor invalid, the Evidence object becomes stale and requires review rather than
reattaching elsewhere (§16); anchor validation reports `valid`, `stale`, or `missing`
(Task 2.4). Manuscript rewording that changes a sentence fingerprint triggers
revalidation (Task 9.2), and stale high-impact objects enter the Review Inbox in priority
position three (§24.2, ADR-007).

## Consequences

### Positive

- A researcher can reconstruct why a taxonomy or claim changed months later (§41.7), and a
  revision becomes visible work with a bounded scope, corrected in front of them, not behind.
- Stale sets are testable: propagation terminates and is order-independent (ROADMAP.md §5).

### Negative / costs

- One large taxonomy change can mark many objects stale at once, and that triage is work.
- The dependency graph is another projection to build and keep correct, `stale` is a state
  every surface must display, and users can ignore it, so impact ordering is load-bearing.

## Invariants this ADR protects

- Changing an accepted taxonomy marks dependent matrices, Claims, and manuscript anchors
  stale — §42 I; the chain classification → matrix → claim → anchor is explicit, and stale
  propagation never rewrites derived objects automatically (Task 3.4).
- A one-byte artifact change prevents silent reattachment, and anchor validation returns
  `valid`/`stale`/`missing` (Task 2.4) — what keeps §42 D true over time.
- Manuscript rewording that changes the sentence fingerprint triggers revalidation rather
  than retaining a stale anchor (Task 9.2).
- The manuscript auditor detects stale Claims and anchors and invalid source Evidence
  anchors (Task 9.4), part of the citation-integrity behavior in §42 J.
- Researcher override creates a Decision and invalidates downstream objects (Task 7.5).
- Dependency propagation terminates and is order-independent (ROADMAP.md §5).

## Rejected alternatives

- **Auto-recompute downstream objects.** §19.2 forbids it: the researcher would never
  learn that a conclusion changed under them.
- **Leave downstream objects untouched and unmarked.** The §2 failure where a taxonomy
  revision does not invalidate dependent synthesis and manuscript text.
- **Heuristically reattach a broken anchor to the nearest match.** Silently moves
  provenance and breaks §42 D; §16 requires staleness instead.
- **A global "everything is stale" flag.** Without impact ordering (§37) it is ignored.

## Where it is enforced

- `src/research_harness/projection/dependencies.py`: `mark_changed(object_id) -> StaleSet`
  and downstream queries; `workspace/journal.py` and `events.py` commit the stale set with
  the mutation.
- `parsing/anchors.py` (`AnchorValidationResult`), `manuscript/anchors.py` and
  `manuscript/audit.py`, `claims/service.py`, `evidence/review.py` (stale items in the
  queue), and the `state.stale` capability (§22).
- Tests: `tests/unit/projection/test_staleness.py`, `tests/unit/parsing/test_anchors.py`,
  `tests/integration/manuscript/test_claim_attachment.py`,
  `tests/integration/claims/test_override_decision.py`,
  `tests/e2e/test_manuscript_audit.py`, Task 17.1 stale propagation.
