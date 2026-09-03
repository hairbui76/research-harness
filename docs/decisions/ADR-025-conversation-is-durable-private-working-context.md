# ADR-025: Conversation is durable private working context, never accepted state

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §26, §39, §42 (M); ROADMAP.md Phase 18, Gate P18; `docs/superpowers/specs/2026-09-03-conversation-workspace-design.md` §3–§8 and `2026-09-03-research-workspace-experience-design.md` §3, §5, §6; implemented in `domain/conversation.py`, `workspace/conversations.py`, `workspace/layout.py`, `conversation/{context,retrieval,send,promote,service}.py`, `capabilities/conversation.py`

## Context

Making chat the front door of a research workstation is the fastest way to lose the
property the workstation exists for. A transcript is persuasive, cheap to produce, and
sits next to the accepted objects in the same window; anything that lets it be cited,
digested, or silently preferred turns a model's paraphrase into project knowledge. The
opposite failure is as bad: a chat that lives only in `.research/` is thrown away by the
one command the product tells researchers to run without fear (`rm -rf .research/`), and a
chat that is committed publishes a private thinking log by default.

## Decision

A session is **durable, private working context** and forms a *third* storage tier.
`conversations/CS####/` sits outside `.research/` — `session.yaml`, an append-only
`messages.jsonl`, `attachments/`, one `context/CP####.json` per model call, and a derived
`summary.md` — so deleting the projection loses no transcript, no attachment, and no
receipt. It is *not* canonical: `init`'s generated `.gitignore` lists it, `iter_canonical_entries`
skips it, so chat can never restate or invalidate the canonical digest, and no conversation
object is written through a canonical transaction.

**A message cannot carry accepted authority.** `Message` refuses `authority=accepted` in a
validator, so the label is unreachable rather than merely unused. The only way out of a
session is `session.promote`, which *copies* an excerpt into a Note, a Question, a Claim
candidate, or a *drafted* Decision through `note.add` / `question.create` / `claim.create`,
with provenance naming the session and message; the message itself is never edited,
deleted, or relabelled. A promoted Claim is created unverified at the weakest allowed
strength and still faces `claim.audit`; a promoted Decision is drafted, and accepting it is
`decision.accept`, which this path deliberately does not call. **Evidence is not a promotion
target**: prose has no artifact and no exact anchor, so it is refused by name with the
route that does work (`EvidenceRequiresAnchorError`).

**Accepted state outranks chat mechanically, not by intention.** Every model call assembles
a `ContextPack` in the fixed `CONTEXT_ORDER` — policy, accepted state, current session,
prior sessions, attachments, corpus blocks, discovery — so the accepted objects are already
packed before conversational memory is considered. A remembered passage that contradicts an
accepted Decision or Claim is omitted as `conflicts_with_accepted` and the disagreement is
recorded as a `ContextDiscrepancy` on the receipt rather than dropped. Private material is
filtered *before* provider selection whenever the selected endpoint is external (ADR-018).
Every call persists its pack, so the `Context used` receipt — included and omitted items,
each with authority, source pointer, token cost and omission reason, plus the per-class
budget and the effective egress class — is readable before the answer exists and a week
after it.

`session.send` is the capability; the stream is a read of the durable run it started
(`GET /runs/{run_id}/events`). Every delta is persisted before it is emitted, so an
interruption keeps the partial text marked `incomplete`, and `session.retry` is a *new*
attempt that keeps the failed one.

## Consequences

### Positive

- A researcher can hand the model everything it may see and still answer "what did it
  actually read?" from a file, months later, with the projection deleted.
- Deleting `.research/` costs cross-session *ranking* (the graph-backed retriever falls
  back to a transcript scan) and nothing else; `research chat show` and `chat search` work
  with no index at all.
- The privacy boundary is a data property, not a UI convention: a private session refuses
  an external provider rather than quietly sending less.

### Negative / costs

- Three tiers is one more than the product had, and `conversations/` is the only durable
  directory `init` does not create and `path_for` does not know — a real special case,
  written down in `workspace/layout.py` rather than implied.
- Relevance is deliberately naive (term overlap with a frequency tie-break), so
  cross-session retrieval finds the obvious passage and misses the paraphrased one. The
  receipt says which passages were considered, which is the honest form of that limit.
- Token counting is one estimate (`estimate_tokens`), so a receipt's numbers are
  comparable across runs but are not the provider's own accounting.

## Invariants this ADR protects

- No message, summary, or retrieved excerpt is accepted scientific state (§42 M); a
  message cannot even be labelled `accepted`, and a summary never outranks its transcript.
- Promotion goes through the capability that already owns each rule, so the strict review
  gate cannot be reached around from a chat window (ADR-004, ADR-007).
- Evidence requires an Artifact and a resolvable anchor; prose promotion is refused (§42 M,
  ADR-003).
- Deleting `.research/` loses no transcript, attachment, or receipt (§42 C, ADR-001).
- Conversation content never enters the canonical digest, so chat cannot make a workspace
  inconsistent (ADR-014).
- Private context does not leave the machine: it is removed before provider selection, not
  after (ADR-018, PRODUCT §34).

## Rejected alternatives

- **Store sessions under `.research/`.** Makes the documented recovery step destroy the
  researcher's own notes, and makes "rebuild" a data-loss command.
- **Commit `conversations/` by default.** Publishes a private thinking log, and puts chat
  in the same review a `git diff` gives accepted state — the confusion this ADR exists to
  prevent. Export stays an explicit action with a visible destination.
- **Let a promoted excerpt be accepted when the researcher promotes it.** Promotion is a
  human action, but so is review; collapsing them makes the fast path the unreviewed one.
- **Rank prior sessions with an embedding model by default.** A hidden ranker makes
  "included because it is relevant" uncheckable, and the receipt is the product.
- **Assemble context, then filter for privacy.** Filtering after selection means the
  private passage has already displaced something, and one bug is the difference between
  a receipt and a leak.

## Where it is enforced

- `src/research_harness/domain/conversation.py`: `Message._chat_is_never_accepted_state`,
  `CONTEXT_ORDER`, `ContextPack` / `ContextReceipt` / `ContextDiscrepancy`, `OmissionReason`.
- `workspace/layout.py` (`CONVERSATIONS_DIRNAME`, `GITIGNORE_CONTENT`, `DURABLE_DIRECTORIES`)
  and `workspace/events.py::iter_canonical_entries` (the digest exclusion).
- `conversation/context.py` (budgeted, ordered, privacy-first assembly),
  `conversation/retrieval.py` (`GraphExcerpts` / `TranscriptScan`), `conversation/send.py`
  (durable run, persist-then-emit, `incomplete`, retry), `conversation/promote.py`
  (`EvidenceRequiresAnchorError`), `capabilities/conversation.py`, `server/routes_sessions.py`.
- Tests: `tests/e2e/test_conversation_gate.py`, `tests/unit/conversation/`,
  `tests/integration/conversation/`, `tests/integration/workspace/test_conversations.py`,
  `tests/contract/capabilities/test_conversation.py`,
  `tests/contract/protocol/test_session_events.py`, `tests/unit/domain/test_conversation.py`.
