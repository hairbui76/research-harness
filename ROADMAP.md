# Research Harness Implementation Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this roadmap task-by-task. Each phase is a review gate; do not start the next phase until the current gate passes.

**Goal:** Build the local-first, provider-neutral Research Harness defined in `PRODUCT.md`, progressing from a trustworthy canonical research state to source-grounded evidence, auditable claims, manuscript traceability, multi-host access, and domain plugins.

**Architecture:** The implementation is a Python 3.12 core with Git-readable canonical scientific state and regenerable SQLite/FTS/vector projections. LLMs are bounded semantic workers behind provider-neutral contracts; accepted-state mutation flows only through validated capabilities. CLI, Web, VS Code, Claude, and ChatGPT remain replaceable clients of the same application services.

**Tech Stack:** Python 3.12+, Pydantic v2, FastAPI, Typer, SQLite/FTS5, SQLAlchemy 2.x, PyMuPDF-based first parser adapter, embedded local vector index, pytest, Hypothesis where useful, Ruff, mypy/pyright, React + TypeScript, pnpm, VS Code Extension API, MCP.

**Spec:** `PRODUCT.md`

## Global Constraints

- Canonical scientific state is human-readable and Git-versionable; `.research/` is always regenerable.
- No model-generated interpretive scientific state may bypass staging, verification, and the strict human review gate.
- No Claude-, OpenAI-, Anthropic-, or host-specific concept may enter the Research Domain Core.
- No frontend may write SQLite or canonical files directly; all supported mutation flows pass through application capabilities.
- `Work`, `Version`, and `Artifact` are distinct identities from the first schema version.
- Evidence must remain anchorable to an exact source artifact and must become stale rather than silently reattach when provenance breaks.
- `not_found`, `not_reported`, `absent`, `not_applicable`, and `unclear` remain distinct states.
- Confidence never substitutes for claim scope or corpus coverage.
- Embeddings, FTS indexes, caches, and model traces are disposable projections.
- Workflows are resumable and idempotent; changing one field/provider must not invalidate unrelated accepted state.
- Human overrides are allowed only as explicit `Decision` objects with rationale and provenance.
- Cross-model verification is selective and reserved for high-value scientific gates rather than routine extraction.
- Personal workstation first: no multi-user auth, SaaS backend, remote synchronization, Redis, Elasticsearch, graph database, or Kubernetes before a demonstrated need.
- Tests must not depend on the live structured-traffic research corpus. Unit/integration tests use synthetic fixtures; the real project is a dogfood acceptance corpus.

---

## 1. Delivery Strategy

The product should be built as a sequence of **vertical, usable research loops**, not as separate backend/frontend projects that only integrate at the end.

The critical path is:

```text
Foundation
   ↓
Canonical State
   ↓
Ingest + Parse + Provenance
   ↓
Rebuildable Projections + Retrieval
   ↓
Provider Runtime
   ↓
Evidence + Human Review
   ↓
Claims + Epistemic Audit
   ↓
Manuscript Traceability
   ↓
Protocol API + MCP
   ↓
Web Cockpit
   ↓
Discovery + Coverage
   ↓
VS Code + Plugins
```

Three product cuts should remain continuously runnable:

- **v0.1 — Evidence Loop:** initialize → ingest → parse → extract → verify → review → rebuild.
- **v0.2 — Claim Loop:** evidence → synthesis → claim → audit → manuscript attachment → manuscript audit.
- **v0.3 — Multi-Host Workstation:** local daemon → MCP → Web → Claude/ChatGPT over one state.
- **v0.4 — Literature Research Loop:** discovery → SearchRun → citation graph → coverage → prevalence/absence audit.
- **v1.0 — Research Workstation:** VS Code + plugin SPI + structured-traffic plugin + real-project dogfood acceptance.

Do not implement later-scope features merely because interfaces leave room for them.

---

## 2. Repository Shape to Lock Before Feature Work

Recommended monorepo:

```text
research-harness/
├── PRODUCT.md
├── ROADMAP.md
├── pyproject.toml
├── uv.lock
├── README.md
├── src/
│   └── research_harness/
│       ├── domain/
│       │   ├── ids.py
│       │   ├── enums.py
│       │   ├── errors.py
│       │   ├── work.py
│       │   ├── document.py
│       │   ├── evidence.py
│       │   ├── claim.py
│       │   ├── research.py
│       │   ├── manuscript.py
│       │   └── transitions.py
│       ├── workspace/
│       │   ├── layout.py
│       │   ├── repository.py
│       │   ├── serialization.py
│       │   ├── migrations.py
│       │   ├── locking.py
│       │   └── events.py
│       ├── projection/
│       │   ├── schema.py
│       │   ├── rebuild.py
│       │   ├── fts.py
│       │   └── dependencies.py
│       ├── ingest/
│       │   ├── service.py
│       │   ├── identity.py
│       │   └── hashing.py
│       ├── parsing/
│       │   ├── base.py
│       │   ├── pymupdf_parser.py
│       │   ├── tables.py
│       │   └── anchors.py
│       ├── retrieval/
│       │   ├── planner.py
│       │   ├── structured.py
│       │   ├── lexical.py
│       │   ├── semantic.py
│       │   ├── rerank.py
│       │   └── service.py
│       ├── providers/
│       │   └── models/
│       │       ├── base.py
│       │       ├── router.py
│       │       ├── openai_provider.py
│       │       ├── anthropic_provider.py
│       │       └── local_provider.py
│       ├── roles/
│       │   ├── contracts.py
│       │   ├── extractor.py
│       │   ├── verifier.py
│       │   ├── skeptic.py
│       │   ├── auditor.py
│       │   └── writer.py
│       ├── workflows/
│       │   ├── engine.py
│       │   ├── fingerprints.py
│       │   ├── ingest.py
│       │   ├── interrogate.py
│       │   ├── verify.py
│       │   ├── claim_audit.py
│       │   └── manuscript_audit.py
│       ├── evidence/
│       │   ├── service.py
│       │   ├── extraction.py
│       │   ├── verification.py
│       │   └── review.py
│       ├── claims/
│       │   ├── service.py
│       │   ├── audit.py
│       │   ├── strength.py
│       │   ├── coverage.py
│       │   └── negative_evidence.py
│       ├── manuscript/
│       │   ├── latex.py
│       │   ├── anchors.py
│       │   ├── citations.py
│       │   └── audit.py
│       ├── capabilities/
│       │   ├── registry.py
│       │   ├── permissions.py
│       │   └── handlers.py
│       ├── protocol/
│       │   ├── http.py
│       │   ├── mcp.py
│       │   └── dto.py
│       ├── plugins/
│       │   ├── spi.py
│       │   ├── manifest.py
│       │   └── loader.py
│       ├── server/
│       │   └── app.py
│       └── cli/
│           └── app.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   └── fixtures/
├── web/
│   ├── package.json
│   └── src/
├── vscode/
│   ├── package.json
│   └── src/
├── plugins/
│   ├── structured-traffic/
│   └── academic-writing/
└── docs/
    ├── architecture/
    ├── decisions/
    └── plans/
```

### Repository rules

- `domain/` contains pure domain schemas and transitions; it must not import FastAPI, Typer, provider SDKs, React concerns, or database ORM models.
- `workspace/` owns canonical file layout and atomic persistence.
- `projection/` may be deleted and rebuilt.
- `capabilities/` is the only supported mutation surface used by CLI/API/MCP/frontends.
- `plugins/` in `src/` is the SPI/runtime; top-level `plugins/` contains actual extensions.
- Tests mirror responsibilities rather than technical layers where possible.

---

# Phase 0 — Engineering Foundation

**Outcome:** A reproducible repository with quality gates strong enough that later scientific invariants can be tested rather than trusted.

**Relative effort:** Small

### Task 0.1: Bootstrap the Python package and quality toolchain

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/research_harness/__init__.py`
- Create: `src/research_harness/cli/app.py`
- Create: `tests/unit/test_smoke.py`

**Interfaces:**
- Produces: `research` CLI entry point.
- Produces: one importable `research_harness` package.

**Implementation requirements:**
- Python floor: 3.12.
- Package/dependency management: `uv`.
- Test runner: `pytest`.
- Lint/format: Ruff.
- Static typing: mypy or pyright; choose one and apply it to `src/` in CI.
- Add `research --version` and `research doctor` as smoke commands.

**Verification:**

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run research --version
uv run research doctor
```

**Gate P0:** clean checkout installs and all commands above pass without external API keys.

---

# Phase 1 — Canonical Research State

**Outcome:** The scientific data model exists independently of parsers, LLMs, retrieval, or UI.

**Relative effort:** Large

### Task 1.1: Stable identifiers and core enums

**Files:**
- Create: `src/research_harness/domain/ids.py`
- Create: `src/research_harness/domain/enums.py`
- Test: `tests/unit/domain/test_ids.py`
- Test: `tests/unit/domain/test_enums.py`

**Interfaces:**
- Produces typed stable IDs for `W`, `V`, `A`, `B`, `E`, `I`, `C`, `RQ`, `D`, `SR`, and `S`.
- Produces the core epistemic/status vocabularies defined in `PRODUCT.md`.

**Acceptance requirements:**
- IDs serialize as stable strings and validate their prefix.
- Negative-evidence states remain distinct enum values.
- Claim scope/status and evidence origin/type/strength are schema-level enums rather than free-form strings.

### Task 1.2: Core domain objects

**Files:**
- Create: `src/research_harness/domain/work.py`
- Create: `src/research_harness/domain/document.py`
- Create: `src/research_harness/domain/evidence.py`
- Create: `src/research_harness/domain/claim.py`
- Create: `src/research_harness/domain/research.py`
- Create: `src/research_harness/domain/manuscript.py`
- Test: `tests/unit/domain/`

**Interfaces:**
- Produces Pydantic models for all first-class entities in Product §7.
- Consumed by every later persistence, workflow, API, and plugin task.

**Acceptance requirements:**
- `Evidence` cannot exist without a source `Work`/`Version`/`Artifact` reference.
- Numeric evidence has metric/dataset/condition/provenance fields rather than a naked number.
- Claim `requested_strength` and `allowed_strength` are separate.
- `ResearchNote` has lower authority than Claim/Decision by schema and transition rules.
- All canonical objects carry `schema_version`, stable ID, created/updated timestamps, and provenance metadata.

### Task 1.3: Domain transitions and authority rules

**Files:**
- Create: `src/research_harness/domain/transitions.py`
- Create: `src/research_harness/domain/errors.py`
- Test: `tests/unit/domain/test_transitions.py`

**Interfaces:**
- Produces explicit state transitions such as candidate → verified → accepted/rejected and unverified claim → supported/qualified/contested/unsupported.

**Acceptance requirements:**
- No transition from `model_proposed` directly to `source_observed`.
- No interpretive candidate can become accepted without a human-review transition under strict policy.
- Researcher override creates/requires a `Decision` rather than mutating claim scope invisibly.

### Task 1.4: Canonical workspace repository

**Files:**
- Create: `src/research_harness/workspace/layout.py`
- Create: `src/research_harness/workspace/serialization.py`
- Create: `src/research_harness/workspace/repository.py`
- Create: `src/research_harness/workspace/locking.py`
- Create: `src/research_harness/workspace/journal.py`
- Create: `src/research_harness/workspace/migrations.py`
- Test: `tests/integration/workspace/test_repository.py`
- Test: `tests/integration/workspace/test_transaction_recovery.py`

**Interfaces:**
- Produces `WorkspaceRepository` with typed read/write/list operations.
- Writes canonical YAML/JSONL/Markdown only through atomic replace.

**Acceptance requirements:**
- `research init <dir>` creates the Product §8 layout.
- Writes are atomic.
- A multi-file accepted-state mutation uses a durable transaction journal and recovers by completing the whole unit or restoring the prior state.
- A workspace schema version is explicit.
- Unsupported future schema versions fail closed with a useful error.
- Concurrent accepted-state mutation is serialized by a workspace lock.

### Task 1.5: Semantic event log

**Files:**
- Create: `src/research_harness/workspace/events.py`
- Test: `tests/unit/workspace/test_events.py`

**Interfaces:**
- Produces append-only semantic `ResearchEvent` records.

**Acceptance requirements:**
- Events record state-changing semantics, not raw prompts or hidden reasoning.
- A mutation and its event either both persist or both fail.
- Event/canonical mismatch fails closed; the event log is an audit companion, not an alternative scientific authority.

### Task 1.6: Minimal application capability layer

**Files:**
- Create: `src/research_harness/capabilities/handlers.py`
- Create: `src/research_harness/capabilities/dto.py`
- Test: `tests/contract/capabilities/test_core_mutations.py`

**Interfaces:**
- Produces the typed application handlers used by the CLI for project initialization and canonical state transitions.
- Coordinates domain validation, workspace locking/journaling, semantic events, and dependency invalidation hooks.

**Acceptance requirements:**
- CLI commands do not call repository writes as an alternative business-logic path.
- Every accepted-state mutation has one application handler regardless of future CLI, HTTP, MCP, Web, or VS Code transport.
- The early layer is deliberately small; capability discovery, host permissions, and network transports remain Phase 10 work.

**Gate P1:** a project can be initialized and populated through typed capability handlers with hand-authored Work/Evidence/Claim/Decision fixtures, round-tripped through canonical files, recovered from an interrupted journaled mutation, and validated without SQLite, a parser, or any model provider.

---

# Phase 2 — Ingest, Identity, Parsing, and Provenance

**Outcome:** A local PDF becomes a stable Work/Version/Artifact with structural document blocks and durable anchors.

**Relative effort:** Large

### Task 2.1: Immutable artifact ingestion

**Files:**
- Create: `src/research_harness/ingest/hashing.py`
- Create: `src/research_harness/ingest/service.py`
- Test: `tests/integration/ingest/test_local_pdf.py`

**Interfaces:**
- Produces `ingest_local_pdf(path) -> WorkCandidate`.
- Computes SHA-256 and records original filename, MIME type, and artifact provenance.

**Acceptance requirements:**
- Re-ingesting the exact same bytes is idempotent.
- Same work/different PDF revision does not silently overwrite the old Artifact.
- Source artifacts are immutable once registered.

### Task 2.2: Identity resolver

**Files:**
- Create: `src/research_harness/ingest/identity.py`
- Test: `tests/unit/ingest/test_identity.py`

**Interfaces:**
- Produces deterministic candidate matching by DOI/arXiv/title/authors/year when metadata exists.
- External metadata lookup remains an adapter hook; Phase 2 only requires local/PDF metadata resolution.

**Acceptance requirements:**
- `same_artifact`, `same_version`, `same_work`, and `distinct_work` are different outcomes.
- Resolver decisions preserve field-level provenance rather than erasing conflicting metadata.

### Task 2.3: Parser abstraction and first PDF parser

**Files:**
- Create: `src/research_harness/parsing/base.py`
- Create: `src/research_harness/parsing/pymupdf_parser.py`
- Create: `src/research_harness/parsing/tables.py`
- Test: `tests/integration/parsing/test_document_ir.py`
- Fixture: `tests/fixtures/synthetic_research_paper.pdf`

**Interfaces:**
- Produces a structural `DocumentIR` containing Pages, Sections, Paragraphs, Tables, captions, equations/references where detected.

**Acceptance requirements:**
- Preserve page number and bounding box for every text block.
- Preserve table cell row/column coordinates on the synthetic fixture.
- Parsing failure never mutates accepted scientific state.

### Task 2.4: Anchor construction and validation

**Files:**
- Create: `src/research_harness/parsing/anchors.py`
- Test: `tests/unit/parsing/test_anchors.py`

**Interfaces:**
- Produces anchor fingerprint from artifact hash + page + block + text hash + offsets + optional bbox.
- Produces `AnchorValidationResult` with `valid`, `stale`, or `missing`.

**Acceptance requirements:**
- A one-byte source artifact change invalidates the artifact hash and prevents silent reattachment.
- Re-parsing unchanged bytes may change parser-internal IDs, but evidence can be reconciled only through explicit anchor validation.

**Gate P2:** `research ingest` followed by `research parse W####` can open a synthetic and a real technical PDF, list structural blocks, and resolve a persisted anchor back to the exact page/span.

---

# Phase 3 — Rebuildable Projections and Dependency/Staleness Core

**Outcome:** Canonical state can be indexed for fast local queries and fully reconstructed after deleting `.research/`.

**Relative effort:** Medium

### Task 3.1: SQLite projection schema

**Files:**
- Create: `src/research_harness/projection/schema.py`
- Test: `tests/integration/projection/test_schema.py`

**Interfaces:**
- Produces normalized tables for Works, Versions, Artifacts, Blocks, Evidence, Claims, claim-evidence relations, Decisions, Questions, SearchRuns, ManuscriptAnchors, events, and dependencies.

**Acceptance requirements:**
- SQLite rows never become the only copy of scientific state.
- Projection IDs exactly match canonical object IDs.

### Task 3.2: Deterministic rebuild

**Files:**
- Create: `src/research_harness/projection/rebuild.py`
- Test: `tests/e2e/test_rebuild.py`

**Interfaces:**
- Produces `rebuild_workspace(workspace) -> RebuildReport`.

**Acceptance requirements:**
- Deleting `.research/` and rebuilding produces semantically equivalent projections.
- Rebuild reports invalid canonical files rather than partially accepting corrupted state.
- Rebuild does not change accepted object content or IDs.

### Task 3.3: FTS5 index

**Files:**
- Create: `src/research_harness/projection/fts.py`
- Test: `tests/integration/projection/test_fts.py`

**Interfaces:**
- Indexes DocumentBlocks, Evidence text, Claim text, Work metadata, and ResearchNotes.

**Acceptance requirements:**
- Exact terminology search works without embeddings or external services.

### Task 3.4: Dependency graph and stale propagation

**Files:**
- Create: `src/research_harness/projection/dependencies.py`
- Test: `tests/unit/projection/test_staleness.py`

**Interfaces:**
- Produces `mark_changed(object_id) -> StaleSet` and query APIs for affected downstream objects.

**Acceptance requirements:**
- A taxonomy Decision can mark classifications → matrix → claim → manuscript anchor stale.
- Stale propagation never rewrites derived scientific objects automatically.

### Task 3.5: Durable workflow and checkpoint substrate

**Files:**
- Create: `src/research_harness/workflows/models.py`
- Create: `src/research_harness/workflows/engine.py`
- Create: `src/research_harness/workflows/fingerprints.py`
- Create: `src/research_harness/workspace/runs.py`
- Test: `tests/integration/workflows/test_resume.py`

**Interfaces:**
- Produces durable run IDs, stage checkpoints, input fingerprints, attempt history, cancellation state, and terminal status.
- Supports idempotent resume/recompute without requiring a long-lived CLI/API connection.

**Acceptance requirements:**
- An interrupted run resumes from the last valid checkpoint or safely recomputes an idempotent stage.
- Checkpoints can preserve candidates/staging artifacts but cannot promote accepted scientific state.
- Deleting workflow runtime state never changes canonical accepted conclusions.

**Gate P3:** delete `.research/`, run `research rebuild`, and demonstrate identical accepted object hashes plus functional FTS and stale dependency queries; separately interrupt and resume a staged workflow without duplicate canonical mutations.

---

# Phase 4 — Provider-Neutral Semantic Runtime

**Outcome:** OpenAI and Anthropic can perform the same structured semantic job through one contract, with no provider concept leaking into the domain model.

**Relative effort:** Large

### Task 4.1: Provider contract and model router

**Files:**
- Create: `src/research_harness/providers/models/base.py`
- Create: `src/research_harness/providers/models/router.py`
- Test: `tests/contract/providers/test_model_contract.py`

**Interfaces:**
- Produces a provider-neutral request containing role, requirements, input object IDs/content envelope, and response schema.
- Produces validated structured responses and normalized usage metadata.

**Acceptance requirements:**
- Provider selection is based on capabilities/configuration, not domain code branches.
- Invalid structured output is rejected before it reaches staging.
- Hidden chain-of-thought is neither required nor persisted.

### Task 4.2: OpenAI adapter

**Files:**
- Create: `src/research_harness/providers/models/openai_provider.py`
- Test: `tests/contract/providers/test_openai_provider.py`

**Interfaces:**
- Implements the provider contract.
- Contract tests use a fake transport; live smoke is opt-in with an environment flag.

### Task 4.3: Anthropic adapter

**Files:**
- Create: `src/research_harness/providers/models/anthropic_provider.py`
- Test: `tests/contract/providers/test_anthropic_provider.py`

**Interfaces:**
- Implements the exact same provider contract and structured output semantics.

### Task 4.4: Local provider placeholder with real interface, minimal backend

**Files:**
- Create: `src/research_harness/providers/models/local_provider.py`
- Test: `tests/contract/providers/test_local_provider.py`

**Interfaces:**
- Supports an OpenAI-compatible local endpoint or equivalent minimal local adapter without changing role contracts.

### Task 4.5: Bounded role contracts

**Files:**
- Create: `src/research_harness/roles/contracts.py`
- Create: role definitions under `src/research_harness/roles/`
- Test: `tests/unit/roles/test_permissions.py`

**Interfaces:**
- Defines Evidence Extractor, Verifier, Skeptic, Claim Auditor, Synthesizer, and Writer as stateless role contracts.

**Acceptance requirements:**
- Writer cannot create accepted Evidence/Claims.
- Extractor writes staging only.
- Verifier cannot silently rewrite an accepted candidate.

**Gate P4:** run one provider contract fixture through OpenAI and Anthropic adapters and prove that both produce the same canonical response schema while domain objects remain provider-neutral.

---

# Phase 5 — Local Retrieval Engine

**Outcome:** The harness can answer corpus questions using structured + lexical + semantic signals without treating vector retrieval as scientific truth.

**Relative effort:** Medium/Large

### Task 5.1: Structured and lexical retrieval

**Files:**
- Create: `src/research_harness/retrieval/structured.py`
- Create: `src/research_harness/retrieval/lexical.py`
- Test: `tests/integration/retrieval/test_structured_lexical.py`

**Interfaces:**
- Query by entity/status/field plus FTS terms and structural section constraints.

### Task 5.2: Embedded semantic index

**Files:**
- Create: `src/research_harness/retrieval/semantic.py`
- Test: `tests/integration/retrieval/test_semantic.py`

**Interfaces:**
- Embeds Work/Section/Paragraph/Evidence representations behind an index abstraction.

**Acceptance requirements:**
- Deleting the vector index changes retrieval performance only; it does not remove accepted research state.
- Embedding provider/model is recorded in index metadata, not canonical scientific objects.

### Task 5.3: Query planner and retrieval ladder

**Files:**
- Create: `src/research_harness/retrieval/planner.py`
- Create: `src/research_harness/retrieval/service.py`
- Test: `tests/unit/retrieval/test_planner.py`

**Interfaces:**
- Produces retrieval plans such as structured-only, FTS + section constraint, or structured + semantic.
- Applies authority ladder: accepted state → structured paper state → parsed local corpus → later citation graph → later external discovery.

### Task 5.4: Research-utility reranking

**Files:**
- Create: `src/research_harness/retrieval/rerank.py`
- Test: `tests/unit/retrieval/test_rerank.py`

**Acceptance requirements:**
- Results sections/table evidence outrank abstract claims when auditing empirical results.
- Accepted direct Evidence outranks semantically similar raw prose for support queries.
- Retrieval responses expose source, structural location, authority, and score components.

**Gate P5:** demonstrate the same local corpus answering an exact dataset query through structured/FTS retrieval and a terminology-mismatch query through semantic retrieval, with provenance shown in both cases.

---

# Phase 6 — Evidence Pipeline and Strict Human Review

**Outcome:** The first complete scientific loop works: source → candidate evidence → verification → review → accepted Evidence.

**Relative effort:** Very Large

### Task 6.1: Candidate evidence extraction

**Files:**
- Create: `src/research_harness/evidence/extraction.py`
- Create: `src/research_harness/workflows/interrogate.py`
- Test: `tests/integration/evidence/test_extraction.py`

**Interfaces:**
- Consumes DocumentIR + interrogation field contract.
- Produces staging Evidence candidates with exact anchors, origin/type/strength, and structured values.

**Acceptance requirements:**
- Extraction cannot write canonical accepted Evidence.
- A candidate with no valid source anchor is invalid.

### Task 6.2: Independent verification

**Files:**
- Create: `src/research_harness/evidence/verification.py`
- Create: `src/research_harness/workflows/verify.py`
- Test: `tests/integration/evidence/test_verification.py`

**Interfaces:**
- Consumes source context + candidate.
- Produces `supported`, `partially_supported`, `contradicted`, or `insufficient_evidence` plus concise rationale.

**Acceptance requirements:**
- Verifier is not given extractor hidden reasoning.
- A paper name/dataset name alone cannot establish properties not stated in the source.

### Task 6.3: Review Inbox and strict mutation service

**Files:**
- Create: `src/research_harness/evidence/review.py`
- Create: `src/research_harness/evidence/service.py`
- Test: `tests/integration/evidence/test_review_gate.py`

**Interfaces:**
- Produces review queue ordered conflict → high-risk → stale → ambiguous → routine.
- Supports Accept, Accept with qualification, Edit, Reject, Defer, Request more evidence.

**Acceptance requirements:**
- Partial acceptance can split source fact from interpretation.
- Model confidence alone cannot trigger acceptance.
- Batch acceptance requires explicit deterministic policy conditions.

### Task 6.4: CLI Evidence Loop

**Files:**
- Modify: `src/research_harness/cli/app.py`
- Test: `tests/e2e/test_evidence_cli_loop.py`

**Commands:**

```text
research ingest <pdf>
research parse <work>
research interrogate <work>
research verify <object>
research inbox
research review <id>
research rebuild
```

**Gate P6 / v0.1:** on a synthetic paper and one real local paper, complete ingest → parse → extraction → verification → human acceptance; delete `.research/`; rebuild; accepted Evidence and anchors remain identical.

---

# Phase 7 — Claim/Evidence Engine and Epistemic Audit

**Outcome:** The system can distinguish what the literature supports from what the researcher is trying to say.

**Relative effort:** Very Large

### Task 7.1: Claim service and claim-evidence relations

**Files:**
- Create: `src/research_harness/claims/service.py`
- Test: `tests/integration/claims/test_relations.py`

**Interfaces:**
- Supports `supports`, `contradicts`, `qualifies`, `contextualizes`, `exemplifies`, and `incomparable_under_current_evidence`.

**Acceptance requirements:**
- Relations are many-to-many.
- A paper may simultaneously support and qualify different aspects of a Claim.

### Task 7.2: Scope and maximum-defensible-wording engine

**Files:**
- Create: `src/research_harness/claims/strength.py`
- Test: `tests/unit/claims/test_strength.py`

**Interfaces:**
- Consumes claim type, requested scope, supporting/qualifying/contradicting evidence, and current coverage.
- Produces allowed scope and wording recommendation.

**Acceptance requirements:**
- L0–L4 scopes are explicit.
- High confidence in local Evidence cannot justify a field-generalization claim.
- Universal wording requires stricter evidence than corpus-level wording.

### Task 7.3: Negative evidence discipline

**Files:**
- Create: `src/research_harness/claims/negative_evidence.py`
- Test: `tests/unit/claims/test_negative_evidence.py`

**Acceptance requirements:**
- `not_reported` cannot become `absent` without an explicit audited transition.
- Missing lexical hits alone result in `not_found`, never `absent`.

### Task 7.4: Claim auditor and Skeptic workflow

**Files:**
- Create: `src/research_harness/claims/audit.py`
- Create: `src/research_harness/workflows/claim_audit.py`
- Test: `tests/integration/claims/test_claim_audit.py`

**Interfaces:**
- Resolves support, counter-evidence, qualifiers, independence warnings, coverage state, and maximum defensible wording.

**Acceptance requirements:**
- Auditor tries to falsify/qualify the Claim rather than maximize support.
- Incomparable results are not labeled direct contradictions merely because outcomes differ.

### Task 7.5: Research Decisions and overrides

**Files:**
- Extend: `src/research_harness/domain/research.py`
- Extend: `src/research_harness/claims/service.py`
- Test: `tests/integration/claims/test_override_decision.py`

**Acceptance requirements:**
- Researcher can override the auditor.
- Override creates a visible `Decision` and invalidates downstream derived objects.

**Gate P7:** create a claim deliberately stronger than its evidence; `research claim audit` must return a weaker maximum defensible wording, show support/qualifiers/counter-evidence, and prevent silent strength escalation.

---

# Phase 8 — Synthesis, Questions, Notes, and Research Decisions

**Outcome:** Cross-paper reasoning becomes durable research state rather than transient chat output.

**Relative effort:** Medium

### Task 8.1: ResearchQuestion and ResearchNote services

**Files:**
- Create/extend: `src/research_harness/domain/research.py`
- Create: `src/research_harness/research/questions.py`
- Create: `src/research_harness/research/notes.py`
- Test: `tests/integration/research/test_notes_questions.py`

**Interfaces:**
- Notes may be promoted to Claim, Question, or Decision through explicit transitions.
- Questions link Claims, SearchRuns, Evidence, and unresolved uncertainty.

### Task 8.2: Synthesis matrices

**Files:**
- Create: `src/research_harness/synthesis/service.py`
- Create: `src/research_harness/synthesis/matrix.py`
- Test: `tests/integration/synthesis/test_matrix.py`

**Interfaces:**
- Matrix cells link back to accepted Evidence and project taxonomy.

**Acceptance requirements:**
- A matrix is derived state and becomes stale when upstream taxonomy/evidence changes.
- A cell can express multi-label classification rather than force false exclusivity.

### Task 8.3: CLI research capture

**Commands:**

```text
research note add "..."
research question create "..."
research compare <field>
```

**Gate P8:** change an accepted taxonomy Decision and demonstrate that the relevant synthesis matrix and dependent Claim become stale while the old accepted records remain inspectable.

---

# Phase 9 — Manuscript Traceability and LaTeX Audit

**Outcome:** The research graph becomes useful during actual Q1 manuscript writing before any polished UI is required.

**Relative effort:** Very Large

### Task 9.1: LaTeX parser/anchor adapter

**Files:**
- Create: `src/research_harness/manuscript/latex.py`
- Create: `src/research_harness/manuscript/anchors.py`
- Test: `tests/integration/manuscript/test_latex_anchors.py`

**Interfaces:**
- Maps source file + line/range + sentence fingerprint to `ManuscriptAnchor`.

### Task 9.2: Claim attachment

**Files:**
- Extend: `src/research_harness/manuscript/anchors.py`
- Test: `tests/integration/manuscript/test_claim_attachment.py`

**Acceptance requirements:**
- Substantive manuscript text can link to an existing Claim.
- Rewording that changes sentence fingerprint triggers revalidation rather than silently retaining a stale anchor.

### Task 9.3: Citation closure and support verification

**Files:**
- Create: `src/research_harness/manuscript/citations.py`
- Test: `tests/integration/manuscript/test_citations.py`

**Acceptance requirements:**
- Every attached citation key must exist in BibTeX.
- Citation existence is not treated as evidence support.
- Numeric claims require compatible metric/dataset/condition Evidence.

### Task 9.4: Manuscript auditor

**Files:**
- Create: `src/research_harness/manuscript/audit.py`
- Create: `src/research_harness/workflows/manuscript_audit.py`
- Test: `tests/e2e/test_manuscript_audit.py`

**Detect:**
- unregistered substantive claims;
- sentence stronger than accepted Claim;
- citation mismatch;
- unsupported numeric values;
- stale Claim/anchor;
- invalid source Evidence anchor.

**Gate P9 / v0.2:** on a small LaTeX fixture, click/resolve sentence → Claim → Evidence → exact PDF span, and demonstrate at least one citation mismatch plus one over-strong wording warning.

---

# Phase 10 — Capability Exposure, Local Daemon, and MCP

**Outcome:** The application capability handlers established in Phase 1 are discoverable through one permission model and exposed consistently to CLI, HTTP, and MCP hosts.

**Relative effort:** Large

### Task 10.1: Capability registry and permissions

**Files:**
- Create: `src/research_harness/capabilities/registry.py`
- Create: `src/research_harness/capabilities/permissions.py`
- Modify: `src/research_harness/capabilities/handlers.py`
- Test: `tests/contract/capabilities/test_registry.py`

**Interfaces:**
- Expose named Product §22 capabilities.
- Each capability declares read/write permissions, accepted input DTO, output DTO, and scientific mutation semantics.

### Task 10.2: Local FastAPI daemon

**Files:**
- Create: `src/research_harness/server/app.py`
- Create: `src/research_harness/protocol/http.py`
- Create: `src/research_harness/protocol/dto.py`
- Test: `tests/contract/protocol/test_http.py`

**Acceptance requirements:**
- API never exposes direct arbitrary SQLite mutation.
- Workspace mutations are serialized.
- Long workflows return durable run IDs/checkpoints rather than requiring an open HTTP request forever.

### Task 10.3: MCP server

**Files:**
- Create: `src/research_harness/protocol/mcp.py`
- Test: `tests/contract/protocol/test_mcp.py`

**Acceptance requirements:**
- Claude and ChatGPT-compatible hosts see the same capability names and semantics.
- MCP does not contain host-specific research business logic.

### Task 10.4: CLI/transport capability parity

**Files:**
- Modify: `src/research_harness/cli/app.py`
- Test: `tests/e2e/test_cli_capability_parity.py`

**Acceptance requirements:**
- CLI and API produce equivalent state transitions for the same operation.
- Phase 10 adds discovery, permissions, and transports; it does not create a second business-logic layer or replace the Phase 1 mutation handlers.

**Gate P10 / v0.3 backend:** create a Claim through CLI, inspect/audit it through HTTP and MCP, and verify there is exactly one canonical Claim object.

---

# Phase 11 — Basic Web Research Cockpit

**Outcome:** Strict human review becomes comfortable enough for daily use.

**Relative effort:** Very Large

### Task 11.1: Web shell and typed API client

**Files:**
- Create: `web/package.json`
- Create: `web/src/api/`
- Create: `web/src/app/`
- Test: frontend unit tests + API contract tests.

**Interfaces:**
- Uses generated or hand-maintained DTO types matching the local API.
- No business rules duplicated in React.

### Task 11.2: Overview and attention surfaces

**Views:**
- Overview
- Review Inbox
- Conflicts
- Stale

**Acceptance requirements:**
- Dashboard prioritizes next actions, not model confidence vanity metrics.

### Task 11.3: Evidence source-beside-decision review

**Views:**
- exact source/PDF pane;
- highlighted evidence span;
- candidate/verification pane;
- Accept / Qualify / Edit / Reject / Defer / Request more evidence.

**Acceptance requirements:**
- Researcher never has to trust a candidate summary without the source context visible.

### Task 11.4: Claim explorer

**Views:**
- Claim status/scope;
- supporting/qualifying/contradicting Evidence;
- coverage summary;
- maximum defensible wording;
- decision history;
- stale dependencies.

### Task 11.5: Corpus / Questions / Synthesis / Taxonomy / Manuscript navigation

Implement basic inspectability first; advanced visualizations wait until real use proves value.

**Verification:**

```bash
cd web
pnpm install
pnpm test
pnpm build
```

**Gate P11 / v0.3:** a researcher can complete the Evidence review loop and Claim audit loop from Web without using direct file edits or CLI mutation commands.

---

# Phase 12 — External Discovery, Citation Graph, SearchRun, and Coverage

**Outcome:** Literature-wide prevalence and absence claims become auditable rather than intuition-driven.

**Relative effort:** Very Large

### Task 12.1: Discovery provider abstraction

**Files:**
- Create: `src/research_harness/providers/search/base.py`
- Create adapters for Crossref, OpenAlex, Semantic Scholar, DBLP; arXiv as supplement.
- Test: contract tests with recorded/fake responses.

**Acceptance requirements:**
- Search result = candidate source only.
- Search snippets never become accepted Evidence.
- Provider errors, rate limits, authentication failures, and access barriers remain distinct from a successful zero-result search.

### Task 12.2: SearchRun persistence and screening

**Files:**
- Create: `src/research_harness/discovery/search_runs.py`
- Create: `src/research_harness/discovery/screening.py`
- Test: `tests/integration/discovery/test_search_run.py`

**Interfaces:**
- Persist query/source/filter/result counts and screening reasons.

**Acceptance requirements:**
- SearchRun also records pagination/cursor boundaries, cutoff, failed/incomplete source queries, unresolved identity matches, and unavailable full text.
- Work-level deduplication preserves related Version and Artifact records rather than merging them into one paper row.

### Task 12.3: Citation graph and snowballing

**Files:**
- Create: `src/research_harness/citations/graph.py`
- Create: `src/research_harness/citations/snowball.py`
- Test: `tests/integration/citations/test_graph.py`

**Acceptance requirements:**
- `cites` is deterministic from source metadata/references.
- Semantic relations such as `extends` or `contradicts` require Evidence/verification.
- Same Work/version relations prevent double-counting support.

### Task 12.4: Coverage and overturn risk

**Files:**
- Create/complete: `src/research_harness/claims/coverage.py`
- Test: `tests/integration/claims/test_coverage.py`

**Interfaces:**
- Coverage tracks defined universe, cutoff, discovered/screened/relevant/full-text/examined/unresolved works and overturn risk.

### Task 12.5: Advanced prevalence/absence audit

**Acceptance requirements:**
- “No work exists” is not permitted from a partial unrecorded search.
- Preferred output under strong but non-exhaustive search is “we identified no work that …” with scope and cutoff.
- Empty synthesis cells and model agreement cannot be promoted directly to novelty or absence Claims.
- Baseline recommendations compare explicit task/data/metric/compute/deployment/reproducibility axes and remain reviewable candidates.

**Gate P12 / v0.4:** run a reproducible SearchRun, snowball from one seed, record inclusion/exclusion, and audit one absence claim with explicit unresolved works and overturn risk.

---

# Phase 13 — Selective Cross-Model Verification

**Outcome:** Claude and OpenAI are used as independent checks where disagreement is scientifically valuable, not as duplicated routine cost.

**Relative effort:** Medium

### Task 13.1: Cross-provider verification policy

**Files:**
- Create: `src/research_harness/providers/models/cross_verify.py`
- Test: `tests/unit/providers/test_cross_verify_policy.py`

**Default eligible gates:**
- research gap / absence claim;
- numeric high-impact claim;
- counter-evidence interpretation;
- submission-ready field-level claim;
- manuscript sentence with high consequence.

### Task 13.2: Conflict materialization

**Acceptance requirements:**
- Provider disagreement becomes a Review Inbox conflict object.
- Agreement does not auto-accept a Tier-2 scientific judgment under strict policy.

**Gate P13:** deliberately feed a fixture where two provider results disagree and verify the user receives one explicit conflict rather than one provider silently overwriting the other.

---

# Phase 14 — Plugin SPI and Skill Audit Gate

**Outcome:** Domain-specific behavior can be added without contaminating the invariant core, and only now are existing research/reviewer skills assessed for reuse.

**Relative effort:** Large

### Task 14.1: Plugin manifest and loader

**Files:**
- Create: `src/research_harness/plugins/manifest.py`
- Create: `src/research_harness/plugins/spi.py`
- Create: `src/research_harness/plugins/loader.py`
- Test: `tests/contract/plugins/test_plugin_boundaries.py`

**Plugin contributions allowed:**
- domain schema;
- interrogation schema;
- validators;
- workflow fragments;
- bounded roles/contracts;
- search providers;
- writing policies;
- UI extension descriptors.

**Acceptance requirements:**
- Plugin cannot write canonical state directly.
- Plugin cannot bypass strict review gates or expand role permissions silently.
- Core meanings of Evidence/Claim/Decision cannot be redefined.

### Task 14.2: Audit the existing skill collection

Do this **after** the SPI passes its boundary tests.

Classify every supplied skill/agent asset as:

- `reuse-as-contract` — semantics/role definition can be reused nearly unchanged;
- `adapt-to-plugin` — useful domain/workflow logic but must call core capabilities;
- `inspiration-only` — useful design idea but architecture conflicts with Research Harness invariants;
- `exclude` — redundant, unsafe, host-coupled, or outside the product scope.

For each reused/adapted skill, document:
- source asset;
- target plugin/role/workflow;
- authority level;
- allowed capabilities;
- forbidden mutations;
- required output schema;
- whether it depends on Claude/ChatGPT-specific behavior.

Seed this audit from `skills/INVENTORY.md`. The initial locked decisions are:

- `humanizer`: `adapt-to-plugin` as an `academic-writing` policy with protected scientific spans and semantic-diff review;
- `my-literature-review` v2.1.0 monolith: `inspiration-only`;
- its provider-neutral query planning, discovery, Work/Version/Artifact ingest handoff, snowballing, multi-label classification, coverage, and baseline-comparison concepts: `adapt-to-plugin`;
- its Claude-in-Chrome CAPTCHA path, direct accepted-file writes, static venue-rank table, and incomplete hard dependency on `academic-paper-reviewer`: `exclude`.

**Do not copy a skill into the core merely because it already exists.**

### Task 14.3: Plugin compatibility tests

Create a minimal example plugin and prove it can add an interrogation field and validator without altering core schemas or accepted-state mutation rules.

**Gate P14:** plugin boundary tests pass and the skill inventory has an explicit reuse/adapt/inspiration/exclude mapping before any large skill migration begins.

---

# Phase 15 — Structured-Traffic and Academic-Writing Plugins

**Outcome:** Dogfood the generic architecture on the exact research workflow that motivated the product.

**Relative effort:** Large

### Task 15.1: `structured-traffic` plugin

**Files:**
- Create: `plugins/structured-traffic/plugin.yaml`
- Create schemas/interrogation/validators/roles under the plugin directory.

**Initial fields:**
- traffic unit;
- representation family;
- raw information retained;
- derived information;
- serialization;
- tokenization;
- LLM architecture;
- LLM role;
- training strategy;
- detection target;
- dataset / dataset age / encryption status;
- train/test partition;
- evaluation unit;
- baselines / metrics / ablations;
- robustness evaluation;
- deployment assumptions;
- author-stated limitations;
- researcher-observed limitations.

**Acceptance requirements:**
- `raw sequential`, `field-based`, `behavior-aware` are project/plugin taxonomy terms, not core enums.
- Hybrid/multi-label classification is permitted.

### Task 15.2: `academic-writing` plugin

**Files:**
- Create: `plugins/academic-writing/plugin.yaml`
- Add writing policies for claim language, citation discipline, and project style constraints.

**Acceptance requirements:**
- Writing policy may constrain wording but cannot upgrade scientific authority.
- Unsupported content becomes an audit warning, not a fabricated citation.
- Adapt the retained `skills/humanizer` policy as an optional candidate-only style pass.
- Protect citations, identifiers, anchors, quotations, numbers/units/equations, Claim scope, epistemic qualifiers, and negative-evidence wording.
- Produce a semantic diff; any added/removed/strengthened/weakened proposition triggers manuscript audit and human review before acceptance.

### Task 15.3: Real Q1 project dogfood migration

Use the current structured-network-traffic review as a **manual acceptance corpus**, not a CI fixture.

Dogfood goals:
- ingest representative papers already used in the review;
- encode current representation taxonomy as a Decision;
- create Evidence for serialization/tokenization/LLM role/evaluation claims;
- recreate at least three previously debated literature-wide Claims;
- attach at least one manuscript subsection to Claims;
- run claim and citation audits;
- record workflow friction discovered during real use.

**Gate P15:** the harness can reproduce the current paper's accepted taxonomy/claims without depending on old chat history, and every substantive dogfood claim can be traced to accepted source evidence.

---

# Phase 16 — VS Code Manuscript Client

**Outcome:** The researcher can stay inside the LaTeX editing loop while using the same Research Core.

**Relative effort:** Large

### Task 16.1: VS Code extension shell and protocol client

**Files:**
- Create: `vscode/package.json`
- Create: `vscode/src/extension.ts`
- Create: `vscode/src/client/`
- Test: VS Code extension integration tests.

### Task 16.2: Claim-under-cursor and status hover

Show Claim ID, status, scope, evidence count, qualifiers, and stale state.

### Task 16.3: Audit selection / attach Claim / quick note

Commands:
- `Research: Audit Selection`
- `Research: Attach Claim`
- `Research: Create Claim from Selection`
- `Research: Add Research Note`
- `Research: Open Evidence`

### Task 16.4: Stale and unsupported manuscript diagnostics

Use editor diagnostics for:
- unlinked substantive text;
- citation mismatch;
- stale Claim;
- invalid Evidence anchor;
- over-strong wording.

**Verification:**

```bash
cd vscode
pnpm install
pnpm test
pnpm run compile
```

**Gate P16 / v1.0 client:** edit a LaTeX section, attach/audit a Claim, open exact Evidence in the Web cockpit, and observe the same state from CLI/MCP without duplication.

---

# Phase 17 — v1.0 Hardening

**Outcome:** The personal workstation is reliable enough for sustained real research rather than a demo.

**Relative effort:** Large

### Task 17.1: End-to-end invariant suite

Create deterministic end-to-end tests for all Product §42 acceptance behaviors:
- provider independence;
- host independence;
- rebuildability;
- provenance;
- epistemic separation;
- negative-evidence discipline;
- claim-strength discipline;
- strict review gate;
- stale propagation;
- citation integrity;
- atomic canonical/event/invalidation mutation and crash recovery;
- style transformations cannot alter accepted scientific meaning or protected manuscript spans without review.

### Task 17.2: Crash/recovery and atomicity tests

Simulate interruption during:
- canonical mutation;
- rebuild;
- long provider workflow;
- review acceptance;
- manuscript attachment.

No half-accepted scientific state may remain.

### Task 17.3: Performance budgets for personal-scale research

Measure rather than prematurely optimize. Initial target corpus for benchmarks:
- 1,000 Works;
- 100,000 DocumentBlocks;
- 50,000 Evidence records;
- 5,000 Claims/relations.

Track:
- project open/rebuild time;
- FTS latency;
- Review Inbox latency;
- Claim graph query latency;
- vector rebuild time;
- Web interaction latency.

Optimize only paths that fail actual workstation usability.

### Task 17.4: Privacy and egress controls

Add:
- per-provider egress declaration;
- project-level external-model disable switch;
- secrets from environment/keychain only;
- disposable/redactable traces;
- visible network activity policy.

### Task 17.5: Documentation and first-run experience

Document:
- install/init;
- workspace structure;
- strict review semantics;
- provider setup;
- MCP host setup for Claude/ChatGPT;
- Web startup;
- VS Code setup;
- rebuild/recovery;
- plugin authoring boundaries.

**Gate P17 / v1.0:** all end-to-end invariants pass; the real Q1 project is usable for a full research session without direct DB editing or dependence on conversation memory.

---

# Post-v1.0 Roadmap

These items stay deliberately outside the v1.0 critical path.

## v1.1 — Systematic Review Plugin

Add:
- PRISMA-oriented screening/reporting;
- inclusion/exclusion protocol templates;
- deduplication audit;
- SearchRun coverage reports;
- systematic-review export artifacts.
- adapt the retained `my-literature-review` contract into plugin workflow fragments only after the Phase 14 mapping and boundary tests pass.

The systematic-review plugin consumes existing SearchRun/coverage primitives; it must not force PRISMA concepts into the generic core.

## v1.2 — Reviewer / Calibration Extensions

After the skill audit, consider:
- bounded domain reviewer role;
- devil's-advocate claim/paper stress test;
- editorial synthesis workflow;
- calibration against user-supplied gold sets;
- panel disagreement visualization.

These remain **review extensions**, not authorities that can mutate accepted scientific state automatically.

## v1.3 — Packaging and Desktop Experience

Only after Web + daemon usage is stable:
- Tauri desktop shell;
- single-click local daemon lifecycle;
- bundled update channel;
- workspace picker and recent-project UX.

## v2+ — Collaboration Only If Demanded

Potential later scope:
- remote synchronization;
- team review queues;
- role-based human permissions;
- conflict resolution across human editors;
- hosted service.

Do not introduce collaboration architecture into v1.0 schemas unless a concrete use case requires it.

---

# 3. Capability Release Matrix

| Capability | v0.1 | v0.2 | v0.3 | v0.4 | v1.0 |
|---|---:|---:|---:|---:|---:|
| Project init / canonical state | ✓ | ✓ | ✓ | ✓ | ✓ |
| Core mutation capability handlers | ✓ | ✓ | ✓ | ✓ | ✓ |
| Durable workflow/checkpoint substrate | ✓ | ✓ | ✓ | ✓ | ✓ |
| PDF ingest / structural parse | ✓ | ✓ | ✓ | ✓ | ✓ |
| SQLite / FTS / vector rebuild | ✓ | ✓ | ✓ | ✓ | ✓ |
| OpenAI + Anthropic providers | ✓ | ✓ | ✓ | ✓ | ✓ |
| Evidence extraction/verification | ✓ | ✓ | ✓ | ✓ | ✓ |
| Strict Review Inbox | ✓ | ✓ | ✓ | ✓ | ✓ |
| Claim model / audit |  | ✓ | ✓ | ✓ | ✓ |
| Synthesis / Questions / Notes |  | ✓ | ✓ | ✓ | ✓ |
| LaTeX claim traceability |  | ✓ | ✓ | ✓ | ✓ |
| Local daemon / HTTP |  |  | ✓ | ✓ | ✓ |
| MCP / Claude / ChatGPT host access |  |  | ✓ | ✓ | ✓ |
| Basic Web cockpit |  |  | ✓ | ✓ | ✓ |
| External discovery |  |  |  | ✓ | ✓ |
| Citation graph / snowball |  |  |  | ✓ | ✓ |
| SearchRun / coverage audit |  |  |  | ✓ | ✓ |
| Selective cross-model verification |  |  |  | ✓ | ✓ |
| Plugin SPI |  |  |  |  | ✓ |
| Structured-traffic plugin |  |  |  |  | ✓ |
| Academic-writing plugin |  |  |  |  | ✓ |
| VS Code client |  |  |  |  | ✓ |

---

# 4. Critical Path and Parallel Work

The following must remain sequential because downstream scientific semantics depend on them:

```text
P1 Canonical State
→ P2 Provenance/Parsing
→ P3 Rebuild/Staleness
→ P6 Evidence Review
→ P7 Claim Audit
→ P9 Manuscript Audit
```

Safe parallelization after interfaces stabilize:

- P4 provider adapters can run in parallel with late P3 projection work.
- P5 semantic retrieval can run in parallel with provider adapter implementation once DocumentIR and projection contracts are stable.
- P11 Web work can begin after P10 DTO/capability contracts stabilize; it should not invent new backend semantics.
- P12 discovery providers can be implemented in parallel with Web after SearchRun schemas are locked.
- P16 VS Code can begin after P9 manuscript anchors and P10 protocol DTOs are stable.

Do not parallelize two tasks that both redefine canonical schemas or scientific transition rules.

---

# 5. Testing Strategy

## Unit tests

Use for:
- schemas/enums;
- transitions;
- ID generation;
- claim strength rules;
- negative-evidence state discipline;
- dependency propagation;
- query planning;
- permission boundaries.

## Property-based tests

Use Hypothesis for invariants such as:
- serialize → deserialize preserves canonical meaning;
- accepted-state transitions never skip required states;
- rebuild is idempotent;
- dependency propagation terminates and is order-independent;
- stable IDs remain stable under projection rebuild.

## Contract tests

Use for:
- OpenAI/Anthropic/local model adapters;
- discovery providers;
- capabilities;
- HTTP/MCP DTO parity;
- plugin boundaries.

Provider tests should use fake/recorded transports by default. Live API tests are opt-in and must never be required for CI.

## Integration tests

Use generated/synthetic documents with known pages, tables, citations, and manuscript claims. Avoid coupling CI to publisher PDFs.

## End-to-end tests

Maintain a tiny synthetic project that can exercise:

```text
init
→ ingest
→ parse
→ extract candidate
→ verify
→ review accept
→ create claim
→ audit claim
→ attach manuscript sentence
→ audit citation
→ delete .research
→ rebuild
```

## Dogfood tests

Use the real structured-traffic Q1 project manually at P15/P17. Findings become product issues or design decisions, not hidden one-off fixes.

---

# 6. Definition of Done for Every Phase

A phase is complete only when:

1. its deterministic tests pass;
2. its documented acceptance gate is demonstrated;
3. no new canonical scientific state exists only in SQLite/cache/vector/traces;
4. new accepted-state mutations produce semantic events and dependency invalidation;
5. provider/model failures leave canonical state unchanged;
6. no frontend/client has acquired direct persistence responsibility;
7. user-facing operations expose provenance for scientific outputs;
8. the phase introduces no scope from a later release merely for convenience;
9. relevant docs/ADRs are updated;
10. the implementation can be reviewed as a self-contained change before proceeding.

---

# 7. Architecture Decisions to Record as ADRs

Create ADRs when implementation begins for at least these choices:

- ADR-001: Git-readable canonical state vs SQLite projection authority.
- ADR-002: Work/Version/Artifact identity separation.
- ADR-003: Candidate/verified/accepted authority model.
- ADR-004: One application capability layer for CLI/API/MCP/UI.
- ADR-005: Provider-neutral structured semantic runtime.
- ADR-006: Embedded retrieval indexes are disposable.
- ADR-007: Strict human review as default policy.
- ADR-008: Staleness instead of silent derived-state rewriting.
- ADR-009: MCP primary host boundary with HTTP fallback.
- ADR-010: Domain plugins may extend vocabularies but not core scientific authority.

If implementation pressure suggests violating one of these, change the ADR/Product explicitly rather than introducing an undocumented exception.

---

# 8. Recommended Commit Discipline

Each task should land as a small reviewable commit or short series of commits. Preferred pattern:

```text
test: define <invariant>
feat: implement <small capability>
refactor: isolate <boundary>        # only if necessary
 docs: record <decision/gate>
```

Never combine schema redesign, provider integration, UI work, and migration logic in one large commit.

Before merging each phase:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
```

When Web exists:

```bash
cd web && pnpm test && pnpm build
```

When VS Code exists:

```bash
cd vscode && pnpm test && pnpm run compile
```

---

# 9. MVP Cut Rules

If development time becomes constrained, **cut breadth, not scientific invariants**.

Safe cuts before v1.0:
- fewer discovery providers;
- no fancy graph visualization;
- no desktop shell;
- minimal Web styling;
- no automatic table reconstruction beyond the first robust adapter;
- no plugin marketplace;
- no review calibration;
- no generic citation-manager synchronization.

Unsafe cuts:
- removing Work/Version/Artifact distinction;
- storing accepted Evidence only in SQLite/vector DB;
- allowing models to directly accept Tier-2 judgments;
- merging author claims and observed results;
- dropping stale dependency tracking;
- letting Claude/ChatGPT maintain separate project state;
- omitting exact Evidence provenance;
- treating citation existence as citation support;
- turning absence claims into unchecked natural-language judgments.

---

# 10. v1.0 Exit Criteria

Research Harness reaches v1.0 only when all of the following are true:

- A project survives complete `.research/` deletion/rebuild with identical accepted scientific state.
- The same accepted Evidence/Claim can be inspected from CLI, Web, MCP host, and VS Code.
- OpenAI and Anthropic can run the same structured verification contract.
- Evidence source anchoring opens the exact PDF location and detects invalidation after source mutation/revision.
- The strict review gate prevents a model from promoting interpretive state by itself.
- A Claim audit distinguishes support, qualification, contradiction, incomparability, scope, and coverage.
- A researcher override creates a visible Decision.
- A taxonomy change marks dependent synthesis/Claim/manuscript objects stale.
- A LaTeX sentence can trace to Claim → Evidence → source and citation mismatch is detected.
- External discovery produces reproducible SearchRuns and does not turn snippets into Evidence.
- At least one absence/prevalence claim is audited with explicit coverage and overturn risk.
- Claude and ChatGPT access the same capabilities/state through the host-neutral protocol layer.
- The structured-traffic plugin reproduces the Q1 project's taxonomy/interrogation needs without adding traffic-specific fields to the core.
- A real research session can be completed without relying on conversation history as project knowledge.

---

# 11. Immediate Next Build Sequence

When implementation starts, execute in this order:

```text
1. Phase 0 — repository/tooling
2. Phase 1 — domain + canonical persistence
3. Phase 2 — ingest/parser/anchors
4. Phase 3 — rebuild/projection/staleness
5. Phase 4 — provider-neutral runtime
6. Phase 5 — retrieval
7. Phase 6 — Evidence + review       → v0.1
8. Phase 7 — Claim audit
9. Phase 8 — synthesis/notes/questions
10. Phase 9 — manuscript audit       → v0.2
11. Phase 10 — daemon/MCP
12. Phase 11 — Web cockpit           → v0.3
13. Phase 12 — discovery/coverage    → v0.4
14. Phase 13 — cross-model gates
15. Phase 14 — plugin SPI + skill audit
16. Phase 15 — structured-traffic dogfood
17. Phase 16 — VS Code
18. Phase 17 — hardening             → v1.0
```

The first implementation milestone worth protecting at all costs is **v0.1 Evidence Loop**. If that loop is trustworthy, every later interface has a sound scientific substrate. If it is not trustworthy, Web/Claude/ChatGPT integrations only make unreliable state easier to access.
