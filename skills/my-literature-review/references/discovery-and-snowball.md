# Discovery and snowballing

Use this reference for multi-source searches and citation expansion.

## Search record

For every source/query pair preserve:

- normalized query and source-specific translation;
- source, retrieval timestamp, filters, cursor/page boundary, and result count;
- returned stable identifiers and raw metadata provenance;
- rate-limit, authentication, parsing, access, or interruption status;
- deduplication and screening decisions made afterward.

An unsuccessful request is not a zero-result search. Keep the failure visible and exclude it from coverage claims.

## Source selection

Choose sources from the question and domain. Prefer stable APIs and indexes with reproducible metadata. Use broad indexes for recall and authoritative registries or publisher metadata for identity confirmation. Preprints supplement rather than silently replace a published Version.

Venue rank is optional external metadata. Record the ranking system, edition/year, retrieved-at time, and matched venue. Never use rank as a substitute for relevance, validity, or evidence quality.

## Identity resolution

1. Match exact DOI or stable source identifier.
2. Link known preprint/published identifiers as Versions of one Work when provenance supports the relation.
3. Use title, authors, year, and venue similarity only to propose a match.
4. Send ambiguous matches to identity review.

Keep source records so an identity decision can be reversed without losing provenance.

## Snowballing

For each accepted seed:

- extract backward references from an authorized Artifact;
- obtain forward citations from recorded discovery providers;
- persist direction, seed, provider, retrieval time, and depth;
- screen newly discovered candidates under the same protocol;
- stop at the declared depth, saturation rule, budget, or cutoff.

Citation direction alone supports only the `cites` relation. Any stronger semantic relation requires anchored Evidence.
