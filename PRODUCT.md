# Research Harness — PRODUCT.md

**Status:** Product design baseline  
**Version:** 0.1  
**Primary mode:** Personal research workstation  
**Primary users:** Individual researchers conducting literature-heavy technical research and academic writing  
**Deployment model:** Local-first, single-user, multi-client  
**Reference architecture:** Independent research core with plugin/profile ideas inspired by modern agent harnesses; not a fork or runtime dependency of DeepSeek Harness.

---

## 1. Product Summary

Research Harness is a local-first research operating system for evidence-grounded literature research and academic writing.

It is not a PDF chatbot, not a generic RAG application, and not an autonomous multi-agent swarm. Its purpose is to maintain a durable, inspectable chain from **source → evidence → interpretation → claim → synthesis → manuscript**, while allowing multiple interfaces and model providers to work over the same research state.

The product should support four daily interaction surfaces without duplicating research logic:

1. **CLI** for reproducible and scriptable workflows.
2. **Web cockpit** for corpus inspection, evidence review, claim auditing, conflicts, and research state navigation.
3. **VS Code integration** for manuscript-centric claim/citation auditing and research notes.
4. **Agent-host integrations** for Claude, ChatGPT, and future hosts through a provider-neutral protocol layer.

The core product principle is:

> **Models may propose; evidence must justify; the researcher decides.**

A second principle is equally important:

> **Conversation is not project knowledge. Only accepted research objects are project knowledge.**

---

## 2. Problem Statement

Current research workflows built around chat assistants, PDF readers, web search, reference managers, and LaTeX editors fragment scientific state across tools and conversations. This creates recurring problems:

- a model remembers that a paper “said something” without preserving the exact source location;
- author claims, measured results, and researcher inference are silently conflated;
- the same paper is repeatedly re-read because extracted knowledge is not durable;
- literature-wide claims are written from a small subset of papers without explicit coverage accounting;
- negative claims such as “no prior work” are asserted without recorded search provenance;
- revisions to a taxonomy or research decision do not invalidate dependent synthesis and manuscript text;
- citations may exist without actually supporting the sentence in which they appear;
- Claude, ChatGPT, CLI tools, and editor integrations each accumulate separate hidden state;
- vector indexes become accidental knowledge stores even though they are disposable retrieval artifacts.

Research Harness addresses these failures by making evidence, claims, decisions, provenance, and review status first-class objects.

---

## 3. Product Goals

### 3.1 Primary goals

Research Harness must:

- preserve exact provenance from manuscript claims back to source artifacts;
- distinguish source facts, author claims, author interpretations, researcher inference, and model proposals;
- make claim strength, scope, evidence coverage, and counter-evidence explicit;
- allow Claude, ChatGPT, CLI, Web, and VS Code to operate over one shared research state;
- support OpenAI, Anthropic, local models, and future model providers without coupling the domain core to any one provider;
- make research workflows resumable, idempotent, inspectable, and dependency-aware;
- keep canonical scientific state human-readable and Git-versionable;
- use SQLite and indexes as regenerable projections rather than scientific truth;
- reduce unnecessary human review while preserving human epistemic control;
- support evidence-grounded academic drafting and manuscript auditing.

### 3.2 Secondary goals

The design should remain extensible to:

- systematic reviews and PRISMA-style workflows;
- snowball sampling and citation graph research;
- domain-specific interrogation schemas;
- calibration and multi-reviewer protocols;
- additional editors and agent hosts;
- other research domains beyond network traffic and LLM-based intrusion detection.

---

## 4. Non-Goals

The first product should deliberately avoid the following:

- multi-user accounts, teams, permissions, or cloud collaboration;
- a hosted SaaS backend;
- an autonomous agent swarm that owns research decisions;
- a proprietary vector database as canonical storage;
- automatic acceptance of interpretive scientific judgments;
- a universal ontology for every academic discipline;
- full citation-manager replacement in the first version;
- automatic paper writing without claim/evidence constraints;
- forcing a single LLM provider or a single chat host;
- coupling product identity to DeepSeek Harness, Claude Code, ChatGPT, or any other external harness.

---

## 5. Product Principles

### P1. Scientific state must be inspectable
No important conclusion may exist only in a conversation, vector index, model memory, or opaque database row.

### P2. Canonical state and machine projections are different
Git-readable files are the canonical scientific record. SQLite, full-text indexes, vector indexes, caches, and traces are rebuildable projections.

### P3. Workflows are deterministic orchestration; models are bounded judgment workers
Software should enforce invariants. Models should be used only where semantic judgment is actually needed.

### P4. Human authority is explicit
Human override is always permitted, but the override is persisted as a visible research decision.

### P5. Absence of evidence is not evidence of absence
`not_found`, `not_reported`, `absent`, `not_applicable`, and `unclear` must remain distinct states.

### P6. Confidence is not scope
A model can be highly confident about a local observation while the evidence is still insufficient for a field-level statement.

### P7. Embeddings are disposable indexes, not knowledge
Changing embedding models must not change Papers, Evidence, Claims, Decisions, or manuscript provenance.

### P8. Researcher attention is the scarce resource
Human review should be asynchronous, batchable, conflict-first, risk-prioritized, and source-visible.

### P9. No provider-specific concept in the Research Domain Core
Claude-, OpenAI-, DeepSeek-, or local-model-specific behavior belongs in provider adapters.

### P10. Frontends do not own research logic
CLI, Web, VS Code, Claude, and ChatGPT are clients of the same core capabilities.

---

## 6. High-Level Architecture

```text
                           Agent Hosts / Clients
         ┌────────────┬────────────┬────────────┬───────────────┐
         │ CLI        │ Web        │ VS Code    │ Claude/ChatGPT│
         └──────┬─────┴──────┬─────┴──────┬─────┴──────┬────────┘
                └─────────────┴──── Research Protocol API ──────┘
                                      │
                        MCP + local HTTP/JSON-RPC + SDK
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
     Conversation Services      Workflow Runtime          Providers
     sessions · attachments     DAGs · checkpoints        Models/Search/
     context assembler          permissions · review      Parsers/Metadata
             │                        │
             └──────────────┬─────────┘
                            │
                 Research Domain Services
        Work · Evidence · Claim · Decision · RQ · Manuscript
                            │
          ┌─────────────────┼─────────────────────┐
          │                 │                     │
  Canonical Scientific  Durable Private       Local LaTeX
  State + Git           Conversations         Compilation
          │                 │                     │
          └─────────────────┴──────────┬──────────┘
                                      ▼
                         Regenerable Projections
                  SQLite · FTS · vectors · ResearchGraph
```

The recommended product shape is **one local research core with replaceable clients and providers**.

---

## 7. Domain Model

### 7.1 Core entities

The core should define these first-class entities:

- `Work` — a scholarly work independent of a particular file or revision.
- `Version` — arXiv revision, camera-ready, publisher version, author manuscript, etc.
- `Artifact` — PDF, HTML, supplementary material, code archive, dataset document, etc.
- `DocumentBlock` — parsed section, paragraph, table, figure caption, equation, or reference.
- `Evidence` — exact source-grounded evidence with provenance and epistemic classification.
- `Interpretation` — a derived reading of one or more evidence objects.
- `Claim` — a research statement with scope, type, strength, evidence links, and status.
- `ResearchQuestion` — an active question whose resolution may span papers, searches, and claims.
- `Decision` — an explicit researcher-approved choice, including taxonomy changes and epistemic overrides.
- `TaxonomyTerm` / `Taxonomy` — project-approved conceptual classification.
- `SearchRun` — a reproducible discovery operation with sources, queries, filters, results, and screening counts.
- `Synthesis` / `Matrix` — cross-paper comparison objects derived from accepted state.
- `ManuscriptAnchor` — a mapping between manuscript text and accepted Claims/Evidence.
- `ResearchNote` — low-authority capture that can later be promoted to a Claim, Question, or Decision.
- `ResearchEvent` — semantic state-changing event.

Working-context entities are durable but have lower authority than accepted scientific objects:

- `ConversationSession` — a private/local research conversation and its lifecycle.
- `Message` — an append-oriented user, assistant, tool, or system content record.
- `SessionAttachment` — session working material that is not a corpus Artifact until explicitly promoted.
- `ContextPack` — the exact, policy-filtered set of context supplied to one model call.

### 7.2 Stable IDs

Recommended prefixes:

- `W####` — Work
- `V####` — Version
- `A####` — Artifact
- `B####` — Document block
- `E####` — Evidence
- `I####` — Interpretation
- `C####` — Claim
- `RQ####` — Research Question
- `D####` — Decision
- `SR####` — Search Run
- `S####` — Synthesis
- `CS####` — Conversation Session
- `M####` — Message
- `SA####` — Session Attachment
- `CP####` — Context Pack

IDs must be stable across rebuilds of machine indexes.

---

## 8. Persistence Model

### 8.1 Canonical scientific state

Recommended workspace:

```text
my-research-project/
├── research.yaml
├── corpus/
│   └── works/
│       └── W0001/
│           ├── work.yaml
│           ├── versions/
│           ├── artifacts/
│           └── evidence.jsonl
├── claims/
│   ├── C0001.yaml
│   └── ...
├── questions/
│   ├── RQ0001.yaml
│   └── ...
├── taxonomy/
├── decisions/
├── matrices/
├── notes/
├── searches/
├── conversations/
│   └── CS0001/
│       ├── messages.jsonl
│       ├── attachments/
│       └── summary.md
├── manuscript/
│   ├── main.tex
│   ├── references.bib
│   └── figures/
├── events/
│   └── research.jsonl
└── .research/
    ├── research.db
    ├── index/
    ├── cache/
    ├── staging/
    └── traces/
```

### 8.2 Authority rule

Canonical files have scientific authority. `.research/` does not.

Conversation transcripts and their original session attachments are durable, private working records, but they are not accepted scientific state. They are local and excluded from Git publication by default unless the researcher explicitly exports or shares them. Derived conversation summaries and cross-session retrieval indexes may be regenerated and never outrank the transcript or accepted Evidence, Claims, and Decisions.

The semantic event log is a Git-visible audit companion to canonical state, not a second scientific authority and not the only source from which accepted state must be replayed. If an event and its canonical mutation disagree, the workspace is inconsistent and must fail closed pending recovery or repair.

Accepted-state mutation must be recoverable as one logical unit: validate and stage the canonical changes, the matching semantic event, and dependency invalidation under the workspace lock; then commit them through a durable transaction journal. After interruption, recovery must either finish the whole unit or restore the prior canonical state. A half-written object or an event without its matching mutation is never a valid workspace state.

Deleting `.research/` and running:

```bash
research rebuild
```

must reconstruct the machine state without changing accepted research conclusions.

### 8.3 Candidate versus accepted state

All model-generated scientific judgments first enter staging:

```text
raw source
   ↓
model proposal
   ↓
verification
   ↓
review queue
   ↓
researcher acceptance
   ↓
canonical research state
```

No model may directly mutate accepted scientific state.

---

## 9. Evidence Model

Evidence should preserve more than a quote.

Recommended fields:

```yaml
id: E0482
source:
  work: W0017
  version: V0017-2
  artifact: A0017-3
  file_hash: sha256:...
  page: 8
  section_path: [Experiments, Dataset]
  block: B0081
  text_hash: sha256:...
  char_start: 284
  char_end: 516
  bbox: [x1, y1, x2, y2]

content:
  exact_text: "..."

origin:
  type: source_observed

evidence_type:
  type: experimental_setup

strength:
  type: direct

verification:
  status: accepted
  extractor: anthropic/...
  verifier: openai/...
  accepted_by: human
```

### 9.1 Epistemic origin

Core values:

- `source_observed`
- `author_claimed`
- `author_interpreted`
- `researcher_inferred`
- `model_proposed`
- `external_metadata`

### 9.2 Evidence types

Core types:

- `method_description`
- `representation_description`
- `experimental_setup`
- `experimental_result`
- `ablation_result`
- `dataset_description`
- `baseline_description`
- `limitation`
- `author_conclusion`
- `definition`
- `theoretical_result`
- `implementation_detail`
- `deployment_assumption`
- `bibliographic_metadata`

Domain plugins may extend the vocabulary.

### 9.3 Evidence strength

- `direct`
- `indirect`
- `derived`

Derived evidence is permitted but must never be silently displayed as direct evidence.

---

## 10. Claim Model

A Claim is not a free-form sentence with citations. It is a structured object.

Recommended structure:

```yaml
id: C0041
statement: >
  Existing systems employ heterogeneous traffic tokenization schemes.

type: prevalence

semantics:
  subject: existing_systems
  predicate: use
  object: traffic_tokenization
  qualifier:
    property: heterogeneous

scope:
  corpus: structured-traffic-llm
  publication_until: 2026-08

relations:
  supporting: [E0132, E0134]
  contradicting: []
  qualifying: [E0180]

coverage:
  relevant_works: 17
  examined_works: 14
  unresolved_works: 3
  overturn_risk: low_moderate

assessment:
  requested_strength: field_generalization
  allowed_strength: corpus_pattern
  status: qualified
```

### 10.1 Claim types

Core types:

- `descriptive`
- `comparative`
- `prevalence`
- `absence`
- `causal`
- `taxonomic`
- `methodological`
- `synthesis`
- `recommendation`

### 10.2 Claim scope ladder

- `L0 individual`
- `L1 observed_subset`
- `L2 corpus_pattern`
- `L3 field_generalization`
- `L4 universal_or_absence`

### 10.3 Claim status

- `unverified`
- `supported`
- `qualified`
- `contested`
- `unsupported`
- `superseded`

### 10.4 Evidence relation types

- `supports`
- `contradicts`
- `qualifies`
- `contextualizes`
- `exemplifies`
- `incomparable_under_current_evidence`

### 10.5 Claim wording policy

The harness should compute a **maximum defensible wording**, not merely a confidence score.

Examples:

- weak coverage → “among the papers examined”
- several independent supports → “several existing approaches”
- majority under defined corpus → “most systems in the reviewed corpus”
- strong systematic coverage → “existing work generally”
- exhaustive negative search → prefer “we identified no work that…” over an unqualified “no work exists”.

---

## 11. Negative Evidence and Absence Claims

The following states must be different:

- `absent`
- `not_found`
- `not_reported`
- `not_applicable`
- `unclear`

A missing keyword is not sufficient evidence of absence.

Negative-evidence workflows should search:

- relevant sections;
- tables;
- supplementary materials when available;
- synonyms and semantic variants;
- structured paper fields;
- method-specific expectations.

Absence claims require recorded corpus/search coverage and explicit overturn risk.

---

## 12. Numeric Evidence Policy

Numbers require structured provenance.

Recommended representation:

```yaml
value:
  raw: "94.32"
  parsed: 94.32
  unit: percent
metric: F1
dataset: CICIDS2017
condition:
  model: ...
  split: ...
source:
  table: T004
  row: ...
  column: ...
```

The writer must never silently change metric, unit, dataset, experimental condition, rounding, or denominator.

Specific numeric claims must be source-backed. Abstract-only or snippet-only sources may establish existence/direction but not specific measured values.

---

## 13. Work / Version / Artifact Identity

The system must distinguish a scholarly work from its files.

```text
Work
 ├── Version: arXiv v1
 ├── Version: arXiv v2
 ├── Version: camera-ready
 └── Artifact: PDF / HTML / supplement / code
```

Citations primarily reference `Work`. Evidence references the exact `Version` and `Artifact` used.

The identity resolver should reconcile DOI, arXiv, DBLP, Semantic Scholar, OpenAlex, title, author list, venue, and year while preserving source provenance for metadata fields.

---

## 14. Discovery Space versus Research Corpus

External discovery results are not automatically corpus members.

```text
discovery result
   ↓
candidate work
   ↓
screening
   ↓
source acquisition
   ↓
identity verification
   ↓
included corpus
```

Core screening states:

- `discovered`
- `screened`
- `included`
- `excluded`

Exclusion reasons should be persisted.

This distinction allows future PRISMA/systematic-review plugins without changing the core model.

---

## 15. Retrieval Architecture

Research Harness should not use “vector RAG” as its primary architecture.

### 15.1 Recommended indexes

Use five complementary projections:

1. **SQLite structured projection** — metadata, relationships, statuses, joins.
2. **FTS5 lexical index** — exact terminology and fast full-text search.
3. **Local vector index** — semantic similarity and terminology mismatch retrieval.
4. **Citation graph adjacency tables** — references, citations, work lineage, evidence independence.
5. **ResearchGraph projection** — unified typed nodes and edges for stable references, bidirectional navigation, provenance paths, dependency traversal, and context assembly.

No external distributed search infrastructure is needed for a personal workstation.

ResearchGraph uses SQLite node, edge, and adjacency structures alongside FTS5 and local vectors. It projects Project, Session, Message, Attachment, Work, Version, Artifact, document structure, Evidence, Claim, Question, Decision, Synthesis, and manuscript objects. Deterministic edges such as `contains`, `version_of`, `artifact_of`, `cites`, `attached_to`, `anchored_at`, and `mentioned_in` are rebuildable. Scientific edges such as `supports`, `contradicts`, `qualifies`, `derived_from`, and `depends_on` retain their candidate/accepted authority and provenance.

User-facing references such as `@W0017`, `@E0482`, and `@C0041` resolve through stable domain identity rather than disposable database rows. Deep links may address exact local targets, for example `rh://artifact/A0017-3?page=6&block=B0081`. Exact warm reference lookup should target under 100 ms and one- or two-hop local traversal under 250 ms on the personal-scale benchmark corpus.

### 15.2 Query planning

Queries should be classified before retrieval.

Examples:

- “Which papers use CICIDS2017?” → structured query / FTS.
- “Which systems serialize traffic similarly but use different terminology?” → structured filters + semantic search.
- “Does this paper acknowledge encrypted-traffic limitations?” → FTS + semantic search constrained to Discussion/Limitations/Conclusion.
- “Which independent papers challenge C0041?” → claim/evidence graph + citation graph + semantic search.

### 15.3 Retrieval ladder

Prefer higher-authority existing research state before reopening raw sources:

1. accepted Evidence / Claims;
2. accepted paper cards / structured fields;
3. parsed local corpus;
4. citation neighborhood;
5. external discovery.

### 15.4 Retrieval granularity

Use task-specific units:

- Work
- Version
- Section
- Paragraph
- Table
- Table row
- Figure caption
- Evidence span
- Claim

A retrieval chunk is an implementation artifact, not a research object.

Context assembly is a graph-aware retrieval operation. It returns a token- and privacy-bounded `ContextPack` with stable identities, authority labels, provenance paths, and omission reasons. Accepted scientific state ranks above conversation history; private session nodes are excluded whenever provider egress policy forbids them.

---

## 16. PDF / Document Parsing

The parser must produce a structural document IR, not only plain chunks.

```text
Document
├── Pages
├── Sections / Subsections
├── Paragraphs
├── Tables / cells / captions / footnotes
├── Figures / captions
├── Equations
└── References
```

Tables must preserve row/column relationships because many technical research claims are supported primarily by tabular results.

Every Evidence object should remain anchorable to page, block, offsets, hash, and optional bounding box.

If a later parser or artifact revision makes an anchor invalid, the Evidence object becomes stale and requires review rather than silently reattaching elsewhere.

---

## 17. Search and Citation Graph

Recommended discovery providers:

- Semantic Scholar
- OpenAlex
- Crossref
- DBLP
- arXiv
- venue-specific sources where useful
- generic web search as discovery support

Search snippets are discovery hints, never final evidence.

The citation graph should support:

- backward snowballing;
- forward citations;
- predecessor/successor exploration;
- same-work/version resolution;
- evidence-dependence warnings;
- independent-support counting.

Semantic relations such as `extends`, `compares`, or `contradicts` require evidence and verification; raw `cites` can be deterministic from references.

---

## 18. Search Provenance and Coverage

Every significant discovery operation should produce a `SearchRun`.

```yaml
id: SR0019
question: "protocol-compliant adversarial traffic"
sources: [semantic_scholar, openalex, dblp]
queries: [...]
filters: {...}
results:
  discovered: 143
  screened: 38
  included: 11
executed_at: ...
```

Absence/prevalence claims should link to SearchRuns and coverage objects.

Coverage should track:

- defined universe;
- date cutoff;
- discovery runs;
- discovered works;
- screened works;
- relevant works;
- full-text availability;
- examined works;
- unresolved works;
- estimated overturn risk.

---

## 19. Workflow Runtime

Research Harness should use a resumable DAG/build-system model rather than a free-running autonomous loop.

Primary workflow:

```text
INGEST
  ↓
PARSE + NORMALIZE
  ↓
INTERROGATE
  ↓
VERIFY
  ↓
HUMAN REVIEW
  ↓
SYNTHESIZE
  ↓
CLAIM BUILD / AUDIT
  ↓
DRAFT
  ↓
MANUSCRIPT AUDIT
```

Each stage produces artifacts with dependencies, fingerprints, and stale-state propagation.

### 19.1 Idempotence

Re-running a field with a different provider should not rerun unrelated accepted fields.

Every long workflow has a durable run ID, stage checkpoints, input fingerprints, attempt history, and an explicit terminal state. Restarting a process resumes from the last valid checkpoint or safely recomputes an idempotent stage. Checkpoints may preserve proposed/staged work, but they never grant accepted authority.

Example:

```bash
research interrogate W0017 --rerun tokenization --provider openai
```

### 19.2 Dependency invalidation

A changed taxonomy may mark dependent classifications, claims, matrices, and manuscript sections as stale. The system should never silently rewrite them.

### 19.3 Semantic event log

Persist only meaningful state changes in Git-visible events:

- `work.ingested`
- `evidence.proposed`
- `evidence.accepted`
- `evidence.rejected`
- `claim.created`
- `claim.audited`
- `claim.qualified`
- `taxonomy.revised`
- `decision.accepted`
- `manuscript.claim_attached`

Low-level prompts, latency, retrieval traces, and tool output belong in disposable `.research/traces/`.

Events support audit, synchronization diagnostics, and recovery checks. Canonical snapshots remain the source of scientific truth; rebuilding projections must not depend on replaying every historical event.

---

## 20. Model Provider Architecture

### 20.1 Provider abstraction

Support at least:

- OpenAI
- Anthropic
- local model provider
- future providers through adapters

The Research Domain Core must not import or depend on provider-specific concepts.

### 20.2 Capability-based model routing

Workflows should request capabilities, not hard-coded model names.

Example:

```yaml
requirements:
  structured_output: true
  context_tokens: 100000
  reasoning: high
  vision: false
```

A router selects the configured provider/model.

### 20.3 Structured output requirement

Scientific worker roles should return validated schemas. Natural-language prose is presentation, not canonical state.

### 20.4 Cross-model verification

Use cross-provider verification selectively at high-value gates:

- strong literature claims;
- research gaps;
- numeric results;
- counter-evidence;
- submission-ready manuscript claims.

Do not double every routine task by default.

### 20.5 Reproducibility metadata

Persist:

- provider;
- model identifier;
- model configuration;
- workflow/template version;
- timestamp;
- source object IDs;
- structured output;
- concise rationale where useful.

Do not rely on or persist hidden chain-of-thought.

---

## 21. Agent Hosts versus Model Providers

These are separate abstractions.

**Agent Hosts** are where the researcher interacts:

- Claude
- ChatGPT
- CLI
- Web
- VS Code

**Model Providers** are workers used internally by the harness:

- Anthropic
- OpenAI
- local models
- others

Claude can be both a host and an internal model without the two layers being coupled. The same applies to ChatGPT/OpenAI.

---

## 22. Capability Registry

Clients and agent hosts should call named capabilities rather than implementation details.

Recommended initial capabilities:

```text
corpus.search
corpus.ingest
corpus.screen

work.get
work.parse
work.interrogate

retrieval.search
retrieval.resolve_source

 evidence.extract
 evidence.verify
 evidence.accept
 evidence.reject

claim.create
claim.find_support
claim.find_counterevidence
claim.audit

question.create
question.resolve

synthesis.compare
synthesis.build_matrix
synthesis.find_pattern

manuscript.draft
manuscript.attach_claim
manuscript.audit
citation.verify

review.inbox
review.accept_batch
review.resolve_conflict

state.rebuild
state.stale
```

Capabilities must enforce permissions and state transitions server-side. Clients must not bypass them with direct DB writes.

---

## 23. Roles, Not Autonomous Agents

The runtime may use bounded semantic roles such as:

- Evidence Extractor
- Evidence Verifier
- Skeptic / Counter-evidence Finder
- Claim Auditor
- Synthesizer
- Writer

A role is a configuration consisting of:

- objective;
- allowed input objects;
- allowed capabilities;
- output schema;
- provider/model policy;
- write permissions.

Roles do not own independent long-term memory.

Example permissions:

```text
Evidence Extractor
  READ: source document
  WRITE: staging evidence
  FORBIDDEN: accepted evidence

Verifier
  READ: candidate + source
  WRITE: verification result
  FORBIDDEN: rewrite accepted state

Writer
  READ: accepted claims/evidence/decisions
  WRITE: manuscript candidate
  FORBIDDEN: create accepted scientific facts
```

---

## 24. Human Review Model

Default policy: **strict**.

### 24.1 Review tiers

- **Tier 0 — automatic:** deterministic/mechanical facts such as hashes, page count, validated DOI resolution.
- **Tier 1 — quick triage:** directly evidenced extraction such as dataset, metric, traffic unit.
- **Tier 2 — deep review:** taxonomy, methodological limitations, gap claims, claim strength, counter-evidence interpretation.

### 24.2 Review Inbox

Human review should be asynchronous rather than interrupt-driven.

Priority order:

1. conflicts;
2. high-risk scientific claims;
3. stale high-impact objects;
4. ambiguous extractions;
5. routine verified candidates.

### 24.3 Review actions

- Accept
- Accept with qualification
- Edit
- Reject
- Defer
- Request more evidence

Partial acceptance must be supported so a source fact can be accepted while an attached interpretation is rejected.

### 24.4 Batch acceptance

Allow policy-based acceptance only when deterministic conditions are satisfied, for example:

- verifier says supported;
- anchor remains valid;
- no competing candidate;
- field is low-risk;
- no accepted-state conflict.

Model confidence alone is never sufficient.

---

## 25. Conflict-First UX

The system should prioritize disagreement rather than consensus.

Conflicts include:

- extractor versus verifier;
- provider A versus provider B;
- candidate versus accepted state;
- new evidence versus existing Claim;
- revised paper version versus existing anchor;
- taxonomy revision versus dependent classifications.

The UI should show source context, candidate values, competing interpretations, and a diff of proposed state changes.

---

## 26. Web Cockpit

The Web application should be a **conversation-first research workspace**. Conversation is the fastest entry point, while accepted scientific state and full research pages remain the authority and depth surfaces.

The default route uses three panes:

- **Left:** project switcher, session history/search, settings, and research navigation.
- **Centre:** conversation, Markdown/KaTeX rendering, composer, model controls, attachments, `@` references, and `Context used`.
- **Right:** a collapsible inspector for Context, Evidence, Claims, Review Inbox, Conflicts, and Stale objects.

Corpus, Claims, Questions, Synthesis, Taxonomy, Manuscript, Review Inbox, Conflicts, and Stale remain available as full pages. Conversation does not replace evidence review, source inspection, matrices, or manuscript editing.

All Web surfaces use one Research Harness Design System package. It provides semantic tokens, dark/light themes, accessible primitives, research-specific presentation components, and workspace composition. Dark is the default; light is selectable. The package owns presentation only: it does not call the daemon, invoke models, or mutate research state.

The visual language is warm-neutral, dense, and editorial. AI/action accent is distinct from accepted/candidate/qualified/contested/stale/private scientific status. Runtime fonts, icons, styles, and components must work locally without CDN requests. Status is never communicated through colour alone, and WCAG 2.2 AA is the accessibility baseline.

Recommended navigation:

- Overview
- Corpus
- Evidence
- Claims
- Questions
- Synthesis
- Taxonomy
- Manuscript
- Review Inbox
- Conflicts
- Stale

The Overview should emphasize next actions rather than vanity metrics:

```text
Project: Structured Traffic + LLM Detection
42 works · 186 accepted evidence · 31 claims

Attention
- 12 review items
- 3 conflicts
- 5 stale objects
- 2 unsupported manuscript claims

Claim health
- 24 supported
- 5 qualified
- 2 contested

Open questions
- 7 active
```

Evidence review should show the exact source beside the proposed decision.

Conversation output is working context. Explicit actions promote a selection to a Note, Question, Claim candidate, or Decision candidate. Evidence promotion requires a source and exact anchor. No message becomes accepted scientific state automatically.

---

## 27. CLI

The CLI should remain a first-class power interface.

Recommended command family:

```bash
research init
research ingest <file-or-url>
research discover <query>
research screen
research parse <work>
research interrogate <work>
research verify <object>
research inbox
research conflicts
research stale
research review <id>
research compare <field>
research claim create "..."
research claim audit <claim>
research question create "..."
research note add "..."
research draft <section>
research manuscript audit
research rebuild
```

Every important Web operation should map to a core capability and therefore be scriptable.

---

## 28. VS Code Integration

VS Code should focus on manuscript work rather than replicating the full Web cockpit.

Recommended features:

- claim under cursor;
- claim status hover;
- citation-to-evidence navigation;
- manuscript warnings;
- attach existing Claim;
- create Claim from selected text;
- audit selected sentence/paragraph;
- open exact evidence in Web/PDF view;
- quick research note capture;
- stale-section warning.

Example:

```text
C0041 — QUALIFIED
7 supporting works · 1 qualifying work
[Open Claim] [Open Evidence] [Audit]
```

Unlinked substantive prose should be visibly flagged.

---

## 29. Claude and ChatGPT Integrations

Claude and ChatGPT should act as reasoning clients over the same Research Protocol API.

They may:

- ask research questions;
- compare papers;
- challenge claims;
- search for counter-evidence;
- explain decision history;
- draft from accepted claims;
- surface review queues;
- request approval through core review capabilities.

They may not treat conversation content as accepted project knowledge unless it is promoted into a research object.

### Recommended integration protocol

Use **MCP as the primary host integration boundary** where supported, with local HTTP/JSON-RPC and a small SDK as fallbacks for clients that need different transport.

Do not implement separate ChatGPT and Claude business logic.

---

## 30. Manuscript Layer

The manuscript should be downstream of the accepted research graph.

Recommended drafting input:

```text
section purpose
+ approved taxonomy
+ accepted Claims
+ supporting Evidence
+ qualifying/counter Evidence
+ project Decisions
+ style constraints
```

The writer must not invent unsupported scientific facts to improve prose.

The Web Manuscript page should provide a file tree, source editor, real PDF preview produced by a local LaTeX compiler, and a collapsible scientific-audit inspector. The researcher owns the source and every edit/save is explicit. A compile failure shows file/line diagnostics and keeps the last successful PDF visible as stale. Source-to-PDF and PDF-to-source navigation should use SyncTeX when available and degrade honestly when it is not.

Conversation rendering is a separate presentation path: chat messages support Markdown plus inline/display mathematics through KaTeX. KaTeX rendering must never be presented as proof that a complete manuscript compiles.

### 30.1 Claim traceability

Every substantive factual/research sentence should be linkable as:

```text
Manuscript sentence
   ↓
Claim
   ↓
Claim–Evidence relation
   ↓
Evidence
   ↓
Version / Artifact / page / table / span
```

### 30.2 Citation policy

The product should enforce:

- citation key must exist;
- citation must actually support the attached Claim;
- specific numbers require direct source-backed evidence;
- author claims and verified measured results must be distinguished;
- unresolved support becomes a visible `NEEDS SOURCE`/audit warning rather than a fabricated citation.

### 30.3 Manuscript audit

Audit should detect:

- unregistered substantive claims;
- unsupported wording strength;
- citation mismatch;
- unverified numeric claims;
- stale claims after research-state changes;
- manuscript sentence stronger than the accepted Claim;
- claims whose supporting source anchor has become invalid.

### 30.4 Style transformation and semantic diff

Humanization, venue formatting, copy-editing, and other style passes operate only on manuscript candidates. A writing policy must preserve:

- Claim/Evidence/Work/Version/Artifact/Decision IDs and source anchors;
- citation commands/keys, exact quotations, numbers, units, equations, code, and links;
- epistemic qualifiers, population/setting/method scope, comparison conditions, and negative-evidence wording;
- the maximum defensible wording established by the accepted Claim graph.

Each style pass records a semantic diff that identifies propositions added, removed, weakened, or strengthened. A changed candidate must pass manuscript audit and human acceptance before it replaces accepted manuscript text. Style preferences, including punctuation preferences, never outrank scientific meaning or venue requirements.

---

## 31. Research Notes and Questions

Conversation insights should be capturable without automatically becoming accepted knowledge.

`ResearchNote` supports quick capture and later promotion:

```text
Note
  ↓
[Promote to Claim]
[Promote to Question]
[Promote to Decision]
[Discard]
```

`ResearchQuestion` should track status such as:

- `open`
- `partially_answered`
- `answered`
- `blocked`

and link to Claims, SearchRuns, supporting evidence, counter-evidence, and remaining uncertainty.

---

## 32. Plugin and Extension Architecture

The recommended plugin model is **domain extension over invariant core**, not unrestricted code injection into research state.

### 32.1 Plugin categories

A plugin may contribute:

1. **Domain schema** — additional fields and controlled vocabularies.
2. **Interrogation schema** — questions every relevant paper should answer.
3. **Validators** — domain-specific semantic or consistency checks.
4. **Workflow fragments** — optional DAG steps using core capabilities.
5. **Roles/contracts** — domain-specific bounded worker roles.
6. **Search providers** — venue/database connectors.
7. **Writing policies** — domain/venue-specific manuscript constraints.
8. **UI extensions** — optional domain panels or matrix views.

### 32.2 Plugin boundaries

Plugins must not:

- write directly to canonical files without core validation;
- write directly to SQLite as scientific state;
- bypass review gates;
- redefine core meanings of Evidence, Claim, Decision, or accepted state;
- silently expand model permissions;
- create host-specific state.

### 32.3 Plugin manifest

Recommended shape:

```yaml
name: structured-traffic
version: 0.1.0
requires_core: ">=0.1"

contributes:
  schemas:
    - schemas/traffic.yaml
  interrogation:
    - interrogation/paper.yaml
  validators:
    - validators/traffic_unit.py
  workflows:
    - workflows/traffic_interrogate.yaml
  roles:
    - roles/domain_reviewer.yaml
  writing_policies:
    - writing/q1-survey.yaml
```

### 32.4 Initial plugins

Recommended first plugins after the generic core is stable:

- `academic-review`
- `structured-traffic`
- `network-security`
- `systematic-review`
- `academic-writing`

Existing skill assets can later be audited and adapted into these extension points rather than being copied directly into the core.

### 32.5 Research skill adaptation contract

Imported skills are design inputs, not trusted runtime components. Each asset must be classified as `reuse-as-contract`, `adapt-to-plugin`, `inspiration-only`, or `exclude` before integration.

An adapted skill must declare:

- target plugin, role, workflow fragment, or writing policy;
- input and output object types plus epistemic authority;
- allowed capabilities and forbidden mutations;
- provider/host/tool dependencies and egress needs;
- checkpoint/resume behavior for long operations;
- review gates, stale dependencies, and failure/coverage reporting.

Skills may propose canonical objects only through Research Core capabilities. They must not write accepted files or projections directly, collapse Work/Version/Artifact identity, convert failed searches into zero-result evidence, or infer novelty from missing matrix cells.

Initial decisions are recorded in `skills/INVENTORY.md`: `humanizer` is adapted as an `academic-writing` policy; the former `my-literature-review` monolith is `inspiration-only`, while its provider-neutral discovery, snowballing, ingestion handoff, classification, and coverage concepts are adapted as bounded plugin/workflow contracts.

---

## 33. Domain Plugin: Structured Traffic / LLM Detection

For the current research project, the domain plugin should initially support:

```text
traffic unit
representation family
raw information retained
derived information
serialization
tokenization
LLM architecture
LLM role
training strategy
detection target
dataset
dataset age
encryption status
train/test partition
evaluation unit
baselines
metrics
ablations
robustness evaluation
deployment assumptions
author-stated limitations
researcher-observed limitations
```

Recommended project taxonomy starts with:

- raw sequential
- field-based
- behavior-aware

but taxonomy remains a researcher-approved project decision, not a universal domain fact.

---

## 34. Security, Privacy, and Secrets

Because this is a personal local research workstation, privacy should be a default property.

Recommended rules:

- source PDFs remain local unless a configured provider call requires content transfer;
- every provider must declare what content leaves the workstation;
- API keys live in environment variables or OS keychain, never in canonical workspace files;
- traces may contain source text and should be disposable and optionally redacted;
- per-project policy can disable external-model egress for sensitive corpora;
- external network access should be visible and configurable;
- no automatic background upload of the research corpus;
- source file hashes are recorded to detect mutation.

---

## 35. Recommended Implementation Stack

The following stack best matches a personal local-first research workstation and keeps the architecture simple.

### Core/runtime

- **Python 3.12+** — strongest ecosystem fit for PDF parsing, scholarly APIs, ML tooling, structured data, and local model integrations.
- **Pydantic** — canonical schemas and provider-neutral structured outputs.
- **SQLite + FTS5** — relational projection and lexical search.
- **SQLAlchemy or SQLModel** — projection/query layer.
- **Typer** — CLI.
- **FastAPI** — local daemon/API for Web, VS Code, and host integrations.
- **NetworkX or plain SQLite adjacency tables initially** — citation/dependency graph; avoid a graph database until proven necessary.
- **FAISS, LanceDB, or another embedded local vector index** — semantic retrieval; keep it fully rebuildable.

### Parsing

Use a parser abstraction so the implementation can evolve. Start with a robust PDF text/layout parser and preserve page geometry. Table extraction should be separately replaceable.

### Web

- **React + TypeScript** frontend.
- A first-class **Research Harness Design System** package in the pnpm workspace for semantic tokens, dark/light themes, strict TypeScript primitives, research presentation components, and layout composition.
- Dark theme by default with optional light theme; local runtime fonts/icons and no Design System CDN dependency.
- Keep KaTeX, PDF.js, source-editor engines, and SyncTeX/compiler integrations behind Web adapters rather than primitive component dependencies.
- Run against the local FastAPI daemon.
- A desktop shell such as Tauri can be added later if packaging becomes important; do not make it a core dependency initially.

### VS Code

- TypeScript extension calling the local Research Protocol API.

### Claude / ChatGPT

- MCP server exposing stable Research capabilities.
- Local HTTP/JSON-RPC fallback for clients where MCP is not the best transport.

### Packaging

Start as a local developer tool installable with a single command. Avoid distributed services, Redis, Elasticsearch, Kubernetes, or remote databases.

---

## 36. API and State Mutation Policy

All accepted-state mutation must occur through explicit commands/capabilities.

Examples:

```text
propose_evidence(...)
verify_evidence(...)
accept_evidence(...)
qualify_claim(...)
accept_decision(...)
attach_claim_to_manuscript(...)
```

Direct file editing remains technically possible because the state is human-readable, but the supported product path should validate and normalize edits on next load/rebuild.

Every mutation should produce:

- validation result;
- semantic diff;
- event entry;
- dependency invalidation set.

---

## 37. Staleness and Dependency Graph

Derived artifacts should declare dependencies.

Examples:

```text
Taxonomy D0012
   ↓
Paper classifications
   ↓
Representation matrix
   ↓
Claim C0021
   ↓
Manuscript §3.1
```

When an upstream object changes, downstream objects become `stale`, not silently rewritten.

Stale priority should reflect scientific impact:

- manuscript claim affected;
- accepted Claim affected;
- synthesis affected;
- classification affected;
- low-level index only.

---

## 38. Researcher Overrides

The system may recommend a maximum defensible claim strength, but the researcher retains authority.

An override must create a visible Decision:

```yaml
id: D0027
type: epistemic_override
claim: C0041
auditor_recommendation: corpus_pattern
researcher_selected: field_generalization
rationale: "..."
status: accepted
```

This preserves human control without making overrides invisible.

---

## 39. Research Session Model

A research session is a durable, private conversation bound to one project. Its transcript is shared with the model as working context subject to the active context window, token budget, model capability, and egress policy. Relevant excerpts or summaries from earlier sessions may be retrieved automatically, but accepted Evidence, Claims, Decisions, and anchors have higher authority than chat memory.

Each model call records a `ContextPack` and exposes a human-readable `Context used` receipt. The receipt names included and omitted messages, sessions, attachments, Evidence, Claims, and corpus blocks with reasons. Cross-session indexes and summaries are rebuildable projections; transcripts remain durable source records.

All attached files, including PDFs, are session-only by default. `Save to corpus` is an explicit promotion that resolves Work/Version/Artifact identity and runs normal ingestion. It never creates accepted Evidence or Claims automatically.

A productive daily loop should look like:

```text
DISCOVER
  ↓
READ
  ↓
CAPTURE
  ↓
VERIFY
  ↓
REVIEW
  ↓
SYNTHESIZE
  ↓
WRITE
  ↓
AUDIT
```

The product should make it obvious at session end:

- what was added;
- what remains unreviewed;
- what conflicts appeared;
- which Claims changed strength;
- what manuscript content became stale;
- what open Questions remain.

---

## 40. MVP Product Boundary

The first usable product should be intentionally narrow but architecturally complete.

### Must-have

- local project initialization;
- Work/Version/Artifact identity;
- local PDF ingest;
- structural parsing with page anchors;
- canonical YAML/JSONL state;
- SQLite/FTS rebuildable projection;
- local semantic index;
- Evidence objects and review workflow;
- Claim objects and basic claim audit;
- Decisions and taxonomy;
- strict review inbox;
- OpenAI provider adapter;
- Anthropic provider adapter;
- provider-neutral structured output contracts;
- CLI;
- local API daemon;
- MCP capability server;
- basic Web evidence/claim/review cockpit;
- manuscript claim attachment and citation audit for LaTeX;
- semantic event log and stale dependency propagation.

### Next experience milestone

After the core v1.0 boundary, the next coherent product milestone is the conversation-first research workspace:

- persistent local sessions with current- and cross-session context;
- three-pane conversation UI and full research pages;
- visible `Context used` receipts and explicit promotion actions;
- session-only image/PDF attachments with `Save to corpus`;
- Markdown and KaTeX chat rendering;
- unified rebuildable ResearchGraph references and traversal;
- a real LaTeX source/editor/compiler/PDF/audit workspace.

These capabilities must preserve all existing authority, review, provenance, rebuildability, privacy, and provider-neutrality rules. Detailed sequencing belongs in `ROADMAP.md` and the design specifications under `docs/superpowers/specs/`.

### Should-have soon after

- external paper discovery;
- citation graph / snowballing;
- SearchRun coverage accounting;
- advanced absence/prevalence auditing;
- richer Web matrix views;
- VS Code extension;
- selective cross-model verification;
- structured-traffic domain plugin;
- academic-writing policy plugin.

### Explicitly later

- systematic-review/PRISMA plugin;
- multi-reviewer calibration;
- advanced reviewer panels;
- Tauri desktop packaging;
- plugin marketplace/distribution;
- multi-user collaboration;
- remote synchronization.

Detailed sequencing belongs in `ROADMAP.md` rather than this document.

---

## 41. Success Criteria

Research Harness is successful when a researcher can:

1. ingest a technical paper once and retain durable, source-anchored research knowledge;
2. ask Claude and ChatGPT about the same project and receive answers grounded in the same accepted state;
3. switch model providers without migrating scientific state;
4. inspect exactly why a paper has a given classification;
5. audit a literature-wide statement and see supporting, contradicting, and qualifying evidence;
6. see whether claim wording exceeds corpus coverage;
7. reconstruct why a taxonomy or claim changed months later;
8. delete machine indexes and rebuild them without changing scientific conclusions;
9. click from manuscript sentence → Claim → Evidence → exact PDF/table span;
10. detect unsupported or citation-mismatched manuscript prose before submission;
11. review model output in batches instead of repeatedly answering interruptive approval questions;
12. preserve research state independently of any Claude, ChatGPT, Web, or editor conversation.
13. reopen durable local research conversations and see exactly which context each model response used;
14. attach a PDF or image without changing the corpus, then explicitly save the chosen file through Work/Version/Artifact identity;
15. resolve and traverse stable `@` references quickly across sessions, sources, Evidence, Claims, and manuscript anchors;
16. render mathematical discussion in chat and compile owned LaTeX source into a real, auditable PDF.

---

## 42. Acceptance Tests for the Core Product

The architecture should not be considered complete until the following behaviors are demonstrable.

### A. Provider independence
The same Evidence verification workflow can run with Anthropic or OpenAI without changing canonical schemas.

### B. Host independence
A Claim created through CLI can be inspected through Web, VS Code, Claude, and ChatGPT without duplication.

### C. Rebuildability
Deleting `.research/` and rebuilding reproduces the same accepted Works, Evidence, Claims, Decisions, and manuscript links.

### D. Provenance
Every accepted Evidence object opens the exact source artifact and location it was accepted from.

### E. Epistemic separation
An author claim cannot automatically become a verified experimental result.

### F. Negative evidence discipline
`not_reported` cannot be converted to `absent` without an explicit review path.

### G. Claim-strength discipline
A claim with incomplete coverage is prevented from silently escalating from corpus-level to universal wording.

### H. Human review
A model cannot bypass the strict review gate for interpretive scientific state.

### I. Stale propagation
Changing an accepted taxonomy marks dependent matrices/Claims/manuscript anchors stale.

### J. Citation integrity
A manuscript citation that exists but does not support the attached Claim is flagged.

### K. Atomic accepted-state mutation
Interrupting a multi-file canonical mutation leaves either the complete prior state or the complete new state with its matching event and invalidation set; recovery rejects any mismatch.

### L. Style-pass semantic preservation
A humanization or venue-style pass that changes a protected span or strengthens/weakens a proposition is prevented from replacing accepted manuscript text until semantic audit and human review succeed.

### M. Conversation authority and context receipt
A reopened session retains its transcript; the model receives policy-allowed current and relevant prior context; accepted scientific state outranks conflicting chat; and `Context used` records every included or omitted class with a reason.

### N. Attachment promotion boundary
Dragging an image or PDF creates only a session attachment. `Save to corpus` explicitly resolves Work/Version/Artifact identity, survives partial failure without losing the session copy, and does not accept Evidence automatically.

### O. ResearchGraph rebuild and reference resolution
After deleting `.research/`, rebuilding resolves the same stable `@` references and scientific relations from durable sources. Candidate edges remain candidate, privacy filters remain enforced, and exact/two-hop lookups meet the measured workstation budgets.

### P. LaTeX rendering and source ownership
Chat renders Markdown mathematics, while the Manuscript page compiles user-owned source through a real local LaTeX toolchain, preserves the last good PDF on failure, reports file/line errors, and applies model suggestions only as explicit reviewed diffs.

### Q. Shared Design System integrity
Conversation, research, and manuscript surfaces consume one local Design System package. Dark/light themes preserve semantic meaning and WCAG 2.2 AA accessibility; keyboard interactions work; runtime assets require no CDN; and page code cannot silently fork primitive or raw theme definitions.

---

## 43. Key Risks and Recommended Mitigations

### Risk: Over-engineering the ontology
**Mitigation:** Keep core entities small; push domain vocabulary into plugins.

### Risk: Human review fatigue
**Mitigation:** conflict-first queue, batch operations, risk tiers, source-beside-decision UI.

### Risk: False precision from model confidence
**Mitigation:** use categorical verification status as primary UI; confidence is secondary metadata.

### Risk: Parser instability
**Mitigation:** source hashes, anchor hashes, page geometry, stale detection, parser abstraction.

### Risk: Model cascade hallucination
**Mitigation:** candidate/accepted separation, bounded roles, verifier receives source + candidate, no agent-to-agent claims as trusted facts.

### Risk: Provider lock-in
**Mitigation:** capability-based routing, Pydantic schemas, provider adapters, MCP/API host boundary.

### Risk: RAG becoming the de facto knowledge model
**Mitigation:** accepted research objects are queried before raw-vector retrieval; indexes are disposable.

### Risk: Plugin bypass of scientific invariants
**Mitigation:** plugins call core capabilities and cannot directly mutate accepted state.

### Risk: Scope explosion
**Mitigation:** personal workstation first; defer collaboration and SaaS requirements.

---

## 44. Recommended Product Decisions — Locked Baseline

The following decisions should be treated as the baseline unless future evidence shows a concrete need to change them:

1. Build an **independent Research Core**, using DeepSeek Harness only as architectural inspiration.
2. Support **CLI + Web + VS Code + agent hosts** as clients of one core.
3. Support **Claude and ChatGPT equally** through a host-neutral protocol boundary.
4. Separate **Agent Hosts** from **Model Providers**.
5. Use **Git-readable canonical state + SQLite/index projections**.
6. Use **strict human-in-the-loop** as the first default policy.
7. Use **bounded roles**, not autonomous persistent agents.
8. Use **resumable deterministic workflows** with model calls inside explicit semantic steps.
9. Make **Evidence, Claims, Decisions, Questions, and SearchRuns** first-class.
10. Treat **Work / Version / Artifact** separately.
11. Treat **embeddings as disposable**.
12. Require **structured model outputs** for scientific workflows.
13. Use **selective cross-model verification** for high-value scientific gates.
14. Use **SQLite + FTS5 + embedded local vectors + adjacency tables** before considering specialized search/graph infrastructure.
15. Use **MCP first** for Claude/ChatGPT-style host integration, with local HTTP/JSON-RPC fallback.
16. Use **Python + Pydantic + FastAPI + Typer** as the recommended core implementation stack.
17. Keep domain logic such as structured network traffic in **plugins**, not the core.
18. Preserve **researcher override**, but require visible Decision provenance.
19. Require **claim-to-evidence manuscript traceability**.
20. Optimize the UX for **minimum unnecessary human attention**, not maximum autonomy.
21. Treat canonical snapshots as scientific authority and the semantic event log as an **atomic audit companion**, with journaled recovery for accepted-state mutations.
22. Treat imported skills as **audited plugin/contract inputs**, never trusted Research Core code by default.
23. Keep humanization and other style transforms **candidate-only**, protected by semantic diff, manuscript audit, and human acceptance.
24. Make the Web client a **conversation-first three-pane research workspace** while retaining full research pages.
25. Keep conversation transcripts **durable, private/local working context** that never outranks accepted scientific state.
26. Make all session attachments, including PDFs, **session-only by default** and require explicit **Save to corpus** promotion.
27. Use a unified, rebuildable **ResearchGraph** over SQLite/FTS/local vectors for stable references, provenance traversal, and context assembly; do not make it canonical authority.
28. Render chat mathematics with **KaTeX**, but require **real local LaTeX compilation and PDF output** for the manuscript workspace.
29. Keep `deepseek-harness/` as a **reference submodule only**, with no Research Harness runtime dependency.
30. Use one first-class **Research Harness Design System** package across Web surfaces, with dark default/light optional themes, local runtime assets, accessible typed components, and presentation-only boundaries.

---

## 45. Product Definition in One Sentence

> **Research Harness is a local-first, provider-neutral research operating system that converts scholarly sources into durable evidence, auditable claims, explicit research decisions, and traceable manuscript prose across CLI, Web, VS Code, Claude, and ChatGPT.**
