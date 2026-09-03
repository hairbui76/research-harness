# Plugins

Domain extensions live here. The invariant core lives in `src/research_harness/`; a plugin
adds vocabulary and questions to it and never adds authority (PRODUCT.md §32, ADR-010).

The SPI is `research_harness.plugins`. Its boundary tests are
`tests/contract/plugins/test_plugin_boundaries.py`, and the worked example the tests load is
`tests/fixtures/plugins/minimal/`.

## Directory layout

One directory per plugin, named exactly as its `name:` field:

```text
plugins/
└── structured-traffic/
    ├── plugin.yaml            # the manifest; nothing outside it is loaded
    ├── schemas/traffic.yaml   # vocabulary: plugin-namespaced labels and fields
    ├── interrogation/paper.yaml
    ├── validators/traffic_unit.py
    ├── workflows/interrogate.yaml
    ├── roles/domain_reviewer.yaml
    ├── providers/some_index.py
    ├── writing/q1-survey.yaml
    └── ui/matrix.yaml
```

`plugin.yaml` is the whole self-description. A file the manifest does not list is not
loaded, and every listed path must be relative and inside the plugin directory — `..`,
absolute paths, and symlinks that resolve outside are refused before anything is opened.

```yaml
name: structured-traffic          # kebab-case
version: 0.1.0
requires_core: ">=0.1,<1.0"       # PEP 440 clauses, checked against research_harness.__version__
description: Representation and detection vocabulary for structured network traffic.

contributes:                      # the eight extension points of PRODUCT.md §32.1
  schemas: [schemas/traffic.yaml]
  interrogation: [interrogation/paper.yaml]
  validators: [validators/traffic_unit.py]
  workflows: [workflows/interrogate.yaml]
  roles: [roles/domain_reviewer.yaml]
  search_providers: [providers/some_index.py]
  writing_policies: [writing/q1-survey.yaml]
  ui_extensions: [ui/matrix.yaml]

egress:                           # mandatory whenever search_providers is non-empty (§34)
  - endpoint_host: api.example.org
    sends_source_text: false
    sends_identifiers: true
    description: Sends the query string and DOIs; never sends source text.

permissions:
  capabilities: [work.get, evidence.extract, review.inbox]
  roles_used: [evidence_extractor]
```

## What a plugin may ask for

`permissions.capabilities` must be a subset of the plugin surface — reading, retrieving,
and staging only (`plugins.manifest.PLUGIN_ALLOWED_CAPABILITIES`):

```text
claim.find_counterevidence   claim.find_support   evidence.extract
evidence.verify              retrieval.resolve_source
retrieval.search             review.inbox         work.get
```

`corpus.search` is **not** on this list. It records a canonical `SearchRun`, which makes it
a `mutate` capability, so a plugin granted it would pass the gateway only to be refused for
want of human authority. A plugin that needs discovery declares a workflow fragment and the
host runs it. `docs/guide/plugins.md` carries the same list with the deny list beside it.

## The boundaries, and where each one is enforced

A plugin cannot write canonical state, bypass a review gate, redefine a core meaning, or
widen a permission quietly (PRODUCT.md §32.2). Each of those is a load-time check, not a
convention:

| Rule | Enforced by | Refusal |
|---|---|---|
| A plugin calls capabilities by name through a gateway; it never receives a repository, a `CapabilityContext`, or a database handle | `spi.PermissionedGateway`, `PluginRuntime` | `PluginBoundaryError` |
| `permissions.capabilities` ⊆ `PLUGIN_ALLOWED_CAPABILITIES` (read and staging only) | `manifest.PluginPermissions` | `PluginManifestError` |
| Accepted-state mutations stay refused **whatever the manifest says** | `manifest.DENIED_CAPABILITIES` + the gateway's first check | `PluginBoundaryError` |
| Contribution modules may not import `research_harness.workspace`, `research_harness.capabilities.handlers`/`context`, `sqlite3`, `sqlalchemy`, `os`, `subprocess`, …, nor call `open()` or a filesystem write | `validation.scan_module` (AST scan, before execution) | `PluginBoundaryError` |
| A contribution imports *names* from the harness (`from research_harness.providers.search.base import SearchProvider`), never a module (`import research_harness.x`, which binds the root package) | `validation.scan_module` | `PluginBoundaryError` |
| A vocabulary label equal to a core `EvidenceType`/`ClaimType`/interrogation field is refused; every plugin label is namespaced | `validation.check_vocabulary` | `PluginBoundaryError` |
| A role may not exceed the plugin's permissions, may not widen the core role of the same name, and writes one candidate scope (no `WriteScope` names accepted state) | `validation.check_role` | `PluginBoundaryError` |
| A writing policy is `authority: candidate_only` and preserves every core `ProtectedSpanKind` | `validation.check_writing_policy` | `PluginBoundaryError` |
| A search provider only contacts a host the manifest declared | `validation.check_search_provider`, `SearchProviderFactory.build` | `PluginBoundaryError` |

Two consequences worth knowing before writing a plugin:

- **A validator is a pure function over a plain dict.** `validate(candidate)` returns a list
  of `{"field", "message", "severity"}` mappings. It is handed JSON-shaped data only, and
  `LoadedValidator.run` refuses to pass anything else, so there is no object graph leading
  back into canonical state. It needs no harness import at all.
- **A role names a core output schema** (`extraction`, `verification`, `skeptic`,
  `claim_audit`, `synthesis`, `writer`) rather than supplying one. The epistemic rules in
  those models — a model may not label quoted text `researcher_inferred`, may not report
  `absent`, and returns a categorical verdict rather than a confidence score — therefore
  apply to plugin roles for free.

`PluginBoundaryError` is also an `AuthorityError`, so code that already guards accepted
state catches a plugin overreach without knowing plugins exist.

## Where the audited skills land

`docs/plans/skill-audit.md` classifies every asset under `skills/`; `skills/INVENTORY.md`
carries the table. The two plugins ROADMAP Phase 15 builds are the destination for the
`adapt-to-plugin` assets that are in scope for v1.0:

**`structured-traffic`** (Task 15.1) — the domain vocabulary of PRODUCT.md §33 as a
`SchemaContribution` plus an `InterrogationContribution`, with `raw sequential`,
`field-based`, and `behavior-aware` as multi-label plugin taxonomy terms, never core enums.
It receives:

- the reading framework and information matrix of `my-literature-review`
  (`references/reading_framework.md`) as interrogation fields and validators;
- the discovery, identity-resolution, and snowballing protocol
  (`references/discovery-and-snowball.md`) as a workflow fragment plus search providers,
  and the coverage/gap ladder (`references/coverage-and-baselines.md`) as the wording
  bound on any literature-wide statement;
- the omit-on-degradation discipline of `deep-research`'s Crossref/OpenAlex/Semantic
  Scholar protocols, which is already how a `SourceFailure` differs from an empty page;
- `slr-writer`'s evidence-card field set, rebound to Evidence with real anchors and a
  Work/Version/Artifact triple instead of one `citation_key`.

**`academic-writing`** (Task 15.2) — writing policies only, `authority: candidate_only`.
It receives:

- `skills/humanizer` as the style pass, already carrying its Research Harness manuscript
  mode, minus its file-writing mode;
- `slr-writer`'s anti-hallucination rules (`[NEEDS SOURCE]` instead of an invented
  reference) and its assembler's `UNVERIFIED` reporting, as manuscript-audit warnings;
- `slr-writer`'s IEEE survey structure as venue style rules.

Everything classified `inspiration-only` or `exclude` stays out of both. Nothing under
`skills/` is a runtime dependency of the core, and no skill is copied into it.
