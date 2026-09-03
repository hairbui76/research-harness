# ADR-003: Candidate/verified/accepted authority model

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P3, P4), §8.3, §9.1, §20.4, §23, §25, §36, §42 (E, H), §43, §44.6–44.9; ROADMAP.md Global Constraints, Task 1.3, Phase 6 Tasks 6.1–6.3, Task 3.5, Phase 13

## Context

Models produce plausible text. If a model proposal can land directly in canonical state,
cascade hallucination follows: a later role reads the earlier model's output as an
established fact and builds on it (PRODUCT.md §43). The same collapse conflates author
claims, measured results, and researcher inference (§2).

## Decision

Every model-generated scientific judgment enters staging and moves through the pipeline
in §8.3: raw source → model proposal → verification → review queue → researcher
acceptance → canonical research state. No model mutates accepted state directly.

Three authority tiers exist: a **candidate** in `.research/staging/` has no authority; a
**verified** candidate carries an independent verification result and still has none; an
**accepted** object lives in canonical files and is authoritative.

Epistemic origin is a schema-level enum — `source_observed`, `author_claimed`,
`author_interpreted`, `researcher_inferred`, `model_proposed`, `external_metadata` (§9.1)
— and transitions between those values are constrained. Verification returns a categorical
status (`supported`, `partially_supported`, `contradicted`, `insufficient_evidence`) plus
a rationale; confidence is secondary metadata, never an acceptance signal (§43). Roles
carry write permissions: the extractor writes staging only, the verifier cannot rewrite an
accepted candidate, and the writer cannot create accepted facts (§23).

## Consequences

### Positive

- A model failure, bad prompt, or provider outage leaves canonical state unchanged
  (ROADMAP.md §6, item 5); disagreement becomes a conflict object, not last-writer-wins.
- The verifier gets source plus candidate, not the extractor's reasoning, so agreement
  carries information, and re-running extraction elsewhere costs nothing scientifically.

### Negative / costs

- Each object carries more states, more storage, and more transitions to test, and
  high-value gates cost two model calls where one would produce an answer.
- A review backlog is the normal steady state (mitigated by ADR-007), and staging is
  disposable, so an unreviewed candidate can be lost to a rebuild.

## Invariants this ADR protects

- An author claim cannot automatically become a verified experimental result — §42 E.
- A model cannot bypass the strict review gate for interpretive scientific state — §42 H.
- There is no transition from `model_proposed` directly to `source_observed` (Task 1.3).
- Extraction cannot write accepted Evidence, a candidate with no valid anchor is invalid
  (Task 6.1), and the verifier is not given extractor hidden reasoning; a paper or dataset
  name alone cannot establish properties the source does not state (Task 6.2).
- Provider disagreement materializes as a Review Inbox conflict rather than one provider
  silently overwriting the other (Task 13.2).
- Checkpoints may preserve staged candidates but never grant accepted authority (Task 3.5).

## Rejected alternatives

- **Auto-accept above a confidence threshold.** Confidence alone is never sufficient
  (§24.4) and confidence is not scope (§5 P6).
- **Self-verification by the same model and prompt.** Correlated errors make agreement
  meaningless; §20.4 requires an independent check at gates that matter.
- **An agent-to-agent trust chain** where one role's output is a trusted fact for the
  next: the cascade failure §43 names.
- **One combined `status` field** mixing epistemic origin with review state: §42 E would
  be untestable, since "author claimed" and "verified result" share a scale.

## Where it is enforced

- `src/research_harness/domain/`: `enums.py`, `transitions.py`, `errors.py` — illegal
  transitions raise `TransitionError`.
- `evidence/` (`extraction.py`, `verification.py`, `review.py`, `service.py`), `roles/`
  (`contracts.py` plus the role modules), `workflows/interrogate.py` and `verify.py`,
  `providers/models/cross_verify.py`.
- Tests: `tests/unit/domain/test_transitions.py`, `tests/unit/roles/test_permissions.py`,
  `tests/integration/evidence/` (`test_extraction.py`, `test_verification.py`,
  `test_review_gate.py`), `tests/unit/providers/test_cross_verify_policy.py`, Task 17.1.
