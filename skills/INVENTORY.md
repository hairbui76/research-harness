# Research skill adaptation inventory

Status: initial audit for the Research Harness plugin boundary. This inventory records design decisions only; it does not imply that the corresponding Research Core capabilities or plugins have been implemented.

## Assessed assets

| Source asset | Classification | Intended target | Authority | Required boundary |
|---|---|---|---|---|
| `humanizer` | `adapt-to-plugin` | `academic-writing` writing policy | manuscript candidate only | Preserve accepted Claims/Evidence/Decisions, protected spans, scope, qualifiers, citations, numbers, and anchors; require semantic diff, manuscript audit, and human acceptance. |
| `my-literature-review` monolith v2.1.0 | `inspiration-only` | none as a monolith | none | Former host-specific orchestration and direct-file workflow conflict with core capabilities, review gates, durable runs, and Work/Version/Artifact identity. |
| `my-literature-review`: query planning and discovery | `adapt-to-plugin` | discovery workflow fragment and search-provider adapters | candidate metadata only | Produce QueryPlan/SearchRun candidates; search results and snippets are not Evidence. |
| `my-literature-review`: snowballing | `adapt-to-plugin` | citation graph workflow fragment | deterministic `cites` candidates | Stronger semantic relations require anchored Evidence and review. |
| `my-literature-review`: collection | `adapt-to-plugin` | Work/Version/Artifact ingest handoff | candidate identity/artifact records | Deduplicate Works without merging Versions or Artifacts; all persistence goes through core capabilities. |
| `my-literature-review`: classification and gap finding | `adapt-to-plugin` | synthesis and coverage workflow fragments | model-proposed candidates only | Multi-label classification; absence/novelty wording is bounded by SearchRun coverage and overturn risk. |
| Claude-in-Chrome CAPTCHA protocol | `exclude` | none | none | Host-coupled and attempts to operationalize access-control challenges. Record the access limitation instead. |
| Static venue-rank table | `exclude` | none | none | Stale, unprovenanced ranking data. If needed later, treat rank as timestamped external metadata. |
| Hard dependency on imported `academic-paper-reviewer` | `exclude` | optional future review contract | none | The imported copy references missing resources and cannot be a required runtime dependency. |

## Retained skill surfaces

```text
skills/
├── humanizer/
│   ├── SKILL.md
│   ├── LICENSE
│   └── agents/openai.yaml
└── my-literature-review/
    ├── SKILL.md
    ├── agents/openai.yaml
    └── references/
        ├── discovery-and-snowball.md
        ├── coverage-and-baselines.md
        └── reading_framework.md
```

## Pending audit

The remaining imported folders (`academic-paper-reviewer`, `deep-research`, `grill-with-docs`, and `slr-writer`) are not approved for integration by this document. They remain pending the Phase 14 audit and must not be treated as Research Core dependencies.
