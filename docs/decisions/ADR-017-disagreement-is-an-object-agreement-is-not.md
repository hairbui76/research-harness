# ADR-017: Provider disagreement becomes an object; agreement never accepts

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §20.4, §24.2, §24.4, §25, §42 (E, H), §43; ROADMAP.md Phase 13 Tasks 13.1–13.2, Gate P13, Task 17.1; implemented in `providers/models/cross_verify.py`, `evidence/conflicts.py`, `evidence/review.py`, `workflows/verify.py`, `workflows/claim_audit.py`

## Context

ADR-005 restricts cross-model verification to high-value gates; ADR-003 says disagreement
must materialize as a Review Inbox conflict rather than one provider overwriting the other.
Disagreement is easy to store. **Agreement** is the trap: a record saying "two independent
providers agreed" is one refactor away from being read as permission to accept, which §24.4
and §43 forbid. Two correlated models agreeing is not evidence; it is two samples from the
same prior.

## Decision

Cross-verification runs only at the five declared gates — absence claim, high-impact
numeric, counter-evidence interpretation, submission field claim, high-consequence
manuscript claim — with at least two providers, distinct vendors by default, and one extra
call per object. Providers are compared only on the caller-named decision fields.
**When providers agree, nothing is created**: `CrossVerification` records `agreement` and
stops, with no `accepted` field and no winner, and one surviving position is not agreement.

When they disagree, a `ConflictRecord` is written naming every position — provider, model,
request fingerprint, decision, rationale — and the fields that differ, and the disagreeing
candidate is never written back: keeping the first provider's verdict is what makes "one
explicit conflict rather than one provider silently overwriting the other" true on disk.
Conflicts live in regenerable staging, because an unresolved disagreement is a queue item
and not a conclusion; they are first in the inbox, and resolution is human-only.

## Consequences

### Positive

- The expensive second opinion buys the thing worth buying — a visible disagreement at the
  top of the queue — and buys no shortcut past review.
- One conflict shape serves provider disagreement, extractor-versus-verifier, and
  candidate-versus-accepted, so the inbox and the cockpit have one thing to render.

### Negative / costs

- Gate-level cross-verification doubles the cost of the calls it covers, and which gates
  count as high-value is a judgment.
- An open conflict is regenerable, so a disagreement found before a rebuild must be
  rediscovered after one; only the resulting acceptance or refusal is durable.

## Invariants this ADR protects

- Provider agreement does not auto-accept a Tier-2 judgment under strict policy (Task 13.2,
  ADR-007) — there is no field in which an agreement could say otherwise.
- Provider disagreement materializes as a Review Inbox conflict rather than one provider
  overwriting the other (Gate P13), and the candidate is left as it was.
- Conflicts are first in the queue (§24.2), including ones with no staged candidate behind
  them, and only a human resolves one, with a reason (§42 H).
- A disagreement names two positions and a differing field, or it is unconstructable, and
  cross-verification runs at declared gates rather than on routine extraction (§20.4).

## Rejected alternatives

- **Accept on agreement at low-risk gates.** Correlated errors make agreement meaningless
  as an acceptance signal; it reinstates confidence-shaped acceptance under a new name.
- **Record an `agreement` object.** Storing it invites something downstream to read it as
  permission; not storing it costs nothing, because agreement changes no state.
- **Pick a winner by confidence or model tier.** Confidence is not scope (§5 P6), and §43
  lists score-weighted arbitration as an excluded pattern.
- **Store conflicts as canonical objects.** An unresolved disagreement is a queue item; the
  durable record is the acceptance or refusal it leads to (ADR-012).

## Where it is enforced

- `src/research_harness/providers/models/cross_verify.py`: `CrossVerificationGate`,
  `CrossVerifyPolicy`, `CrossVerification` (no `accepted` field), `_outcome`.
- `evidence/conflicts.py`: `ConflictRecord`, `ConflictKind`, `ConflictStore`
  (`open_or_put`, `resolve`), `materialize_provider_conflict`.
- `evidence/review.py` (`ReviewCategory.CONFLICT` first), `workflows/verify.py` and
  `claim_audit.py`, and the `review.resolve_conflict` capability.
- Tests: `tests/unit/providers/test_cross_verify_policy.py`,
  `tests/unit/evidence/test_inbox_ordering.py`,
  `tests/integration/evidence/test_conflicts.py`, `tests/e2e/test_cross_verify_conflict.py`.
