# Acceptance matrix — Product §42, the crash suite, and the v1.1 gates

What demonstrates each acceptance behaviour, where it lives, and whether it holds today.
Written for ROADMAP Tasks 17.1 and 17.2 and for Gate P17 ("all end-to-end invariants
pass"), and extended for the conversation-first track's Gates DS and P18–P21
([§ The v1.1 gates](#the-v11-gates-ds-and-p18p21)) and for the v1.1 follow-on's fifteen
criteria ([§ Subscription-backed local CLI
providers](#subscription-backed-local-cli-providers-spec-24)). Counts are the tests each
module collects, including parametrized cases.

Run the whole thing with:

```bash
uv run pytest tests/e2e/invariants tests/e2e/crash -q
```

Both suites are deterministic, hermetic, and offline: providers are scripted or driven
through `httpx.MockTransport`, and every workspace is built under `tmp_path`.

## The shared loop

Both suites are built on `tests/e2e/invariants/workstation.py`, which runs the ROADMAP §5
end-to-end loop through the supported surfaces only — `capabilities/` handlers and the
services that drive them:

```text
init → ingest → parse → extract candidate → verify → review accept
     → create claim → audit claim → attach manuscript sentence → audit citation
```

It leaves two Works (one ingested from `tests/fixtures/synthetic_research_paper.pdf`, one
registered so a citation key can resolve to a corpus Work that supports nothing), two
accepted Evidence objects, two audited Claims, and a three-sentence LaTeX manuscript with
three anchors.

## Product §42 invariants — `tests/e2e/invariants/`

| § | Behaviour | Module | Tests | Status | ADR |
|---|---|---|---|---|---|
| A | Provider independence | `test_a_provider_independence.py` | 7 | pass | ADR-005 |
| B | Host independence | `test_b_host_independence.py` | 7 | pass | ADR-004, ADR-009 |
| C | Rebuildability | `test_c_rebuildability.py` | 6 | pass | ADR-001, ADR-006 |
| D | Provenance | `test_d_provenance.py` | 7 | pass | ADR-002, ADR-008 |
| E | Epistemic separation | `test_e_epistemic_separation.py` | 9 | pass | ADR-003 |
| F | Negative-evidence discipline | `test_f_negative_evidence.py` | 15 | pass | ADR-003, ADR-007 |
| G | Claim-strength discipline | `test_g_claim_strength.py` | 14 | pass | ADR-007 |
| H | Human review | `test_h_human_review.py` | 21 | pass | ADR-003, ADR-007, ADR-009 |
| I | Stale propagation | `test_i_stale_propagation.py` | 7 | pass | ADR-008 |
| J | Citation integrity | `test_j_citation_integrity.py` | 10 | pass | ADR-003 |
| K | Atomic accepted-state mutation | `test_k_atomic_mutation.py` | 21 | pass | ADR-001 |
| L | Style-pass semantic preservation | `test_l_style_preservation.py` | 10 | pass | ADR-007, ADR-008 |
| M–P | Conversation, attachments, ResearchGraph, LaTeX (v1.1) | `test_v11_invariants.py` | 23 | pass | ADR-025 to ADR-028 |

### What each letter actually demonstrates

**A — provider independence.** The same verification workflow runs once against the real
OpenAI adapter and once against the real Anthropic adapter, both over
`httpx.MockTransport`. One neutral `ModelRequest` fingerprints identically on both, both
return the same validated `VerificationOutput`, and the canonical `evidence.jsonl` the loop
then accepts is identical once provenance, clocks, and the backend label are stripped
(`workstation.digest`). The only recorded difference is `verification.verifier`.

**B — host independence.** A Claim written by `research claim create` is read back through
the CLI, the HTTP daemon (`starlette.testclient.TestClient`), and the in-process MCP bridge;
all three report the same id, statement, status, and allowed strength, and `claims/`
holds exactly one file. Every `mutate`/`admin` capability is refused over MCP with
`permission_denied`, and two hosts get byte-identical refusal messages.

**C — rebuildability.** The whole loop runs, `.research/` is deleted, and the rebuild
reproduces the same canonical digest, the same object counts, the same `verify_rebuild`
(empty), and the same stale marks. Rebuilding writes no canonical file.

**D — provenance.** Every accepted Evidence anchor is replayed with `resolve_anchor`
against a parse of the *stored artifact bytes*; page, bbox, and exact text match, and the
`94.32` cell resolves on page 4 of the real PDF. A revised copy of the artifact makes the
anchor `stale` and `resolve_anchor` refuses rather than re-anchoring.

**E — epistemic separation.** An `author_claimed` reading of a measured value is counted as
a qualifier and never as support, so a numeric Claim resting only on it audits
`unsupported` at L0. `reclassify_origin` refuses `model_proposed → source_observed` under
every actor and policy, requires a human plus a rationale for any other change, and the
extractor role schema cannot emit `model_proposed` at all.

**F — negative-evidence discipline.** `negative_state_from_search` and `classify_absence`
never return `absent`; `not_found` must first become `not_reported`; promotion needs a
human actor, an *accepted* Decision, a coverage cutoff, and a recorded search run, each
checked in isolation. `research coverage` refuses the sentence "no work exists" and names
the strongest honest form instead.

**G — claim-strength discipline.** An L3 ask over one examined work out of twelve is capped
with `escalation_prevented`, the audit names the requirement that failed, and the recorded
wording is neither the field-level nor the universal phrase. An L4 ask lands at the same
floor. Escalation costs an accepted, human-authored `epistemic_override` Decision; a
proposed one, a model-authored one, and one exceeding the requested scope are all refused.

**H — human review.** Accepting an interpretive (Tier-2) candidate as a model is refused at
the handler, through the registry (as a model principal *and* as a human principal running
under a model actor), over HTTP, and over MCP — and none of the four refusals leaves
Evidence behind. A policy batch under strict review is refused, as is one whose declared
conditions are unmet. `confidence` appears as a field in no acceptance DTO, no inbox item,
no session summary, and no review capability schema.

**I — stale propagation.** Revising an accepted taxonomy marks the matrix, the Claim read
off it, and the manuscript anchor above it, ordered manuscript → claim → synthesis. A
rebuild from canonical files alone reaches the same set. Nothing downstream is rewritten:
the matrix file is byte-identical and every claim and anchor digest is unchanged.

**J — citation integrity.** Three keys, three outcomes: a key whose Work carries the
Claim's Evidence raises nothing; a key that resolves to a corpus Work supporting nothing
the Claim records is a `citation_mismatch` error saying "citation existence is not evidence
support"; a key the bibliography never defines is a second error. The audit writes nothing
and never invents a key.

**K — atomic accepted-state mutation.** `work.register` (Work + Version + Artifact +
artifact bytes + id counter + event = six files, one unit) is interrupted at every journal
phase; the outcome is always all six or none, with the event agreeing, `verify_consistency`
clean, no duplicate or skipped id, and a clean rebuild. Accepting Evidence and creating a
Claim are shown to be two units. An event whose digest disagrees with its canonical file
makes `WorkspaceRepository.open` fail closed; `repair=True` reports it and rewrites
nothing.

**M to P — the v1.1 boundaries.** One module, four sections, one fixture each, because
these sentences are boundaries rather than workflows and share no workspace. **M**: a
reopened session keeps every message; the pack carries current and policy-allowed prior
context; a private prior session never reaches an external provider; accepted state
outranks conflicting chat *and the transcript keeps both*; the receipt records every
included and omitted item with a reason, and reads back unchanged after the projection is
deleted. **N**: attaching creates no corpus object; `Save to corpus` resolves identity
before it writes; promotion accepts no Evidence and no Claim; a promotion that fails
half-way leaves the session copy intact; an unsendable attachment is never silently
dropped. **O**: rebuilding after `rm -rf .research/` resolves the same references and
scientific relations, a proposal stays a proposal, a project-visible traversal cannot reach
a private session, and exact and two-hop lookups stay inside the measured budgets. **P**:
the manuscript compiles through the real toolchain path, a failure reports file and line
and keeps the last good PDF, compiler errors and scientific findings stay two lists, and a
model suggestion reaches source only through a reviewed diff — including that chat
mathematics is stored byte for byte and never compiled or normalised. §42 Q is a JavaScript
gate and is covered under [Gate DS](#gate-ds--the-design-system).

**L — style-pass semantic preservation.** Over the workstation's own manuscript and the
real `academic-writing` humanizer policy: widening a scope, dropping a hedge, rounding
`94.32`, and dropping a citation are each held. Neither human approval nor a clean audit
alone unlocks a changed meaning, and the manuscript's own audit (which has errors, from
§42.J) is what would have to supply `audit_ok`. A meaning-preserving copy-edit passes on
its own. After every path, the workspace is byte-identical.

## Crash and recovery — `tests/e2e/crash/`

| Interruption | Module | Tests | Status |
|---|---|---|---|
| Canonical mutation (journal phases, real `os._exit`) | `test_canonical_mutation.py` | 13 | pass |
| Rebuild (temp DB and the swap) | `test_rebuild_interrupted.py` | 12 | pass |
| Long provider workflow (extraction and verification) | `test_provider_workflow.py` | 12 | pass |
| Review acceptance (both orderings) | `test_review_acceptance.py` | 9 | pass |
| Manuscript attachment (anchor vs event) | `test_manuscript_attachment.py` | 9 | pass |

Crash points come from `tests/e2e/crash/interrupts.py`:

| Point | What is on disk when it fires | Recovery |
|---|---|---|
| `Transaction._prepare` | nothing staged | prior state |
| `Transaction._write_record` | staged, record not landed | roll back |
| `Transaction._apply` | record landed, nothing applied | roll forward |
| `Transaction._apply_intent` (call 2) | part of the unit applied | roll forward |
| `Transaction._commit_record` | everything applied, rename pending | roll forward |

After every interruption the same four checks run (`interrupts.reopen`):
`WorkspaceRepository.open` succeeds, `verify_consistency` is clean, no id is duplicated,
and `rebuild_workspace` + `verify_rebuild` come back empty. The journal directory is empty
afterwards in every case.

### Notes per interruption

**Canonical mutation.** Besides the in-process crash points, a child process runs a real
`claim.create` and calls `os._exit(70)` inside `_apply`, `_write_record`, and
`_commit_record` — no `finally`, no in-process recovery — so only the on-open recovery can
finish or undo the unit. A torn journal record (half-written JSON) rolls back; a committed
but uncleaned transaction is only tidied.

**Rebuild.** Interrupting `_persist_stale`, `build_fts`, or `_replace_database` leaves the
previous `research.db` byte-identical and still answering FTS queries, with no
`research.db.rebuild-<pid>` left behind. On a workspace with no projection yet, the same
crash leaves no `research.db` at all — better none than one that silently omits half the
corpus. A retry always succeeds and canonical state is never written.

**Long provider workflow.** A scripted provider raising on call *N* fails the run with an
explicit terminal state naming the stage. Canonical state does not move. Resuming with the
same run id recomputes the failed stage and only that stage (the succeeded one comes back
`skipped_cached`), and staging ends with one candidate per field: candidate ids are content
addressed, so rerunning the whole interrogation afterwards adds no second copy.
Verification behaves the same way — a candidate that already carries a verdict is not
selected again, so a resume costs exactly the calls the crash cost.

**Review acceptance.** `EvidenceReviewService.accept` commits the canonical mutation first
and marks staging second, and the suite asserts that order explicitly. A crash between them
leaves the accepted Evidence standing with a staging record that still looks unreviewed —
`.research/` is allowed to be behind canonical state. The reverse order is driven by hand
to show what it would cost: staging claims an acceptance that does not exist and the review
service then refuses to retry the candidate. Re-accepting after such a crash now answers
with the Evidence that already exists rather than allocating a second `EvidenceId` for the
same anchor, and a repeat carrying a *different* qualification is refused by name — the
guard moved onto canonical evidence, which is what closed the open item below.

**Manuscript attachment.** The anchor and its event are two intents of one transaction, so
crashing on either lands on either side of the pair; the assertion is that the anchor is
present exactly when its event is. Retrying leaves one anchor (anchors are keyed by
`(file, sentence fingerprint)`), the Claim is untouched, and the researcher's `main.tex` is
never written.

## The v1.1 gates (DS and P18–P21)

The ROADMAP states each of these gates as a short list of sentences, and each gate has one
`tests/e2e/*_gate.py` module written as those sentences in order. The tables below map every
clause to the test that demonstrates it. Run them with:

```bash
uv run pytest -q tests/e2e/test_conversation_gate.py tests/e2e/test_attachments_gate.py \
                 tests/e2e/test_graph_gate.py tests/e2e/test_manuscript_workspace_gate.py
RESEARCH_HARNESS_PERF=1 uv run pytest -q tests/perf/test_graph_budgets.py
pnpm --filter @research-harness/design lint && pnpm --filter @research-harness/design test
pnpm --filter research-harness-web test
```

Last run on 2026-09-03: the four gate modules **50 passed**;
`tests/e2e/invariants/test_v11_invariants.py` **23 passed**; `tests/perf/test_graph_budgets.py`
**14 passed**; the Design System **920 passed in 69 files**, `lint` clean (76 gated contrast
pairs pass, raw-palette lint clean over `design/src` *and* `web/src`); the Web client
**280 passed in 19 files** at the final gate, once the conversation, attachments, references
and manuscript routes had landed (see *Web halves* below).

### Gate P18 — conversation workspace · `tests/e2e/test_conversation_gate.py` (10 tests)

| clause | test | status |
|---|---|---|
| reopen and continue a session | `test_a_session_reopens_with_its_transcript_and_continues` | pass |
| inspect exactly what context a response used | `test_the_receipt_names_every_class_that_reached_the_model_and_every_one_that_did_not`; the CLI and the capability agree in `test_the_cli_and_the_capability_show_the_same_receipt` | pass |
| cross-session retrieval with privacy filtering | `test_a_prior_session_excerpt_is_retrieved_locally_and_withheld_from_an_external_model`, `test_a_private_session_refuses_an_external_provider_instead_of_sending_nothing`, `test_a_project_visible_session_is_shareable_and_a_private_one_is_not` | pass |
| conflicting accepted state outranks chat | `test_accepted_state_outranks_a_conflicting_memory_and_the_conflict_is_visible` | pass |
| promote an excerpt without bypassing review | `test_an_excerpt_is_promoted_through_the_cli_without_bypassing_review`, `test_promoting_prose_to_evidence_is_refused_and_names_the_anchor` | pass |
| (the whole gate, with no projection) | `test_the_gate_holds_when_the_projection_is_deleted` | pass |

Supporting: `tests/unit/conversation/` (68), `tests/integration/conversation/` (40),
`tests/integration/workspace/test_conversations.py` (30),
`tests/contract/capabilities/test_conversation.py` (35),
`tests/contract/protocol/test_session_events.py` (9),
`tests/unit/domain/test_conversation.py` (40). ADR-025.

### Gate P19 — research attachments · `tests/e2e/test_attachments_gate.py` (7 tests)

| clause | test | status |
|---|---|---|
| attach and preview an image and a PDF without corpus mutation | `test_attaching_an_image_and_a_pdf_changes_no_canonical_state` (asserts the canonical *and* corpus digests are unchanged) | pass |
| send with a compatible model and inspect `Context used` | `test_a_compatible_model_receives_both_attachments_and_the_receipt_says_so` | pass |
| block an incompatible send without losing the draft | `test_an_incompatible_model_blocks_the_send_and_leaves_every_attachment_intact`, `test_a_blocked_item_names_a_model_that_would_take_it_when_one_is_configured` | pass |
| promote a PDF through identity resolution | `test_a_pdf_is_promoted_through_identity_resolution_and_the_same_bytes_deduplicate` | pass |
| recover cleanly from a failed promotion | `test_a_failed_promotion_keeps_the_session_copy_and_retries_cleanly` | pass |
| an unsupported file is never silently dropped | `test_an_unsupported_file_stays_visible_with_a_reason_and_never_blocks_the_others` | pass |

Supporting: `tests/unit/conversation/test_attachments_sendability.py`,
`tests/integration/conversation/test_attachments_intake.py` and `test_save_to_corpus.py`
(40 integration tests in total), `tests/contract/capabilities/test_attachments.py` (15),
`tests/contract/providers/test_media_inputs.py` (7), `tests/unit/providers/test_media.py`
(21). ADR-026.

**Not demonstrated against a live provider.** The media encoders are asserted against the
real OpenAI and Anthropic adapters over `httpx.MockTransport`, not against the vendors'
endpoints; the environment's API keys are rejected upstream (dogfood §1). Nothing in the
gate depends on a live call.

### Gate P20 — ResearchGraph · `tests/e2e/test_graph_gate.py` (16 tests)

| clause | test | status |
|---|---|---|
| rebuild from durable sources and resolve the same stable references | `test_rebuilding_from_durable_sources_resolves_every_stable_reference`, `test_the_transcript_and_the_corpus_outlive_the_projection`, `test_the_status_capability_reports_the_rebuilt_index` | pass |
| traverse Claim ↔ Evidence ↔ Artifact anchor | `test_the_claim_reaches_its_supporting_and_contradicting_evidence`, `test_the_evidence_reaches_the_claim_in_the_other_direction`, `test_the_evidence_reaches_the_exact_artifact_anchor`, `test_provenance_walks_the_whole_claim_to_anchor_path_in_one_call` | pass |
| preserve candidate/accepted labels | `test_a_model_proposed_relation_stays_candidate_beside_the_accepted_one`, `test_a_staged_candidate_never_takes_an_evidence_identity`, `test_a_transcript_is_never_labelled_accepted` | pass |
| enforce session privacy during traversal | `test_a_project_visible_traversal_cannot_reach_the_private_session`, `test_a_project_visible_context_pack_carries_no_private_material`, `test_the_researcher_still_sees_the_private_session_locally` | pass |
| meet < 100 ms exact and < 250 ms one/two-hop | `test_the_gate_workspace_meets_every_warm_latency_budget`, `test_the_budgets_measured_are_the_ones_the_spec_states`; at benchmark scale `tests/perf/test_graph_budgets.py` (14 tests, `RESEARCH_HARNESS_PERF=1`) | pass |
| (the same answers from the CLI) | `test_the_cli_resolves_and_completes_the_same_references` | pass |

Measured at `--scale 1.0` on 33,180 nodes / 74,617 edges: exact reference 0.07 ms,
one-hop 0.88 ms, two-hop 11.9 ms, autocomplete 0.41 ms, provenance 3.1 ms — every mode
passing, reproduced independently in
[`dogfood-2026-09-03-v1.1.md`](dogfood-2026-09-03-v1.1.md) §5 and recorded in
[`performance-budgets.md`](performance-budgets.md).

Supporting: `tests/integration/graph/` (134: rebuild, incremental, queries, resolver,
privacy, context fragments, session rebuild), `tests/unit/graph/` (72),
`tests/unit/domain/test_graph.py` (57), `tests/contract/capabilities/test_graph.py` (36).
ADR-027.

### Gate P21 — LaTeX manuscript workspace · `tests/e2e/test_manuscript_workspace_gate.py` (17 tests)

| clause | test | status |
|---|---|---|
| compile a real project and inspect its PDF | `test_compiling_produces_a_pdf_the_daemon_serves_as_pdf_bytes`, `test_the_latest_alias_serves_the_same_bytes`, `test_a_workspace_that_never_compiled_answers_404_rather_than_an_empty_file` | pass |
| retain the last good PDF on a new failure, labelled stale | `test_a_syntax_error_reports_file_and_line_and_keeps_the_last_good_pdf` | pass |
| navigate source/PDF when the mapping exists, honestly when it does not | `test_synctex_navigates_forward_and_back_through_the_capability`, `test_an_engine_that_wrote_no_map_says_so_instead_of_guessing` | pass |
| distinguish compiler errors from scientific errors | `test_a_clean_compile_still_fails_the_scientific_audit`, `test_a_broken_compile_adds_a_compiler_error_and_no_scientific_finding`, `test_the_cli_prints_the_two_lists_under_two_headings` | pass |
| apply a model suggestion only through an explicit reviewed diff | `test_a_suggestion_stages_a_diff_and_leaves_the_file_byte_identical`, `test_applying_a_reviewed_candidate_writes_the_source_and_records_the_event`, `test_a_candidate_that_changes_meaning_is_refused_and_says_which_rule_refused_it`, `test_applying_against_a_stale_hash_is_refused_and_changes_nothing` | pass |
| (the host ceiling) | `test_an_agent_host_may_read_the_manuscript_but_not_write_it`, `test_the_daemon_refuses_a_manuscript_write_to_a_caller_without_the_token`, `test_the_terminal_reaches_every_capability_by_the_same_name` | pass |

The gate's engine is `tests/fixtures/latex/fake-latex` on a throwaway `PATH` — a real
subprocess with real argv writing real files, so everything except the typesetting is the
production path. **The real-engine half is demonstrated outside the suite**: the dogfood
session compiled `tests/fixtures/latex/project` with `tectonic 0.17.0` (0.38 s, a real
PDF, SyncTeX both directions, last-good retention on a real `Undefined control sequence`)
— [`dogfood-2026-09-03-v1.1.md`](dogfood-2026-09-03-v1.1.md) §6.
`tests/integration/manuscript/test_compile.py` carries an opt-in real-toolchain test that
is skipped when no engine is installed.

Supporting: `tests/integration/manuscript/` (107), `tests/unit/manuscript/` (318),
`tests/contract/capabilities/test_manuscript_workspace.py` (27),
`tests/e2e/test_manuscript_cli.py`. ADR-028.

### Gate DS — the Design System

| clause | evidence | status |
|---|---|---|
| the package builds and is consumed locally | `pnpm --filter @research-harness/design build` (ESM + CSS + `.d.ts` into `design/dist`); `web/package.json` depends on `workspace:*` and `web/src/main.tsx` imports the one stylesheet | pass |
| representative conversation, full research, and manuscript compositions | `design/src/workspace/{ConversationWorkspace,FullPageWorkspace,ManuscriptWorkspace}` with their `*.test.tsx`, `*.specimen.tsx`, and per-variant snapshots; the specimen gallery (`pnpm --filter @research-harness/design specimens`) | pass for the package |
| dark/light and compact/comfortable pass accessibility and visual checks | every interactive component asserts `axe-core` with no violations (`design/tests/axe.ts`) and snapshots four variants (`design/tests/variants.tsx`); `design/tests/tokens.test.ts` snapshots the resolved token maps; `scripts/check-contrast.mjs` gates 76 declared pairs at WCAG 2.2 AA | pass, **with a substitution**: there is no browser in this workspace, so DOM snapshots stand in for screenshot regression (DS spec §8; recorded as the gate's form, not as screenshot testing) |
| runtime makes no Design System CDN request | `scripts/check-tokens.mjs` fails on a remote `@import`/`url()` under `design/src`; fonts are system stacks, icons are bundled `lucide-react`, KaTeX ships from the package; `web/dist` contains no `https://` reference to a font, icon, or stylesheet | pass |
| application screens do not duplicate primitives or theme definitions | `scripts/check-tokens.mjs` runs over `web/src` too and **fails** on a raw palette value there; `web/src/styles.css` holds only application layout, every value an `--rh-*` token; the Warmline prototype tree is deleted | pass |

Supporting: 920 tests in 69 files. ADR-029; the consumption map, the token contract, and the
known gaps are in [`docs/architecture/design-system.md`](../architecture/design-system.md).

### Product §42 M–Q

| § | behaviour | where it is demonstrated | status |
|---|---|---|---|
| M | conversation authority and context receipt | `tests/e2e/invariants/test_v11_invariants.py` §M (6 tests) and Gate P18 above, all five clauses | pass |
| N | attachment promotion boundary | `test_v11_invariants.py` §N (5 tests, including `test_n_promotion_accepts_no_evidence_and_no_claim`) and Gate P19 above | pass |
| O | ResearchGraph rebuild and reference resolution | `test_v11_invariants.py` §O (5 tests) and Gate P20 above, including the measured budgets | pass |
| P | LaTeX rendering and source ownership | `test_v11_invariants.py` §P (6 tests, including `test_p_chat_mathematics_is_never_compiled_and_never_normalized`) and Gate P21 above; the browser half (Markdown + KaTeX, raw HTML never rendered) is `web/src/render/markdown.test.tsx` | pass |
| Q | shared Design System integrity | Gate DS above (a JavaScript gate: `pnpm --filter @research-harness/design lint` + `test`, and the raw-palette lint over `web/src`) | pass, with the visual-regression substitution noted |

### Web halves

The four v1.1 Web surfaces were still being written when this matrix was first compiled;
all four landed the same day and the final gate ran the whole Web suite green
(`pnpm --filter research-harness-web test`: 280 passed in 19 files; `typecheck`, `lint`,
`build` clean; the raw-palette lint over `web/src` clean).

| surface | files | final state on 2026-09-03 |
|---|---|---|
| conversation route (P18) | `web/src/views/conversation/{ConversationRoute,Transcript,ComposerPane,ReceiptPanel,PromoteDialog,InspectorPane,SessionListPane}.tsx`, the `use*` hooks, `mappers.ts`; `web/src/app/routes.tsx`, `Layout.tsx` | **landed** — `ConversationRoute.test.tsx` and `mappers.test.ts` cover conversation spec §10 items 1–7 from the Web side (reopen/continue, receipt with accepted evidence and a prior-session excerpt, discrepancy, promote to a claim candidate, evidence not offered, private omission reason, `@E####` → object → message), plus draft survival, streaming interruption and mid-stream reload |
| attachments (P19) | `web/src/views/conversation/attachments/*` | **landed** — `attachments.test.tsx` and `mappers.test.ts` cover attachments spec §9 items 1–7 (preview without corpus calls, both ids sent, blocked send keeps draft and files, save to an existing Work, same bytes → existing Artifact, failed promotion retryable, no evidence created) |
| references and inspector (P20) | `web/src/views/conversation/references/*`, `/source/:artifactId` | **landed** — `references.test.tsx` and `mappers.test.ts` cover autocomplete → token → exact resolved id, unresolved/stale/private marks, every `rh://` kind including a broken link, Claim ↔ Evidence ↔ anchor traversal with candidate relations labelled, a private message absent under project visibility, and the graph-unavailable fallback |
| manuscript workspace route (P21) | `web/src/views/manuscript/*`, replacing the v1.0 `web/src/views/Manuscript.tsx` | **landed** — `ManuscriptWorkspace.test.tsx` and `mappers.test.ts` cover LaTeX spec §10 items 1, 2, 4, 5, 6 from the Web side (open/edit/save/conflict, compile success and failure with the last good PDF, SyncTeX both ways and honest unavailability, suggest → apply refused when blocked, unsaved content surviving a failed compile) |

`tests/contract/protocol/test_web_routes.py` pins every hand-declared field of these
surfaces' DTOs to the schema the daemon publishes (26 passed). None of this affects the
Python gates: every clause above is demonstrated through the capability layer and the CLI,
which is what the Web routes call.

## Subscription-backed local CLI providers (spec §24)

The v1.1 follow-on of `docs/superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md`:
a researcher already logged in to Codex CLI or Claude Code routes research work through
that CLI, with no API key, under the same privacy policy, traces, and review gates
(ADR-030). The spec states fifteen acceptance criteria; each one below names the test that
demonstrates it. Run them with:

```bash
uv run pytest -q tests/unit/providers/cli tests/contract/providers/test_cli_provider.py \
                 tests/contract/providers/test_cli_provider_runtimes.py \
                 tests/contract/capabilities/test_cli_providers.py \
                 tests/e2e/test_cli_providers_commands.py tests/e2e/test_cli_capability_parity.py
# the browser half, once the Models & providers settings section has landed:
pnpm --filter research-harness-web test -- src/app/settings
```

| # | criterion | what demonstrates it | where it lives | holds today |
|---|---|---|---|---|
| 1 | Open Design is a pinned submodule, not a runtime dependency | `git submodule status` reports `-9bb4a7d66d31a4bb7a678a93c6940d3677774e51 open-design` — the pin, with the leading `-` of a submodule this checkout never initialized; the shipped registry imports and orders itself, and no module under `src/` names the submodule | `open-design/` (submodule); `tests/unit/providers/cli/test_registry.py::test_the_shipped_registry_is_importable_and_ordered` | holds |
| 2 | A fresh scan detects all seven runtimes independently, with normalized version/auth/model status | all seven are registered in display order; detection keeps registry order, isolates a runtime that raises, and normalizes each probe into one `CliRuntimeStatus`; the capability answers the same seven and edits nothing | `tests/unit/providers/cli/test_defs_others.py::test_all_seven_runtimes_are_registered_in_display_order`; `tests/unit/providers/cli/test_detection.py` (whole module); `tests/contract/capabilities/test_cli_providers.py::test_scan_lists_all_seven_runtimes_in_registry_order_and_edits_nothing` | holds |
| 3 | Web and `research providers add` create the same validated entry | the capability writes exactly one validated `local_cli` entry; the terminal refuses an unroutable runtime and writes an available one; the settings screen posts the same request with the chosen model and reasoning | `tests/contract/capabilities/test_cli_providers.py::test_configure_writes_one_validated_entry`; `tests/e2e/test_cli_providers_commands.py::test_add_refuses_an_unavailable_runtime_and_writes_an_available_one`; `web/src/app/settings/settings.test.tsx` ("adds a provider with the chosen model and reasoning, after the egress warning") | holds on the Python side; the browser half lands with the settings section |
| 4 | A logged-in user with no API key completes a schema-validated request through each routable CLI | one real subscription-backed call per routable runtime, validated against the same response schema as an HTTP provider | `tests/contract/providers/test_live_cli_smoke.py`, gated by `RESEARCH_HARNESS_LIVE_CLI_TESTS=1` — neither is on the tree yet | not yet demonstrated: the live module and its gate variable arrive with Task 15, which records the run with its date and the CLI versions |
| 5 | Existing commands select the CLI through `--provider`, with no workflow branch | the same workflow path selects a `local_cli` entry by name; no workflow or domain module knows the kind | `tests/e2e/test_cli_providers_commands.py::test_existing_workflow_commands_select_the_cli_entry_with_provider` | holds |
| 6 | Research content is delivered through stdin/RPC, never argv | the prompt is written to the child's stdin and is absent from the recorded argv; every other runtime answers the same contract; the registry refuses a definition that could place research content in argv | `tests/contract/providers/test_cli_provider.py::test_research_content_travels_on_stdin_never_argv`; `tests/contract/providers/test_cli_provider_runtimes.py::test_every_other_runtime_answers_the_same_contract`; `tests/unit/providers/cli/test_registry.py::test_research_content_may_not_reach_argv` | holds |
| 7 | A CLI provider is external egress unless local inference is positively established | declared capabilities are external, text-only, and structured; `unknown.external` is never classified local; a definition declaring a local egress host is refused; a configured entry appears in the catalog as external | `tests/contract/providers/test_cli_provider.py::test_capabilities_are_external_text_only_and_structured`; `tests/unit/providers/cli/test_types.py::test_the_unknown_external_host_is_never_local`; `tests/unit/providers/cli/test_registry.py::test_a_local_egress_host_is_refused`; `tests/contract/capabilities/test_cli_providers.py::test_a_configured_cli_entry_appears_in_the_catalog_as_external` | holds |
| 8 | The project privacy policy prevents the process from spawning | `privacy.external_models: disabled` refuses the request before any process exists, on the provider path and on the capability path alike | `tests/contract/providers/test_cli_provider.py::test_the_privacy_policy_refuses_before_any_process_is_spawned`; `tests/contract/capabilities/test_cli_providers.py::test_the_test_call_is_refused_by_the_policy_before_any_spawn` | holds |
| 9 | The runtime cannot edit files or run project tools; a tool/file-write event fails the request | a tool event cancels the process and fails as `bounded_authority_violation`, for the reference runtime and for every other one; a bypass flag anywhere in a definition's argv is refused at registry construction | `tests/contract/providers/test_cli_provider.py::test_a_tool_event_cancels_the_process_and_is_a_bounded_authority_violation`; `tests/contract/providers/test_cli_provider_runtimes.py::test_every_other_runtime_fails_on_a_tool_event`; `tests/unit/providers/cli/test_registry.py::test_a_bypass_flag_anywhere_in_argv_is_refused` | holds |
| 10 | Invalid, partial, or schema-incompatible output never reaches staging or accepted state | invalid JSON fails through the same structured-output path an HTTP provider uses, and a schema violation returns no partial object | `tests/contract/providers/test_cli_provider.py::test_invalid_json_fails_through_the_shared_structured_output_path` and `::test_a_schema_violation_never_returns_a_partial_object` | holds |
| 11 | Cancellation and timeout terminate the whole process tree | cancel kills grandchildren, exiting stays bounded when a grandchild inherits the pipes, and abandoning the stream — directly or through the wrapper — cancels the process | `tests/unit/providers/cli/test_process.py::test_cancel_terminates_grandchildren` and `::test_exiting_is_bounded_when_a_grandchild_inherits_the_pipes`; `tests/contract/providers/test_cli_provider.py::test_abandoning_the_stream_cancels_the_process` and `::test_abandoning_the_stream_through_the_wrapper_also_cancels_the_process` | holds |
| 12 | Web and CLI display identical availability and failure reasons from shared capabilities | configure and scan answer identically in process and over the daemon; the scan view and the catalog agree about a refused entry; the terminal prints every runtime with its state; the settings screen renders the daemon's own words | `tests/contract/capabilities/test_cli_providers.py::test_configure_and_scan_answer_identically_over_the_daemon` and `::test_the_scan_view_and_the_catalog_agree_about_a_refused_entry`; `tests/e2e/test_cli_providers_commands.py::test_scan_prints_every_runtime_with_its_state`; `web/src/app/settings/settings.test.tsx` ("renders the daemon states …") | holds on the Python side; the browser half lands with the settings section |
| 13 | Existing HTTP, local-server, and scripted providers pass their contract and integration tests unchanged | the pre-existing provider contract, native-streaming, and provider-independence modules are untouched by this work and green | `tests/contract/providers/test_model_contract.py`, `tests/contract/providers/test_native_streaming.py`, `tests/e2e/invariants/test_a_provider_independence.py` — unchanged; the wave gate ran the full suite at **4250 passed / 40 skipped** on the tree before Tasks 8–13 | holds; Task 15 re-runs the full suite |
| 14 | Default CI needs no installed CLI, no login, no key, and no network | every default test drives `tests/fixtures/cli/fakes.py` — a fake executable replaying sanitized fixtures — instead of a real binary; the capability-parity test empties `PATH`, so no CLI on the developer's own workstation is ever probed; the live test is gated by an environment variable | `tests/fixtures/cli/fakes.py`; `tests/contract/protocol/test_new_capability_parity.py` (sets `PATH` to `""`); `RESEARCH_HARNESS_LIVE_CLI_TESTS=1` gates `tests/contract/providers/test_live_cli_smoke.py` | holds for the default suite; the gate variable and the live module arrive with Task 15 |
| 15 | Logs, traces, fixtures, configuration, and UI contain no credential material | an error carries the runtime identity and a next action but no secret, including a secret straddling the stderr truncation boundary; a diagnostic carries neither a home path nor a token; a failed `test` reports the failure without one | `tests/unit/providers/cli/test_errors.py::test_messages_carry_identity_and_a_next_action_but_no_secret` and `::test_a_secret_straddling_the_stderr_truncation_boundary_is_still_redacted`; `tests/unit/providers/cli/test_detection.py::test_a_diagnostic_never_carries_a_home_path_or_a_token`; `tests/contract/capabilities/test_cli_providers.py::test_the_test_call_reports_a_failure_without_a_secret` | holds; Task 15 adds the repository-wide secret scan |

Supporting: `tests/unit/providers/cli/` (142 tests at the wave gate);
`tests/contract/providers/test_cli_provider.py` and `test_cli_provider_runtimes.py`, inside
the `tests/contract/providers` run that reported 226 passed and 3 skipped — the skips are
the pre-existing live-provider smokes; `tests/contract/capabilities/test_cli_providers.py`
and `tests/e2e/test_cli_providers_commands.py`, inside the 348 that Task 11's gate ran
green; and `web/src/app/settings/{settings.test.tsx,mappers.test.ts}` on the browser side.
ADR-030; the researcher-facing text is
[the providers guide](../guide/providers.md#subscription-backed-local-clis) and the cockpit
half is [`docs/architecture/web.md`](../architecture/web.md).

**Three things this table does not claim.** Criterion (4) is the only one that needs a real
subscription login, and neither its module nor its gate variable is on this tree at all, so
the row says *not yet demonstrated* rather than `holds`: Task 15 writes
`tests/contract/providers/test_live_cli_smoke.py`, runs it behind
`RESEARCH_HARNESS_LIVE_CLI_TESTS=1`, and records the date and the CLI versions.

Second, five of the seven runtimes are detected but not routable in this release — Cursor
Agent, Amp, DeepSeek Harness, and Pi have no documented bounded mode, and OpenCode's
environment-injected posture is unproven until a version with recorded fixtures is verified
— so (4) will cover Codex CLI and Claude Code, which are the two runtimes the release
routes.

Third, the two rows that cite `web/src/app/settings/settings.test.tsx` cite a module being
written as this matrix is compiled: the daemon side of (3) and (12) is green now, and the
browser side is green when the *Models & providers* section lands — exactly how the four
v1.1 Web halves above were recorded before they landed.

## Open items

Nothing is currently marked `xfail(strict=True)`, and the suite reports **no xfails**. Four
sites keep a *conditional* `pytest.xfail`, described below; they are guards against a defect
that is fixed rather than a defect still open.

### Closed

**Server-side id allocation, over HTTP — pending reentrant workspace lock, now landed.**
`server/app.py::_invoke` takes `ctx.repo.lock()` for every `mutate`/`admin` capability, and
the handlers that allocate an id server-side (`create_claim`, `accept_decision`,
`create_question`, `record_search_run`, plus `ingest_local_pdf` and `add_artifact`) take it
again to allocate under it. `WorkspaceRepository.lock()` used to raise rather than nest, so
the id-less form the Web cockpit and the VS Code extension post came back `workspace_error`
over HTTP while the same call succeeded in process — the handler was right and the transport
was not. `lock()` now nests within one repository object (an inner `lock()` reuses the held
lock, the outermost context releases it, and the OS lock stays non-reentrant), which is what
`transaction()` already did.

Four tests were written to report the refusal as an expected failure rather than as a red
test nobody could act on, and to pass the moment the lock nests with nothing to un-mark.
They pass. The guards stay, because each fires only on the specific
`the workspace lock is not reentrant` message, so a regression is reported as the same
diagnosis rather than as a bare assertion failure:

| Module | Test | Guard |
|---|---|---|
| `tests/e2e/test_web_gate.py` | `test_the_claim_audit_loop_runs_entirely_over_the_cockpit_calls` | via `allocating()` |
| `tests/e2e/test_web_gate.py` | `test_an_override_is_a_decision_before_it_is_a_claim_edit` | via `allocating()` |
| `tests/e2e/test_web_gate.py` | `test_gate_p11_both_loops_complete_with_no_file_edit_and_no_cli_mutation` | via `allocating()` |
| `tests/contract/protocol/test_vscode_contract.py` | `test_claim_create_lets_the_daemon_name_the_claim` | inline |

`tests/e2e/test_web_gate.py::ALLOCATION_DEFECT` carries the full description, and the helper
`allocating()` is where the xfail is raised, so any capability driven through it inherits
the same report.

**Re-accepting a candidate after an interrupted acceptance.** `_reviewable` used to refuse a
repeat acceptance only when the *staging* record said the candidate was already accepted,
and staging is regenerable — so after a crash between the canonical commit and
`mark_reviewed`, or simply after deleting `.research/` and re-running the loop, the same
candidate allocated a fresh `EvidenceId` and appended a second accepted Evidence object with
the identical anchor, text, and content. The guard now sits on canonical evidence (an
accepted record at the same `anchor_fingerprint` with the same content), and
`test_re_accepting_after_the_crash_must_not_create_a_second_evidence_object` passes with no
xfail. Two tests were added beside it: the repeat answers with the Evidence that already
exists, and a repeat carrying a different qualification is refused by name.
