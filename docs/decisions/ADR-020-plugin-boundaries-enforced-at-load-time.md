# ADR-020: Plugin boundaries are enforced at load time, not by convention

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §30.4, §32.1–§32.3, §42 (E, H, L), §43; ROADMAP.md Phase 14 Tasks 14.1, 14.3, Gate P14, Phase 15; implemented in `src/research_harness/plugins/` (`spi.py`, `manifest.py`, `validation.py`, `loader.py`), `manuscript/style.py`, `manuscript/protected.py`

## Context

ADR-010 says a plugin may extend vocabulary but not authority. That is policy; this is what
makes it true of code running in the same process. A plugin contributes Python, so "must not
write canonical files" is one `open()` away from being violated by accident, and a
contribution that can `import research_harness.workspace` has the repository whatever its
manifest says. Documented boundaries nothing checks are the plugin-bypass risk §43 names.

## Decision

A plugin never receives an object that can reach state. `PermissionedGateway` exposes one
method — `call(name, request, *, actor)` — with no repository, no `CapabilityContext`, and no
way to ask for one, so ADR-004's single mutation surface holds for plugin code by
construction. It refuses in three steps: a capability in `DENIED_CAPABILITIES` is never
available; one outside `PLUGIN_ALLOWED_CAPABILITIES` is not part of the plugin surface; one
the manifest did not declare is not this plugin's.

Every contributed module is scanned as an AST before it executes. `scan_module` runs in
`load_plugin` ahead of any import and refuses a forbidden import (`workspace`,
`capabilities.handlers`/`context`, `projection`, `os`, `sqlite3`, `subprocess`, …), a
forbidden call (`open`, `eval`, `exec`, `__import__`), and a filesystem or database method
by name; `import research_harness.x` is refused outright because it binds the root package.
Vocabularies are namespaced under the plugin's own name, and a label equal to a core
`EvidenceType` or `ClaimType` is refused. Writing policies are candidate-only by type and
keep every core `ProtectedSpanKind`; a style pass runs through `semantic_diff`, cannot claim
it needs no review when its diff changes meaning, and `accept_style_pass` requires both
human approval and a clean audit.

## Consequences

### Positive

- The boundary fails at load with a file, a line, and a named finding, not later inside a
  researcher's workflow.
- `PluginBoundaryError` is also an `AuthorityError`, so code guarding accepted state catches
  an overreach without knowing plugins exist.

### Negative / costs

- **The static scan is a gate, not a sandbox.** A determined contribution can defeat an AST
  check; real isolation needs a separate process, which v1.0 does not have.
- **The plugin surface is narrower than "what a plugin might want".** `corpus.search` was
  on `PLUGIN_ALLOWED_CAPABILITIES` while being a `mutate` capability — it records a
  canonical `SearchRun` — so a plugin passed the gateway only to be refused by
  `Principal.authorize`, and the two lists disagreed about which layer should say so. It is
  off the allowlist: the surface is read, retrieve, and stage, and nothing on it writes
  accepted state. A plugin that needs discovery declares a workflow fragment and the host
  runs it, which is the boundary ADR-010 asks for rather than a hole in it.

## Invariants this ADR protects

- A plugin cannot write canonical state, a projection, or SQLite, and cannot bypass a review
  gate or widen a permission (Task 14.1) — what keeps §42 H true for domain workflows; no
  manifest, however written, can hand it an accepted-state mutation.
- Core meanings of Evidence, Claim, and Decision cannot be redefined, every plugin label is
  namespaced (§42 E, F, G), and a plugin role writes candidates only.
- A style pass changing a protected span or a proposition cannot replace accepted
  manuscript text before semantic audit and review — §42 L.

## Rejected alternatives

- **Document the boundaries and review plugins by hand.** The failure mode is the plugin
  nobody reviewed; §43 lists it as a risk.
- **Hand the plugin a read-only repository wrapper.** A wrapper is one attribute from the
  real object, and `capabilities/` would stop being the only mutation surface.
- **Enforce only at call time.** An import at module scope has already run by then, and a
  plugin declaring its own protected-span set could drop the protection on a citation.

## Where it is enforced

- `src/research_harness/plugins/spi.py`: `PermissionedGateway`, `PluginRuntime`,
  `ensure_plain_data`, `WritingPolicyContribution`.
- `plugins/manifest.py` (`PLUGIN_ALLOWED_CAPABILITIES`, `DENIED_CAPABILITIES`,
  `namespaces_for`), `plugins/validation.py` (`scan_module`, `check_vocabulary`,
  `check_role`, `check_writing_policy`), `plugins/loader.py`.
- `manuscript/protected.py` and `manuscript/style.py` (`semantic_diff`, `accept_style_pass`).
- Tests: `tests/contract/plugins/` (boundaries, the shipped plugins, the minimal example),
  the `tests/fixtures/plugins/bad_*` set, `tests/e2e/invariants/test_l_style_preservation.py`.
