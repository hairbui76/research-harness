# ADR-019: The claim strength ladder is a table of named, checkable requirements

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §10.2, §10.5, §11, §12, §37, §38, §42 G; ROADMAP.md Phase 7 Tasks 7.2, 7.4, 7.5, Task 12.4, Task 17.1; implemented in `claims/strength.py`, `claims/audit.py`, `claims/service.py`, `domain/claim.py`, `domain/transitions.py`

## Context

§10.2 names five scope levels, L0 through L4, and §42 G requires that a claim with
incomplete coverage cannot silently escalate its wording. A scoring function returning a
level fails the researcher twice: it cannot say *why* a claim stopped at L1, and it buries
every threshold in a branch. Worse, a single function invites the inverse operation —
raising a level when the evidence looks good — which turns a model auditor into an advocate.

## Decision

The ladder is a table. `LEVEL_REQUIREMENTS` maps each `ClaimScope` to a tuple of
`LevelRequirement`s, each carrying a stable key, a plain-words demand, a predicate over
`StrengthFacts`, and an explanation. Assessment walks upward and stops at the first level
whose requirements are not all met, and the failing key is what the audit reports: "L3 was
refused because `l3.examined_ratio` needs 0.8 and the corpus is at 0.08". The rungs are
about coverage and independence, not volume of agreement:
L2 needs three independent works, half the universe examined, and contradictions under a
third of support; L3 needs five works, 80 % examined, an acceptable overturn risk, a recorded
search run, and no unqualified contradiction; L4 adds low overturn risk and a cutoff.

**A new claim starts at L0, allowed with no evidence at all**: `create` records the
requested strength but sets `allowed_strength` to L0 as `unverified`, and when even L0's
support requirement fails the floor is reported `unsupported` with `blocked_by` naming it.
**An audit can only lower**: the transition refuses an allowed strength above the requested
one, the audit mapping takes the minimum of requested, recommended, and computed, and a
model auditor recommending *higher* is ignored, because an auditor falsifies a claim rather
than maximizing support for it. **Escalation costs a Decision**: `override` refuses a
non-human actor and a missing rationale, writes an accepted `epistemic_override` Decision,
and only then applies it.

## Consequences

### Positive

- An audit explains itself in the researcher's terms, and the recorded wording is the
  strongest honest form rather than the requested one.
- Retuning a rung is a table edit with a named key, and at 0.04 ms per claim the inbox and
  the manuscript audit assess without caching.

### Negative / costs

- The thresholds are judgment calls presented with the precision of constants.
- L2 and above depend on a coverage record, so a claim whose funnel was never written
  cannot exceed L1 however much evidence it has; overriding costs three writes.

## Invariants this ADR protects

- A claim with incomplete coverage cannot silently escalate its wording — §42 G: the audit
  names the requirement that failed and records the strongest honest phrase.
- `allowed_strength` never exceeds `requested_strength`, a new claim is `unverified` at L0
  whatever was requested, and a model recommendation above the engine's is discarded.
- Escalation requires an accepted, human-authored `epistemic_override` Decision within the
  requested scope (Task 7.5); an author-claimed reading is a qualifier, never support (§42 E).

## Rejected alternatives

- **A scalar score mapped to a level.** Cannot say which requirement failed, and turns a
  threshold change into a silent re-grading of the whole corpus.
- **Confidence-weighted strength.** Confidence is not scope (§5 P6).
- **Let the auditor recommend a higher scope.** An auditor that can promote is an advocate,
  and §42 G is only testable if the ladder is one-directional.
- **Count evidence objects rather than independent works.** Ten quotes from one paper
  would reach L2; independence is the property the rung is about.

## Where it is enforced

- `src/research_harness/claims/strength.py`: `LEVEL_REQUIREMENTS`, `LevelRequirement`,
  `StrengthFacts`, `assess_strength`, and the threshold constants.
- `claims/audit.py` (`apply_auditor`, `to_assessment`), `claims/coverage.py`,
  `claims/service.py` (`INITIAL_ALLOWED_STRENGTH`, `override`), `domain/claim.py`, and
  `domain/transitions.py` (`audit_claim`, `override_claim_strength`).
- Tests: `tests/unit/claims/` (`test_strength.py`, `test_audit_rules.py`),
  `tests/integration/claims/test_override_decision.py` and `test_claim_audit.py`,
  `tests/e2e/invariants/test_g_claim_strength.py`.
