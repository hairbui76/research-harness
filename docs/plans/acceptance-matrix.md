# Acceptance matrix — Product §42 and the crash suite

What demonstrates each acceptance behaviour, where it lives, and whether it holds today.
Written for ROADMAP Tasks 17.1 and 17.2 and for Gate P17 ("all end-to-end invariants
pass"). Counts are the tests each module collects, including parametrized cases.

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
