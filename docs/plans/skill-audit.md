# Skill audit — rationale (ROADMAP Task 14.2, Gate P14)

**Status:** complete. **Date:** 2026-09-03. **Scope:** every file under `skills/` (97 assets
plus `INVENTORY.md` itself). **Register:** `skills/INVENTORY.md` holds the tables; this
document holds the reasoning, the quoted conflicts, and the decisions a reader would
otherwise have to reconstruct.

This audit ran only after the plugin SPI passed its boundary tests
(`tests/contract/plugins/`, 72 tests), as Task 14.2 requires. Nothing here has been copied
into `src/research_harness/`. No skill is a runtime dependency of the core.

## 1. What the audit is measuring against

Each asset was read and judged against the invariants the core already enforces, not
against a general sense of quality. Nine rules did the work:

1. **Nothing a model produces is accepted state.** Candidate → verification → review queue
   → researcher acceptance (PRODUCT.md §8.3, ADR-003). A skill that issues "Accept" is
   issuing something the architecture does not let it hold.
2. **A failed search is not a zero result.** `SearchProviderError` becomes a
   `SourceFailure`; an empty `SearchPage` means the source answered and matched nothing
   (§18, §42 F).
3. **Novelty is not inferred from an empty cell.** An absence claim needs recorded coverage
   and an overturn-risk judgement (§11, §32.5, `claims/coverage.py`).
4. **Work / Version / Artifact stay distinct** (ADR-002). A preprint and its published
   version are two Versions of one Work, not a duplicate to be discarded.
5. **No host- or vendor-specific behaviour** reaches the core (§4, ADR-009). `CLAUDE.md`,
   `.claude/`, the `Read` tool, `WebSearch`, `$skill` invocation syntax, and slash commands
   are host artefacts.
6. **Confidence is never an acceptance signal.** Verification returns a categorical verdict
   (§24.4, §43, `VerificationOutput` deliberately has no confidence field).
7. **Core meanings are not redefined.** Evidence types, epistemic origin, the claim scope
   ladder, and claim status are core; project taxonomies are extension points (ADR-010).
8. **Taxonomy is a researcher-approved `Decision`**, not a plugin- or model-declared fact
   (§33, §38).
9. **Egress is declared.** Anything that leaves the workstation is named before it leaves
   (§34).

Rules 1, 2, 3, 4 and 6 are also the acceptance tests of §42 E–H, which is why a conflict
with one of them is enough to keep an asset out of a plugin regardless of how useful the
rest of the file is.

## 2. What the classifications mean here

- **`reuse-as-contract`** — the semantics can be lifted almost verbatim. Reserved for
  assets whose rules are already the harness's rules; the only edits are removing a host
  reference or a stray sentence.
- **`adapt-to-plugin`** — real domain or workflow value, but it must be rebound: its writes
  become capability calls, its identifiers become harness IDs, its outputs become
  candidates, and its host couplings are dropped.
- **`inspiration-only`** — a good idea whose architecture fights an invariant. Read it,
  do not wire it.
- **`exclude`** — redundant, unsafe, host-coupled, or outside the product scope.

Counts: **5 reuse-as-contract, 30 adapt-to-plugin, 48 inspiration-only, 14 exclude** over 97
assets.

## 3. The state of the two skills the locked decisions already covered

The locked decisions from the previous inventory are preserved verbatim in
`skills/INVENTORY.md` §2. Two honest corrections to what they imply about the working tree:

**`my-literature-review` v2.1.0 is not in this repository.** What is on disk is
`version: "3.0.0-rh1"`, `adapted_for: "research-harness"`,
`status: "contract-only-until-capabilities-exist"` — the adaptation the locked decision
called for, already written. Its own closing section says so: *"The former seven-agent
orchestration, host-specific browser flow, direct file writes, static venue-rank table, and
hard dependency on `academic-paper-reviewer` are intentionally not part of this contract."*
The monolith therefore stays classified `inspiration-only` as a historical decision, while
the four files that survive it are classified on what they now contain. They read as a
plugin contract already: *"Route all scientific mutations through Research Core
capabilities. Do not write canonical files, projections, or accepted manuscript text
directly."*

One real defect survives the adaptation. `references/reading_framework.md` lists epistemic
origins as *"`author_stated`: an author claim or interpretation"*. The core keeps
`author_claimed` and `author_interpreted` apart precisely so that an author's assertion
cannot become an author's interpretation of a result and then a measured one (§9.1,
§42 E). The adapted field list must map onto `EvidenceOrigin`, not onto its own four-value
approximation. That is the single blocking edit for this file.

**`humanizer` is likewise pre-adapted** (`2.12.0-rh1`) and already carries a "Research
Harness manuscript mode" section that names the protected spans, requires a semantic-change
report, and states *"Return a revised **manuscript candidate**, never accepted scientific
state."* Its §14 even anticipates the boundary: *"do not change a protected span merely to
remove it."* One clause must not travel into the plugin: *"**File mode.** When the user
names a file, run the full rewrite process but write only the final text to the file."*
Under §32.2 a plugin does not write files; the `academic-writing` policy returns a candidate
plus a diff, and `manuscript.*` capabilities do any writing after review.

Both skills' `agents/openai.yaml` files are `exclude`. They are agent-host interface
descriptors (`display_name`, `default_prompt`, `$humanizer` invocation syntax) — host-specific
state by definition (§32.2, ADR-009), and worth nothing to a local-first workstation.

## 4. `academic-paper-reviewer` — a decision engine, not a reviewer

This skill is well built and points the wrong way. Its terminal artefact is an acceptance,
issued by a model, computed from a weighted average, weighted again by the model's own
self-reported confidence. Three quotes carry the whole judgement:

- `references/editorial_decision_standards.md`: *"Average score across all universal
  dimensions >= 4.0"* is a criterion for **Accept**, with no human step anywhere in the
  document.
- The same file's confidence table ends *"| 1 (Very Low) | Ignore this reviewer's
  recommendation (but retain specific comments) |"*, and
  `agents/editorial_synthesizer_agent.md` states the rule outright: *"A finding supported by
  one Score-5 reviewer and opposed by two Score-2 reviewers -> the Score-5 finding takes
  precedence. Quality of expertise > quantity of opinions."* That is confidence deciding
  which evidence wins — the exact thing §24.4 and ADR-003 forbid.
- `templates/editorial_decision_template.md` drafts the letter: *"We are pleased to accept
  your manuscript for publication in [Journal Name]."*

Those three, plus `SKILL.md` (which routes through *"`.claude/CLAUDE.md` \"Routing Discipline
(v3.9.2)\""* — a host artefact) and `agents/eic_agent.md` (whose rigor is set from
*"Q1 journal acceptance rate ~10-15%, Q3 journal ~30-40%"*), are `exclude`.

`references/top_journals_by_field.md` is `exclude` and was already locked as such. It is a
frozen table of impact-factor ranges — *"| *Nature Machine Intelligence* | Springer Nature |
20-25 | High-impact AI research, interdisciplinary |"* — with no source, no as-of date, and
no verification path, and it admits as much (*"Impact Factor is for reference only"*) while
still being consumed to set review rigor. If venue rank is ever needed it is timestamped
external metadata with a provenance record, which is what
`my-literature-review/references/discovery-and-snowball.md` already says.

What survives is the machinery underneath the verdict, and it is genuinely good:

- **`references/sprint_contract_protocol.md`** (`adapt-to-plugin`) — *"The load-bearing
  mechanism is the **physical separation of calls**: Phase 1 never sees paper content."*
  A reviewer commits to what would count as a failure *before* reading the paper. That is a
  vendor-neutral anti-drift mechanism and maps cleanly onto a two-stage workflow fragment
  whose first stage's fingerprint contains no document content. Its terminal
  `editorial_decision` field does not travel; the output is an audit result.
- **`references/re_review_mode_protocol.md`** (`adapt-to-plugin`) — the traceability matrix
  requires independent verification of an author's claim and has an honest fallback:
  *"If Author's Claim is empty or vague (\"addressed as suggested\"), mark Verified? as
  `🔍 Cannot verify`"*. "Cannot verify" as a first-class outcome is exactly
  `VerificationVerdict.INSUFFICIENT_EVIDENCE`. Its weakness is identity: the manuscript is
  `[If available]` free text, so it must gain a Work/Version/Artifact triple before reuse.
- **`references/statistical_reporting_standards.md`** (`adapt-to-plugin`) — inert reference
  content with no authority; a natural source of interrogation fields and validators.
- The four reviewer personas (methodology, domain, perspective, devil's advocate) are
  `adapt-to-plugin` as bounded roles writing `audit_result`. Note the defect a future
  adapter will hit: `agents/devils_advocate_reviewer_agent.md` says its job *"is not to
  score the paper"* and then carries the copy-pasted sprint-contract block telling it to
  produce `## Dimension Scores` and `## Editorial Decision`. Pick the first.
- **`templates/revision_response_template.md`** is the one `reuse-as-contract` asset here:
  a comment → response → change ledger with a page-level change log and no decision
  authority at all.

`references/quality_rubrics.md` is `inspiration-only` rather than adaptable for a reason
worth naming: its top originality band reads *"no prior work addresses this exact
question"*. That is novelty inferred from absence in rubric form, and it is the same
failure §32.5 names for matrix cells. `references/review_criteria_framework.md` joins it,
partly for its own score→decision table and partly because the two files define two
different, unreconciled rubrics (0–100 over five dimensions versus 1–5 over seven) that
`SKILL.md` presents as both authoritative.

## 5. `deep-research` — the best failure discipline in the collection, inside the wrong runtime

Fifty files, ten of the fourteen agents pinned to a `phase{N}_*/` directory contract and a
"Material Passport", with cross-session resume through `ARS_PASSPORT_RESET=1`. None of that
survives contact with durable `WorkflowRun`s and a capability layer, so the orchestration
is `inspiration-only` and the value is in three places.

**The API protocols are `reuse-as-contract`.** `references/crossref_api_protocol.md` and
`references/openalex_api_protocol.md` both say the thing the harness spent an ADR on:
*"Caller MUST omit `crossref_unmatched` from the entry (per spec v3.9.0 R-L3-2-C: absent !=
false)."* A service that could not be reached does not get to look like a service that
answered "no". `agents/bibliography_agent.md` states the general form — *"Absence ≠ negative
confirmation. Setting `semantic_scholar_unmatched: false` would imply \"checked and found\",
which is not what happened."* — and pairs it with *"**Iron Rule 2 — No silent skip.** Any
skipped corpus entry must be recorded ... Silently dropping an entry is a prompt-layer
violation."* These are invariant 2 written in someone else's vocabulary; they belong in the
`structured-traffic` discovery fragment and in provider adapters.

`references/semantic_scholar_api_protocol.md` has the same discipline but names a host tool
— *"This supplements (not replaces) WebSearch-based verification"* — so it is
`adapt-to-plugin`: the tiering is kept, `WebSearch` becomes `retrieval.search`.

**Two agents carry structure worth taking.** `agents/timeline_extraction_agent.md` is the
only asset in the whole collection that models version identity: `supersedes`,
`superseded_by`, `version_family_id`, and a categorical rather than numeric confidence. It
is `adapt-to-plugin` only because it writes files directly (*"Write the entry to
`phase2_investigation/timeline.yaml`."*). `agents/source_verification_agent.md` contributes
the verification-outcome enum and, importantly, a required "Verification Limitations"
section — a coverage report by another name.

**Two things are excluded outright.** `agents/editor_in_chief_agent.md` maps a weighted
score straight to delivery (*"| 4.0-5.0 | **Accept** | Ready for delivery with at most
cosmetic changes |"*). `references/irb_decision_tree.md` is Taiwan-specific human-subjects
compliance process, outside the product scope of a literature workstation.

**And one thing is the textbook violation.** `templates/literature_matrix_template.md`
interprets its own matrix as *"- **Gap** (0 sources): Knowledge gap identified"*, and
`agents/synthesis_agent.md` echoes it: *"**Silence**: What themes have < 2 sources? These
are potential gaps."* §32.5 forbids inferring novelty from missing matrix cells and
`claims/coverage.py` exists to make an absence claim earn its wording. The matrix shape is
useful and the harness already has `SynthesisMatrix`/`MatrixCell`; the interpretation rule
is not adaptable, so the template stays `inspiration-only`.

`agents/bibliography_agent.md` needs one repair before it can be adapted. Its
deduplication merges what the harness keeps apart: *"deduplication via S2 IDs prevents the
same paper from appearing with slightly different metadata (e.g., preprint vs published
version, conference vs journal version)"*. Under ADR-002 those are Versions of one Work.
Deduplicate at the Work level and keep every Version — which, notably, is exactly what
`my-literature-review` already tells you to do.

`references/argumentation_reasoning_framework.md` is `inspiration-only` for a subtler
reason than the rest: its epistemic-status ladder
(`Established/Supported/Preliminary/Speculative/Contested`) is *good*, and that is the
problem. Adopting a second status vocabulary beside `ClaimStatus`, `EvidenceStrength` and
the L0–L4 scope ladder would redefine core meanings by accretion (ADR-010). If any of it is
wanted, it is a change to the core enums with an ADR, not a plugin contribution.

## 6. `slr-writer` — the closest thing to a working contract

This skill is the strongest `adapt-to-plugin` cluster in the collection because its
discipline already matches the harness's:

- *"**Cite only the corpus.** Every `\cite` must resolve to a paper in the collected corpus
  (`papers.json`). No invented references, ever."*
- `references/anti_hallucination_rules.md` (`reuse-as-contract`): *"If you feel a citation
  is needed but no corpus paper fits → write `[NEEDS SOURCE]` inline and surface it to the
  user; never invent an author/title/year."* That is ROADMAP Task 15.2's "unsupported
  content becomes an audit warning, not a fabricated citation", already written.
- `references/evidence_card_spec.md`: *"Every verified fact carries a `[Table/§/p]`
  location. A fact without a location is not verified — move it to Claims or drop it."* and
  *"**`not reported`** is a valid, important value — record it so the writer knows not to
  invent one."* Anchor-or-it-isn't-evidence, and a negative state that is not an absence
  claim.
- `agents/assembler_checker_agent.md` lists every unbacked sentence as **UNVERIFIED** and
  requires *"Fix or surface every UNVERIFIED item before declaring the draft done."*
- `SKILL.md` is genuinely resumable: *"Every gate result and artifact is persisted; the
  pipeline can stop and resume across sessions via `state.json`."*

Four things must change on the way in:

1. **Every write goes through a capability.** *"derive `<review-slug>`; create
   `slr-output/<slug>/`; init `state.json`"* becomes a `WorkflowRun` with stage
   checkpoints; `05_evidence_cards/<key>.md` becomes staged Evidence.
2. **`citation_key` is not an identity.** Every asset addresses a paper by one string that
   serves as bibliographic identity, PDF identity, and evidence-card identity at once. It
   must become `WorkId` / `VersionId` / `ArtifactId` (ADR-002).
3. **Drop the `CLAUDE.md` dependency.** Six files treat a Claude Code project-memory file as
   the authority for the survey's vocabulary and its no-competitor-bashing policy — e.g.
   *"Keywords (`IEEEkeywords`): pull from the CLAUDE.md stable vocabulary."* Under §32.2
   that is host-specific state. The vocabulary belongs in the plugin's
   `SchemaContribution`; the tone rule belongs in the `academic-writing` policy.
   `agents/deep_reader_agent.md` also names a host tool: *"Read the full PDF (use the Read
   tool's PDF paging)."* — that is `work.parse` plus `parsing/`.
4. **Two gates must not be optional.** Phase 3 (deep read) is the only phase in the
   workflow with no gate, yet it is where facts get labelled `verified` and assigned a
   `quality` band; and `agents/section_writer_agent.md` ships an escape hatch: *"If
   `SLRW_SECTION_GATE=0`, draft all sections then present one combined audit."* Under strict
   review policy neither is portable — an environment variable cannot lower a review gate
   (ADR-007).

`agents/scope_taxonomy_agent.md` is adaptable specifically as a *proposer*: its chosen
taxonomy axis becomes a `Decision` candidate, because taxonomy is a researcher-approved
Decision and never a plugin-declared fact (§33). `agents/outline_architect_agent.md` is
`inspiration-only`: outline shape is presentation, and it carries the `CLAUDE.md`
dependency without carrying anything the core needs.

## 7. `grill-with-docs` — right instinct, wrong write model

`SKILL.md` and `CONTEXT-FORMAT.md` are `inspiration-only`. The glossary discipline —
challenge a term against the existing definition, refuse to let one word mean two things —
is exactly the pressure a taxonomy `Decision` should apply, and the harness has no UX for it
yet. What cannot travel is when it writes: *"When a term is resolved, update `CONTEXT.md`
right there. Don't batch these up — capture them as they happen."* The model decides a term
is resolved and the write happens in the same breath, with no distinct acceptance. A
taxonomy revision is a `Decision` a researcher accepts (§38), and it invalidates dependent
classifications (ADR-008); neither survives an inline edit.

`ADR-FORMAT.md` is `exclude` — redundant. This repository already has an ADR convention
(`docs/decisions/`, ten records, a different and richer template), and a second, conflicting
format for the same artefact is worse than none.

## 8. What Phase 15 inherits

`plugins/README.md` carries the mapping in the form a plugin author needs. In short:

- **`structured-traffic`** gets `my-literature-review`'s reading framework, discovery and
  snowball protocol, and coverage/gap ladder; `deep-research`'s omit-on-degradation
  protocols and version-identity fields; `slr-writer`'s evidence-card field set and PRISMA
  counters; `academic-paper-reviewer`'s statistical reporting standards as validators.
- **`academic-writing`** gets `humanizer`, `slr-writer`'s anti-hallucination rules,
  `UNVERIFIED` reporting, and IEEE survey structure.
- **A future `academic-review` plugin** (§32.4, unscheduled) is the target for the four
  reviewer personas, the sprint contract, the re-review traceability matrix, and the
  calibration protocol. Nothing depends on it; the locked decision that the imported
  `academic-paper-reviewer` *"cannot be a required runtime dependency"* stands.

## 9. Open items for the PM

- The reviewer personas and the sprint contract are classified `adapt-to-plugin` against a
  plugin (`academic-review`) that no phase currently schedules. If it stays unscheduled
  through v1.0, those nine assets are effectively `inspiration-only` in practice; the
  classification records what they are worth, not a commitment to build it.
- `PLUGIN_ALLOWED_CAPABILITIES` names nine capabilities from PRODUCT.md §22, of which
  **zero** are implemented in `CAPABILITY_HANDLERS` today — every registered handler is an
  accepted-state mutation. A plugin can be loaded and bounded now, but it cannot yet call
  anything. `evidence.extract`, `evidence.verify`, `retrieval.search`,
  `retrieval.resolve_source`, `work.get`, `corpus.search`, `claim.find_support`,
  `claim.find_counterevidence`, and `review.inbox` need handlers before Phase 15's workflow
  fragments can run. This is asserted by
  `test_no_plugin_capability_is_an_accepted_state_mutation`, which will start failing the
  day one of those names is registered as a mutation — deliberately.
- No plugin-callable capability has a request DTO yet, so `CapabilityGateway.call` takes a
  `BaseModel` the host constructs. When the read/staging DTOs land, decide whether
  `research_harness.capabilities.dto` stays importable from plugin code (it currently is;
  `handlers` and `context` are not).
