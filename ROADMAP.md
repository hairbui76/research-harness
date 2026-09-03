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

# Next Product Track — v1.1 Conversation-first Research Workspace

This track turns the proven research core into the primary daily workspace described in the approved design specifications under `docs/superpowers/specs/`. The phase descriptions below define outcomes and gates only.

**Status, 2026-09-03: executing, on the researcher's explicit instruction to finish this roadmap — the "proceed" this track required.** The implementation plan is `docs/plans/v1.1-implementation-plan.md`; the decisions it locked are ADR-025 to ADR-029; the clause-by-clause evidence for every gate below is `docs/plans/acceptance-matrix.md`, and the loop was exercised end to end in `docs/plans/dogfood-2026-09-03-v1.1.md`. PRODUCT §42 M–P joined the invariant suite as `tests/e2e/invariants/test_v11_invariants.py` (23 tests), and §42 Q is the Design System's own JavaScript gate. Each gate carries its own dated status block.

## Cross-cutting Foundation — Research Harness Design System

**Outcome:** Every conversation, research, and manuscript surface composes one local production Design System rather than accumulating page-specific UI rules.

**Relative effort:** Medium–Large

### Product scope

- convert `design/` from a Warmline prototype bundle into a strict TypeScript package in the pnpm workspace;
- establish semantic tokens with dark default and optional light themes;
- replace CDN fonts/icons with local runtime assets or system fallbacks;
- implement accessible primitives, pane/layout foundations, and research-specific presentation components;
- provide comfortable/compact density and reduced-motion behaviour;
- add component interaction, accessibility, contrast, and dark/light visual-regression gates;
- migrate routes incrementally before removing replaced Web CSS and prototype assets.

### Boundary requirements

- Components receive typed view models and callbacks; they never call the daemon or implement research mutations.
- KaTeX, PDF.js, editor engines, compilation, and SyncTeX remain Web/application adapters.
- Scientific authority is conveyed with text/icon as well as colour and remains independent of AI/action accent.
- DeepSeek Harness and the source Warmline UI kit are references, not runtime dependencies.
- Obsolete marketing/helpdesk/generator artifacts are removed only after useful foundations have verified production replacements.

**Gate DS:** the package builds and is consumed locally by representative conversation, full research, and manuscript compositions; dark/light and compact/comfortable modes pass accessibility and visual checks; runtime makes no Design System CDN requests; and application screens do not duplicate migrated primitives or theme definitions.

> **Status 2026-09-03 — met, with one recorded substitution.** `design/` is
> `@research-harness/design` in a root pnpm workspace: semantic tokens, dark default and
> light themes, comfortable/compact density, 25 accessible primitives, the research,
> conversation, manuscript and workspace component layers, and a specimen gallery.
> **Evidence:** 920 tests in 69 files pass, each interactive component asserting `axe-core`
> with no violations; `pnpm --filter @research-harness/design lint` is clean, including the
> raw-palette lint (over `design/src` *and* `web/src`) and the WCAG 2.2 AA contrast gate
> (76 gated pairs); `web/dist` makes no CDN request for a font, icon or stylesheet; the
> Warmline prototype bundle is deleted, and `web/src/styles.css` is application layout in
> `--rh-*` tokens only. Recorded in ADR-029 and `docs/architecture/design-system.md`.
> **Substitution:** there is no browser in this workspace, so per-theme × per-density DOM
> snapshots plus a resolved-token snapshot stand in for screenshot regression. That is the
> gate's form here, not a claim to have run screenshot tests.
> **Composition:** the conversation and manuscript *routes* that compose the conversation
> and manuscript component layers landed the same day (`web/src/views/conversation/`,
> `web/src/views/manuscript/`); the final gate ran the Web suite at 280 passed with the
> raw-palette lint clean over `web/src`. See the Phase 18–21 status blocks.

# Phase 18 — Conversation Workspace Foundation

**Outcome:** A persistent three-pane research conversation becomes the default Web experience without turning chat into scientific authority.

**Relative effort:** Large

### Product scope

- left project/session/navigation rail, central conversation/composer, and collapsible research inspector;
- compose the shared Design System shell, primitives, themes, density, and research status components;
- durable private/local sessions, append-oriented messages, summaries, search, rename, and resume;
- current-session context plus relevance-selected excerpts/summaries from prior sessions;
- graph-aware, token-bounded, privacy-filtered `ContextPack` assembly;
- visible `Context used` receipts with included/omitted reasons;
- Markdown and KaTeX rendering in chat;
- explicit promotion to Note, Question, Claim candidate, and Decision candidate;
- keyboard, focus, responsive, and non-colour status requirements.

### Boundary requirements

- Accepted Evidence, Claims, Decisions, and source anchors outrank chat memory.
- Conversation records are durable but private and excluded from Git publication by default.
- Evidence promotion requires a source and resolvable anchor.
- The DeepSeek Harness submodule is interaction reference only and is not imported at runtime.

**Gate P18:** reopen and continue a session; inspect exactly what context a response used; demonstrate cross-session retrieval with privacy filtering; demonstrate that conflicting accepted scientific state outranks chat; and promote an excerpt without bypassing review.

> **Status 2026-09-03 — met on the capability, CLI and daemon surfaces; the Web route is in
> progress.** Sessions are durable and private under `conversations/CS####/`, outside
> `.research/` and git-ignored by default; every model call assembles an ordered,
> token- and privacy-budgeted `ContextPack` and records a `Context used` receipt; promotion
> reaches Note, Question, Claim candidate and Decision candidate through the existing
> capabilities, and Evidence from prose is refused. **Evidence:** all five clauses in
> `tests/e2e/test_conversation_gate.py` (10 tests), plus 68 unit, 40 integration, 30
> conversation-store, 35 capability-contract and 9 SSE-contract tests; the whole gate is
> re-run with `.research/` deleted. Recorded in ADR-025.
> **Web route:** the `/` three-pane route (`web/src/views/conversation/`,
> `web/src/app/routes.tsx`) landed with its attachments and graph-reference layers;
> `ConversationRoute.test.tsx`, `attachments.test.tsx` and `references.test.tsx` cover the
> Web side of the same clauses, and the final gate ran the Web suite at 280 passed.
> **Deferred:** a real-provider run. Both API keys in this environment are rejected
> upstream, so every send was scripted; provider neutrality itself is covered by §42 A.

---

# Phase 19 — Research Attachments

**Outcome:** Images, PDFs, and supported files can participate safely in conversation and be explicitly promoted into the scientific corpus.

**Relative effort:** Medium–Large

### Product scope

- drag/drop and picker intake with per-item validation and failure states;
- durable session-only attachment storage for every file type, including PDFs;
- image thumbnails, gallery, zoom, and download;
- PDF cards, page preview/navigation, and download;
- selected-model capability checks and egress checks before send;
- preservation of composer draft and successful items when one item fails;
- `Save to corpus` from composer, transcript, viewer, and inspector;
- Work/Version/Artifact identity resolution, hashing, deduplication, and normal ingest/parsing after confirmation.

### Boundary requirements

- Attaching a file does not create a corpus Artifact.
- `Save to corpus` does not accept Evidence or Claims.
- Unsupported files are never silently omitted from a model request.
- A failed promotion leaves the original session attachment intact and retryable.

**Gate P19:** attach and preview an image and PDF without corpus mutation; send with a compatible model and inspect `Context used`; block an incompatible send without losing the draft; promote a PDF through identity resolution; and recover cleanly from a failed promotion.

> **Status 2026-09-03 — met.** An attachment gets an `SA####` identity and nothing else:
> per-item validation, a state machine whose every failure is retryable, disposable
> previews, a total sendability check against the selected model's media, size, count,
> egress and visibility (blocking with a per-item reason and a compatible-model
> suggestion), and a `Save to corpus` that resolves identity by hash and metadata and runs
> the normal ingest. No Evidence or Claim is ever created. **Evidence:** all five clauses in
> `tests/e2e/test_attachments_gate.py` (7 tests), plus 40 integration, 15 capability-contract,
> 7 provider-media-contract and 21 media-unit tests; the dogfood session saved a duplicate
> PDF and got the existing Artifact back. Recorded in ADR-026.
> **Deferred:** the media encoders are asserted against the real OpenAI and Anthropic
> adapters over `httpx.MockTransport`, not against the vendors' endpoints — no usable key.
> The Web attachment tray composes the Design System's `AttachmentTray`, `ImageAttachment`
> and `PdfAttachment` and lands with the conversation route.

---

# Phase 20 — Unified ResearchGraph Index

**Outcome:** Stable `@` references, fast local graph traversal, and provenance-bearing context assembly work across conversation, corpus, scientific state, and manuscript objects.

**Relative effort:** Large

### Product scope

- typed node/edge/adjacency projection in local SQLite;
- projection of Project, Session, Message, Attachment, Work, Version, Artifact, document structure, Evidence, Claim, Question, Decision, Synthesis, and manuscript objects;
- deterministic structural edges plus authority-labelled scientific edges;
- stable `@W####`, `@E####`, `@C####`, and namespaced working/manuscript references;
- validated `rh://` deep links to exact source locations;
- composer autocomplete and two-way inspector traversal;
- exact, one-hop, two-hop, structured, FTS, vector, provenance, citation, and dependency query modes;
- incremental fingerprint/event updates and deterministic full rebuild;
- graph-aware context packs with authority and privacy filtering.

### Boundary requirements

- ResearchGraph is a disposable projection, never canonical scientific authority.
- Model-proposed scientific edges remain candidate until reviewed.
- Deleting `.research/` cannot change stable references or accepted relations.
- Code-symbol graph concepts remain a later plugin with a separate namespace.

**Gate P20:** rebuild the graph from durable sources and resolve the same stable references; traverse Claim ↔ Evidence ↔ Artifact anchor; preserve candidate/accepted labels; enforce session privacy during traversal; and meet warm targets of under 100 ms for exact refs and under 250 ms for one- or two-hop queries on the agreed benchmark.

> **Status 2026-09-03 — met, budgets included.** `.research/graph/research-graph.db` is a
> disposable projection with `authority` and `visibility` on every node and edge; a
> model-proposed edge cannot be written as accepted; privacy prunes the walk rather than the
> result; and the resolver answers from canonical files, checking project, existence,
> authority, privacy and anchor freshness. **Evidence:** all five clauses in
> `tests/e2e/test_graph_gate.py` (16 tests), 134 integration and 72 unit graph tests, 36
> capability-contract tests, and `tests/perf/test_graph_budgets.py` (14 tests) asserting the
> product budgets themselves. **Measured** at `--scale 1.0` on 33,180 nodes / 74,617 edges
> from 2,307 durable files: exact reference **0.07 ms**, one-hop **0.88 ms**, two-hop
> **8–12 ms**, autocomplete **0.41 ms**, provenance **3.1 ms** — every mode passing, and
> privacy filtering measurably free. Recorded in ADR-027,
> `docs/plans/performance-budgets.md` and `benchmarks/README.md`.
> **Deferred:** vector/semantic retrieval constrained by graph neighbourhoods is present as
> lexical + structural retrieval only; the embedded vector projection stays where §15 left
> it. Composer autocomplete and two-way inspector traversal in the browser land with the
> conversation route.

---

# Phase 21 — LaTeX Manuscript Workspace

**Outcome:** Research Harness provides owned LaTeX source editing, actual local PDF compilation, and scientific audit in one workspace.

**Relative effort:** Large

### Product scope

- manuscript file tree, source editor, PDF preview, and collapsible audit inspector;
- explicit read/edit/save semantics with external-change conflict detection;
- bounded local LaTeX toolchain invocation with timeout and structured diagnostics;
- real PDF output, build provenance, and retained last-good PDF after failure;
- file/line compiler errors distinct from scientific audit findings;
- source↔PDF navigation through SyncTeX when available;
- conversation references to files, selections, diagnostics, Claims, and anchors;
- model/humanizer suggestions as protected, reviewable candidate diffs only.

### Boundary requirements

- KaTeX chat rendering is not manuscript compilation.
- The compiler cannot silently rewrite user source or receive implicit network/shell authority.
- A successful compile does not imply scientific audit success.
- Applying a model suggestion is an explicit user-owned source mutation.

**Gate P21 / v1.1 conversation-first milestone:** compile a real project and inspect its PDF; retain the last good PDF on a new compile failure; navigate source/PDF when mapping exists; distinguish compiler and scientific errors; and apply a model suggestion only through an explicit reviewed diff.

> **Status 2026-09-03 — met on a real engine, Web route landed.** Compilation is
> a bounded, confined local process (allowlisted engine and flags, scrubbed environment, no
> shell escape, `tectonic --untrusted`, `latexmk -norc`, its own process group and timeout),
> outputs are disposable, the last good PDF survives a failure and is labelled stale, and
> compiler diagnostics and scientific audit findings are two lists that are never merged. A
> model rewrite is a staged candidate diff; applying is hash-checked, refused on a changed
> protected span or a failed audit, and recorded as `manuscript.source_written`.
> **Evidence:** all five clauses in `tests/e2e/test_manuscript_workspace_gate.py` (17 tests,
> against a real subprocess toolchain), 107 integration and 318 unit manuscript tests, 27
> capability-contract tests. **On a real engine:** the dogfood session compiled with
> `tectonic 0.17.0` — a real PDF in 0.38 s, SyncTeX in both directions, and a real
> `Undefined control sequence` at `main.tex:28` that kept the last good PDF. Recorded in
> ADR-028 and `docs/plans/dogfood-2026-09-03-v1.1.md` §6.
> **Web route:** the manuscript workspace (`web/src/views/manuscript/`) replaced the v1.0
> Manuscript page — file tree, editor with hash-checked saves, real PDF preview with the
> last-good banner, two diagnostics lists, SyncTeX both ways, candidate diffs;
> `ManuscriptWorkspace.test.tsx` covers the Web side of the clauses.
> **Deferred:** the suite's own engine is a hermetic fake toolchain, and the real-toolchain
> integration test stays opt-in (skipped when no engine is installed), so CI does not
> depend on a TeX distribution.

---

## v1.1 follow-on — Subscription-backed local CLI providers

**Outcome:** A researcher who already pays for a coding CLI reuses that login as a model backend, with no API key, and gives up none of the harness's authority, privacy, or provenance guarantees.

**Relative effort:** Medium

### Product scope

- reuse an existing CLI subscription or account login instead of supplying a provider API key;
- detect supported executables, versions, authentication state, and available models without mutating the workspace;
- keep every runtime-specific detail below the model-provider boundary, as one declarative definition per runtime;
- present the same runtime status and configuration behaviour in the Web cockpit and the terminal;
- convert every successful CLI answer into the existing `RawCompletion` / `ModelResponse` path, so Pydantic validation stays authoritative;
- support bounded cancellation, timeouts, process-tree cleanup, and useful error classification on Windows, macOS, and Linux;
- preserve existing workspaces and HTTP providers with no migration.

### Boundary requirements

- A CLI is a model backend, never an agent: it does not drive the workflow, cannot accept Evidence, Claims, or Decisions, and cannot edit the project, run project commands, or choose unreviewed tools.
- "Local" names where the process starts, not where inference happens. A CLI provider is external egress unless local inference is positively established; each definition declares a host or `unknown_external`, and `privacy.external_models: disabled` refuses it before it spawns.
- Bounded execution is native or nothing: a runtime is routable only when the installed version proves a no-tools, read-only posture through its own controls. There is no prompt-only safety fallback, and no full-agent bypass flag is copied into a definition.
- Research content travels on stdin or the runtime's RPC channel, never argv, from an empty temporary working directory under an environment with provider API-key and unrelated cloud-credential variables removed.
- One capability surface answers every client: `provider.cli.scan|configure|remove|test` is the only way Web or CLI learns availability or changes `research.yaml`, and no client recomputes a gate the daemon already decided.

**Gate CLI-P:** each of the fifteen acceptance criteria in the design specification's §24 is demonstrated by a named test; five of the seven registered runtimes may be listed as detected-but-not-routable, provided each says which gate stopped it.

> **Status 2026-09-04 — met, with one criterion resting on an opt-in live run.** Seven
> runtimes are registered and detected; Codex CLI and Claude Code are routable, and the
> other five report the gate that stops them. The clause-by-clause evidence is
> `docs/plans/acceptance-matrix.md` § *Subscription-backed local CLI providers*; the
> decision is ADR-030 and the researcher-facing text is `docs/guide/providers.md`.
> **Pending:** criterion (4)'s live module and the repository-wide secret scan belong to
> the release task, and the *Models & providers* settings section is the browser half of
> (3) and (12) — the daemon half of both is green now.

| § | criterion | demonstrated by | status |
|---|---|---|---|
| 1 | Open Design is a pinned submodule, not a runtime dependency | `git submodule status` shows `9bb4a7d…`; `tests/unit/providers/cli/test_registry.py::test_the_shipped_registry_is_importable_and_ordered` | holds |
| 2 | A fresh scan detects all seven runtimes independently and normalizes their status | `test_defs_others.py::test_all_seven_runtimes_are_registered_in_display_order`; `tests/unit/providers/cli/test_detection.py`; `test_cli_providers.py::test_scan_lists_all_seven_runtimes_in_registry_order_and_edits_nothing` | holds |
| 3 | Web and `research providers add` create the same validated entry | `test_cli_providers.py::test_configure_writes_one_validated_entry`; `test_cli_providers_commands.py::test_add_refuses_an_unavailable_runtime_and_writes_an_available_one`; `settings.test.tsx` ("adds a provider with the chosen model and reasoning, after the egress warning") | holds on the Python side; browser half with the settings section |
| 4 | A logged-in user with no API key completes a schema-validated request through each routable CLI | `tests/contract/providers/test_live_cli_smoke.py`, gated by `RESEARCH_HARNESS_LIVE_CLI_TESTS=1` | holds (opt-in live run) — Task 15 records the date and versions |
| 5 | Existing commands select the CLI through `--provider`, with no workflow branch | `test_cli_providers_commands.py::test_existing_workflow_commands_select_the_cli_entry_with_provider` | holds |
| 6 | Research content is delivered through stdin/RPC, never argv | `test_cli_provider.py::test_research_content_travels_on_stdin_never_argv`; `test_cli_provider_runtimes.py::test_every_other_runtime_answers_the_same_contract`; `test_registry.py::test_research_content_may_not_reach_argv` | holds |
| 7 | A CLI provider is external egress unless local inference is positively established | `test_cli_provider.py::test_capabilities_are_external_text_only_and_structured`; `test_types.py::test_the_unknown_external_host_is_never_local`; `test_registry.py::test_a_local_egress_host_is_refused`; `test_cli_providers.py::test_a_configured_cli_entry_appears_in_the_catalog_as_external` | holds |
| 8 | The privacy policy prevents the process from spawning | `test_cli_provider.py::test_the_privacy_policy_refuses_before_any_process_is_spawned`; `test_cli_providers.py::test_the_test_call_is_refused_by_the_policy_before_any_spawn` | holds |
| 9 | The runtime cannot edit files or run project tools; a tool event fails the request | `test_cli_provider.py::test_a_tool_event_cancels_the_process_and_is_a_bounded_authority_violation`; `test_cli_provider_runtimes.py::test_every_other_runtime_fails_on_a_tool_event`; `test_registry.py::test_a_bypass_flag_anywhere_in_argv_is_refused` | holds |
| 10 | Invalid, partial, or schema-incompatible output never reaches staging or accepted state | `test_cli_provider.py::test_invalid_json_fails_through_the_shared_structured_output_path` and `::test_a_schema_violation_never_returns_a_partial_object` | holds |
| 11 | Cancellation and timeout terminate the whole process tree | `test_process.py::test_cancel_terminates_grandchildren` and `::test_exiting_is_bounded_when_a_grandchild_inherits_the_pipes`; `test_cli_provider.py::test_abandoning_the_stream_cancels_the_process` and `::test_abandoning_the_stream_through_the_wrapper_also_cancels_the_process` | holds |
| 12 | Web and CLI display identical availability and failure reasons | `test_cli_providers.py::test_configure_and_scan_answer_identically_over_the_daemon` and `::test_the_scan_view_and_the_catalog_agree_about_a_refused_entry`; `test_cli_providers_commands.py::test_scan_prints_every_runtime_with_its_state`; `settings.test.tsx` ("renders the daemon states …") | holds on the Python side; browser half with the settings section |
| 13 | Existing HTTP, local-server, and scripted providers pass their tests unchanged | `tests/contract/providers/test_model_contract.py`, `test_native_streaming.py`, `tests/e2e/invariants/test_a_provider_independence.py`, all unchanged; the wave gate ran the full suite at 4250 passed / 40 skipped | holds; Task 15 re-runs the full suite |
| 14 | Default CI needs no installed CLI, login, key, or network call | every default test drives `tests/fixtures/cli/fakes.py`; `tests/contract/protocol/test_new_capability_parity.py` empties `PATH`; the live test is environment-gated | holds for the default suite; the gate variable and the live module arrive with Task 15 |
| 15 | Logs, traces, fixtures, configuration, and UI contain no credential material | `test_errors.py::test_messages_carry_identity_and_a_next_action_but_no_secret` and `::test_a_secret_straddling_the_stderr_truncation_boundary_is_still_redacted`; `test_detection.py::test_a_diagnostic_never_carries_a_home_path_or_a_token`; `test_cli_providers.py::test_the_test_call_reports_a_failure_without_a_secret` | holds; Task 15 adds the repository-wide secret scan |

> **Not routable in this release, and why.** Cursor Agent and Amp run headless only behind
> an approval bypass; DeepSeek Harness's profile and Pi's RPC session execute tools of
> their own; all four therefore report `bounded_mode: unsupported`. OpenCode declares a
> `native_env` posture — a deny table injected through the environment rather than proved
> by a flag — so a help probe cannot establish it, and its bounded mode stays `unknown`
> until a version with recorded fixtures is verified. Adding any of them later is a change
> to one definition's `BoundedPosture` plus fixtures, not to the engine.

---

# Later Post-v1.0 Extensions

These items stay deliberately outside the v1.0 critical path.

## v1.2 — Systematic Review Plugin

Add:
- PRISMA-oriented screening/reporting;
- inclusion/exclusion protocol templates;
- deduplication audit;
- SearchRun coverage reports;
- systematic-review export artifacts.
- adapt the retained `my-literature-review` contract into plugin workflow fragments only after the Phase 14 mapping and boundary tests pass.

The systematic-review plugin consumes existing SearchRun/coverage primitives; it must not force PRISMA concepts into the generic core.

## v1.3 — Reviewer / Calibration Extensions

After the skill audit, consider:
- bounded domain reviewer role;
- devil's-advocate claim/paper stress test;
- editorial synthesis workflow;
- calibration against user-supplied gold sets;
- panel disagreement visualization.

These remain **review extensions**, not authorities that can mutate accepted scientific state automatically.

## v1.4 — Packaging and Desktop Experience

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

## Conversation-first track matrix

| Capability | DS | P18 | P19 | P20 | P21 |
|---|---:|---:|---:|---:|---:|
| Shared typed Design System package | ✓ | ✓ | ✓ | ✓ | ✓ |
| Dark default / light optional themes | ✓ | ✓ | ✓ | ✓ | ✓ |
| Accessible primitives and pane composition | ✓ | ✓ | ✓ | ✓ | ✓ |
| Three-pane conversation workspace |  | ✓ | ✓ | ✓ | ✓ |
| Durable private sessions |  | ✓ | ✓ | ✓ | ✓ |
| Cross-session retrieval / `Context used` |  | ✓ | ✓ | ✓ | ✓ |
| Markdown + KaTeX chat rendering |  | ✓ | ✓ | ✓ | ✓ |
| Session-only image/PDF attachments |  |  | ✓ | ✓ | ✓ |
| Explicit `Save to corpus` |  |  | ✓ | ✓ | ✓ |
| Unified ResearchGraph projection |  |  |  | ✓ | ✓ |
| Stable `@` refs and `rh://` deep links |  |  |  | ✓ | ✓ |
| Graph-aware context packs |  |  |  | ✓ | ✓ |
| LaTeX source/editor/PDF workspace |  |  |  |  | ✓ |
| Real local compilation / SyncTeX |  |  |  |  | ✓ |
| Candidate-only model manuscript diffs |  |  |  |  | ✓ |

**Status 2026-09-03.** Every row above is built on the capability, CLI, daemon and MCP
surfaces, and each gate's dated status block says on what evidence. Two rows are still
half-landed in the browser: the *three-pane conversation workspace* and the *LaTeX
source/editor/PDF workspace* have their Design System components and their Python
capabilities, and their Web routes were still being written when the blocks were dated.

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
- P18 must lock session identity, privacy, and `ContextPack` contracts before dependent conversation features.
- P19 attachment presentation/intake and P20 projection/query work can proceed in parallel after those P18 contracts stabilize.
- P21 can begin its isolated compiler/editor work after source ownership is locked, then integrate P20 references and the P18 inspector/context contracts.

The conversation-first dependency path is:

```text
DS Design System Foundation
   └── P18 Conversation Foundation
          ├── P19 Research Attachments
          └── P20 ResearchGraph
                 └── P21 LaTeX Workspace
```

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
19. Review and explicitly approve the written conversation-first design specifications   ✓ 2026-09-03
20. Establish the Research Harness Design System foundation                                ✓ Gate DS met
21. Phase 18 — conversation workspace foundation                                           ✓ Gate P18 met
22. Phase 19 — research attachments                                                        ✓ Gate P19 met
23. Phase 20 — unified ResearchGraph index                                                 ✓ Gate P20 met
24. Phase 21 — LaTeX manuscript workspace → v1.1 conversation-first milestone              ✓ Gate P21 met → v1.1
```

The first implementation milestone worth protecting at all costs is **v0.1 Evidence Loop**. If that loop is trustworthy, every later interface has a sound scientific substrate. If it is not trustworthy, Web/Claude/ChatGPT integrations only make unreliable state easier to access.

Steps 19–24 were authorised on 2026-09-03 by the researcher's explicit instruction to finish this roadmap, which is the "proceed" the *Next Product Track* required; they were executed against `docs/plans/v1.1-implementation-plan.md`. Each gate's dated status block above says what is met, what evidence demonstrates it, and what is deferred. All four Web surfaces (the `/` conversation workspace with its attachments and references layers, and the manuscript workspace) landed the same day and passed the final gate. Nothing beyond Phase 21 is authorised, and the later extensions (v1.2 onward) still need their own explicit instruction.
