# ADR-024: Imported research skills are classified design inputs, not runtime components

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §32.1, §32.2, §32.5, §33, §42 (E, F, G, H), §43; ROADMAP.md Phase 14 Task 14.2, Gate P14, Phase 15 Tasks 15.1–15.2; recorded in `skills/INVENTORY.md` and `docs/plans/skill-audit.md`, bounded by `src/research_harness/plugins/manifest.py` and `validation.py`, tested by `tests/contract/plugins/`

## Context

`skills/` holds 97 imported assets — literature-review, deep-research, SLR-writing, paper
review, and style skills — written for a chat host with a filesystem. They encode real
working practice and, alongside it, the patterns this product exists to prevent: a model
issuing an editorial decision, a score mapped to "Accept", a failed search reported as a
zero result, one `citation_key` standing in for Work, Version, and Artifact. ADR-010 fixed
the rule but not the outcome, and "check it when we wire it" wires the first one unchecked.

## Decision

Every asset under `skills/` carries one of four rulings, assigned before any use:
**reuse-as-contract** (5), **adapt-to-plugin** (30), **inspiration-only** (48),
**exclude** (14). The register is `skills/INVENTORY.md`; the reasoning, with the quoted
instruction behind each ruling, is `docs/plans/skill-audit.md`.

Assets were judged against nine invariants the core already enforces, not against general
quality: nothing a model produces is accepted state; a failed search is not a zero result;
novelty is not inferred from an empty cell; Work/Version/Artifact stay distinct; no host- or
vendor-specific behavior reaches the core; confidence is never an acceptance signal; core
meanings are not redefined; taxonomy is a researcher-approved Decision; egress is declared.
Five are the §42 E–H acceptance tests, so a conflict with one is disqualifying.

Each `adapt-to-plugin` asset declares its target plugin, role, fragment or policy, its
epistemic authority, its allowed capabilities, what stays forbidden beyond the shared F-core
set, its output schema, host dependency, checkpoint behavior, and its failure and coverage
reporting (§32.5). `skills/` stays read-only: nothing in it is imported or executed.

## Consequences

### Positive

- Phase 15 inherits a mapping rather than a reading list: `structured-traffic` and
  `academic-writing` each know which assets they take and on what authority.
- Every `exclude` names the sentence that earned it, and because the core imports nothing
  from `skills/`, a skill's release cadence and host assumptions are not our problem.

### Negative / costs

- 48 assets classified `inspiration-only` are reading that produced no code, and the audit
  delayed reuse of assets already working elsewhere.
- Nine `academic-paper-reviewer` assets target `academic-review`, a plugin no phase
  schedules; the classification records worth, not a commitment.

## Invariants this ADR protects

- No skill is a runtime dependency of the core, nor copied into it (§32.5, Gate P14).
- A skill proposes canonical objects only through core capabilities: a plugin draws only on
  `PLUGIN_ALLOWED_CAPABILITIES`, and `DENIED_CAPABILITIES` is refused whatever it declares.
- No adapted asset may collapse Work/Version/Artifact identity (ADR-002), turn a failed
  search into zero-result evidence (§42 F), or infer novelty from an empty matrix cell.
- No asset that issues an acceptance verdict, or weights one by confidence, is adapted,
  which keeps §42 E, G, and H true for imported workflows; host artifacts (`CLAUDE.md`,
  `$skill` syntax, `WebSearch`) are excluded rather than genericized (ADR-009).

## Rejected alternatives

- **Copy the working skills into the core.** Task 14.2 forbids it: it imports another
  project's authority model with its prose.
- **Classify lazily, at first use.** The useful assets are exactly the ones carrying the
  strongest embedded verdict logic.
- **Run skills as agents against the workspace.** They write files and issue decisions;
  §32.2 and ADR-003 leave nowhere for that output to land.
- **Two grades, keep or drop.** Loses the difference between an asset whose semantics
  transfer verbatim and one whose idea transfers but whose runtime does not.

## Where it is enforced

- `skills/INVENTORY.md` (the register and per-asset declarations) and
  `docs/plans/skill-audit.md` (the rationale); `plugins/README.md` maps them onto Phase 15.
- `src/research_harness/plugins/manifest.py`: `PLUGIN_ALLOWED_CAPABILITIES` (nine read and
  staging capabilities) and `DENIED_CAPABILITIES`; `plugins/validation.py` checks roles,
  vocabularies, and writing policies against them (ADR-020).
- Tests: `tests/contract/plugins/test_plugin_boundaries.py` and `test_structured_traffic.py`.
