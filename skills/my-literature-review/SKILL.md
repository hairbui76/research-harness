---
name: my-literature-review
description: Use when surveying research literature, finding related work or baselines, expanding from seed papers, or assessing whether a literature-wide claim is supported by documented search coverage.
metadata:
  version: "3.0.0-rh1"
  adapted_for: "research-harness"
  source_version: "2.1.0"
  status: "contract-only-until-capabilities-exist"
---

# Literature review for Research Harness

## Overview

Use auditable discovery and screening to build candidate research objects. Search results are leads, not Evidence; model classifications and gap statements are proposals, not accepted conclusions.

This skill defines the future literature-review plugin contract. Until the named Research Harness capabilities exist, operate read-only and return a proposed import packet. Never pretend that a result was persisted, reviewed, or accepted.

## Choose the review mode

- **Breadth review:** start from a research question and a documented query plan.
- **Seed expansion:** start from one or more identified Works and follow backward references and forward citations.
- **Baseline search:** use either route, then compare candidates against explicit task, data, metric, compute, deployment, and reproducibility criteria.

A DOI, URL, title, or local paper may identify a seed, but it does not collapse the distinction between Work, Version, and Artifact.

## Required boundaries

- Use provider-neutral search and model contracts. Do not require a particular host, browser extension, or model vendor.
- Use only researcher-authorized network access and credentials. Never place secrets in URLs, logs, prompts, or generated files.
- Treat rate limits, authentication failures, bot challenges, and unavailable full text as distinct conditions. Record them as coverage limitations; do not bypass access controls.
- Keep preprints, accepted manuscripts, proceedings versions, and publisher artifacts as related but distinct records.
- Deduplicate at the Work level while preserving every known Version and Artifact.
- Keep search snippets and abstracts labeled as metadata/abstract-only. They cannot support full-text observations.
- Route all scientific mutations through Research Core capabilities. Do not write canonical files, projections, or accepted manuscript text directly.
- Every interpretive classification, baseline recommendation, research-gap statement, and absence claim enters staging and requires review.

## Review workflow

### 1. Scope and query plan

Capture:

- research question and intended deliverable;
- concepts, synonyms, exclusions, date/language/venue bounds;
- sources to search and stopping conditions;
- known seeds and baseline criteria;
- coverage limitations that would make a strong absence claim indefensible.

The query plan is a candidate until the researcher accepts it.

### 2. Discovery

Prefer structured scholarly sources suited to the domain, such as OpenAlex, Crossref, Semantic Scholar, DBLP, PubMed, or arXiv. Use publisher and venue indexes where authorized. Record each query, source, retrieval time, filters, counts, pagination boundary, and error.

Read [discovery-and-snowball.md](references/discovery-and-snowball.md) when running multi-source discovery or seed expansion.

### 3. Identity resolution and screening

Resolve candidates into:

```text
Work
  -> Version
      -> Artifact
```

Use DOI and stable source identifiers first, then normalized bibliographic similarity. Ambiguity creates an identity-review item rather than an automatic merge. Record inclusion, exclusion, duplicate, unresolved, and unavailable-full-text decisions with reasons.

### 4. Snowballing

For each seed, record backward and forward edges separately. Citation edges may establish `cites`; semantic relations such as `extends`, `contradicts`, or `uses-method-from` require source-backed Evidence and verification.

### 5. Ingestion and reading

Ingest only authorized artifacts. Preserve artifact hash, source, retrieval time, access status, parser provenance, and anchorability. Read [reading_framework.md](references/reading_framework.md) when extracting comparable paper information.

### 6. Classification and synthesis

Classifications are multi-label proposals linked to the passages or metadata that support them. Distinguish author-stated claims from researcher interpretations. A synthesis matrix must expose missing, abstract-only, unresolved, and conflicting fields instead of filling them by inference.

### 7. Coverage, gaps, and baselines

Read [coverage-and-baselines.md](references/coverage-and-baselines.md) before making literature-wide statements or recommending baselines.

A gap result contains:

- the bounded universe and cutoff date;
- SearchRun IDs and screening counts;
- examined and unresolved Works;
- supporting and counter-evidence;
- overturn risk;
- maximum defensible wording.

Use wording such as “within the recorded searches, we identified no work that …” when coverage is strong but non-exhaustive. Never equate an empty matrix cell with novelty.

### 8. Review handoff

Return proposed objects and unresolved decisions to the Research Harness Review Inbox. A downstream paper-review skill may add candidate judgments, but it receives no authority to mutate accepted state and is not a required dependency of this skill.

## Output contract

When Research Harness capabilities are available, produce IDs/references for:

- QueryPlan candidate and SearchRun records;
- Work/Version/Artifact candidates and identity conflicts;
- screening decisions and citation edges;
- classification and synthesis candidates with provenance;
- coverage report, baseline comparison, and proposed Claims;
- Review Inbox items and stale dependencies.

In contract-only mode, return the same structure as a clearly labeled proposed import packet. Include failures and unresolved items; do not report them as zero results.

## Stop conditions

Stop and ask for researcher direction when:

- identity ambiguity would merge materially different Works;
- access requires bypassing a control or accepting new terms;
- the requested absence/novelty wording exceeds recorded coverage;
- baseline criteria are missing and different choices would change the ranking;
- full text would be sent to an external model without an applicable egress policy.

## Source and adaptation status

Adapted from the repository-imported `my-literature-review` v2.1.0. The former seven-agent orchestration, host-specific browser flow, direct file writes, static venue-rank table, and hard dependency on `academic-paper-reviewer` are intentionally not part of this contract.
