# ADR-007: Strict human review as default policy

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P4, P8), §24.1–§24.4, §25, §38, §41.11, §42 (F, G, H, L), §43, §44.6, §44.18, §44.20; ROADMAP.md Task 6.3, Task 7.5, Task 11.3, Task 13.2, Task 17.1

## Context

ADR-003 makes acceptance a separate step; this ADR decides who performs it and how often.
Strict review spends the scarcest resource the product has, researcher attention (§5 P8),
and review fatigue is a named risk (§43). Auto-accepting interpretive judgments would
reinstate the failure the product exists to prevent, so the design needs a safe default
plus ergonomics that make it survivable daily.

## Decision

The default review policy is strict (§24). Work is tiered rather than uniformly reviewed:
**Tier 0** is automatic for deterministic mechanical facts (hashes, page count, validated
DOI resolution); **Tier 1** is quick triage for directly evidenced extraction such as
dataset, metric, or traffic unit; **Tier 2** is deep review for taxonomy, method
limitations, gap claims, claim strength, and counter-evidence reading (§24.1).

Review is asynchronous and conflict-first, not interrupt-driven. The queue is ordered
conflicts → high-risk scientific claims → stale high-impact objects → ambiguous
extractions → routine verified candidates (§24.2), and offers Accept, Accept with
qualification, Edit, Reject, Defer, and Request more evidence, with partial acceptance so
a source fact can be accepted while its interpretation is rejected (§24.3). Batch
acceptance is permitted only under explicit deterministic conditions — verifier
reports supported, anchor still valid, no competing candidate, low-risk field, no
accepted-state conflict — and model confidence is never one of them (§24.4). Override
remains available but persists as a visible `Decision` with rationale (§5 P4, §38).

## Consequences

### Positive

- Attention goes to items that can change a conclusion: Tier 0 removes toil without
  weakening the gate, and conflict-first ordering surfaces likely errors first.
- Overrides stay auditable months later (§41.7), and source-beside-decision review keeps
  Tier 1 fast enough to match ingestion (§26). Tier 2 attention is not spent on hashes.

### Negative / costs

- The default is slower than autonomous extraction, deferral builds a backlog, and tier
  assignment is a judgment call to revisit as the corpus grows.
- Review calibration is deferred (ROADMAP.md §9), so tiers stay coarse in v1.0.

## Invariants this ADR protects

- A model cannot bypass the strict review gate for interpretive scientific state — §42 H.
- `not_reported` cannot be converted to `absent` without an explicit review path — §42 F.
- A claim with incomplete coverage cannot silently escalate its wording — §42 G.
- A style pass changing a protected span or strengthening a proposition cannot replace
  accepted manuscript text before semantic audit and review — §42 L.
- Partial acceptance can split source fact from interpretation; confidence alone cannot
  trigger acceptance and batch acceptance needs deterministic conditions (Task 6.3, §24.4).
- Provider agreement does not auto-accept a Tier-2 judgment (Task 13.2).
- Researcher override creates a visible `Decision` and invalidates downstream objects
  (Task 7.5).

## Rejected alternatives

- **Autonomous acceptance with post-hoc spot checks.** Errors reach claims and manuscript
  text before any check runs.
- **Confidence-threshold acceptance.** Ruled out by §24.4; confidence is not scope (§5 P6).
- **Uniform review depth.** Guarantees the fatigue §43 warns about.
- **Strictness as a preference before tiers and the inbox exist.** Ships the unsafe
  default first, then asks users to opt into safety.

## Where it is enforced

- `src/research_harness/evidence/review.py` and `service.py` (queue order, actions,
  batch policy); `domain/transitions.py` (no acceptance without a review transition).
- `claims/negative_evidence.py` (§42 F), `claims/strength.py` and `claims/audit.py`
  (§42 G), `claims/service.py` (override Decisions), `manuscript/audit.py` (§42 L).
- `src/research_harness/capabilities/`: `permissions.py` and `handlers.py` expose
  `review.inbox`, `review.accept_batch`, and `review.resolve_conflict` per §22.
- Tests: `tests/integration/evidence/test_review_gate.py`,
  `tests/unit/claims/test_negative_evidence.py`, `tests/unit/domain/test_transitions.py`,
  `tests/integration/claims/test_override_decision.py`, Task 17.1 review-gate invariants.
