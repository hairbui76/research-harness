# Conversation-first Research Workspace — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Product and architecture design only. This document does not authorize implementation.

## 1. Goal

Research Harness should become the primary place where one researcher can discuss, inspect, organise, verify, and write scientific work without losing the provenance and authority guarantees of the existing Research Core.

The interaction model may take visual and workflow inspiration from DeepSeek Harness, but `deepseek-harness/` remains a reference submodule. Research Harness must not depend on it at runtime and must keep its own domain model, protocol, storage, and interface.

The shared visual and interaction contract is defined by the [Research Harness Design System](2026-09-03-research-harness-design-system-design.md). Dark is the default theme, light is optional, runtime assets remain local, and presentation components never own research authority or application capabilities.

## 2. Product shape

The default Web experience is conversation-first:

```text
┌────────────────────┬──────────────────────────────┬──────────────────────┐
│ Projects / Sessions│ Conversation + composer      │ Research inspector   │
│ Search / Settings  │ rendered Markdown + LaTeX    │ Context / Evidence   │
│ Research navigation│ attachments / Context used   │ Claims / Review      │
└────────────────────┴──────────────────────────────┴──────────────────────┘
```

- The left pane owns project selection, session history, search, settings, and navigation.
- The centre pane owns the active conversation, composer, attachment intake, model/mode controls, and visible context receipt.
- The right pane is collapsible and shows Context, Evidence, Claims, Review Inbox, Conflicts, and Stale items related to the current conversation.
- Corpus, Claims, Synthesis, and Manuscript remain full research pages when depth is more useful than an inspector.

## 3. Authority model

Conversation is durable working context, not accepted scientific truth.

```text
session message / attachment
          │
          ├── remains private working context
          │
          └── explicit promotion
                ├── Note
                ├── Question
                ├── Claim candidate
                ├── Decision candidate
                └── Corpus artifact (Save to corpus)
```

- The model can read the active session and selected relevant material from earlier sessions.
- Accepted Evidence, Claims, Decisions, and source anchors outrank chat history when context conflicts.
- A message cannot silently become scientific state.
- Evidence promotion requires a source and resolvable anchor.
- Model-proposed scientific graph relations remain candidates until the applicable review rule accepts them.

## 4. Subsystems

This design is split into four independently reviewable subsystems:

1. [Conversation workspace](2026-09-03-conversation-workspace-design.md)
2. [Research attachments](2026-09-03-research-attachments-design.md)
3. [LaTeX manuscript workspace](2026-09-03-latex-manuscript-workspace-design.md)
4. [ResearchGraph index](2026-09-03-research-graph-index-design.md)

Their intended dependency order is:

```text
Conversation foundation
   ├── Research attachments
   ├── ResearchGraph references and context assembly
   └── LaTeX manuscript workspace
```

Attachments and ResearchGraph work may proceed in parallel once session identity and privacy contracts are stable. The manuscript workspace can reuse the same references and inspector contracts without making the graph its source of truth.

The Design System is a cross-cutting foundation for all four subsystems. Its tokens, primitives, accessibility contract, and pane composition must stabilise before the corresponding Web surfaces migrate.

## 5. Storage boundary

Durable, local conversation data lives outside `.research/`:

```text
conversations/<session-id>/
├── messages.jsonl
├── attachments/
└── summary.*
```

This data is private/local by default and is not intended for Git publication unless the researcher explicitly exports or shares it. It can be read as working context, but it has lower authority than accepted research objects.

Corpus objects and other accepted scientific state remain Git-readable and user-owned. `.research/` continues to hold disposable projections, indexes, caches, runtime state, and traces that can be rebuilt.

## 6. Context assembly

Every model call receives an explicit `ContextPack` assembled under a token and privacy budget. Its selection order is:

1. system and task policy;
2. relevant accepted Evidence, Claims, Decisions, and source anchors;
3. current-session messages and attachments;
4. relevant excerpts or summaries from prior sessions;
5. parsed corpus blocks and discovery results when needed.

The interface exposes a `Context used` receipt listing included and omitted sessions, messages, attachments, Evidence, Claims, and other sources. Omission reasons include token budget, privacy/egress policy, unsupported media, stale data, and low relevance.

## 7. Privacy and failure principles

- Provider egress policy applies before any conversation, attachment, or graph context leaves the machine.
- Private session nodes cannot be retrieved into an external-model request when policy forbids it.
- Unsupported attachments block sending and offer a compatible model or conversion path; they do not disappear.
- Draft text and ready attachments survive individual upload, indexing, model, and compilation failures.
- Rebuildable indexes may be deleted without deleting transcripts, corpus artifacts, accepted scientific state, or manuscript source.
- Keyboard navigation, focus order, readable error states, and non-colour authority labels are acceptance requirements.

## 8. Explicit non-goals for this track

- Replacing the Research Core with a chat transcript.
- Automatically importing every attachment into the corpus.
- Automatically accepting model-generated scientific claims or graph edges.
- Treating rendered HTML as a substitute for real LaTeX compilation.
- Introducing Neo4j or an external search cluster before local SQLite projections fail measured needs.
- Building a code-symbol graph into the core. It may later be a namespaced plugin linked to Work and Artifact nodes.
- Creating a runtime dependency on the DeepSeek Harness submodule.

## 9. Completion criteria for the design track

The design is ready for a separate implementation plan only after the researcher reviews these written specifications and confirms that:

- the three-pane conversation workspace matches the intended daily workflow;
- session history and scientific authority are clearly separated;
- attachment promotion is explicit and reversible before acceptance;
- LaTeX rendering means actual compilation for manuscripts;
- ResearchGraph is a rebuildable projection, not a new canonical authority;
- privacy and `Context used` behaviour are understandable without implementation knowledge.
