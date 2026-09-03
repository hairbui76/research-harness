# Plugins

A plugin adds vocabulary and questions to the core. It never adds authority: it cannot
write canonical state, bypass a review gate, redefine a core meaning, or widen a permission
quietly (ADR-010). Every one of those is a load-time check, not a convention — a plugin
that wants a forbidden route fails to load rather than failing to behave.

The reference for the SPI itself is **[plugins/README.md](../../plugins/README.md)**, which
lists every boundary and where it is enforced. This page is how to write one.

## Where plugins are found

Most specific first:

1. `<workspace>/plugins/` — plugins belonging to one project;
2. the harness's own top-level `plugins/` — the ones shipped with it.

Only directories that exist are searched. `research doctor` reports what it found:

```text
[note] plugins           academic-writing, structured-traffic (in /home/you/research-harness/plugins)
```

## Using one

The only CLI surface is the interrogation schema:

```bash
research interrogate W0001 --schema plugin:structured-traffic --provider <configured>
research interrogate W0001 --schema plugin:structured-traffic:paper --field traffic.traffic_unit
```

`plugin:<plugin-name>` works when the plugin contributes exactly one interrogation schema;
name it (`plugin:<name>:<schema>`) when it contributes several. The plugin's fields are
merged **beside** the core schema, never over it, so a plugin adds questions and removes
none.

The plugin is loaded through a gateway bounded by its own manifest, wrapping a principal
that is an agent host — so a plugin reads and proposes, and accepted state is reached only
through human review.

## The manifest

One directory per plugin, named exactly as its `name:` field, with `plugin.yaml` as the
whole self-description. A file the manifest does not list is not loaded, and every listed
path must be relative and inside the plugin directory — `..`, absolute paths, and symlinks
resolving outside are refused before anything is opened.

```yaml
name: structured-traffic          # kebab-case; must equal the directory name
version: 0.1.0
requires_core: ">=0.1,<1.0"       # PEP 440 clauses, checked against research_harness.__version__
description: Representation and detection vocabulary for structured network traffic.

contributes:                      # the eight extension points; every entry is a file
  schemas: [schemas/traffic.yaml]
  interrogation: [interrogation/paper.yaml]
  validators: [validators/traffic_unit.py]
  workflows: [workflows/interrogate.yaml]
  roles: [roles/domain_reviewer.yaml]
  search_providers: [providers/some_index.py]
  writing_policies: [writing/q1-survey.yaml]
  ui_extensions: [ui/matrix.yaml]

egress:                           # mandatory whenever search_providers is non-empty
  - endpoint_host: api.example.org
    sends_source_text: false
    sends_identifiers: true
    description: Sends the query string and DOIs; never sends source text.

permissions:
  capabilities: [work.get, evidence.extract, review.inbox]
  roles_used: [evidence_extractor]
```

Every field is closed: an unknown key is a manifest error, not a warning.

## What a plugin may ask for

`permissions.capabilities` must be a subset of the plugin surface — reading, retrieving,
and staging only:

```text
claim.find_counterevidence   claim.find_support   evidence.extract
evidence.verify              retrieval.resolve_source
retrieval.search             review.inbox         work.get
```

`corpus.search` is deliberately not on this list: it records a canonical `SearchRun`, so it
is a `mutate` capability, and a plugin granted one would pass the gateway only to be refused
for want of human authority. A plugin that needs discovery declares a workflow fragment and
the host runs it.

And these stay refused however the manifest is written, because the gateway checks them
first:

```text
claim.override_strength   decision.*              decision.accept
evidence.accept           evidence.reject         manuscript.attach_claim
note.promote              review.accept_batch     review.resolve_conflict
search_run.record         state.rebuild           synthesis.build_matrix
taxonomy.put              work.register           work.store_blocks
```

The two lists are deliberately redundant: the allowlist is what a manifest may ask for,
the deny list is what the gateway refuses regardless. Widening either is a core decision
with a boundary test attached, not a plugin's to make.

A plugin never receives a repository, a `CapabilityContext`, a workspace path, or a
database handle. It calls named capabilities through a gateway, and a refusal raises
`PluginBoundaryError` — which is also an `AuthorityError`, so code that already guards
accepted state catches a plugin overreach without knowing plugins exist.

## What a contribution module may import

Every declared `.py` file is scanned with an AST pass **before** it is executed, so a
validator that reaches into the workspace never runs at all.

| refused | examples |
|---|---|
| imports | `os`, `sys`, `subprocess`, `shutil`, `socket`, `sqlite3`, `sqlalchemy`, `pickle`, `ctypes`, `importlib`, `runpy`, `research_harness.workspace`, `research_harness.projection`, `research_harness.capabilities.context`, `research_harness.capabilities.handlers` |
| importing the harness as a *module* | `import research_harness`, `from research_harness import ...`, `from research_harness.capabilities import ...` — import *names* from a leaf module instead: `from research_harness.providers.search.base import SearchProvider` |
| calls | `open`, `eval`, `exec`, `compile`, `__import__`, `input`, `breakpoint` |
| method names | `write_text`, `write_bytes`, `mkdir`, `makedirs`, `rmtree`, `unlink`, `rename`, `symlink_to`, `hardlink_to`, `touch`, `chmod`, `connect`, `executemany`, `executescript` |

The scan is a gate, not a sandbox: it refuses the obvious routes out of the SPI and makes a
plugin that wants them declare itself by failing to load. Real isolation would need a
separate process.

Modules are executed with `runpy.run_path`, each in a fresh namespace and out of
`sys.modules`, so two plugins may both ship `validators/traffic_unit.py` and neither
becomes importable elsewhere.

## The other boundaries

| rule | refusal |
|---|---|
| a vocabulary label equal to a core `EvidenceType`, `ClaimType`, or interrogation field is refused; every plugin label is namespaced to the plugin's name | `PluginBoundaryError` |
| a role may not exceed the plugin's permissions, may not widen the core role of the same name, and writes one candidate scope — no `WriteScope` naming accepted state | `PluginBoundaryError` |
| a writing policy is `authority: candidate_only` and preserves every core `ProtectedSpanKind` | `PluginBoundaryError` |
| a search provider only contacts a host the manifest declared under `egress:` | `PluginBoundaryError` |
| `search_providers` without a declared `egress:` block is undisclosed egress | `PluginManifestError` |

Two consequences worth knowing before you start:

* **A validator is a pure function over a plain dict.** `validate(candidate)` returns a
  list of `{"field", "message", "severity"}` mappings, is handed JSON-shaped data only, and
  needs no harness import at all:

  ```python
  FIELD = "minimal.traffic_unit"
  ALLOWED = ("packet", "flow", "session")


  def validate(candidate: Mapping[str, object]) -> list[dict[str, str]]:
      if candidate.get("field") != FIELD:
          return []
      ...
  ```

* **A role names a core output schema** (`extraction`, `verification`, `skeptic`,
  `claim_audit`, `synthesis`, `writer`) rather than supplying one. The epistemic rules in
  those models — a model may not label quoted text `researcher_inferred`, may not report
  `absent`, and returns a categorical verdict rather than a confidence score — apply to
  plugin roles for free.

## The worked example

`tests/fixtures/plugins/minimal/` is the smallest plugin that exercises all eight
extension points: one vocabulary, one interrogation field, two validators, one workflow
fragment, one bounded role, one search provider, one writing policy, one UI descriptor.
Copy it. Its boundary tests are `tests/contract/plugins/test_plugin_boundaries.py`, and
`tests/fixtures/plugins/bad_*/` are the manifests that must fail — one per rule.

## The two shipped plugins

**`plugins/structured-traffic/`** — the domain vocabulary for structured network traffic
papers: representation, detection, and evaluation terms as plugin-namespaced labels, plus
the questions to put to every relevant paper. Multi-label where the domain is multi-label
(`raw_sequential`, `field_based`, `behavior_aware` are taxonomy terms, never core enums).
It contributes schemas, interrogation, two validators, a workflow fragment, and a
`traffic.domain_reviewer` role, and asks for six read/stage capabilities. It contributes no
search provider, so its `egress:` block is empty by construction rather than by omission.

**`plugins/academic-writing/`** — writing policies only, `authority: candidate_only`: claim
language bounded by the scope ladder, citation discipline, project style, and a style pass
adapted from the `humanizer` skill. Its manifest asks for **nothing**:

```yaml
permissions:
  capabilities: []
  roles_used: []
```

Four YAML files of wording rules and no code. An empty permission set is the strongest
thing a manifest can say about what a style pass may do.

`docs/plans/skill-audit.md` records which assets under `skills/` went into each, and which
were classified inspiration-only or excluded. Nothing under `skills/` is a runtime
dependency of the core.

## Checking a plugin loads

```bash
research interrogate W0001 --schema plugin:<name> --field <one-field> \
  --provider scripted --script /tmp/empty.json
```

with `/tmp/empty.json` holding `{"evidence_extractor": [{"candidates": [], "fields_not_found": ["<one-field>"]}]}`.
A load failure names the plugin and the rule that refused it:

```console
$ research interrogate W0001 --schema plugin:bad_accept_permission ...
error: plugin 'bad_accept_permission' could not be loaded: .../plugins/bad_accept_permission/plugin.yaml
is not a valid plugin manifest: 1 validation error for PluginManifest
permissions.capabilities
  Value error, a plugin may never call accepted-state capabilities: evidence.accept
```

An unknown name says where it looked and what it found:

```console
$ research interrogate W0001 --schema plugin:mine ...
error: no plugin named 'mine' under /home/you/research-harness/plugins (found: academic-writing, structured-traffic)
```
