# The conversation workspace

A **session** is a durable, private conversation bound to one project. It is the fastest
way into a corpus — ask a question, get an answer, promote what is worth keeping — and it
is deliberately *not* a place where scientific state is decided. Everything a model says
stays working context until you promote it through the same review path everything else
goes through (ADR-025, PRODUCT §39).

Two sentences are worth having in mind before the commands:

* **A message can never be accepted state.** The domain object refuses the label. Promotion
  copies an excerpt into a Note, a Question, a Claim candidate, or a Decision candidate; it
  never rewrites, deletes, or re-labels the message.
* **Accepted state outranks chat.** The context assembler packs policy, then accepted
  Evidence/Claims/Decisions, then the current session, then earlier sessions — in that
  order, under one token budget. A remembered passage that contradicts an accepted object
  is left out and the disagreement is written into the receipt.

## Sessions

```console
$ research chat new "Encoder choices for encrypted traffic"
CS0001  private  Encoder choices for encrypted traffic

$ research chat list
CS0001     3 msg  private  Encoder choices for encrypted traffic

$ research chat rename CS0001 "Encoder choices, week 2"
$ research chat show CS0001
```

`--visibility` is the one decision to make at creation:

| visibility | what it means |
|---|---|
| `private` (default) | the transcript never leaves this machine. A send to an external provider is refused rather than trimmed. |
| `project` | the transcript may reach the selected external provider, subject to the egress policy ([Providers](providers.md)). |

Visibility is decided once: no capability changes it afterwards, so a conversation that
will be answered by an external provider is opened with `--visibility project`.

**What answers this session.** `research chat configure` binds one session to a CLI runtime
and model, or to a `providers:` entry, without touching `research.yaml`. `research chat
list` puts the binding in brackets after the row and `research chat show` prints it as its
second line:

```console
$ research chat configure CS0001 --entry codex-sub
bound to: entry codex-sub

$ research chat list
CS0001     3 msg  private  Encoder choices for encrypted traffic  [entry codex-sub]
```

A per-message `--provider` on `chat send` still wins over the binding, and `--clear` returns
the session to the project default. A binding to a *runtime* — `--runtime codex --model
gpt-5.5 --reasoning high`, shown as `session:codex/gpt-5.5 (reasoning high)` — is external
egress, so it is refused on a private session; see
[Providers](providers.md#binding-a-session-instead-of-configuring-the-project).

Sessions live in `conversations/CS0001/` — outside `.research/`, and listed in the
`.gitignore` `init` writes. Deleting `.research/` costs you the *ranking* of cross-session
retrieval and nothing else; `research chat show` and `research chat search` read the
transcript files directly.

```console
$ rm -rf .research
$ research chat search "twelve layer"
CS0001  Encoder choices, week 2  …the encoder is a twelve layer transformer…
```

`research chat summarize CS0001` regenerates `summary.md`. It is a derived aid: it never
outranks the transcript, and the transcript never outranks accepted state.

## Sending

```console
$ research chat send CS0001 "What does the corpus say about tokenisation granularity?" \
    --ref E0482 --ref C0041 --provider fast
M0003  succeeded  (context CP0002)
The two accepted Evidence objects disagree about granularity: E0482 reports…
```

* `--ref` is a stable reference: `E0482`, `W0017`, `C0041`, `RQ0002`, `D0001`, and the
  conversation prefixes `CS0001`, `M0042`, `SA0003`. Each one is resolved at send time and
  the resolved target is recorded in the receipt; a reference that resolves to nothing is
  reported as `unresolved` rather than sent as text that looks like an id.
* `--provider` selects a configured entry; `research providers list` prints what each one
  accepts and whether it can be called. Without a provider the workspace routes by priority.
* `--script <file>` runs the in-process scripted adapter and sends nothing anywhere. A chat
  reply is `{"text": "…"}`, and the file is either one of those or a **list** of them
  consumed in order. The role-keyed shape the other commands accept does not apply here:
  `conversation` is not a registered role, so an object keyed by it is read as a single
  reply and fails validation. A bare string in the list fails with
  `model output was not valid JSON`. See
  [Providers](providers.md#the-scripted-provider).

The run is durable. `research chat stop <message>` cancels one: what already arrived is
kept and marked incomplete rather than discarded. `research chat retry <message>` answers
again as a **new** attempt — the failed one keeps its own record, with the provider error
on it:

```console
$ research chat show CS0001
CS0001  Encoder choices, week 2
bound to: entry codex-sub

M0002  assistant (incomplete)
    (no text)
    context: CP0001
M0003  assistant
    The demo corpus holds one Work, W0001, with three verified proposals…
    context: CP0002
```

A client that wants the deltas as they arrive reads `GET /runs/{run_id}/events`
([the daemon](http.md#streaming-a-model-call)); every delta is persisted before it is
emitted, so a reconnecting client reads exactly what it already saw.

## `Context used`

Every model call writes a `ContextPack` to `conversations/CS0001/context/CP####.json` and
the pack carries the receipt. Two commands read it:

```console
$ research chat context CS0001 --text "Does E0001 support a corpus-level claim?" --ref E0001
CP0000  none  243 tokens of 8000

included:
  [policy] policy://conversation/task            private   143 tok
  [accepted_state] rh://evidence/E0001           accepted   17 tok
  [current_session] rh://session/CS0001?message=M0001  private  17 tok

$ research chat context CS0001 --pack CP0002        # the receipt of a call already made
```

The preview assembles a pack without sending anything (`context.preview`); `--pack` reads
one that was recorded (`context.get`). `--persist` records a preview under the session.

A receipt names, for every item, its **context class**, its **source pointer**, its
**authority**, and its **token cost**; for everything left out, the **reason**:

| omission reason | when |
|---|---|
| `token_budget` | the class's allocation was full; the tokens it would have cost are recorded |
| `privacy_policy` / `egress_blocked` | the item is private, or the policy refuses this provider |
| `unsupported_media` | the selected model does not accept the attachment ([Attachments](attachments.md)) |
| `stale` | the anchor no longer replays |
| `low_relevance` | it did not score high enough against the draft |
| `unresolved_reference` | an `@` token named nothing this workspace holds |
| `conflicts_with_accepted` | an accepted object said otherwise; the discrepancy is listed too |

The classes are filled in this order, and that order *is* the authority rule: `policy`,
`accepted_state`, `current_session`, `prior_sessions`, `attachments`, `corpus_blocks`,
`discovery`.

## Promotion

```console
$ research chat promote M0003 note --excerpt "granularity is reported inconsistently"
$ research chat promote M0003 question --rationale "worth a search run"
$ research chat promote M0003 claim_candidate \
    --subject "byte-level tokenisation" --predicate "outperforms" --object "packet-level" \
    --scope observed_subset
$ research chat promote M0003 decision_candidate --decision-type taxonomy_revision
```

What each target does:

| target | what is created | what still has to happen |
|---|---|---|
| `note` | a `ResearchNote` with provenance to the session and message | nothing; a note is not citable support |
| `question` | a `ResearchQuestion` | nothing |
| `claim_candidate` | an unverified Claim at the weakest allowed strength | `research claim audit` decides what it may say |
| `decision_candidate` | a *drafted* Decision, captured as a note while it waits | the `decision.accept` capability, which needs a researcher and which this path deliberately does not call |

**Evidence is not a target.** Prose has no artifact and no exact anchor:

```console
$ research chat promote M0003 evidence
error: session.promote: evidence cannot be created from prose: it needs an Artifact and an
       exact resolvable anchor, so the claim can be reopened at its source (Product 9,
       42 M). Save the source to the corpus, then propose evidence against a block of it —
       `corpus.ingest` and `work.parse` give you the anchor, and `evidence.accept` reviews
       the result. Promote the passage to a note, question, or claim candidate instead.
```

The message is untouched by all of this. Promoting twice creates two objects; it never
edits the transcript.

## What breaks, and what survives it

| situation | what happens |
|---|---|
| the provider fails or never answers | the transcript gains one user message and one failed attempt; `research chat retry` starts a new one |
| the stream is interrupted | received text is kept and marked `incomplete` |
| a private session and an external provider | the send is refused by name, not silently trimmed |
| an unsupported attachment | the send is blocked with a per-item reason ([Attachments](attachments.md)) |
| `.research/` deleted | transcripts, attachments, and receipts are all still there; cross-session ranking falls back to a direct transcript scan |

## In the Web cockpit

The three-pane conversation route — session rail, transcript with Markdown and KaTeX
rendering, and a collapsible research inspector — is the Design System's
`ConversationWorkspace` composition; see [The Web cockpit](web.md). Every write it makes is
one of the `session.*` capabilities above, so nothing is reachable from the browser that is
not reachable from this page.

## See also

* [Attachments](attachments.md) — files in a session, and `Save to corpus`.
* [The ResearchGraph](graph.md) — what `@` references resolve against.
* [Review](review.md) — where a promoted candidate goes.
* [Providers](providers.md) — egress policy, and the scripted adapter.
