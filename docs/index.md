# Research Harness documentation

A local-first, provider-neutral research workstation. Canonical scientific state lives in
readable, Git-versionable files; models propose, evidence justifies, and the researcher
decides.

New here? [Install and first run](guide/install.md), then the quickstart in
[README.md](../README.md).

## Guide

Task-oriented pages for using the harness.

| page | when you need it |
|---|---|
| [Install and first run](guide/install.md) | requirements, `uv sync`, `research doctor`, creating a workspace |
| [The workspace](guide/workspace.md) | the directory layout, what is canonical vs `.research/`, Git advice, identifiers |
| [Strict review](guide/review.md) | tiers, inbox order, review actions, batch conditions, conflicts, what a model may not do |
| [Providers](guide/providers.md) | configuring OpenAI/Anthropic/local/scripted, env vars, egress policy, `research egress`, traces, cost |
| [Agent hosts over MCP](guide/mcp.md) | `research mcp`, Claude Desktop and Claude Code config, ChatGPT-compatible hosts, tool names, resources |
| [The local HTTP daemon](guide/http.md) | `research serve`, the token, the routes, the error codes |
| [The Web cockpit](guide/web.md) | building and starting the browser UI |
| [The VS Code extension](guide/vscode.md) | manuscript work in the editor |
| [Rebuild and recovery](guide/rebuild-and-recovery.md) | `research rebuild`, `research doctor`, journal recovery, inconsistency, schema versions, a corrupt `.research/` |
| [Plugins](guide/plugins.md) | authoring boundaries, the manifest, allowed capabilities, the example and the two shipped plugins |
| [Troubleshooting](guide/troubleshooting.md) | real error messages and what they mean |

Generated reference, regenerated from the code rather than written by hand:

| page | generator |
|---|---|
| [CLI reference](guide/cli-reference.md) — every command's own `--help` | `uv run python docs/guide/gen_cli_reference.py` |
| [Capabilities](guide/capabilities.md) — every capability, its permission and MCP tool name | `uv run python docs/guide/gen_capabilities.py` |

## Specification and plan

| document | what it is |
|---|---|
| [PRODUCT.md](../PRODUCT.md) | the product specification; the source of every rule the code enforces |
| [ROADMAP.md](../ROADMAP.md) | the phased implementation plan and the acceptance requirements per task |

## Architecture

| document | what it is |
|---|---|
| [Engineering conventions](architecture/conventions.md) | layering, Python style, canonical serialization, test layout, the rules for parallel work |
| [The Web research cockpit](architecture/web.md) | the React client: startup, the routes the daemon adds for it, the review screen, generated types, known gaps |
| [VS Code manuscript client](architecture/vscode.md) | commands, hover, diagnostics, the sentence port, the backend gaps it works around |
| [Domain changelog](architecture/domain-changelog.md) | additive amendments to `domain/` and the layers that persist or project it |

## Decisions

[ADR index](decisions/README.md). An ADR here is binding: if implementation pressure
suggests violating one, the ADR and `PRODUCT.md` change explicitly.

| # | title |
|---|---|
| [ADR-001](decisions/ADR-001-canonical-state-authority.md) | Git-readable canonical state vs SQLite projection authority |
| [ADR-002](decisions/ADR-002-work-version-artifact-identity.md) | Work/Version/Artifact identity separation |
| [ADR-003](decisions/ADR-003-candidate-verified-accepted-authority.md) | Candidate/verified/accepted authority model |
| [ADR-004](decisions/ADR-004-single-application-capability-layer.md) | One application capability layer for CLI/API/MCP/UI |
| [ADR-005](decisions/ADR-005-provider-neutral-semantic-runtime.md) | Provider-neutral structured semantic runtime |
| [ADR-006](decisions/ADR-006-disposable-retrieval-indexes.md) | Embedded retrieval indexes are disposable |
| [ADR-007](decisions/ADR-007-strict-human-review-default.md) | Strict human review as default policy |
| [ADR-008](decisions/ADR-008-staleness-over-silent-rewriting.md) | Staleness instead of silent derived-state rewriting |
| [ADR-009](decisions/ADR-009-mcp-primary-host-boundary.md) | MCP primary host boundary with HTTP fallback |
| [ADR-010](decisions/ADR-010-plugin-extension-boundary.md) | Domain plugins may extend vocabularies but not core scientific authority |

## Plans and reports

| document | what it is |
|---|---|
| [Acceptance matrix](plans/acceptance-matrix.md) | what demonstrates each acceptance behaviour, where it lives, whether it holds today |
| [Performance budgets](plans/performance-budgets.md) | measured personal-scale timings and the proposed budgets (`benchmarks/`, `tests/perf/`) |
| [Skill audit](plans/skill-audit.md) | every asset under `skills/`, classified, and where the in-scope ones landed |
| [Dogfood session, 2026-09-03](plans/dogfood-2026-09-03.md) | running the harness on a real review; `docs/dogfood/structured-traffic/` is the resulting workspace |

## Extension points

* [plugins/README.md](../plugins/README.md) — the plugin SPI, every boundary, and where each
  one is enforced.
* [benchmarks/README.md](../benchmarks/README.md) — how the performance numbers are produced.
