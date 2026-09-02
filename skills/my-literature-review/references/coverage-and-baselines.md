# Coverage, gap statements, and baselines

Use this reference before a literature-wide claim or baseline recommendation.

## Coverage report

A defensible report names:

- universe definition, source list, query families, filters, languages, and cutoff;
- discovered, deduplicated, screened, included, full-text-examined, and unresolved counts;
- unavailable sources and failed/incomplete searches;
- backward/forward snowball depth and stopping condition;
- likely blind spots and overturn risk.

Coverage is evidence about the search process. It is not proof that an undiscovered paper does not exist.

## Gap ladder

Choose the strongest wording the record supports:

1. `not_observed_in_examined_artifact`
2. `not_reported_by_authors`
3. `not_found_in_recorded_searches`
4. bounded prevalence or absence estimate with an explicit denominator
5. exhaustive absence claim only when the universe is genuinely closed and completely checked

Empty cells, search snippets, venue rank, and model agreement cannot advance a statement up this ladder.

## Baseline comparison

Define comparison axes before ranking candidates:

- task and target;
- dataset/population and split;
- metric and evaluation unit;
- input representation and information access;
- compute, latency, deployment, and privacy conditions;
- code/data availability and reproducibility;
- publication/version status.

Return several candidates when different axes imply different baselines. Label trade-offs and missing fields. A baseline recommendation is a reviewable Decision/Claim candidate, not an automatic project choice.
