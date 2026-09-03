# Research skill adaptation inventory

Complete Phase 14.2 audit of every asset under `skills/`. This inventory records design
decisions only; it does not imply that the corresponding Research Core capabilities or
plugins have been implemented. The long-form rationale, with the quoted instruction behind
each ruling, is `docs/plans/skill-audit.md`. The plugin boundary these classifications are
measured against is `src/research_harness/plugins/` and `plugins/README.md`.

Imported skills are **design inputs, not trusted runtime components** (PRODUCT.md §32.5).
Nothing under `skills/` is a runtime dependency of the core, and no skill has been copied
into it.

## 1. Result

| Classification | Assets | Meaning |
|---|---:|---|
| `reuse-as-contract` | 5 | Semantics lift almost verbatim; edits are removing a host reference, not rewriting a rule. |
| `adapt-to-plugin` | 30 | Real domain or workflow value, but writes become capability calls, identifiers become harness IDs, outputs become candidates. |
| `inspiration-only` | 48 | Good idea, architecture fights an invariant. Read it; do not wire it. |
| `exclude` | 14 | Redundant, unsafe, host-coupled, or outside the product scope. |
| **Total** | **97** | Every file under `skills/` except this register. |

## 2. Locked initial decisions (unchanged)

These were locked before the audit and are preserved verbatim.

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

Two corrections the audit found in the working tree, neither reversing a decision above:

- The `my-literature-review` **v2.1.0 monolith is not in this repository**; the Claude-in-Chrome
  CAPTCHA path and the static venue-rank table are not present either. What is on disk is
  `3.0.0-rh1`, the adaptation those decisions called for. The monolith row stays as the
  historical ruling; the five files on disk are classified below on what they now contain.
- `humanizer` on disk is `2.12.0-rh1` and already carries a "Research Harness manuscript
  mode". One clause still blocks it: its **File mode** writes the rewrite to disk.

## 3. Reused and adapted assets — targets, authority, permissions

**F-core** (forbidden for every plugin asset, enforced by `PermissionedGateway` regardless
of the manifest): `evidence.accept`, `evidence.reject`, `decision.accept`,
`claim.override_strength`, `review.accept_batch`, `review.resolve_conflict`, `taxonomy.put`,
`note.promote`, `manuscript.attach_claim`, `synthesis.build_matrix`, `search_run.record`,
`work.register`, `work.store_blocks`, `state.rebuild`; plus any direct write to canonical
files, projections, or SQLite. Capabilities are drawn from `PLUGIN_ALLOWED_CAPABILITIES`.

### 3.1 Target, authority, capabilities

| Asset (under `skills/`) | Class | Target plugin → role / workflow / policy | Authority | Allowed capabilities | Also forbidden, beyond F-core |
|---|---|---|---|---|---|
| `humanizer/SKILL.md` | adapt | `academic-writing` → policy `academic_writing.humanizer` | manuscript candidate | none (pure text transform) | Writing any file; adding, removing, strengthening or weakening a proposition; altering a protected span |
| `humanizer/LICENSE` | reuse | `academic-writing` (retained verbatim) | none | none | Modifying or omitting the MIT notice |
| `my-literature-review/SKILL.md` | adapt | `structured-traffic` → fragment `literature_review` | candidate | `corpus.search`, `retrieval.search`, `retrieval.resolve_source`, `work.get`, `review.inbox` | Promoting a snippet or abstract to Evidence |
| `my-literature-review/references/discovery-and-snowball.md` | adapt | `structured-traffic` → fragment `discovery` + search providers | candidate metadata | `retrieval.search`, `corpus.search`, `retrieval.resolve_source` | Merging Versions during dedup; a failed request counted as a zero result |
| `my-literature-review/references/coverage-and-baselines.md` | adapt | `structured-traffic` → fragment `coverage` | candidate | `review.inbox`, `claim.find_support`, `claim.find_counterevidence` | Wording an absence claim above the recorded coverage rung |
| `my-literature-review/references/reading_framework.md` | adapt | `structured-traffic` → interrogation schema + validators | candidate (staging) | `evidence.extract`, `work.get` | Its four-value origin list in place of `EvidenceOrigin` (`author_stated` collapses two core origins) |
| `academic-paper-reviewer/agents/methodology_reviewer_agent.md` | adapt | `academic-review` → role `.methodology_reviewer` | audit result | `work.get`, `claim.find_counterevidence` | Emitting `## Editorial Decision`; any score→decision mapping |
| `academic-paper-reviewer/agents/domain_reviewer_agent.md` | adapt | `academic-review` → role `.domain_reviewer` | audit result | `work.get`, `corpus.search`, `claim.find_support` | Emitting `## Editorial Decision`; "missing key references" as a novelty finding |
| `academic-paper-reviewer/agents/perspective_reviewer_agent.md` | adapt | `academic-review` → role `.perspective_reviewer` | audit result | `work.get` | Emitting `## Editorial Decision` |
| `academic-paper-reviewer/agents/devils_advocate_reviewer_agent.md` | adapt | `academic-review` → role `.skeptic`, narrowing core `skeptic` | audit result | `claim.find_counterevidence`, `work.get` | Scoring at all (its own rule); withdrawing a finding on a 1–5 rebuttal score |
| `academic-paper-reviewer/references/sprint_contract_protocol.md` | adapt | `academic-review` → fragment `blind_scoring_plan` | candidate | `evidence.verify`, `review.inbox` | The terminal `editorial_decision` / `action` field |
| `academic-paper-reviewer/references/re_review_mode_protocol.md` | adapt | `academic-review` → fragment `revision_traceability` | candidate | `work.get`, `evidence.verify`, `review.inbox` | Comparing revisions without an explicit `VersionId` on each side |
| `academic-paper-reviewer/references/statistical_reporting_standards.md` | adapt | `academic-review` → interrogation fields + validators | candidate | `evidence.extract` | Turning the completeness score into an accept/reject verdict |
| `academic-paper-reviewer/references/calibration_mode_protocol.md` | adapt | `academic-review` → fragment `calibration` | none (measurement report) | `review.inbox` | Using the error profile as an acceptance gate rather than a disclosure |
| `academic-paper-reviewer/templates/peer_review_report_template.md` | adapt | `academic-review` → rendering of `ClaimAuditOutput` | audit result | none | The inline `Weighted Average → [Accept/…]` cell; confidence-weighted arbitration |
| `academic-paper-reviewer/templates/revision_response_template.md` | reuse | `academic-review` → author response ledger | none (author artefact) | none | Implying or recording acceptance |
| `deep-research/references/crossref_api_protocol.md` | reuse | `structured-traffic` → resolver contract | external metadata | `retrieval.resolve_source` | Recording `false` where the service was unreachable |
| `deep-research/references/openalex_api_protocol.md` | reuse | `structured-traffic` → search provider + resolver | external metadata | `retrieval.resolve_source`, `retrieval.search` | Recording `false` where the service was unreachable |
| `deep-research/references/semantic_scholar_api_protocol.md` | adapt | `structured-traffic` → search provider + resolver | external metadata | `retrieval.search`, `retrieval.resolve_source` | The named `WebSearch` tier (becomes `retrieval.search`) |
| `deep-research/references/failure_paths.md` | adapt | `structured-traffic` → `SourceFailure` kinds + review items | none (taxonomy) | `review.inbox` | Any path folding a blocked or failed search into a zero result |
| `deep-research/references/systematic_review_protocol.md` | adapt | future `systematic-review` → fragment sequencing | candidate | `corpus.search`, `evidence.extract`, `review.inbox` | Model-issued phase verdicts as gates |
| `deep-research/agents/bibliography_agent.md` | adapt | `structured-traffic` → fragments `discovery` + `screening` | candidate metadata | `corpus.search`, `retrieval.search`, `retrieval.resolve_source`, `review.inbox` | Dedup that merges a preprint with its published Version |
| `deep-research/agents/source_verification_agent.md` | adapt | `structured-traffic` → fragment `source_verification` | verification result | `evidence.verify`, `retrieval.resolve_source` | `WebSearch`; letter grade used as an automatic use/do-not-use gate |
| `deep-research/agents/timeline_extraction_agent.md` | adapt | `structured-traffic` → version-identity fields + validators | candidate metadata | `work.get`, `retrieval.resolve_source` | Writing `timeline.yaml` / `citation_provenance.yaml` directly |
| `deep-research/templates/evidence_assessment_template.md` | adapt | `structured-traffic` → interrogation schema | candidate | `evidence.extract`, `evidence.verify` | The A–F roll-up as an accept/reject gate |
| `slr-writer/SKILL.md` | adapt | `structured-traffic` + `academic-writing` → fragments | candidate | `corpus.search`, `work.get`, `evidence.extract`, `evidence.verify`, `review.inbox` | `slr-output/` and `state.json` writes; the ungated deep-read phase |
| `slr-writer/agents/scope_taxonomy_agent.md` | adapt | `structured-traffic` → role `.taxonomy_proposer` | Decision candidate | `work.get`, `corpus.search` | Declaring a taxonomy as fact; `taxonomy.put` |
| `slr-writer/agents/deep_reader_agent.md` | adapt | `structured-traffic` → role `.deep_reader`, narrowing core `evidence_extractor` | staging evidence | `evidence.extract`, `work.get` | The `Read` tool; labelling a fact `verified` without `evidence.verify` |
| `slr-writer/agents/evidence_mapper_agent.md` | adapt | `structured-traffic` → fragment `claim_coverage` | candidate | `claim.find_support`, `claim.find_counterevidence`, `review.inbox` | Deriving a gap from an unplaced or thin cell |
| `slr-writer/agents/section_writer_agent.md` | adapt | `academic-writing` → role `.section_writer`, narrowing core `writer` | manuscript candidate | `work.get` | `SLRW_SECTION_GATE=0`; any number not copied from a card |
| `slr-writer/agents/assembler_checker_agent.md` | adapt | `academic-writing` → fragment `manuscript_audit` | audit result | `review.inbox` | Declaring a draft done with `UNVERIFIED` items outstanding |
| `slr-writer/references/anti_hallucination_rules.md` | reuse | `academic-writing` → policy `academic_writing.citation_discipline` | manuscript candidate | none | Inventing a reference; the `CLAUDE.md` tone clause |
| `slr-writer/references/evidence_card_spec.md` | adapt | `structured-traffic` → interrogation schema + Evidence mapping | staging evidence | `evidence.extract` | `citation_key` used as Work, Version and Artifact identity at once |
| `slr-writer/references/ieee_survey_structure.md` | adapt | `academic-writing` → policy `academic_writing.ieee_survey` | manuscript candidate | none | `CLAUDE.md` as the keyword vocabulary source |
| `slr-writer/references/prisma_protocol.md` | adapt | `structured-traffic` → coverage report rendering | none (reporting) | `review.inbox` | Counts that do not separate a failed search from a zero result |

### 3.2 Output schema, host dependency, checkpoint and coverage expectations

| Asset (under `skills/`) | Required output schema | Claude/ChatGPT-specific? | Checkpoint / resume | Failure & coverage reporting |
|---|---|---|---|---|
| `humanizer/SKILL.md` | `academic_writing.StylePassResult` (new: candidate text, `SemanticDiff`, `ProtectedSpan` preservation report) | No (its `agents/openai.yaml` is, and is excluded) | Stateless single pass; no resume | Passage left unchanged and flagged when it cannot be improved without touching a protected span |
| `humanizer/LICENSE` | none | No | n/a | n/a |
| `my-literature-review/SKILL.md` | `SearchRun`, `WorkCandidate`, `CoverageReport` | No — explicitly provider-neutral | Durable `WorkflowRun` per review; stage checkpoints replace the "proposed import packet" | Required: *"Include failures and unresolved items; do not report them as zero results."* |
| `.../references/discovery-and-snowball.md` | `SearchRun`, `SourceFailure`, `SourceCursor`, `WorkCandidate` | No | Per-source cursor and page boundary persisted; snowball depth is a stop condition | Rate-limit, auth, parse, access and interruption recorded as distinct `SourceFailure` kinds and excluded from coverage |
| `.../references/coverage-and-baselines.md` | `CoverageReport`, `CoverageUniverse`, `Claim` (absence) | No | n/a (read before a literature-wide statement) | The five-rung gap ladder is the wording bound; overturn risk and blind spots are required fields |
| `.../references/reading_framework.md` | `InterrogationSchema` + `InterrogationField`, `ExtractionOutput` | No | Per-field extraction, re-run only for changed fields | Cell status must include `not_reported` / `not_examined` / `unavailable` / `conflicting`; abstract-only stays labelled |
| `apr/agents/methodology_reviewer_agent.md` | `ClaimAuditOutput` | No | Two-call sprint contract (below) | Fallacy checklist findings become audit warnings, never a verdict |
| `apr/agents/domain_reviewer_agent.md` | `ClaimAuditOutput` | No | Two-call sprint contract | A missing reference is a warning, not evidence of a gap |
| `apr/agents/perspective_reviewer_agent.md` | `ClaimAuditOutput` | No | Two-call sprint contract | Assumption audit findings are candidates |
| `apr/agents/devils_advocate_reviewer_agent.md` | `SkepticOutput` | No | Two-call sprint contract | A failed cross-model check is logged, never treated as "no issues" — keep this |
| `apr/references/sprint_contract_protocol.md` | `academic_review.ScoringPlan` (new: dimensions, block/warn triggers) | No | **Its whole point**: Phase 1 commits blind, Phase 2 reads. Stage 1's fingerprint must contain no document content | Panel-cardinality abort rather than a synthesized substitute score — keep this |
| `apr/references/re_review_mode_protocol.md` | `academic_review.TraceabilityMatrix` (new: comment, claim, `VersionId`, verdict) | No | Per-item; unresolved Priority-1 items block completion | `Cannot verify` is a first-class outcome → `VerificationVerdict.INSUFFICIENT_EVIDENCE` |
| `apr/references/statistical_reporting_standards.md` | `InterrogationField` set + `ValidationIssue` | No | Stateless | Red-flag taxonomy becomes validator issues at `warning`/`error` |
| `apr/references/calibration_mode_protocol.md` | `academic_review.CalibrationReport` (new) | No | Session-scoped only; it explicitly refuses cross-session caching | Refuses to run on a degenerate gold set; disclosure is mandatory |
| `apr/templates/peer_review_report_template.md` | `ClaimAuditOutput` | No | n/a | Severity definitions and citation discipline retained; the decision cell removed |
| `apr/templates/revision_response_template.md` | `academic_review.ResponseLedger` (new: comment → response → change, page-level log) | No | n/a | Change log doubles as a lightweight Version delta |
| `dr/references/crossref_api_protocol.md` | `SourceFailure`, `IdentifierField` | No | Retry-then-raise; no partial state | *"absent != false"* — the field is omitted, not falsified, when the service is unreachable |
| `dr/references/openalex_api_protocol.md` | `SourceFailure`, `WorkCandidate` | No | Retry-then-raise | Same omit-on-degradation rule |
| `dr/references/semantic_scholar_api_protocol.md` | `SourceFailure`, `VerificationOutput` | **Yes** — names `WebSearch`; must be genericized | Per-batch; never blocks on API failure | `S2_NOT_FOUND` explicitly is not fabrication; verdict is categorical, `match_score` informational |
| `dr/references/failure_paths.md` | `SourceFailure` kinds, review-inbox items | No | Defines a save-and-continue path for an abandoned run | The asset itself is the failure taxonomy; needs one addition — separate "search blocked" from "few results" |
| `dr/references/systematic_review_protocol.md` | `CoverageReport`, `SynthesisMatrix` | No | Hard phase gates (protocol before search, bias before synthesis) | Blocking rules are retained as workflow preconditions, not as model verdicts |
| `dr/agents/bibliography_agent.md` | `SearchRun`, `WorkCandidate`, `SearchResultCounts` | No | PRISMA counts per stage | *"Iron Rule 2 — No silent skip"* and the zero-hit note (stale corpus / shifted RQ / bad export) are model contributions worth keeping |
| `dr/agents/source_verification_agent.md` | `VerificationOutput` | **Yes** — `WebSearch` tier | Per-batch | Requires a "Verification Limitations" section: what could not be verified and why |
| `dr/agents/timeline_extraction_agent.md` | `WorkCandidate` + version fields (`supersedes`, `superseded_by`, `version_family_id`) | No | Per-Work | Categorical `precision` (`day`/`month`/`year`/`interval`/`unknown`) and `version_catalog_completeness` |
| `dr/templates/evidence_assessment_template.md` | `InterrogationSchema` + `Evidence` | No | Per-source card | 20% spot-check sampling rule becomes an explicit coverage statement |
| `slr-writer/SKILL.md` | `WorkflowRun`, `CoverageReport`, `ManuscriptAuditReport` | Partly — invokes `/my-literature-review` as a slash command | **Strongest in the collection**: every gate result persisted, resume at the first unconfirmed gate → maps to `WorkflowRun` + `StageRecord` | Per-phase gates; deep-read phase must gain the gate it lacks |
| `slr/agents/scope_taxonomy_agent.md` | `Decision` (candidate), `TaxonomyTerm` | No | One confirmation gate | Refuses to promise coverage the corpus lacks |
| `slr/agents/deep_reader_agent.md` | `ExtractionOutput`, `Evidence` + `Anchor` | **Yes** — the `Read` tool's PDF paging | Skips Works already read; per-Work checkpoint | Abstract-only cards flagged at end of phase, never silently treated as no evidence |
| `slr/agents/evidence_mapper_agent.md` | `structured_traffic.ClaimCoverageReport` (new) or `CoverageReport` | No | One confirmation gate | Thin subsections, orphan papers, and unplaced entries are all surfaced pre-gate |
| `slr/agents/section_writer_agent.md` | `WriterOutput` | Partly — `CLAUDE.md` tone rule | Per-section gate (the `SLRW_SECTION_GATE=0` bypass must not travel) | Reports every place the plan wanted a number and no card supplied one |
| `slr/agents/assembler_checker_agent.md` | `ManuscriptAuditReport`, `TraceLink` | Partly — `CLAUDE.md` keywords | Runs after every assembly | *"Checks (report all, do not silently pass)"*; every unbacked sentence listed `UNVERIFIED`; abstract-only misuse flagged |
| `slr/references/anti_hallucination_rules.md` | `ManuscriptAuditReport` findings | Partly — one `CLAUDE.md` quote to drop | n/a | `[NEEDS SOURCE]` inline plus surfaced to the user; claimed vs verified kept distinct |
| `slr/references/evidence_card_spec.md` | `Evidence` + `Anchor`, `NumericValue` | No | Per-Work card | *"A fact without a location is not verified"*; `not reported` recorded as a value |
| `slr/references/ieee_survey_structure.md` | `WritingPolicyContribution` | Partly — `CLAUDE.md` keywords | n/a | n/a (style reference) |
| `slr/references/prisma_protocol.md` | `SearchResultCounts`, `CoverageReport` | No | Counts recomputed per run | Every arrow carries an exact number and exclusion reasons must tally |

## 4. Inspiration-only (48)

Useful design ideas whose architecture conflicts with an invariant. Not wired into any
plugin.

| Asset (under `skills/`) | Why it stays out |
|---|---|
| `grill-with-docs/SKILL.md` | *"When a term is resolved, update `CONTEXT.md` right there."* The model decides a term is settled and writes in the same breath. Taxonomy is a researcher-accepted `Decision` (§38) that invalidates dependents (ADR-008). |
| `grill-with-docs/CONTEXT-FORMAT.md` | Same write-on-resolution trigger; the glossary discipline itself is a good model for the taxonomy Decision UX. |
| `academic-paper-reviewer/agents/field_analyst_agent.md` | Reviewer-persona configuration is useful, but its journal recommendations come from the excluded static venue table. |
| `academic-paper-reviewer/references/quality_rubrics.md` | Top originality band is *"no prior work addresses this exact question"* — novelty from absence (§32.5) — and its Decision Mapping turns a number into Accept. |
| `academic-paper-reviewer/references/review_criteria_framework.md` | A second, unreconciled rubric (1–5 over seven dimensions vs. the other file's 0–100 over five) with its own score→decision table. The bias checklist is the salvageable part. |
| `academic-paper-reviewer/references/review_quality_thinking.md` | Pure reasoning heuristics with no schema, no authority, and nothing to bind to a capability. |
| `academic-paper-reviewer/references/guided_mode_protocol.md` | Dialogue-flow UX; too thin to be a contract. |
| `academic-paper-reviewer/examples/hei_paper_review_example.md` | Worked transcript; demonstrates the model-issued Decision and confidence-weighted arbitration this audit excludes. |
| `academic-paper-reviewer/examples/interdisciplinary_review_example.md` | Worked transcript; good evidence that genuinely non-overlapping reviewers find non-duplicated issues. |
| `deep-research/SKILL.md` | Orchestration is pinned to `phase{N}_*/` directories, a "Material Passport", and `ARS_PASSPORT_RESET=1` resume. The mode taxonomy and quality table are the useful part. |
| `deep-research/agents/synthesis_agent.md` | *"**Silence**: What themes have < 2 sources? These are potential gaps."* — novelty from absence; also appends to the Material Passport. |
| `deep-research/agents/devils_advocate_agent.md` | A 1–5 rebuttal score decides whether a finding is conceded; confidence is not an acceptance signal (§24.4). |
| `deep-research/agents/ethics_review_agent.md` | Model-issued `CLEARED` is functionally terminal; the checklist content is the useful part. |
| `deep-research/agents/report_compiler_agent.md` | Its citation-anchor idea is good; the `<!--ref:slug-->` marker syntax and Material Passport coupling are foreign runtime machinery. |
| `deep-research/agents/research_question_agent.md` | Gates progression on a numeric FINER average. |
| `deep-research/agents/research_architect_agent.md` | Study-design content, no reuse surface for a literature workstation. |
| `deep-research/agents/risk_of_bias_agent.md` | RoB 2 / ROBINS-I is clinical-trial methodology, narrow for this product; phase-blocking gate is a good pattern. |
| `deep-research/agents/meta_analysis_agent.md` | Quantitative pooling is outside scope; its "report all pre-specified subgroups, do not suppress null findings" rule is aligned and worth remembering. |
| `deep-research/agents/monitoring_agent.md` | Generates alert configurations for the human to install; sits outside the capability surface entirely. |
| `deep-research/agents/socratic_mentor_agent.md` | Dialogue pedagogy with no architectural coupling and no contract to extract. |
| `deep-research/references/argumentation_reasoning_framework.md` | Its epistemic-status ladder is good and that is the problem: a second status vocabulary beside `ClaimStatus`, `EvidenceStrength` and L0–L4 would redefine core meanings by accretion (ADR-010). |
| `deep-research/references/source_quality_hierarchy.md` | Collapses six dimensions into an A–F letter used prescriptively (*"F: Do not use"*) — a grade acting as an acceptance gate. |
| `deep-research/references/cross_agent_quality_definitions.md` | Its shared-severity glossary is a good idea; the definitions are framed around a pipeline the harness does not have. |
| `deep-research/references/ethics_checklist.md` | Names vendors as the disclosure example (*"e.g., \"Claude,\" \"GPT-4,\" \"Gemini\""*); content is otherwise reusable for a human review item. |
| `deep-research/references/apa7_style_guide.md` | Citation formatting; the manuscript layer uses BibTeX/LaTeX and its own citation verification. |
| `deep-research/references/equator_reporting_guidelines.md` | Reporting-guideline map; reference knowledge, no contract. |
| `deep-research/references/interdisciplinary_bridges.md` | Concept-transfer catalogue; domain reading, not machinery. |
| `deep-research/references/literature_monitoring_strategies.md` | Platform setup guide for the researcher; nothing the harness executes. |
| `deep-research/references/logical_fallacies.md` | Catalogue for a skeptic prompt; content, not contract. |
| `deep-research/references/methodology_patterns.md` | Research-design templates; outside the evidence pipeline. |
| `deep-research/references/mode_selection_guide.md` | Mode taxonomy is a useful UX reference; it operationalizes the all-model-verdict chain. |
| `deep-research/references/preregistration_guide.md` | Confirmatory-study preregistration; outside a literature workstation's scope. |
| `deep-research/references/socratic_mode_protocol.md` | Dialogue protocol; no schema. |
| `deep-research/references/socratic_questioning_framework.md` | Question banks; content, not contract. |
| `deep-research/references/systematic_review_toolkit.md` | Consolidated Cochrane/PRISMA/GRADE reference; already covered by the templates that would be adapted. |
| `deep-research/templates/literature_matrix_template.md` | *"- **Gap** (0 sources): Knowledge gap identified"* — the exact inference §32.5 forbids. The matrix shape is already covered by `SynthesisMatrix`/`MatrixCell`. |
| `deep-research/templates/prisma_protocol_template.md` | Protocol form; the counters that matter are adapted from `slr-writer/references/prisma_protocol.md`. |
| `deep-research/templates/prisma_report_template.md` | Report form; the terminal artefact of the excluded verdict chain. |
| `deep-research/templates/preregistration_template.md` | Preregistration form; outside scope. |
| `deep-research/templates/research_brief_template.md` | Quick-mode brief; its categorical `Evidence strength` is aligned, the rest is presentation. |
| `deep-research/examples/exploratory_research.md` | Transcript; demonstrates the model-issued Accept chain. |
| `deep-research/examples/fact_check_mode.md` | Transcript; its `Verified / Partially True / False / Unverifiable` set is a good worked illustration of a categorical verdict with a real "cannot verify" outcome. |
| `deep-research/examples/handoff_to_paper.md` | Transcript; hands off to an `academic-paper` skill that is not in this repository. |
| `deep-research/examples/policy_analysis.md` | Transcript; weighted score → "Accept with Minor Revision". |
| `deep-research/examples/review_mode.md` | Transcript; good illustration of a fabricated figure being caught against a real source. |
| `deep-research/examples/socratic_guided_research.md` | Transcript; ends in a candidate plan, correctly framed. |
| `deep-research/examples/systematic_review.md` | Transcript; repeats the gap-from-thin-cells pattern. |
| `slr-writer/agents/outline_architect_agent.md` | Outline shape is presentation; carries the `CLAUDE.md` vocabulary dependency without contributing a contract. |

## 5. Excluded (14)

| Asset (under `skills/`) | Reason | The instruction behind it |
|---|---|---|
| `humanizer/agents/openai.yaml` | Host-specific state (§32.2, ADR-009) | Agent-host interface metadata with `$humanizer` invocation syntax |
| `my-literature-review/agents/openai.yaml` | Host-specific state | Agent-host interface metadata with `$my-literature-review` invocation syntax |
| `grill-with-docs/ADR-FORMAT.md` | Redundant and conflicting | This repository already has an ADR convention (`docs/decisions/`, ten records, a richer template); a second format for the same artefact is worse than none |
| `academic-paper-reviewer/SKILL.md` | Host-coupled orchestration + terminal model authority | *"see `.claude/CLAUDE.md` \"Routing Discipline (v3.9.2)\""*; the pipeline ends in a model-issued Editorial Decision |
| `academic-paper-reviewer/agents/eic_agent.md` | Decision authority + unsourced folklore | *"Acceptance rate: Set review rigor based on journal tier (Q1 journal acceptance rate ~10-15%, Q3 journal ~30-40%)"* |
| `academic-paper-reviewer/agents/editorial_synthesizer_agent.md` | Confidence as the arbitration signal | *"A finding supported by one Score-5 reviewer and opposed by two Score-2 reviewers -> the Score-5 finding takes precedence."* |
| `academic-paper-reviewer/references/editorial_decision_standards.md` | Numeric threshold issues acceptance; confidence weights it | *"Average score across all universal dimensions >= 4.0"* (Accept); *"1 (Very Low) \| Ignore this reviewer's recommendation"* |
| `academic-paper-reviewer/references/top_journals_by_field.md` | Static, unprovenanced reputation data (locked decision) | *"\| *Nature Machine Intelligence* \| Springer Nature \| 20-25 \| High-impact AI research, interdisciplinary \|"*, with *"Impact Factor is for reference only"* and no as-of date |
| `academic-paper-reviewer/references/integration_guide.md` | Wires a cross-skill pipeline of skills not present here | Nine-step chain through `academic-paper`, `integrity check`, and format conversion |
| `academic-paper-reviewer/references/changelog.md` | Upstream version history; no reuse surface | — |
| `academic-paper-reviewer/templates/editorial_decision_template.md` | Drafts an acceptance letter as final | *"We are pleased to accept your manuscript for publication in [Journal Name]."* |
| `deep-research/agents/editor_in_chief_agent.md` | Weighted score maps straight to delivery | *"\| 4.0-5.0 \| **Accept** \| Ready for delivery with at most cosmetic changes \|"* |
| `deep-research/references/irb_decision_tree.md` | Outside product scope | Taiwan-specific human-subjects regulatory process (NSTC/MOE) |
| `deep-research/references/changelog.md` | Upstream version history; no reuse surface | — |

## 6. Retained skill surfaces

`skills/` remains a read-only design-input directory. Nothing in it is imported, executed,
or depended on by `src/research_harness/`.

```text
skills/
├── INVENTORY.md                  ← this register
├── humanizer/                    ← adapted into academic-writing (Task 15.2)
├── my-literature-review/         ← adapted into structured-traffic (Task 15.1)
├── slr-writer/                   ← adapted into both Phase 15 plugins
├── academic-paper-reviewer/      ← nine assets held for a future academic-review plugin
├── deep-research/                ← seven assets adapted; the rest is reading
└── grill-with-docs/              ← inspiration for the taxonomy Decision UX
```

## 7. Gate P14

Boundary tests pass (`tests/contract/plugins/`, 72 tests) and every asset above carries an
explicit reuse / adapt / inspiration / exclude ruling, so large skill migration may begin.
Two conditions on that:

- **A future `academic-review` plugin is not scheduled.** The nine `academic-paper-reviewer`
  assets classified `adapt-to-plugin` target §32.4's `academic-review`, which no phase
  currently builds. The classification records what they are worth, not a commitment.
- **No plugin-callable capability exists yet.** `PLUGIN_ALLOWED_CAPABILITIES` names nine
  capabilities from §22; none is registered in `CAPABILITY_HANDLERS`, because every handler
  registered today is an accepted-state mutation. Plugins can be declared and bounded now;
  their workflow fragments cannot run until those nine handlers land.
