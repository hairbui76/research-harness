# Domain changelog

Additive amendments to `domain/` and the layers that persist or project it, each requested
by the module named beside it. Every entry keeps the existing public names and signatures
working; nothing here renames or removes anything.

`conventions.md` is unchanged: these are schema additions, not new rules.

## 2026-09-03

| # | Change | Requested by |
|---|---|---|
| 1 | `IdentifierField.note` records where a value was found (`"pdf_metadata:title"`, `"page1:regex"`); `ingest.metadata.inspect_pdf` fills it on every extracted field, and `PdfInspection`/`FieldNote` keep working as the per-field index. | `ingest/` |
| 2 | `errors.IngestError` joins the hierarchy; `ingest.metadata` wraps PyMuPDF failures (non-PDF, corrupt, missing) in it and chains the original. | `ingest/` |
| 3 | `Claim.derived_from` names the synthesis matrices a claim was read off, so `DependencyKind.DERIVES_CLAIM` edges (`matrix -> claim`) are derived from canonical fields instead of registered by hand; projected as the `claims.derived_from` JSON column. | `projection/` |
| 4 | `ParsedDocument` requires `work`, `version`, and `file_hash`, so a parse names the bytes it read; anchor validation reads `doc.file_hash` instead of parsing it back out of a provenance note, and block rows projected through their document carry `blocks.file_hash`. | `evidence/`, `retrieval/` |
| 5 | `DocumentBlockKind.TABLE_CAPTION` exists; the PDF parser gives an orphaned `Table N:` line its own kind rather than filing it under `FIGURE_CAPTION`. | `retrieval/` |
| 6 | `ResearchEvent.objects` (object key -> canonical-YAML digest, at most 10 000 entries, keys at most 200 chars) replaces the flattened `object:<key>` payload entries, so recording a large mutation no longer competes with the payload budget; `event_object_digests` still reads the legacy payload form, and events project an `events.objects` JSON column. | `capabilities/` |
| 7 | `WorkspaceRepository.init` emits a `project.initialized` event inside its journalled init transaction, so `iter_events()` on a fresh workspace yields exactly that event and the log names the project its history belongs to. | `capabilities/`, `cli/` |
| 8 | `workspace.rejections.RejectionRecord` is the canonical form of a refused candidate, appended to `corpus/works/W####/rejections.jsonl` via `WorkspaceLayout.rejections_path`, `WorkspaceTransaction.append_rejection`, and `WorkspaceRepository.iter_rejections`; `evidence.reject` writes one instead of the placeholder `ResearchNote` it used to, and `workspace.events` resolves its `rejection/<work>#<candidate id>` digest key. | `evidence/` |
| 9 | `WorkspaceConfig.providers` holds raw model-routing entries from `research.yaml` (`list[dict]`, default empty) so `research.yaml` can carry a `providers:` section without `workspace/` importing `providers/`; `providers.models.RouterConfig` validates them at use. | `cli/`, `providers/` |
| 10 | `SearchRun` carries the discovery space it produced: `candidates` (`SearchCandidate`: node key, `WorkCandidate`, reporting sources and per-source ranks, screening state with its author, timestamp and persisted exclusion reason, identity outcome, matched work, full-text availability), `unresolved_keys`, `full_text_unavailable_keys`, and `reproduces`. A validator makes `results` follow the candidates' discovered/screened/included tally, refuses a repeated candidate key, and refuses derived keys the run never recorded. Candidates project into a new `search_candidates` table keyed by `(run, key)`; `projection.PROJECTION_SCHEMA_VERSION` is 2. | `discovery/` |
| 11 | `ResearchEventType.CLAIM_RELATION_CHANGED` (`claim.relation_changed`) names a change to a claim's evidence relations, and `CLAIM_TRANSITIONS` gains a self-edge for each audited status (`supported`, `qualified`, `contested`, `unsupported`, exported as `AUDITED_CLAIM_STATUSES`) so a re-audit that confirms the current verdict is a legal transition rather than a special case. | `claims/` |
| 12 | The PDF parser is version `1.1`: it rebuilds spaces from glyph geometry, merges extractor lines that share a baseline, and recovers fonts whose character codes are displaced, so identical bytes now yield different block text and numbering than `1.0` and anchors taken under `1.0` must be revalidated (ADR-008). Nothing in `domain/` changes: the new `parsing.base.BlockQuality` and `ParseDiagnostics` are parser-layer types, `PyMuPdfParser.last_diagnostics` exposes the run's soft failures, and `parse_provenance` folds their counts into the provenance note (`file_hash=... diagnostics=undecodable:12;shift:3;pages:1,4`) so a persisted document keeps them; `parsing.diagnostics_summary(doc)` renders that note for a CLI. | `parsing/` |
| 13 | `ResearchEventType.DECISION_SUPERSEDED` (`decision.superseded`) names the retirement of an accepted Decision. `capabilities.extra_handlers.supersede_decision` emits it for every decision type, taxonomy revisions included; `taxonomy.revised` now means only "the classification vocabulary changed", which is what `taxonomy.put` writes. | `capabilities/` |
| 14 | `AddNoteRequest.source` records where a capture came from (`"cli"`, a chat host, an editor). `note.add` stores it in the note's `Provenance.note` as `captured via <source>` and echoes it in the event payload; the note text is untouched. `research/notes.py` lost its `_SourcedContext` workaround. | `research/` |
| 15 | `DiscardNoteRequest.reason` (`str \| None`) is recorded in the `note.discarded` event, and `note.discard` is a real capability handler (`extra_handlers.discard_note_mutation`) rather than a transaction opened inside `research/`. `NoteService.discard(note_key, *, reason=None)` delegates to it and keeps its old signature working. | `research/`, `capabilities/` |
| 16 | `capabilities.handlers.PROVISIONAL_EVIDENCE_ID` and `next_evidence_id(repo)` are public: `evidence.accept` allocates the real `EvidenceId` itself when the candidate still carries the provisional one, so an HTTP or MCP caller that posts a staged candidate verbatim gets a correct id instead of `E0000`. A candidate that already holds a real id is accepted unchanged. `_flat_ids` learned the `E` prefix. | `capabilities/`, `evidence/` |
| 17 | `corpus.search` is registered rather than planned: `extra_handlers.discover_corpus` builds the search registry from `os.environ` under `privacy.load_policy(repo)` and runs `discovery.DiscoveryService`, which persists the run through `search_run.record` as before. `describe().planned` is down to `project.init` and `synthesis.find_pattern`. | `capabilities/`, `discovery/` |
| 18 | `WorkspaceRepository.get_parsed_document(artifact, *, work=None)` and `iter_parsed_documents(work)` rebuild a `ParsedDocument` from stored blocks plus the Artifact's own version and `file_hash`, under the placeholder identity `STORED_PARSER_NAME`/`STORED_PARSER_VERSION`. `evidence.review.stored_document` and `retrieval.corpus_units` read it instead of assembling their own. | `workspace/`, `retrieval/`, `evidence/` |
| 19 | `projection.schema.drop_all` drops the FTS5 virtual tables (via `projection.fts.drop_fts`) before the projection tables, so a deletable projection is fully deletable and cannot answer out of shadow tables whose content table is gone. | `projection/` |
| 20 | `providers.models.describe_backend(client, contract) -> BackendInfo` is the one implementation of "which provider and model would answer this role", with `RoleLike` as its structural contract type. `evidence.extraction.resolve_backend`/`backend_label`/`BackendInfo` and `claims.audit.backend_label` delegate to it and stay importable. | `providers/`, `evidence/`, `claims/` |
| 21 | `capabilities.handlers.CAPABILITY_HANDLERS` covers the whole registry: it merges `CORE_CAPABILITY_HANDLERS`, `claims_ext.CLAIM_EXTENSION_HANDLERS`, and `extra_handlers.EXTRA_CAPABILITY_HANDLERS` on first read (lazily, because the extension modules reach the registry). `manuscript.attach_claim` refuses a non-human actor in the handler and is `human_only` in the registry. | `capabilities/`, `manuscript/` |
| 22 | `cli.providers` holds the CLI's provider selection (`resolve_model_client`, `optional_model_client`, `load_router`, `scripted_model_provider`), and `cli.plugins` resolves `--schema plugin:<name>[:<schema>]` through `plugins.load_plugin`. No domain type changes; `cli.commands.evidence.load_router` and `SCRIPTED_PROVIDER` are re-exports. | `cli/` |
| 23 | `ResearchEventType.WORK_METADATA_UPDATED` (`work.metadata_updated`) and `ResearchEventType.CLAIM_COVERAGE_RECORDED` (`claim.coverage_recorded`) name the two state changes the new `work.update_metadata` and `claim.update_coverage` capabilities make. Neither borrows an existing member: filling a Work's bibliographic fields is not `work.ingested`, and recording a coverage funnel is not `claim.audited`. | `capabilities/` |
| 24 | `ManuscriptAuditFinding.location` (`FindingLocation`: `file`, `line_start`, `line_end`, `char_start`, `char_end`, with `covers_line`/`overlaps`) carries where a finding was raised. Every finding `_Auditor._add` emits fills it, the `"<file>:<line>: "` message prefix is unchanged, and the field is optional so an older report still validates. An editor no longer parses prose to place a diagnostic (vscode.md gap 4). | `capabilities/` |
| 25 | `manuscript.audit.AuditScope` (`file`, optional `line_start`/`line_end`), `sentence_location(sentence)`, and `narrow_report(report, scope, project)` narrow an audit to part of a manuscript. `ManuscriptService.audit(*, parsed=True, scope=None)` and `audit_context(..., scope=None)` take it: with a scope only the artifacts the in-scope anchors rest on are re-parsed, and the report's counts are recomputed over that range. `scope=None` is byte-identical to the old behaviour, and `ManuscriptService.trace` now uses a one-sentence scope instead of auditing the whole project (vscode.md gaps 3, 6). | `capabilities/` |
| 26 | `AcceptEvidenceRequest.candidate_id` (`str | None`) names the staged proposal an acceptance answers. Given, `evidence.accept` marks that candidate reviewed *after* the canonical write, so a transport that posts the staged `Evidence` verbatim drains the review queue; a candidate that is no longer in staging is logged, not refused. Absent, nothing in staging is touched, which is what a hand-built acceptance needs. | `capabilities/` |
| 27 | `evidence.accept` is idempotent on canonical state. `_accepted_duplicate` matches an already-accepted record by anchor identity (the fields `parsing.anchors.anchor_fingerprint` hashes) plus content digest; a repeat returns that Evidence with an empty diff, a validation warning, and *no* journalled event, and a repeat carrying a different qualification is refused by name. The guard moved off staging, which is regenerable: a crash between the commit and `mark_reviewed`, or a deleted `.research/`, can no longer mint a second `EvidenceId` for one span (ADR-001, ADR-003). | `capabilities/` |
| 28 | `capabilities.dto` exports `PROVISIONAL_CLAIM_ID`, `PROVISIONAL_QUESTION_ID`, `PROVISIONAL_DECISION_ID`, and `PROVISIONAL_SEARCH_RUN_ID` (all number `0`, which is never allocated). `claim.create`, `question.create`, `decision.accept`, and `search_run.record` accept a nested object with no `id` - a `mode="before"` validator fills the provisional one in - and allocate the real id under the workspace lock, confirming it inside the transaction. An explicit id is still used unchanged. | `capabilities/` |
| 29 | `capabilities/reads.py` holds the summaries every navigation lists (`WorkSummary`, `ArtifactSummary`, `ClaimSummary`, `QuestionSummary`, `DecisionSummary`, `MatrixSummary`, `TaxonomySummary`, `AnchorSummary`, the new `EvidenceSummary`, `CandidateView`, `WorkspaceIndex`) plus `workspace_index(repo)` and `candidate_view(repo, id)`. `protocol.dto` re-exports them unchanged, and `GET /index` and `GET /candidates/{id}` call those functions, so a route and its capability cannot drift into two shapes for one answer. | `capabilities/` |
| 30 | `ClaimService` gains `record_coverage(claim_id, coverage)`, `derived_coverage(claim)`, and `with_derived_coverage(claim)`. An audit of a claim whose `Coverage` is empty derives the funnel from the claim's recorded `SearchRun`s via `discovery.coverage_for` and appends a warning naming the runs; a claim that records coverage keeps it. A derived funnel never invents a `cutoff` - that stays the researcher's declaration, which is what L4 asks for. `ClaimService._search_runs` and `cli.commands.discover._runs_for` now count a rerun of a named run as named, so a recorded coverage set cannot freeze the funnel. | `capabilities/` |
| 31 | `SearchCandidate.screening_reason`, `Work.screening_reason`, and `WorkCandidate.screening_reason` (`str \| None`) record why a candidate or work was screened the way it was, whatever the decision. The validators now read *"an exclusion persists a reason"* rather than *"a reason is only valid for an exclusion"*; `exclusion_reason` is unchanged, still refused on anything but an exclusion, and `discovery.screen` writes both fields for an exclusion so every existing reader keeps working. `SearchCandidate.reason` and `Work`/`WorkCandidate.screening_note` return whichever field holds the reason. `Work.screening_reason` has no writer yet: `capabilities.handlers.register_work` copies `WorkCandidate.exclusion_reason` and would need the same one-line copy to carry an inclusion reason from a run into the corpus (dogfood F9). | `discovery/`, `cli/` |
| 32 | `EvidenceContent.labels` (`tuple[str, ...]`) carries the categories an answer places the work in, and `domain.evidence.normalize_label` is the one spelling rule for them (casefolded, `_`/`-`/whitespace collapsed). `roles.schemas.EvidenceCandidateOutput.labels` is the extractor's proposal; `evidence.extraction.resolve_labels` checks it against the interrogation field's declared `categories` and rejects anything else, and `synthesis.matrix.declares_label` lets a declared label fill a matrix cell beside the `ClassificationRule` cross-check. Absent labels behave exactly as before (dogfood F13). | `evidence/`, `synthesis/` |
| 33 | `claims.audit.ClaimAuditResult.proposed_wording` keeps the sentence the claim auditor proposed, beside the deterministic `maximum_defensible_wording` ceiling and never in place of it. It is advice: it changes no scope, and an audit with no auditor leaves it empty (dogfood F15). | `claims/` |
| 34 | Reporting additions for what a step could not read: `ingest.service.IngestResult.metadata_notes` (with `undecodable_fields`) carries `ingest.metadata`'s per-field extraction notes, so `research ingest` can say a field is empty because the font would not decode; `parsing.base.document_diagnostics` falls back to the blocks' own parse provenance, so a document rebuilt from stored blocks still reports its diagnostics; and `citations.graph.ReferenceList.warnings` / `citations.snowball.SnowballResult.warnings` carry what a citation-graph call refused to seed from, fed by the new `providers.search.base.ReferenceCandidates` (a `list[WorkCandidate]` with `warnings`), read back by `reference_warnings`, and recorded on the run as non-incomplete `SourceFailure`s (dogfood F6, F10). | `cli/`, `discovery/`, `citations/` |
| 35 | `WorkspaceRepository.open(root, verify=...)` (`"auto"`, the default, or `"full"`) and the verification cache behind it. After a successful full `verify_consistency`, `open` writes `.research/consistency-check.json`: schema version, `checked_at`, the event log's size and sha256, and `(size_bytes, mtime_ns)` for every canonical file. The next `open` skips the full check only when all of that still holds byte-for-byte, and reports why through the new `ConsistencyReport.skipped_reason` / `.skipped`; anything else - one changed byte, an added or removed file, an unreadable or foreign-version marker, a mutation committed by a repository that held no marker - re-verifies, and a failed check deletes the marker. `verify="full"` always runs the whole check, and so does `repo.verify()`. Full verification is still the only thing that can call a workspace consistent, and the marker lives under `.research/`, so deleting the projection re-verifies in full (ADR-001, ADR-014). | `workspace/`, `cli/` |
| 36 | `projection.rebuild.canonical_digest` is sha256 over the sorted `(relative path, sha256 of the file's bytes)` pairs of the canonical tree, instead of over each object's re-serialized canonical YAML. **The value stored in `projection_meta.canonical_digest` therefore changes**; `PROJECTION_SCHEMA_VERSION` is deliberately *not* bumped, because the projection is regenerable and the next rebuild writes the new digest anyway, and `verify_rebuild` never compares it. Per-object digests (`workspace.events.object_digest`), the event log, and `verify_consistency` are untouched - a hand-reformatted YAML file still does not fail a workspace closed, it just no longer keeps the same *projection* digest. `iter_canonical_files` moved to `workspace.events` (with `iter_canonical_entries` and `file_digest` beside it) and is re-exported from `projection.rebuild` unchanged, because `workspace/` must not import `projection/`. | `projection/` |
| 37 | `evidence.interrogation.InterrogationField.multi_label` (`bool`, default `False`) declares that one Work may answer a question several times without contradicting itself, mirroring `plugins.spi.VocabularyField.multi_label`. `evidence.conflicts.is_multi_valued` reads it first and keeps the field-name/question-wording inference only as the fallback for a schema written before the flag and for `inferred_field` (a staged candidate records its field's name, not the contract that asked it). **`InterrogationSchema.fingerprint()` therefore changes**, which is intended: what counts as a conflict for a field is part of the stage contract, and no test pinned a literal value. `DEFAULT_SCHEMA` declares it on `dataset`, `metric_result`, `author_limitation`, and `baseline`; `plugins/structured-traffic/interrogation/paper.yaml` on nineteen of twenty-two questions. The plugin loader needed no change - `InterrogationContribution.fields` validates into `InterrogationField` (dogfood F7). | `evidence/`, `plugins/` |
| 38 | `privacy.traces` owns `TracingRouter`, `traced(router, repo)`, `trace_writer_for(repo)`, and the new `sink_of(client)`; `cli.providers` re-exports all four unchanged. `capabilities.extra_handlers._router` wraps its router in one, so a run started over HTTP or MCP writes `.research/traces/` under the project's `redact_traces`. `providers.models.cross_verify.cross_verify(..., trace=...)` forwards a sink to each provider it calls directly, and `claims.audit.trace_sink_for(audit_input)` recovers it from the audit's own clients - cross-verification bypasses the router's `complete`, and was the one call in a run that left no record. | `privacy/`, `capabilities/`, `claims/`, `providers/` |
| 39 | `providers.models.router.ModelRouter.egress_refusal()` returns the `EgressDeniedError` covering *every* entry, or `None` when one may still be called. `select()` still refuses lazily, which is right for routing; this answers without a request, for a caller about to hand the router to a background run. `capabilities.extra_handlers._router` raises it, so a policy-refused `work.interrogate` / `evidence.verify` over HTTP or MCP comes back as the policy rather than as a failed run record found later (Product 34, ADR-018). | `providers/`, `capabilities/` |
| 40 | `capabilities.reads` gains the `read` capabilities `search_run.list` (`ListSearchRunsRequest` -> `SearchRunList` of `SearchRunSummary`, newest first, filterable by research question or source) and `search_run.get` (`ReadSearchRunRequest` -> `SearchRunView`: the whole `SearchRun` including its candidates, plus the `discovery.search_runs.MetadataEnrichment` proposals its candidates carry and `apply_capability: work.update_metadata`). `enrichments_for` is imported inside the handler, because `discovery/` imports `capabilities/`; a build without the discovery package answers with the run and `enrichments_derived: false`. Closes the read gap `docs/architecture/web.md` recorded (dogfood F5). | `capabilities/`, `discovery/` |
| 41 | Four stable id types join `domain/ids.py` and `ID_TYPES` (Product 7.2): `ConversationSessionId` (`CS`), `MessageId` (`M`), `SessionAttachmentId` (`SA`), `ContextPackId` (`CP`). `parse_id` already dispatched longest-prefix-first, so `CS`/`CP` resolve before `C` and `SA` before `S` with no change to the resolver; every existing id parses exactly as before. `ID_TYPES` also feeds `manuscript.protected`'s identifier pattern, so `CS0001`, `M0042`, `SA0003`, and `CP0007` are now protected spans in a style pass -- which is what a manuscript that cites a session should get. | `conversation/`, `graph/` |
| 42 | `domain/conversation.py` is new. It holds the conversation vocabularies -- `AuthorityLabel`, `Visibility`, `MessageRole`, `AttachmentState`, `ContextClass`, `OmissionReason`, `PromotionTarget`, plus `EgressClass` (`none`/`local`/`external`, the receipt's *effective egress class* without naming a provider), `AttemptStatus`, and `ContentBlockKind` -- and the schemas `ConversationSession` (+ `SessionDefaults`), `Message` (+ `MessageAttempt`, `ModelIdentity`, and the `TextBlock | ReferenceBlock | AttachmentBlock` discriminated union exported as `ContentBlock`), `SessionAttachment`, `ContextPack`/`ContextReceipt`/`ContextItem`/`OmittedContextItem`/`ClassBudget`, and `PromotionRequest`. They live here rather than in `domain/enums.py` because they are one subsystem's vocabulary; `domain/graph.py` imports `AuthorityLabel` and `Visibility` from this module. Math stays inside `TextBlock.text` (never normalized, never split), and there is no reasoning block: hidden model deliberation is neither requested nor stored (Product 20.5). | `conversation/`, `graph/`, `capabilities/` |
| 43 | Conversation authority is enforced by schema, not by convention. A `Message` refuses `AuthorityLabel.ACCEPTED` on its own content (chat is working context; promotion is the only path to research state), a completed message must carry a block while an interrupted one may be empty, a user message may not carry a failed or retried attempt, and every attachment block must appear in the message's `attachments` index. `PromotionTarget` has no Evidence member on purpose: evidence needs an artifact and a resolvable anchor, so prose cannot become one. `ContextReceipt` refuses a source pointer that is both included and omitted or listed twice, and `ContextPack` refuses spending more tokens than its `token_budget` or a class's `ClassBudget`. | `conversation/` |
| 44 | `ATTACHMENT_TRANSITIONS` and `transition_attachment(attachment, to_state, **updates)` implement the attachments spec SS2 state machine the way `domain/transitions.py` implements the others, raising `TransitionError` for an untabled move; `allowed_attachment_transitions()` renders the table as strings for UIs. Two edges go beyond the spec's diagram on purpose: `ready -> {session_only, promoting}`, because `Save to corpus` is offered from the composer, transcript, viewer, and inspector and must not require a send first; and `failed -> {validating, sending, promoting}`, because a failed operation leaves the session copy intact and retryable (spec SS6). `in_corpus` is terminal, and the schema requires a content hash from `ready` onward, a reason on `failed`, and Work/Version/Artifact links exactly when the state is `in_corpus`. | `conversation/` |
| 45 | `WorkspaceLayout` gains the `conversations/CS0001/{session.yaml,messages.jsonl,attachments/,context/,summary.md}` accessors plus `attachment_extension`, `session_attachment_bytes_file`, `.research/cache/attachments` (`attachment_cache_dir`), and `attachment_preview_dir(attachment)` for one attachment's rebuildable previews. `DURABLE_DIRECTORIES` names the third storage tier: durable, private, not canonical scientific state, and not regenerable either. `CANONICAL_DIRECTORIES` is unchanged, so `init` creates exactly the same tree as before and `ConversationStore` creates a session directory on demand. `GITIGNORE_CONTENT` now also lists `conversations/`, and `id_from_path` returns `None` for anything under `conversations/` because `path_for` never produces one -- a conversation object is never written through a canonical transaction. `workspace.events.iter_canonical_entries` skips `conversations/` for the same reason: durable is not authoritative, so a chat message must not restate `projection.rebuild.canonical_digest` or invalidate the `.research/consistency-check.json` proof that the canonical tree is unchanged. | `conversation/`, `graph/`, `projection/` |
| 46 | `workspace/conversations.py` adds `ConversationStore` (`create_session`, `get_session`, `list_sessions`, `rename_session`, `update_session`, `resume`, `append_message`, `iter_messages`/`messages`/`get_message`/`find_message`, `search`, `add_attachment`, `put_attachment`, `get_attachment`, `list_attachments`, `store_attachment_bytes`, `read_attachment_bytes`, `attachment_bytes_path`, `write_context_pack`, `read_context_pack`, `list_context_packs`, `read_summary`, `write_summary`, `regenerate_summary`), with `SessionMatch`, `SessionTranscript`, `ConversationNotFoundError`, and the pure `derive_summary`. Writes take the workspace lock and commit through the existing journal `Transaction`, so a transcript line and the session record that counts it are one recoverable unit; no `ResearchEvent` is written, because a session is not accepted state. `ConversationStore.for_repository(repo)` reuses the repository's reentrant lock so a promotion can write both sides under one lock. | `conversation/`, `graph/`, `capabilities/` |
| 47 | `WorkspaceConfig` gains `manuscript: dict[str, Any]`, the optional `manuscript:` section of `research.yaml` (`engine`, `entry_file`, `timeout_seconds`, `extra_args`, `synctex`). It is held raw for the same reason `providers` is -- `workspace/` must not import `manuscript/` -- and `manuscript.toolchain.ManuscriptSettings.from_config` validates it where it is used, refusing an unknown key, an entry file that escapes `manuscript/`, and any compiler flag outside `ALLOWED_EXTRA_ARGS`. The field was necessary rather than convenient: `WorkspaceConfig` forbids extra keys, so without it a researcher who wrote the section could no longer open the workspace. It defaults to `{}`, so an existing `research.yaml` opens unchanged; a rewritten one gains a `manuscript: {}` line, exactly as `providers: []` behaves. | `manuscript/` |

### Notes for consumers

- `WorkspaceRepository.open` now writes one file: `.research/consistency-check.json`, after
  a full verification it passed. It is regenerable state with no authority, its absence is
  always safe, and a workspace whose `.research/` is read-only opens exactly as before (the
  write is best-effort). `research doctor` should pass `verify="full"` so it reports a
  re-derived verdict rather than a cached one.
- `parsing.base.FILE_HASH_NOTE_PREFIX` and `document_file_hash` stay importable.
  `document_file_hash(doc)` now simply returns `doc.file_hash` and never returns `None`;
  the `file_hash=` provenance note is legacy description only, and nothing reads it back.
- `validate_anchor`, `resolve_anchor`, and `build_anchor` still accept a `file_hash=`
  keyword; it overrides `doc.file_hash` for a caller replaying against bytes it hashed
  itself.
- `workspace.events.MAX_EVENT_OBJECTS` now tracks the domain's object-digest cap
  (10 000) rather than the payload-key cap (32).
- A block projected on its own has `blocks.file_hash = NULL`: only the parsed document
  knows which artifact bytes the parse read.
- `rejections.jsonl` is append-only canonical state and is *not* projected into SQLite; the
  rebuild covers it by file bytes in the canonical digest, and `iter_rejections` is the read
  path. A rejected candidate never receives an `EvidenceId`.
- A candidate or work written before `screening_reason` existed still loads: the field
  defaults to `None`, and an exclusion that carries only `exclusion_reason` still validates.
  New readers should ask `SearchCandidate.reason` / `Work.screening_note`, which cover both.
- `EvidenceCandidateOutput.labels` changes the JSON schema of `ExtractionOutput` and
  `SkepticOutput`, so `RoleOutput.json_schema_fingerprint()` moves for both. That fingerprint
  is persisted on every staged candidate as `response_schema_fingerprint`: results recorded
  before this change keep the old value, which is the point of recording it.
- `EvidenceContent.labels` is not projected into SQLite; `synthesis.matrix` reads it off the
  canonical evidence, and a matrix built from label-free evidence is byte-identical to one
  built before the field existed.
- `SynthesisService.build(..., force=False)` refuses to overwrite a matrix a Claim was read
  off (`Claim.derived_from`). A first build, and a build of a matrix nothing depends on, is
  unchanged; `existing_matrix` and `dependent_claims` are the read paths behind it.
- A workspace written before `WorkspaceConfig.providers` existed still loads: the field
  defaults to an empty list, and `research.yaml` gains `providers: []` on its next rewrite.
- Every pre-existing `SearchRun` field keeps working: a run recorded without `candidates`
  validates exactly as before, and `unresolved_identities`/`unavailable_full_text` are still
  the free-form and Work-id views of the same facts (`discovery/` writes both from one
  source, so they cannot drift).
- Two candidates that resolve to the same `Work` stay two `SearchCandidate` entries with
  their own sources and ranks; work-level deduplication never merges the Version or Artifact
  records behind them (ADR-002).
- The projection schema version bump forces one full rebuild; nothing canonical changes.
- A re-audit into the current status now goes through `transitions.audit_claim` like any
  other audit; `claims.audit.apply_audit` no longer needs its self-transition workaround.
  `unverified` is still unreachable from any audited status, and `superseded` is still
  terminal.
- The parser version bump is the only thing that invalidates anchors: `validate_anchor`
  still reports `stale`/renumbered exactly as before, and a document parsed by `1.0` keeps
  working. `parsing.document_diagnostics` returns an empty mapping for such a document, and
  `diagnostics_summary` says "no parse diagnostics recorded" rather than calling it clean.
- Recovered text is ordinary text: it is hashed, anchored, and quoted like any other block.
  Text that no offset recovers keeps exactly the characters the extractor returned and is
  listed in `ParseDiagnostics.undecodable_blocks`; the parser never invents a reading, and
  an undecodable line never opens a section, so `section_path` falls back to the last
  heading that could be read.
- Table cell text comes from the table finder rather than from the span pipeline, so a table
  drawn in a displaced font is reported undecodable rather than recovered.
- `decision.supersede` used to borrow `taxonomy.revised` (for a taxonomy decision) or
  `decision.accepted` with `payload["transition"] = "superseded"`. Readers of the old log
  still work; new events use the new member. `synthesis.service.revise_taxonomy` is
  unchanged: it supersedes the previous Decision *by reference* (`Decision.supersedes`) and
  leaves it `accepted` and readable, which is what Gate P8 asserts, so no decision
  transition — and therefore no `decision.superseded` event — happens there.
- A note captured before `AddNoteRequest.source` existed is unchanged: the field defaults to
  `None` and no provenance note is written. `note.add` still accepts `text` and `key` alone.
- `evidence/service.py` still allocates an `EvidenceId` before it calls, because it names the
  id in its log line and in `SplitAcceptance`; both paths now ask
  `capabilities.next_evidence_id`, so they cannot disagree and nothing is allocated twice.
- `corpus.search` is `Permission.MUTATE`: it reads external catalogues and writes nothing to
  them, but it records a canonical `SearchRun`. It is also in
  `plugins.PLUGIN_ALLOWED_CAPABILITIES`, so a plugin passes the gateway and is then refused
  by `Principal.authorize` for want of human authority. The permission is the honest half
  and stays; the allowlist is the half to fix, in one line in `plugins/manifest.py` (drop
  `"corpus.search"`), and `tests/contract/capabilities/test_registry.py` now pins both the
  rule ("every plugin-allowed name is `read` or `stage`") and this one exemption, so the
  exemption disappears with the fix rather than outliving it.
- Nineteen capability names are new: `work.list`, `claim.list`, `question.list`,
  `decision.list`, `evidence.list`, `anchor.list`, `review.candidate`, `state.index`
  (all `read`); `review.accept`, `review.qualify`, `review.edit`, `review.reject` (`mutate`,
  human-only); `review.defer`, `review.request_more` (`stage`, human-only);
  `manuscript.anchors`, `manuscript.trace` (`read`), `manuscript.revalidate` (`mutate`,
  human-only); `work.update_metadata` (`mutate`, human-only); `claim.update_coverage`
  (`mutate`). Nothing was renamed or removed, and `GET /index`, `GET /candidates/{id}`, and
  `review.resolve_conflict` all still answer exactly as before.
- `UpdateWorkMetadataRequest` is called by name from `discovery.apply_enrichments`, which
  looks the handler up in `CAPABILITY_HANDLERS` and fills its request by field name
  (`work`, `title`, `authors`, `year`, `venue`, `identifiers`, `overwrite`). Renaming one of
  those fields turns an applied enrichment into a silent refusal, so the shape is a
  contract between the two packages rather than an implementation detail.
- `capabilities/` reaches into `discovery/`, `manuscript/`, and `evidence/`, and each
  reaches back to write, so every such import is deferred into the function that needs it.
  `tests/contract/capabilities/test_import_layering.py` imports each package first in a
  fresh interpreter, because a cycle broken only by import order is invisible to a suite
  that always imports `claims` before `discovery`.
- `STORED_PARSER` in `retrieval/service.py` and `evidence.review.stored_document` keep their
  names and behaviour; a document rebuilt from blocks is a replay surface and must never be
  fingerprinted or stored.
- `manuscript.attach.parsed_documents` still re-parses artifact bytes rather than reading
  stored blocks: the audit's anchor findings depend on a real parse of the file the anchor
  was taken from, so the swap is not the trivial one the repository accessor makes elsewhere.
- `research draft` now accepts a configured provider, so `draft_section(provider=...)` takes
  `manuscript.draft.ModelClient` (`ModelProvider | ModelRouter`) rather than `ModelProvider`.
  Every existing call passing a bare provider still type-checks.
- A `--script` file may now be a list, an object keyed by role name, or a single reply
  object. The third shape is what `research draft` always wrote; it used to be readable only
  by the manuscript command's private loader.
- Conversation id counters are derived from the durable files under `conversations/` --
  session directory names, each session's `last_message` (falling back to the transcript
  when a `session.yaml` is lost), and the attachment/context-pack filenames -- and not from
  `research.yaml`. A canonical transaction rewrites `research.yaml` wholesale from its own
  cached config, so a counter bumped by a chat message would be dropped by the next
  accepted-state mutation; and a committed file should not churn on every message. The
  consequence: `ConversationStore` has no delete operation, and whoever designs session
  deletion must leave a tombstone or a durable ledger, because a scan cannot see an id that
  was removed.
- `GITIGNORE_CONTENT` gained `conversations/`, but nothing rewrites the `.gitignore` of a
  workspace created before this change. A project initialized earlier keeps ignoring only
  `.research/`, so the first session it opens would be Git-visible. Adding the line is a
  one-line `workspace/migrations.py` step; it is not done here because that file belongs to
  another task in this wave.
- A `ConversationStore` write is journalled but reports failure the way every other
  journalled unit does: if the process dies after the intents are applied and before the
  commit point, recovery on the next open rolls the append *forward*. The caller sees an
  exception while the message is durable, which is the same contract
  `WorkspaceTransaction.commit` has always had.

### ResearchGraph projection (Phase 20)

- `domain/graph.py` is new and additive: `NodeKind`, `EdgeKind` (with the
  `DETERMINISTIC_EDGE_KINDS` / `SCIENTIFIC_EDGE_KINDS` partition), `EdgeOrigin`,
  `GraphAuthority`, `GraphVisibility`, the `GraphNode` / `GraphEdge` value objects,
  `StableReference`, and `DeepLink`. `GraphAuthority` and `GraphVisibility` mirror
  `conversation.AuthorityLabel` and `conversation.Visibility` value for value rather than
  importing them, so `domain/graph.py` and `domain/conversation.py` stay independent
  modules; `tests/unit/domain/test_graph.py` pins the two lists together.
- `GraphEdge` refuses `origin=model_proposed` with `authority=accepted`, and
  `origin=accepted` with `authority=candidate`. The rule lives on the value object, not in
  the writer, so no projector, capability, or test helper can construct the forbidden
  combination (ADR-003).
- `StableReference` reads the prefix as the maximal leading run of capitals, which is what
  makes `CS0001` a session rather than claim `S0001` with no longest-prefix table to keep in
  sync. It accepts every `ID_TYPES` prefix plus `CP`, `CS`, `M`, and `SA` as opaque strings,
  so a reference parses whether or not its id class has landed.
- `graph/` is a new package under the layering rule already in `conventions.md`. It reads
  canonical state through `WorkspaceRepository`, reuses `projection.dependencies` for
  `depends_on`, and never imports `providers/`, `cli/`, `server/`, `capabilities/`, or
  `roles/` — `tests/unit/graph/test_layering.py` imports it in a fresh interpreter to prove
  it. Staged proposals under `.research/staging/` are read as plain JSON for that reason:
  `evidence.staging` and `workflows.claim_audit` pull `providers/` and `capabilities/` in.
- Node identities are the graph's public contract and are stable across rebuilds:
  `W0017` / `V0017-2` / `A0017-3` / `E0482` / `C0041` / `RQ0003` / `D0027` / `S0007`
  verbatim; `project:<name>`, `block:<artifact>#<block>` (a `BlockId` is unique inside its
  artifact, not globally), `file:<workspace-relative path>`,
  `anchor:<file>#<sentence fingerprint>`, `cite:<key>`, and `candidate:<candidate id>` for a
  staged proposal, which never borrows an `EvidenceId`.
- Namespaces the graph deliberately does not project: taxonomies, search runs, matrix
  cells, notes, and interpretations. `projection.dependencies` keeps every one of those
  edges and stays the authority for staleness; `graph.projectors.graph_identity` returns
  `None` for them, and `SynthesisProjector` collapses the `evidence -> cell -> matrix` chain
  into `synthesis --depends_on--> evidence` so the real dependency is not lost.
- A claim–evidence relation that is not `supports`, `contradicts`, or `qualifies`
  (`contextualizes`, `exemplifies`, `incomparable_under_current_evidence`) is projected as
  `mentioned_in` carrying the exact canonical relation in edge metadata. Calling any of them
  `qualifies` would put a relation in the graph that the Claim does not assert.
- `projection.rebuild.RebuildReport` gained `graph_nodes` and `graph_edges` (both default
  `0`), and `summary()` mentions them when non-zero. `rebuild_workspace` calls
  `graph.rebuild.rebuild_graph` after the projection database is swapped in; a graph failure
  is logged and reported as zero rows rather than failing a rebuild whose canonical files
  projected cleanly (ADR-006). `dump_projection` is unaffected: the graph has its own
  `MetaData` and its own database at `.research/graph/research-graph.db`.
