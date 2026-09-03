# ADR-010: Domain plugins may extend vocabularies but not core scientific authority

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §4, §9.2, §10.1, §32.1–§32.5, §33, §42 (E, F, G, H), §43, §44.17, §44.22; ROADMAP.md Phase 14 Tasks 14.1–14.3, Gate P14, Phase 15, §9 (MVP cut rules)

## Context

The motivating project needs a large domain vocabulary — traffic unit, representation
family, serialization, tokenization, detection target, encryption status and the rest of
PRODUCT.md §33. Putting that in the core would grow the ontology without bound, the risk
§43 names, and §4 rules out a universal ontology. Existing research skills are likewise
tempting to copy into the core wholesale.

## Decision

Plugins extend the domain; they do not redefine it. A plugin may contribute domain schema
fields and controlled vocabularies, interrogation schemas, validators, workflow fragments
built from core capabilities, bounded roles, search providers, writing policies, and UI
extension descriptors (§32.1), declared in a manifest with a `requires_core` range (§32.3).
It may not write canonical files without core validation, write SQLite as scientific
state, bypass review gates, redefine the core meanings of Evidence, Claim, Decision, or
accepted state, expand model permissions silently, or create host-specific state (§32.2).

The line runs between vocabulary and authority. Evidence types (§9.2) and project
taxonomies are extension points; epistemic origin, evidence strength semantics, the claim
scope ladder L0–L4, claim status, and accepted-state transition rules are core.

Imported skills are design inputs, not trusted runtime components. Each is classified
`reuse-as-contract`, `adapt-to-plugin`, `inspiration-only`, or `exclude` before use, and
each adapted skill declares its target, authority, allowed capabilities, and forbidden
mutations (§32.5; classifications are seeded from `skills/INVENTORY.md`, Task 14.2).

## Consequences

### Positive

- The core ontology stays small, §43's mitigation for over-engineering it, and the
  structured-traffic project becomes a dogfood plugin (Phase 15) rather than core code.
- Domain work proceeds in parallel without touching scientific invariants, and plugin
  distribution can be cut before v1.0 without cutting one (ROADMAP.md §9).

### Negative / costs

- The SPI is a contract to design, version, and keep compatible via `requires_core`; some
  domain checks would be shorter written directly into the core.
- The audit gate (Task 14.2) delays reuse of working assets, and plugins restricted to
  core capabilities may be slower than direct access.

## Invariants this ADR protects

- A plugin cannot write canonical state directly or create host-specific state (§32.2,
  ADR-009), nor bypass strict review gates or expand role permissions silently
  (Task 14.1) — this is what keeps §42 H true for domain workflows.
- Core meanings of Evidence, Claim, and Decision cannot be redefined (Task 14.1),
  preserving §42 E, F, and G; an example plugin adds an interrogation field and a
  validator without altering core schemas (Task 14.3).
- Skills propose canonical objects only through core capabilities, and must not collapse
  Work/Version/Artifact identity (ADR-002), turn failed searches into zero-result evidence
  (§42 F), or infer novelty from missing matrix cells (§32.5).
- Taxonomy remains a researcher-approved Decision, not a plugin-declared fact (§33).

## Rejected alternatives

- **Unrestricted code injection into research state.** Rejected by §32; §43 lists plugin
  bypass of scientific invariants as a risk.
- **A universal cross-discipline ontology in the core.** Excluded by §4 and §43's "keep
  core entities small" mitigation.
- **Copying existing skills into the core because they exist.** Task 14.2 forbids it.
- **Per-domain accepted-state semantics.** Each plugin could set its own bar for
  acceptance, making §42 E, F, G, and H unenforceable.

## Where it is enforced

- `src/research_harness/plugins/`: `spi.py`, `manifest.py`, `loader.py` — the SPI and
  runtime; top-level `plugins/` holds the extensions per ROADMAP.md's repository rules.
- `domain/enums.py` holds core vocabularies and their extension points;
  `capabilities/permissions.py` bounds a plugin role, `roles/contracts.py` types it.
- Tests: `tests/contract/plugins/test_plugin_boundaries.py` and the Task 14.3 example
  plugin compatibility test, gated at P14 before any skill migration.
