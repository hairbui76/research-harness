# Conversation Workspace — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Design only; no implementation is authorised by this document.

## 1. Purpose

Make conversation the fastest entry point into a research project while preserving the existing evidence-first authority model. The workspace must feel as direct as a modern model harness, but every scientific conclusion remains inspectable through the Research Core.

## 2. Layout and navigation

### Left pane

- project switcher;
- new session;
- searchable, renameable session history;
- research navigation for Corpus, Claims, Questions, Synthesis, Taxonomy, Manuscript, Review Inbox, Conflicts, and Stale;
- settings and provider status.

### Centre pane

- conversation transcript;
- Markdown and KaTeX rendering;
- composer with model/mode selection and `@` reference completion;
- attachment tray;
- send/stop/retry controls;
- per-response `Context used` receipt;
- explicit promotion actions for useful outputs.

### Right inspector

- collapsible on narrow or focused layouts;
- tabs for Context, Evidence, Claims, Review Inbox, Conflicts, and Stale;
- follows selected text, message, attachment, or graph reference;
- supports two-way navigation: a chat reference opens its object, and an object shows the messages in which it was used.

Full pages remain available for work that needs larger tables, source comparison, or editing. The conversation route does not replace them.

## 3. Session persistence

Each session has a stable `CS####` identity and a local directory:

```text
conversations/CS0001/
├── messages.jsonl
├── attachments/
└── summary.md
```

Messages use stable `M####` identities within the project. The append-oriented transcript records role, content blocks, timestamps, attachment references, model/provider metadata, and the `ContextPack` receipt for each model call. Summaries are derived aids and may be regenerated; they cannot override the transcript or accepted research state.

Conversation data is durable and private/local by default. Explicit export or sharing is a separate action with a visible destination and scope.

## 4. Model context policy

The active model may receive:

- the active session history, subject to the model context window;
- relevant excerpts or summaries from prior sessions;
- relevant accepted research objects and source anchors;
- current session attachments allowed by provider and egress policy.

The context assembler prefers accepted scientific state over conversational memory. If a prior message contradicts an accepted Decision or Claim, the accepted object is selected and the discrepancy can be surfaced in the inspector.

Cross-session retrieval is relevance-based, not a blind concatenation of all chats. Every inclusion carries a stable reference and authority label. Private context is filtered before provider selection and token packing.

## 5. `Context used`

Every submitted request produces a visible receipt containing:

- current-session message range included;
- prior sessions/excerpts included;
- attachments included, converted, or omitted;
- Evidence, Claims, Decisions, and corpus blocks included;
- items omitted and the reason;
- provider/model and effective egress class;
- token-budget allocation by context class.

The receipt must be inspectable after the response so a researcher can explain what the model saw.

## 6. Promotion from conversation

A message or selection can be explicitly promoted to:

- `ResearchNote`;
- `ResearchQuestion`;
- Claim candidate;
- Decision candidate.

Promotion opens a reviewable form with provenance back to the session and message. A Claim or Decision follows the existing candidate/verify/review workflow. Evidence cannot be created from prose alone: promotion must attach an Artifact and exact resolvable anchor.

Promoting does not delete or rewrite the original message.

## 7. ResearchGraph references

Typing `@` searches stable research references such as `@W0017`, `@E0482`, and `@C0041`. Selected references are represented as structured composer tokens rather than ambiguous copied text. The context assembler resolves each token at send time and records the resolved target in `Context used`.

Broken, stale, private, or unresolved references are visibly marked before sending. Deep links open the exact object or source location.

## 8. Errors and recovery

- Composer drafts persist through navigation, refresh, and individual send failures.
- Retry creates a new model attempt while retaining the failed attempt metadata.
- A streaming interruption preserves received content and marks it incomplete.
- Context assembly failure identifies the failing item and permits removal or retry.
- Provider unavailability does not corrupt the session.
- A deleted projection index may temporarily reduce cross-session retrieval, but direct transcript access continues to work.

## 9. Accessibility and responsive behaviour

- All pane, tab, message, composer, reference, and promotion actions are keyboard accessible.
- Focus returns predictably after send, modal close, and inspector navigation.
- Authority, stale, candidate, failure, and privacy states are conveyed by text/icon as well as colour.
- On narrow screens, left and right panes become drawers without hiding the active draft.
- Mathematical content exposes useful text to assistive technology where the renderer supports it.

## 10. Acceptance scenarios

1. Reopen a project and continue a prior session with its transcript intact.
2. Ask a question whose answer uses accepted Evidence and a relevant prior-session excerpt; inspect both in `Context used`.
3. Observe that accepted scientific state wins when remembered chat conflicts with it.
4. Promote a response excerpt into a Claim candidate without changing accepted state.
5. Attempt to promote unsupported prose to Evidence and be required to select a source anchor.
6. Block a private cross-session excerpt from external provider egress and display the omission reason.
7. Navigate from an `@E####` token to the exact Evidence and back to the originating message.
